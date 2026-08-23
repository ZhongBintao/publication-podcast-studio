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

新稿采用与英文一致的 5.3 开闭环结构。开头用两至四个短段落完成“来源锚定的
内容钩子—收听价值—正文承接”，不能从“欢迎收听”、节目名或照念标题开始；
结尾用两至四个短段落完成“来源支持的回收—回扣开头—自然告别”，最后的告别
不带事实和来源链接。短刊以头条首段为锚点，但不得把互不相关的条目写成同一条
因果链。

结构、标点或数字问题只允许一次定向 `retry-request`；当问题只在开头或结尾时，
返回的补丁不得改动正文，`apply-retry` 也只替换被点名的 wrapper。

The target-cap finaliser estimates duration at 260 readable Chinese characters
per minute. A punctuation failure retries only affected paragraphs once. A
duration failure permits one complete source-preserving compression request.
No minimum duration is enforced, and a second cap failure blocks the branch.
