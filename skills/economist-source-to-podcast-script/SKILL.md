---
name: economist-source-to-podcast-script
description: Turn a verified Economist article package into a source-linked, conversational script for one selected English, bilingual-caption, or Chinese podcast variant. Use after economist-article-subtract before Azure Speech production.
---

# Economist Source to Podcast Script

Use only a verified `article.json`. Create and validate frozen scripts before
audio synthesis. Keep final scripts as JSON; a later Azure TTS skill renders
per-segment SSML in memory and never asks AI to create SSML.

## Spoken delivery profile

The spoken script should sound like two well-prepared hosts talking through a
reported story, not like an article being read aloud. Use the supplied
reference transcript as a style guide for rhythm: short turns, relaxed
connectors, occasional emphasis, and natural questions and responses. Recreate
those delivery qualities without copying its content or inventing a host
exchange.

The style boundary is deliberately narrow:

- Treat the supplied paragraph as the evidence boundary, not a wording
  template. The English writing stage may paraphrase, condense, reorder related
  clauses, merge or split sentences, and turn dense nominal or parenthetical
  constructions into natural spoken wording.
- Do not invent any factual proposition, sentence, quotation, number,
  attribution, causal link, evaluation, example, prediction, analogy,
  conclusion or host viewpoint that is not supported by the supplied source.
- Prefer short, direct clauses. Never use a noun followed by a comma and a
  dangling explanatory phrase. Integrate necessary context into a complete
  spoken clause or use two natural sentences.
- English may use contractions and a small set of non-factual discourse
  markers: `well`, `so`, `right`, `you know`, `I mean`, `actually`, `honestly`,
  `exactly`, `okay`, `look`, `sure`, `of course`, and `basically`. Use them
  sparingly, usually no more than one short marker every two or three
  sentences. Never force a filler into every segment or repeat the same one.
- Chinese may use light spoken connectors such as “其实”“你看”“问题是”“确实”
  and “说白了” when they do not add a new claim. Keep Chinese sentences short,
  natural and read-as-written; do not translate the English fillers literally.
- English `source_speaker_id` and `partner_speaker_id` are suggested roles, not
  fixed assignments. Both hosts may deliver factual units from one paragraph.
  Aim for 45--55% of total English words per host and keep normal-length
  scripts within 40--60%. Avoid more than three consecutive segments by one
  host. A prompt immediately precedes a factual answer from the other host;
  reactions remain short, source-linked and free of new claims or viewpoints.

The validator treats only the approved English markers above as removable
delivery language. Any other added English content is a source-fidelity error.

## Workflow

1. Initialise the no-secret production config with the single requested output
   variant. Do not generate scripts for an unselected language:

   ```bash
   RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py init-production ARTICLE.json production.json \
     --variant en --region AZURE_REGION --aspect-ratio 16:9
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py english-request ARTICLE.json > english-request.json
   ```

   Have the writing model return only a body-array draft using the supplied
   `source_paragraph_id`, `source_speaker_id`, `partner_speaker_id`, the
   supplied speaker-balance parameters, the two character budgets, and the five
   script fields. Apply the oral
   delivery profile above, then freeze it with:

   ```bash
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py finalize-english \
     ARTICLE.json english-draft.json script.en.json
   ```

   If finalisation reports an English speaker-balance failure, make at most one
   compact repair request using the reported word counts and repairable factual
   segment IDs. Reassign or lightly reshape only those turns; do not regenerate
   the whole article. Run `finalize-english` once more. A second balance failure
   blocks the English branch.

   The legacy `english ARTICLE.json script.en.json` command remains as a
   deterministic source-preserving fallback for fixtures and recovery. For
   production, `english-request` plus `finalize-english` is the path that
   enables the reviewed conversational rewrite. Variants: `en` creates
   `script.en.json`; `en-zh` creates `script.en.json` plus a reviewed subtitle
   script before media production; `zh-CN` creates only `script.zh-CN.json`
   using steps 2--4.

2. For `zh-CN` only, emit the compact Chinese source payload. It has source IDs and cleaned
   verified English only; it does not contain English TTS punctuation changes:

   ```bash
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py translation-request ARTICLE.json
   ```

   Translate every paragraph faithfully into a source-linked body-only JSON
   array. Use the five script fields and preserve the supplied `speaker_id`
   for each paragraph. Preserve facts, numbers, attribution, conditions and
   judgments. Do not add a title, introduction, conclusion, explanation,
   question, response or commentary. Translate meaning rather than English
   word order: split or merge sentences, reorder clauses inside the same
   source paragraph, and use natural Chinese subjects and connectors when
   needed for spoken flow. Prefer common Chinese names. A proper name may
   remain as bare English only when that is natural; never write
   Chinese-plus-English aliases, parentheses, bracketed notes, or comma-wrapped
   names and conversions.

3. Freeze the Chinese script deterministically. This reassigns IDs while
   preserving the paragraph-level `speaker_id` assignments:

   ```bash
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py finalize-zh ARTICLE.json zh-body.json script.zh-CN.json
   ```

4. Validate the selected script. For `en` and `en-zh`:

   ```bash
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py validate ARTICLE.json script.en.json --language en
   ```

   For `zh-CN`:

   ```bash
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py validate ARTICLE.json script.zh-CN.json --language zh-CN
   ```

   If Chinese punctuation validation fails, generate one minimal retry payload
   and retry only its source paragraphs. Apply the returned body-only patch,
   then validate again. A second failure blocks that language.

   ```bash
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py retry-request ARTICLE.json script.zh-CN.json --attempt 1
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py apply-zh-retry ARTICLE.json script.zh-CN.json zh-retry-body.json script.zh-CN.json
   ```

5. For `en-zh`, print the compact source-linked caption request after freezing
   `script.en.json`. Each already-complete frozen spoken segment becomes one
   immutable subtitle unit: the stage never joins adjacent audio segments back
   into a long sentence. Have the writing model return only each supplied
   `unit_id` and its natural `translation_zh` for the final English wording; it
   must not restore omitted source wording or add unsupported content.
   `finalize-subtitles --production` runs the actual video
   renderer's bilingual safe-area preflight before Azure TTS, and reports only
   the failing unit IDs and aspect ratios for a minimal rewrite.

   ```bash
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py subtitle-request \
     ARTICLE.json script.en.json > subtitle-request.en-zh.json
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py finalize-subtitles \
     ARTICLE.json script.en.json subtitle-draft.en-zh.json subtitle-script.en-zh.json --production production.json
   ```

   `subtitle-script.en-zh.json` is the publication-quality Chinese subtitle
   authority. Version 3 contains each captionable English unit, its exact
   source span, reviewed Chinese and paragraph link. The finaliser rejects
   missing coverage, reordered units, line breaks and English clauses; visual
   line wrapping belongs solely to the video renderer.

6. Create the single publishing-asset package once per verified article. First
   emit the compact source-linked editorial request, then have the writing
   model return only its `draft_schema` shape. It must write exactly two
   English guide questions with Chinese translations, Chinese publishing copy
   and three Chinese cover-text lines; every item cites supporting source
   paragraph IDs.

   ```bash
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py editorial-request ARTICLE.json
   "$RUNTIME_PY" skills/economist-source-to-podcast-script/scripts/source_to_podcast_script.py finalize-editorial \
     ARTICLE.json editorial-draft.json editorial-assets.json --production production.json
   ```

   The finaliser validates the source links, fixed publication-title wrapper,
   question depth/length and distinct three-line cover-copy contracts, performs zero-token local OCR on
   `assets/issue-cover.png`, writes `publish-copy.md`, and renders the shared
   `release/covers/cover-16x9.png` and `release/covers/cover-9x16.png` from
   dedicated release-cover safe layouts. Video-opening layouts remain unchanged;
   article metadata, issue cover and art text occupy non-overlapping regions in
   the release covers.
   OCR never uses a filename or external source; if local Tesseract is absent
   or ambiguous, `cover_issue_info.status` is `unavailable` and all other
   publishing assets still complete. It prefers Microsoft YaHei for artwork
   and records the automatic system-font fallback when that font is absent.

## Rules and Azure Handoff

- English may remove visual-navigation phrases, make parentheses and em-dashes
  speakable, split long sentences, use contractions, and recast formal prose
  into source-bounded spoken English. It may paraphrase or condense wording,
  but cannot add unsupported facts or viewpoints. English speaker assignment is
  segment-level so both hosts can share a source paragraph and approach a
  balanced word share.
- Chinese receives original verified punctuation after visual-navigation
  removal. Keep the prose natural and faithful; never inherit English
  punctuation mechanically or translate word by word. Favour short, clear
  spoken sentences and occasional natural Chinese discourse markers. Retain
  every fact while recasting appositives, nominal phrases and clause order
  into idiomatic Chinese.
- Each final segment has exactly `segment_id`, `speaker_id`, `kind`,
  `spoken_text` and `source_paragraph_ids`. `speaker_id` is either `primary`
  or `secondary`. English factual, `reaction` and `prompt` units may use
  either host, while every unit remains linked to exactly one source paragraph.
- The English validator checks structure, complete ordered source coverage,
  segment and caption budgets, complete spoken punctuation, prompt/answer
  alternation, consecutive-turn limits and the 40--60% word-share range for
  normal-length scripts. It no longer requires lexical source-token equality.
  If balance fails, the diagnostic lists word counts, shares and factual
  segment IDs suitable for one targeted speaker-rebalancing retry. Chinese
  keeps its existing paragraph-level speaker and punctuation rules.
- Do not save SSML or put voice IDs, Azure credentials or markup in scripts.
  The Azure media skill consumes the selected validated JSON plus `production.json`, XML
  escapes each segment, constructs `<speak><voice>` SSML in memory, and sends
  it to Azure separately for every spoken segment. English defaults to
  `en-US-Ava:DragonHDLatestNeural` for `primary` and
  `en-US-Andrew:DragonHDLatestNeural` with `temperature=1` for `secondary`.
  For `en-zh`, Azure uses English WordBoundary timing to
  project the reviewed subtitle script onto the final audio. Legacy packages
  may retain Azure Speech Translation as a machine-unreviewed compatibility
  route, never as publication approval.
- `editorial-assets.json` is the authoritative non-spoken publishing artifact.
  It is shared by every language, voice and aspect-ratio output for the same
  article; `production.json.artifacts.editorial_assets` records its relative
  path and `production.json.artifact_hashes.editorial_assets` records its hash.
