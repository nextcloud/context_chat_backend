#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
"""Run retrieval queries against Context Chat and compute Recall@k and MRR.

Uses ``occ context_chat:search``, which runs the vector search alone. The
``context_chat:prompt`` path would additionally invoke a text2text provider per query,
which costs minutes per query and measures the LLM rather than retrieval.

``--limit`` is deliberately not passed: occ forwards options as strings and Nextcloud
validates the Number slot with ``is_numeric`` without casting, so the backend would
receive ``"10"`` and compute ``ctx_limit * 2 == "1010"``. The provider's registered
default (int 10) is used instead, which fixes the maximum k at 10.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

RECALL_AT_K = (1, 5, 10)
# matches "  0 => '...'," entries emitted by var_export(), honouring escaped quotes
VAR_EXPORT_ITEM = re.compile(r"^\s*\d+\s*=>\s*'((?:[^'\\]|\\.)*)',?\s*$", re.MULTILINE)


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


def run_query(occ: str, user: str, query: str, timeout: int) -> tuple[list[str], str | None]:
	try:
		result = subprocess.run(  # noqa: S603 - fixed argv, no shell
			[occ, 'context_chat:search', user, query],
			capture_output=True, text=True, timeout=timeout, check=False,
		)
	except subprocess.TimeoutExpired:
		return [], f'timeout after {timeout}s'

	if result.returncode != 0:
		detail = (result.stderr or result.stdout or '').strip().replace('\n', ' ')
		return [], f'exit {result.returncode}: {detail[:300]}'

	labels = parse_sources(result.stdout)
	if not labels:
		return [], f'no sources parsed: {result.stdout.strip()[:300]}'

	return doc_ids_from_labels(labels), None


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('--queries', type=Path, default=Path('benchmark_data/queries.json'))
	parser.add_argument('--results', type=Path, default=Path('benchmark_results.json'))
	parser.add_argument('--occ', default='./occ')
	parser.add_argument('--user', default='admin')
	parser.add_argument('--query-timeout', type=int, default=120)
	parser.add_argument('--budget-seconds', type=int, default=3600, help='wall-clock cap for the whole run')
	parser.add_argument('--max-error-rate', type=float, default=0.05)
	args = parser.parse_args()

	queries = json.loads(args.queries.read_text(encoding='utf-8'))
	if not queries:
		print('No queries to evaluate', file=sys.stderr)
		return 1

	hits = dict.fromkeys(RECALL_AT_K, 0)
	reciprocal_rank = 0.0
	evaluated = 0
	errors: list[str] = []
	started = time.monotonic()
	truncated = False

	for index, item in enumerate(queries, start=1):
		elapsed = time.monotonic() - started
		if elapsed > args.budget_seconds:
			print(f'Time budget of {args.budget_seconds}s exhausted after {index - 1} queries, stopping')
			truncated = True
			break

		returned, error = run_query(args.occ, args.user, item['query'], args.query_timeout)
		if error is not None:
			errors.append(f'[{index}] {error}')
			# a handful of failures is tolerable; a broken contract is not
			if len(errors) > max(5, int(len(queries) * args.max_error_rate)):
				print('\n'.join(errors[-5:]), file=sys.stderr)
				print(f'Aborting: {len(errors)} query failures exceed the allowed error rate', file=sys.stderr)
				return 1
			continue

		evaluated += 1
		evidence = set(item['evidence_list'])

		for k in RECALL_AT_K:
			if evidence & set(returned[:k]):
				hits[k] += 1

		for rank, doc_id in enumerate(returned, start=1):
			if doc_id in evidence:
				reciprocal_rank += 1.0 / rank
				break

		if index % 25 == 0:
			rate = (time.monotonic() - started) / index
			print(f'Progress: {index}/{len(queries)} ({rate:.1f}s/query)', flush=True)

	if evaluated == 0:
		print('No query produced a usable result', file=sys.stderr)
		print('\n'.join(errors[:5]), file=sys.stderr)
		return 1

	results = {
		'queries_planned': len(queries),
		'queries_evaluated': evaluated,
		'query_failures': len(errors),
		'truncated': truncated,
		'elapsed_seconds': round(time.monotonic() - started, 1),
		'mrr': round(reciprocal_rank / evaluated, 4),
		**{f'recall_at_{k}': round(hits[k] / evaluated, 4) for k in RECALL_AT_K},
	}

	print('\n=== Benchmark results ===')
	for k in RECALL_AT_K:
		print(f'Recall@{k}: {results[f"recall_at_{k}"]:.4f} ({hits[k]}/{evaluated})')
	print(f'MRR: {results["mrr"]:.4f}')
	print(f'Evaluated {evaluated}/{len(queries)} queries with {len(errors)} failures')
	if errors:
		print('First failures:')
		for line in errors[:5]:
			print(f'  {line}')

	args.results.write_text(json.dumps(results, indent=2), encoding='utf-8')

	# a run that evaluated almost nothing is not a result worth publishing
	if evaluated < len(queries) * 0.5:
		print(f'Aborting: only {evaluated}/{len(queries)} queries completed', file=sys.stderr)
		return 1

	return 0


if __name__ == '__main__':
	sys.exit(main())
