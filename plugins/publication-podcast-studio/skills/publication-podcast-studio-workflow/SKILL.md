---
name: publication-podcast-studio-workflow
description: Top-level workflow for converting one English-language publication article or complete short issue into confirmed bilingual podcast-video products with local artifact reuse and deterministic rendering.
---

# Publication Podcast Studio Workflow

This is the only top-level entrypoint. It coordinates extraction, writing,
Azure media and static video without changing their artifact contracts.

Before production, run the extraction preflight and confirm one frozen request:

- content mode: one selected `article` or complete `short_issue`;
- confirmed publication name, type, date/number when available;
- products: `en`, `en-zh` and/or `zh-CN`;
- aspect ratios: `9:16` and/or `16:9`;
- duration: target plus hard cap, or `coverage_unbounded`;
- video timing: 8-second opening and 20-second asset dwell by default;
- title, description and matching release covers.

Do not ask for item-by-item approval in short-issue mode. Lead selection,
episode order, complete paragraph coverage and layout safety are automated
gates after the single confirmation.

English and Chinese writing both use the policy-5.3 framing arc. The opening
must move from a lead-source hook to listening value and a body handoff; the
closing must move from a source-supported payoff to an opening callback and a
source-free sign-off. A failed wrapper receives one wrapper-only rewrite, so a
good body is never regenerated merely to repair an introduction or ending.

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/publication-podcast-studio-workflow/scripts/publication_podcast_studio_workflow.py run \
  output/publications/PACKAGE --local-only --product en-zh \
  --aspect-ratio 9:16 --confirmed
```

The local-only path reuses verified source data, scripts, reviewed captions,
WAV audio, alignment and approved assets. It never calls an external provider.
If canonical media is missing, it stops with a report naming the artifact that
requires the Azure stage.

For a short issue, alignment is mandatory because it is the chapter clock.
Every aligned content unit must appear once in episode order; returning to an
earlier unit or crossing a unit boundary in one segment is invalid. Rendering
uses unit-owned media and meaning-first Chinese display copy.

The workflow writes `workflow-report.json`, preserves per-product/per-ratio
paths and hashes, and reuses unchanged outputs. `production.json` remains the
only run configuration and state file. Historical single-article packages are
read through the compatibility normalizer rather than rewritten.
