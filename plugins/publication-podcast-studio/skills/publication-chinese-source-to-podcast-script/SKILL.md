---
name: publication-chinese-source-to-podcast-script
description: Create a source-linked, natural Chinese two-host podcast script for a verified English publication article or complete short issue, with frozen duration and one bounded compression retry.
---

# Publication Chinese Source-to-Podcast Script

Use after `publication-content-extract` for the `zh-CN` audio variant. Translate
meaning rather than English word order. Preserve every material fact, number,
attribution, condition, judgment and degree of certainty; never add context,
examples, analysis or conclusions.

Short-issue scripts cover every content unit once in `episode_order`. Transitions
may orient the listener but cannot invent a relationship between items. Use
short natural Chinese sentences, familiar Chinese names where established and
official English names where no stable Chinese equivalent exists. Do not emit
Chinese-plus-English aliases, bracketed notes, pinyin or SSML.

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/publication-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  init-production article.json production.json --region AZURE_REGION --aspect-ratio 9:16 \
  --duration-mode target_cap --target-minutes 20 --max-minutes 25 \
  --opening-seconds 8 --asset-dwell-target-seconds 20 --confirmed
"$RUNTIME_PY" skills/publication-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  chinese-request article.json --production production.json > chinese-request.json
"$RUNTIME_PY" skills/publication-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  finalize-chinese article.json chinese-draft.json script.zh-CN.json --production production.json
```

The result has `opening`, `body` and `closing`, then flattens into the canonical
five-field TTS segment contract. Generic wrappers may have empty source links;
source-specific wrapper language must cite verified paragraphs.

The target-cap finaliser estimates duration at 260 readable Chinese characters
per minute. A punctuation failure retries only affected paragraphs once. A
duration failure permits one complete source-preserving compression request.
No minimum duration is enforced, and a second cap failure blocks the branch.
