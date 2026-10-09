#!/usr/bin/env python3
#
# SPDX-FileCopyrightText: 2026 Nextcloud GmbH and Nextcloud contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
#
"""Build a retrieval corpus and query set for the Context Chat RAG benchmark.

Writes ``<out>/docs/<doc_id>.txt`` for every corpus document and ``<out>/queries.json``
holding ``[{"query": str, "stratum": str, "evidence_list": [doc_id, ...]}, ...]``.

Queries without resolvable evidence are dropped: they can never contribute a hit and
would silently deflate recall.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

# The datasets library is deliberately not used: it pulls in pyarrow, whose wheels
# declare no numpy bound but require numpy >= 2 at runtime, which conflicts with the
# numpy 1.x resolved for the backend's own requirements. Both datasets are published
# as plain JSON/TSV, so the stdlib is enough.
HF_BASE = 'https://huggingface.co/datasets'
MULTIHOP_CORPUS_URL = f'{HF_BASE}/yixuantt/MultiHopRAG/resolve/main/corpus.json'
MULTIHOP_QUERIES_URL = f'{HF_BASE}/yixuantt/MultiHopRAG/resolve/main/MultiHopRAG.json'
FRAMES_URL = f'{HF_BASE}/google/frames-benchmark/resolve/main/test.tsv'

WIKI_API = 'https://en.wikipedia.org/w/api.php'
USER_AGENT = 'nextcloud-context-chat-benchmark/1.0 (https://github.com/nextcloud/context_chat_backend)'
# the extracts API caps whole-article requests at one title per call, so we fetch
# lead sections, which allows the full 20-title batch limit
WIKI_BATCH = 20
WIKI_RETRIES = 4
SEED = 42


def http_get(url: str) -> bytes:
	"""Fetch a URL with retries, following HF's CDN redirects."""
	request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})  # noqa: S310 - fixed https hosts
	last_error: Exception | None = None
	for attempt in range(WIKI_RETRIES):
		try:
			with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
				return response.read()
		except (urllib.error.URLError, TimeoutError) as error:
			last_error = error
			time.sleep(2 ** attempt)
	raise RuntimeError(f'Failed to download {url}') from last_error


def doc_id_for(value: str) -> str:
	"""Stable, filesystem-safe document id."""
	return hashlib.md5(value.encode('utf-8')).hexdigest()[:16]  # noqa: S324 - not security relevant


def stratified_sample(records: list[dict], limit: int) -> list[dict]:
	"""Round-robin over strata so every question type keeps its share of the sample."""
	if limit <= 0 or limit >= len(records):
		return sorted(records, key=lambda r: r['query'])

	buckets: dict[str, list[dict]] = defaultdict(list)
	for record in records:
		buckets[record['stratum']].append(record)

	rng = random.Random(SEED)  # noqa: S311 - sampling, not cryptography
	for bucket in buckets.values():
		bucket.sort(key=lambda r: r['query'])
		rng.shuffle(bucket)

	picked: list[dict] = []
	names = sorted(buckets)
	while len(picked) < limit:
		progressed = False
		for name in names:
			if buckets[name] and len(picked) < limit:
				picked.append(buckets[name].pop())
				progressed = True
		if not progressed:
			break

	return sorted(picked, key=lambda r: r['query'])


def write_corpus(docs_dir: Path, documents: dict[str, str]) -> None:
	docs_dir.mkdir(parents=True, exist_ok=True)
	for doc_id, content in sorted(documents.items()):
		(docs_dir / f'{doc_id}.txt').write_text(content, encoding='utf-8')


def finish(out: Path, documents: dict[str, str], records: list[dict], limit: int) -> None:
	records = stratified_sample(records, limit)
	# only keep documents reachable as evidence plus the full distractor corpus;
	# the corpus is always written in full so retrieval stays realistic
	write_corpus(out / 'docs', documents)
	(out / 'queries.json').write_text(json.dumps(records, indent=2), encoding='utf-8')

	strata = defaultdict(int)
	for record in records:
		strata[record['stratum']] += 1
	print(f'Corpus documents: {len(documents)}')
	print(f'Queries: {len(records)}')
	for name in sorted(strata):
		print(f'  {name}: {strata[name]}')


def build_multihop(out: Path, limit: int) -> None:
	print('Downloading MultiHop-RAG corpus and queries')
	corpus = json.loads(http_get(MULTIHOP_CORPUS_URL).decode('utf-8'))
	queries = json.loads(http_get(MULTIHOP_QUERIES_URL).decode('utf-8'))

	documents: dict[str, str] = {}
	by_url: dict[str, str] = {}
	by_title: dict[str, str] = {}

	for row in corpus:
		url = (row.get('url') or '').strip()
		title = (row.get('title') or '').strip()
		if not url and not title:
			continue
		doc_id = doc_id_for(url or title)
		documents[doc_id] = f'{title}\n\n{row.get("body") or ""}'
		if url:
			by_url.setdefault(url, doc_id)
		if title:
			by_title.setdefault(title, doc_id)

	records: list[dict] = []
	dropped = 0
	for row in queries:
		question_type = row.get('question_type') or 'unknown'
		# null_query rows carry no evidence by design; they test abstention, not retrieval
		if question_type == 'null_query':
			dropped += 1
			continue

		evidence = set()
		for item in row.get('evidence_list') or []:
			doc_id = by_url.get((item.get('url') or '').strip()) or by_title.get((item.get('title') or '').strip())
			if doc_id:
				evidence.add(doc_id)

		if not evidence:
			dropped += 1
			continue

		records.append({
			'query': row['query'],
			'stratum': question_type,
			'evidence_list': sorted(evidence),
		})

	print(f'Dropped {dropped} queries without usable evidence')
	finish(out, documents, records, limit)


def wiki_request(titles: list[str]) -> dict:
	params = {
		'action': 'query',
		'format': 'json',
		'formatversion': '2',
		'prop': 'extracts',
		'exintro': '1',
		'explaintext': '1',
		'exlimit': str(WIKI_BATCH),
		'redirects': '1',
		'titles': '|'.join(titles),
	}
	url = f'{WIKI_API}?{urllib.parse.urlencode(params)}'
	request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})  # noqa: S310 - fixed https host

	last_error: Exception | None = None
	for attempt in range(WIKI_RETRIES):
		try:
			with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
				return json.loads(response.read().decode('utf-8')).get('query', {})
		except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
			last_error = error
			time.sleep(2 ** attempt)

	raise RuntimeError(f'Wikipedia API failed after {WIKI_RETRIES} attempts') from last_error


def resolve_alias(title: str, alias: dict[str, str]) -> str:
	seen = set()
	while title in alias and title not in seen:
		seen.add(title)
		title = alias[title]
	return title


def fetch_wiki_pages(titles: list[str]) -> dict[str, tuple[str, str]]:
	"""Map requested title -> (canonical title, lead section text)."""
	resolved: dict[str, tuple[str, str]] = {}

	for start in range(0, len(titles), WIKI_BATCH):
		batch = titles[start:start + WIKI_BATCH]
		query = wiki_request(batch)

		alias: dict[str, str] = {}
		for entry in query.get('normalized', []):
			alias[entry['from']] = entry['to']
		for entry in query.get('redirects', []):
			alias[entry['from']] = entry['to']

		pages = {}
		for page in query.get('pages', []):
			if page.get('missing'):
				continue
			extract = (page.get('extract') or '').strip()
			if extract:
				pages[page['title']] = extract

		for title in batch:
			canonical = resolve_alias(title, alias)
			if canonical in pages:
				resolved[title] = (canonical, pages[canonical])

		print(f'  fetched {min(start + WIKI_BATCH, len(titles))}/{len(titles)} pages', flush=True)
		time.sleep(0.2)

	return resolved


def title_from_link(link: str) -> str:
	return urllib.parse.unquote(link.rsplit('/', 1)[-1]).replace('_', ' ').strip()


def build_frames(out: Path, limit: int) -> None:
	print('Downloading FRAMES benchmark')
	# csv module default field size cap is too small for the wiki_links column
	csv.field_size_limit(10 * 1024 * 1024)
	text = http_get(FRAMES_URL).decode('utf-8')
	dataset = list(csv.DictReader(text.splitlines(), delimiter='\t'))

	# wiki_links is a *string* holding a Python list literal, not a list
	rows = []
	for row in dataset:
		try:
			links = ast.literal_eval(row['wiki_links'])
		except (ValueError, SyntaxError):
			continue
		if not isinstance(links, list):
			continue
		# reasoning_types is a " | "-joined combination; the leading type keeps the
		# strata coarse enough to stay balanced at small sample sizes
		reasoning = (row.get('reasoning_types') or 'unknown').split('|')[0].strip() or 'unknown'
		rows.append((row['Prompt'], reasoning, links))

	titles = sorted({title_from_link(link) for _, _, links in rows for link in links if link})
	print(f'Resolving {len(titles)} Wikipedia pages')
	# FRAMES ships only links, so the corpus has to be fetched; the full link set is
	# indexed (not just the sampled queries') to keep a realistic distractor pool
	pages = fetch_wiki_pages(titles)
	print(f'Resolved {len(pages)}/{len(titles)} pages')

	documents: dict[str, str] = {}
	title_to_doc: dict[str, str] = {}
	for requested, (canonical, extract) in pages.items():
		doc_id = doc_id_for(canonical)
		documents[doc_id] = f'{canonical}\n\n{extract}'
		title_to_doc[requested] = doc_id

	records: list[dict] = []
	dropped = 0
	for prompt, reasoning, links in rows:
		evidence = {title_to_doc[title_from_link(link)] for link in links if title_from_link(link) in title_to_doc}
		if not evidence:
			dropped += 1
			continue
		records.append({
			'query': prompt,
			'stratum': reasoning,
			'evidence_list': sorted(evidence),
		})

	print(f'Dropped {dropped} queries without usable evidence')
	finish(out, documents, records, limit)


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument('dataset', choices=['multihop-rag', 'frames'])
	parser.add_argument('--out', type=Path, default=Path('benchmark_data'))
	parser.add_argument('--limit', type=int, default=200, help='max queries to keep (0 = all)')
	args = parser.parse_args()

	args.out.mkdir(parents=True, exist_ok=True)
	if args.dataset == 'multihop-rag':
		build_multihop(args.out, args.limit)
	else:
		build_frames(args.out, args.limit)
	return 0


if __name__ == '__main__':
	sys.exit(main())
