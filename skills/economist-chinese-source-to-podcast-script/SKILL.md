---
name: economist-chinese-source-to-podcast-script
description: Turn a verified Economist article into a source-linked, natural Chinese two-host podcast script and Chinese editorial assets for the selected zh-CN production variant.
---

# Economist Chinese Source-to-Podcast Script

Use this skill after `economist-article-subtract` and before Azure Speech
production. It is the dedicated Chinese writing stage for the `zh-CN`
variant. The writing model translates and orally adapts verified English in one
pass; it does not produce a literal translation, SSML, pronunciation markup or
unsupported host commentary.

## Quality target

The script should sound like two prepared Chinese hosts talking through a
reported story. Follow the successful English writing profile:

- use short, direct, read-once Chinese sentences;
- reorder clauses and split dense English sentences when Chinese requires it;
- use light spoken connectors sparingly, without adding claims;
- allow source-linked prompts, answers and short reactions;
- use the policy-5.3 three-turn opening and two-turn closing around the
  source-linked body;
- keep every factual, prompt and reaction segment traceable to one verified
  source paragraph;
- preserve every material fact, number, attribution, condition and judgment;
- never add an example, explanation, prediction, conclusion or host opinion.

## Translation and mixed-language policy

Translate meaning rather than English word order. Use a common Chinese name or
term when it has a stable, familiar Chinese usage. Keep the original English
for brands, products, institutions, acronyms and technical names when there is
no reliable common Chinese equivalent. Do not write duplicate aliases such as
`中文名（English name）`, comma-wrapped abbreviations, bracketed notes or TTS
pronunciation hints.

English tokens in `spoken_text` are intentional read-as-written content. Keep
official spelling and casing, avoid long English clauses, and do not add SSML,
pinyin, phonetics or markup. The downstream Chinese voice is expected to
handle short Chinese-English mixed phrases.

## Commands

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3

"$RUNTIME_PY" skills/economist-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  init-production ARTICLE.json production.json --region AZURE_REGION --aspect-ratio 9:16 --aspect-ratio 16:9

"$RUNTIME_PY" skills/economist-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  chinese-request ARTICLE.json > chinese-request.json

"$RUNTIME_PY" skills/economist-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  finalize-chinese ARTICLE.json chinese-draft.json script.zh-CN.json

"$RUNTIME_PY" skills/economist-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  validate ARTICLE.json script.zh-CN.json
```

The writing request returns an object with `opening`, `body` and `closing`
arrays. The finalizer flattens them into one TTS-ready script in that order.
For backwards compatibility, a body-only array is still accepted. New policy
5.3 drafts use exactly three `opening` turns in `primary`, `secondary`,
`primary` order and two `closing` turns in `primary`, `secondary` order. The
first opening turn is a concrete hook linked only to the first two source
paragraphs and must not start with `欢迎收听`, `本期节目` or `今天我们来聊`.
The second turn is a source-linked natural question; the third is a short
bridge. The first closing turn cites only the final three source paragraphs and
separates what is known from what remains unsettled; the second is a generic
sign-off with empty source links. Every wrapper turn is at most 48 readable
characters, with 144 characters for the opening and 72 for the closing.

For articles with 20 or more source paragraphs, include at least four
`prompt` → other-host factual-answer pairs, with one pair in each quarter of
the source paragraph sequence. Factual character share remains within 40–60%
and no host may speak more than three consecutive segments.

Before freezing a new draft, run one compact wrapper-only polish pass. It sends
only the current wrappers, their cited source paragraphs and the first and last
body turns; it never resends the full article:

```bash
"$RUNTIME_PY" skills/economist-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  framing-polish-request ARTICLE.json chinese-draft.json > framing-polish-request.json

"$RUNTIME_PY" skills/economist-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  apply-framing-polish ARTICLE.json chinese-draft.json framing-polish-draft.json script.zh-CN.json
```

This one pass checks the hook, core question, body bridge, known-versus-
unsettled conclusion, opening-to-closing callback and separation of factual
summary from the sign-off. A failed polished wrapper is rewritten once; a
second failure blocks the Chinese writing stage.

If validation fails, `retry-request --attempt 1` identifies only affected
source paragraphs or wrapper sections. Apply the returned patch with
`apply-retry`; unchanged body or wrapper sections are preserved, and a second
failure blocks the Chinese branch.

The same skill owns Chinese video and publication copy, using a separate
compact request so a script failure never invalidates already-valid editorial
copy:

```bash
"$RUNTIME_PY" skills/economist-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  chinese-editorial-request ARTICLE.json > chinese-editorial-request.json

"$RUNTIME_PY" skills/economist-chinese-source-to-podcast-script/scripts/chinese_source_to_podcast_script.py \
  finalize-editorial ARTICLE.json chinese-editorial-draft.json editorial-assets.json --production production.json
```

## Output contract

The spoken script contains exactly `segment_id`, `speaker_id`, `kind`,
`spoken_text` and `source_paragraph_ids`. IDs are assigned deterministically by
the finalizer as `zh-CN-001`, `zh-CN-002`, and so on. A new script is ordered as
opening, source-linked body, closing; Chinese audio consumes this final text
directly and the existing Azure timeline includes all three parts. It must not
contain SSML or secret/provider data.

The validator rejects a wrong wrapper turn count or speaker order, a missing
opening question or source link, programme-boilerplate hooks, a combined
factual-summary/sign-off turn, a hook that repeats the first factual body turn,
and missing four-quarter interactions for a long article. Its validation result
includes a `framing_quality` record for the workflow report.

`editorial-assets.json` remains the shared article-level publishing artifact.
For `zh-CN`, its English question fields are compatibility metadata only; the
Chinese video template renders `translation_zh` and the Chinese display fields.
The editorial draft returns only `publication.title_body_zh`; it must be a
12--28-character content-based distillation rather than a direct translation of
the English headline. The shared finaliser adds the fixed Economist/podcast
format markers and rejects repetition of the Chinese display headline.
