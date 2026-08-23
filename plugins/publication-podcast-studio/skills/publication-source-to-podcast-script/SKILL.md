---
name: publication-source-to-podcast-script
description: Turn a verified publication source package into a source-linked English podcast script, reviewed bilingual subtitle copy, and natural Chinese editorial assets. Supports one article and complete short issues while preserving every verified paragraph.
---

# Publication Source to Podcast Script

Use only a verified `article.json` from `publication-content-extract`. This
skill owns English scripts, reviewed `en-zh` subtitle units and publication
copy. Use `publication-chinese-source-to-podcast-script` for Chinese audio.

## Frozen production request

Initialise exactly one selected variant after the user confirms the request:

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/publication-source-to-podcast-script/scripts/source_to_podcast_script.py init-production \
  article.json production.json --variant en-zh --region AZURE_REGION \
  --aspect-ratio 9:16 --duration-mode target_cap --target-minutes 20 \
  --max-minutes 25 --opening-seconds 8 --asset-dwell-target-seconds 20 --confirmed
```

`article` defaults to a 10-minute target and 12-minute cap. `short_issue`
defaults to 20 and 25 minutes. A target is not a minimum: finish early when
coverage is complete. `coverage_unbounded` removes the cap. All verified
paragraphs remain mandatory in either mode.

## English writing

Generate a compact request and finalise the returned JSON:

```bash
"$RUNTIME_PY" skills/publication-source-to-podcast-script/scripts/source_to_podcast_script.py english-request article.json --production production.json > english-request.json
"$RUNTIME_PY" skills/publication-source-to-podcast-script/scripts/source_to_podcast_script.py finalize-english article.json english-draft.json script.en.json --production production.json
```

Write prepared two-host speech, not an article read-through. Paraphrase,
condense and reorder clauses within the supplied evidence, but never add a
fact, attribution, causal link, evaluation, example, prediction or conclusion.
Every body segment cites exactly one verified paragraph. Short-issue scripts
cover content units once in frozen episode order and use natural transitions;
do not invent relationships between neighbouring items or mechanically read
every headline aloud.

New scripts use the framing arc frozen in policy 5.3. The opening contains two
to four short turns: enter through a source-linked hook anchored to the first
lead paragraph, establish listening value, then hand directly to the body. The
closing contains two to four short turns: give a source-supported payoff, call
back to the same anchor, then end with one source-free natural sign-off. Generic
greetings, title-reading and a stock farewell used as the whole wrapper fail
the writing contract.

If only this framing arc fails, do not regenerate the body. Run
`english-framing-retry-request --attempt 1`, generate only the requested
`opening` and/or `closing` arrays, then apply them with
`apply-english-framing-retry`. A second framing retry is blocked.

The target-cap finaliser estimates duration at 150 English words per minute.
If the hard cap is exceeded, run `duration-retry-request --attempt 1`; this is
the only automatic compression retry. It may condense wording but may not drop
a paragraph or content unit. A second failure blocks production or requires a
new user-confirmed cap.

## Meaning-first Chinese editorial copy

Run `editorial-request`, then `finalize-editorial`. Chinese headlines,
standfirsts and guide-question translations are editorial transcreation, not
word-for-word translation. Preserve the core meaning, facts, stance and degree
of certainty, while freely changing clause order, subjects, idioms and length
to sound native in Chinese. Never mirror awkward English syntax or strengthen
the claim.

The request silently compares multiple Chinese phrasings and returns the best
one. Each short-issue content unit receives its own `content_unit_display`.
Guide question one belongs to the lead item; question two belongs to the
highest-priority remaining item. All copy remains source-linked.

## Bilingual subtitles

For `en-zh`, generate reviewed schema-3.0 subtitle units from the frozen
English script. They preserve meaning in natural Chinese and stay within the
renderer budget. Azure phrase translation is historical compatibility data,
not approval. The finaliser runs the real local font/layout engine before TTS,
so unrenderable captions fail before provider cost is incurred.
