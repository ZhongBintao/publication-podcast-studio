---
name: publication-content-extract
description: Extract either one selected article or every editorial item in a short English-language magazine or newspaper PDF into a verified, publication-aware source package. Use for multimodal page reading, content boundaries, source images, front-page evidence, and downstream podcast production.
---

# Publication Content Extract

Use this as the first production stage. It supports `article` and
`short_issue`; the latter is intended for a complete small newspaper or a
magazine issue with only a few editorial pages. The PDF remains the source of
truth. Use local PDF text only to find pages and prepare evidence, never as the
final copy.

## Freeze the request first

Run a local preflight before model reading:

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/publication-content-extract/scripts/publication_content_extract.py preflight ISSUE.pdf \
  --content-mode short_issue --work-dir tmp/publication-content-extract
```

Show the page count, source-word estimate, front-page preview and recommended
duration to the user. Confirm once: content mode, publication identity,
products, ratios, duration policy, 8-second opener and 20-second asset dwell.
Do not start production before confirmation.

## Prepare visual evidence

For one article, provide a query. For a short issue, omit it and review every
page:

```bash
"$RUNTIME_PY" skills/publication-content-extract/scripts/publication_content_extract.py prepare ISSUE.pdf \
  --content-mode short_issue \
  --publication-name "City Ledger" --publication-display-name "城市纪事" \
  --publication-kind newspaper --issue-date "2026-08-23" \
  --work-dir tmp/publication-content-extract --output-dir output/publications
```

For `article`, add `--query` and optionally `--page-hint`. Resolve ambiguous
article candidates with the user. Short-issue mode creates a review image for
every page and never asks the user to choose each item.

## Scope with vision

Fill the generated scope template using multimodal page reading.

- Article mode: identify the chosen article's exact start, continuations, end,
  metadata, paragraphs and owned media.
- Short-issue mode: identify every editorial item and classify adverts,
  mastheads, furniture and promotional panels as excluded regions.
- Give every included region and approved asset exactly one
  `content_unit_id`.
- Freeze `source_order`, one `editorial_priority=1` lead story, and visual
  evidence for every item boundary. `episode_order` becomes lead first, then
  the remaining items in source order.
- Audit every PDF page exactly once. A page audit must account for all included
  and excluded regions on that page.
- If a boundary, character or asset attribution is uncertain, request a
  bounded high-resolution page escalation. Never guess.

## Assemble, read and finalise

```bash
"$RUNTIME_PY" skills/publication-content-extract/scripts/publication_content_extract.py assemble REVIEW_MANIFEST.json scope.json
"$RUNTIME_PY" skills/publication-content-extract/scripts/publication_content_extract.py expand EXTRACTION_REQUEST.json visual-escalation.json
"$RUNTIME_PY" skills/publication-content-extract/scripts/publication_content_extract.py finalize EXTRACTION_REQUEST.json model-extraction.json
```

Read each layout-context image before its high-resolution regions. Transcribe
complete paragraphs in reading order and attach source-region ids. The model
result must cover every content unit and preserve its region ownership.

The canonical `article.json` is schema 2.0 and contains `content_mode`,
confirmed `publication`, `front_page`, ordered `content_units`, verified
paragraphs and approved assets. Historical single-article packages are
normalised downstream without being rewritten.
