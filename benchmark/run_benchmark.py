#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
"""Run retrieval queries against Context Chat and compute retrieval metrics.

Uses ``occ context_chat:search``, which runs the vector search alone. The
``context_chat:prompt`` path would additionally invoke a text2text provider per query,
which costs minutes per query and measures the LLM rather than retrieval.

Metrics follow the MultiHop-RAG paper (arXiv:2401.15391, section 2.3):

hit_rate@k
    Fraction of queries with *at least one* evidence document in the top-k. This is
    the number that matters for Context Chat, which passes the whole retrieved set to
    the LLM, so partial evidence is frequently enough to answer.
evidence_recall@k
    Fraction of a query's evidence documents present in the top-k, averaged over
    queries. This is the paper's "Hits@K" and is the value comparable to its Table 5.
map@k
    Mean average precision at k; rewards ranking evidence documents highly.
mrr
    Reciprocal rank of the first evidence document.

k=30 matches the ``CONTEXT_LIMIT`` the backend uses when feeding the LLM, so it
reflects the production operating point. The MultiHop-RAG paper reports only
Hits@4 and Hits@10 (Table 5, page 7), so k=4 and k=10 are the cutoffs that can be
held against it; k=1, 5 and 30 are reported for this project's own tracking.

Comparisons with that table remain indicative rather than exact:

* The paper scores *chunks*; ``do_doc_search`` dedups chunks to source documents
  before returning, so these numbers are document-level and read higher.
* Chunking differs (``embedding_chunk_size`` 2000 characters here versus 256
  tokens there).
* ``do_doc_search`` searches ``ctx_limit * 2`` chunks and then dedups, so with
  ``--limit 30`` only the top 60 chunks are considered. A document whose best
  chunk ranks 61st or lower cannot appear, which makes evidence_recall@30 a lower
  bound on true document-level recall@30.

Each query requests ``--limit`` documents, defaulting to the largest scored cutoff so
every k is measured against a full result set.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_K_VALUES = (1, 4, 5, 10, 30)
# matches "  0 => '...'," entries emitted by var_export(), honouring escaped quotes
VAR_EXPORT_ITEM = re.compile(r"^\s*\d+\s*=>\s*'((?:[^'\\]|\\.)*)',?\s*$", re.MULTILINE)
# presence of the 'sources' key proves occ returned a well-formed result, even when
# the array inside it is empty
VAR_EXPORT_SOURCES = re.compile(r"^\s*'sources'\s*=>", re.MULTILINE)


def parse_sources(stdout: str) -> list[str]:
	"""Extract ordered source labels from occ's var_export() output.

	occ prints ``var_export($task->getOutput(), true)`` - PHP literal syntax, not JSON.
	Each ``sources`` entry is a JSON string with id/label/icon/url. ``label`` holds the
	file name, and file sources keep retrieval rank order.
	"""
	labels = []
	for match in VAR_EXPORT_ITEM.finditer(stdout):
		raw = match.group(1).replace("\\'", "'").replace('\\\\', '\\')
		try:
			source = json.loads(raw)
		except json.JSONDecodeError:
			continue
		if isinstance(source, dict) and 'label' in source:
			labels.append(source['label'])
	return labels


def doc_ids_from_labels(labels: list[str]) -> list[str]:
	"""Map file names back to corpus document ids, preserving rank and dropping repeats."""
	seen = set()
	ordered = []
	for label in labels:
		doc_id = label.rsplit('.', 1)[0] if '.' in label else label
		if doc_id not in seen:
			seen.add(doc_id)
			ordered.append(doc_id)
	return ordered


def run_query(occ: str, user: str, query: str, timeout: int, limit: int) -> tuple[list[str], str | None]:
	try:
		result = subprocess.run(  # noqa: S603 - fixed argv, no shell
			[occ, 'context_chat:search', user, query, '--limit', str(limit)],
			capture_output=True, text=True, timeout=timeout, check=False,
		)
	except subprocess.TimeoutExpired:
		return [], f'timeout after {timeout}s'

	if result.returncode != 0:
		detail = (result.stderr or result.stdout or '').strip().replace('\n', ' ')
		return [], f'exit {result.returncode}: {detail[:300]}'

	# an empty "sources" array is a legitimate retrieval result (the query matched
	# nothing) and must score as a miss; only output that is not a well-formed
	# var_export dump counts as a failure, otherwise misses are silently dropped
	# from the denominator and every metric is inflated
	if not VAR_EXPORT_SOURCES.search(result.stdout):
		return [], f'unparseable output: {result.stdout.strip()[:300]}'

	return doc_ids_from_labels(parse_sources(result.stdout)), None


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--queries', type=Path, default=Path('benchmark_data/queries.json'))
	parser.add_argument('--results', type=Path, default=Path('benchmark_results.json'))
	parser.add_argument('--occ', default='./occ')
	parser.add_argument('--user', default='admin')
	parser.add_argument('--query-timeout', type=int, default=120)
	parser.add_argument('--budget-seconds', type=int, default=3600, help='wall-clock cap for the whole run')
	parser.add_argument('--max-error-rate', type=float, default=0.05)
	parser.add_argument(
		'--k-values',
		type=lambda v: tuple(sorted({int(x) for x in v.split(',') if x.strip()})),
		default=DEFAULT_K_VALUES,
		help='comma-separated cutoffs to score at (default: 1,5,10,30)',
	)
	parser.add_argument(
		'--limit',
		type=int,
		default=None,
		help='documents to request per query (default: the largest --k-values entry)',
	)
	args = parser.parse_args()

	if not args.k_values:
		print('--k-values must contain at least one cutoff', file=sys.stderr)
		return 1

	queries = json.loads(args.queries.read_text(encoding='utf-8'))
	if not queries:
		print('No queries to evaluate', file=sys.stderr)
		return 1

	k_values = args.k_values
	# retrieve deep enough to score the largest cutoff
	retrieval_limit = args.limit if args.limit is not None else max(k_values)
	if retrieval_limit < max(k_values):
		print(
			f'--limit {retrieval_limit} is below the largest k ({max(k_values)}); '
			'deeper cutoffs will be truncated',
			file=sys.stderr,
		)

	hits = dict.fromkeys(k_values, 0)
	evidence_recall = dict.fromkeys(k_values, 0.0)
	average_precision = dict.fromkeys(k_values, 0.0)
	reciprocal_rank = 0.0
	evaluated = 0
	errors: list[str] = []
	started = time.monotonic()
	truncated = False
	aborted: str | None = None

	for index, item in enumerate(queries, start=1):
		elapsed = time.monotonic() - started
		if elapsed > args.budget_seconds:
			print(f'Time budget of {args.budget_seconds}s exhausted after {index - 1} queries, stopping')
			truncated = True
			break

		returned, error = run_query(args.occ, args.user, item['query'], args.query_timeout, retrieval_limit)
		if error is not None:
			errors.append(f'[{index}] {error}')
			# a handful of failures is tolerable; a broken contract is not
			if len(errors) > max(5, int(len(queries) * args.max_error_rate)):
				print('\n'.join(errors[-5:]), file=sys.stderr)
				aborted = f'{len(errors)} query failures exceed the allowed error rate'
				break
			continue

		evaluated += 1
		evidence = set(item['evidence_list'])

		for k in k_values:
			top_k = returned[:k]
			found = evidence & set(top_k)

			# hit_rate@k: at least one evidence doc retrieved
			if found:
				hits[k] += 1

			# evidence_recall@k: share of this query's evidence that was retrieved
			evidence_recall[k] += len(found) / len(evidence)

			# average precision@k: precision at each rank holding an evidence doc,
			# normalised by the number of evidence docs reachable within k
			relevant_seen = 0
			precision_sum = 0.0
			for rank, doc_id in enumerate(top_k, start=1):
				if doc_id in evidence:
					relevant_seen += 1
					precision_sum += relevant_seen / rank
			average_precision[k] += precision_sum / min(len(evidence), k)

		for rank, doc_id in enumerate(returned, start=1):
			if doc_id in evidence:
				reciprocal_rank += 1.0 / rank
				break

		if index % 25 == 0:
			rate = (time.monotonic() - started) / index
			print(f'Progress: {index}/{len(queries)} ({rate:.1f}s/query)', flush=True)

	# always write what was measured, even on the abort paths: a failed run is
	# exactly when the partial numbers and the failure list are most useful
	results = {
		'queries_planned': len(queries),
		'queries_evaluated': evaluated,
		'query_failures': len(errors),
		'truncated': truncated,
		'aborted': aborted,
		'retrieval_limit': retrieval_limit,
		'elapsed_seconds': round(time.monotonic() - started, 1),
		'first_failures': errors[:5],
	}
	if evaluated:
		results.update({
			'mrr': round(reciprocal_rank / evaluated, 4),
			**{f'hit_rate_at_{k}': round(hits[k] / evaluated, 4) for k in k_values},
			**{f'evidence_recall_at_{k}': round(evidence_recall[k] / evaluated, 4) for k in k_values},
			**{f'map_at_{k}': round(average_precision[k] / evaluated, 4) for k in k_values},
		})
	args.results.write_text(json.dumps(results, indent=2), encoding='utf-8')

	if evaluated == 0:
		print('No query produced a usable result', file=sys.stderr)
		print('\n'.join(errors[:5]), file=sys.stderr)
		return 1

	print('\n=== Benchmark results ===')
	width = max(len(str(k)) for k in k_values)
	print(f'{"k":>{width}}  {"hit_rate":>9}  {"evid_recall":>11}  {"MAP":>7}')
	for k in k_values:
		print(
			f'{k:>{width}}  {results[f"hit_rate_at_{k}"]:>9.4f}'
			f'  {results[f"evidence_recall_at_{k}"]:>11.4f}'
			f'  {results[f"map_at_{k}"]:>7.4f}'
		)
	print(f'MRR: {results["mrr"]:.4f}')
	print(f'Evaluated {evaluated}/{len(queries)} queries with {len(errors)} failures')
	if errors:
		print('First failures:')
		for line in errors[:5]:
			print(f'  {line}')

	if aborted is not None:
		print(f'Aborting: {aborted}', file=sys.stderr)
		return 1

	# a run that evaluated almost nothing is not a result worth publishing
	if evaluated < len(queries) * 0.5:
		print(f'Aborting: only {evaluated}/{len(queries)} queries completed', file=sys.stderr)
		return 1

	return 0


if __name__ == '__main__':
	sys.exit(main())
