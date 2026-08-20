# Economist Podcast Studio

## Project Goal

This project turns one Economist article selected by the user from a PDF issue
into a complete bilingual static-slide podcast-video production package.

The user reads the issue and chooses the article. AI then locates the article
in the PDF, extracts and verifies its source material, adapts it conservatively
for spoken delivery, produces audio and subtitles, and renders static-slide
videos.

## Product

Input:

- An Economist PDF issue.
- A user-selected article, identified by its title, topic, or visual location.

Output:

- Verified article metadata: section or column, kicker, headline, subtitle,
  byline or dateline when present.
- Verified English source text and selected article images.
- Source-linked scripts, audio, subtitles and static-slide videos for each
  requested variant, voice profile and aspect ratio.

## Core Principles

1. The user makes all production choices once before a run starts: article,
   one or more output variants, one or more voice profiles, one or more video
   aspect ratios, target duration, output formats and approved defaults. No
   intermediate human approval is required during a normal run.
2. The PDF is the source of truth for English text and source images.
3. Use multimodal reasoning to locate, read, and verify the selected article.
4. Keep verified source material separate from generated translations,
   spoken formatting, audio, alignment and subtitles.
5. Every spoken body segment must remain traceable to verified article
   paragraphs. Do not add facts, explanations, examples, predictions or
   conclusions not supported by those paragraphs.
6. Optimise for one excellent article-to-video workflow, not for processing an
   entire magazine issue automatically.
7. The project has resolved the necessary rights for its source content and
   output use. Do not reopen or repeat copyright analysis unless the user
   explicitly asks for it.

## Current Focus

The article, selected-script, Azure audio, alignment, caption, two-state
storyboard and static-slide MP4 renderer stages are implemented. The next stage
is the orchestrated multi-output request that invokes the completed skills with
shared-artifact reuse.

### August 2026 Real-Production Hold

The `The rise of the deserving rich` package at
`output/articles/2026-07-25-print-the-rise-of-the-deserving-rich/` was used to
test the Aria `newscast-casual` delivery and both static-video ratios. The
current test renders are visual QA artifacts only, not publishable outputs:

- its `en-zh` captions still originate from Azure Speech Translation and are
  marked `machine_unreviewed` / `review_required` in `production.json`;
- the legacy bilingual cues contain semantic truncation and translation-quality
  defects, so do not treat them as an approved subtitle reference;
- the 9:16 opening metadata layout still allows the English and Chinese article
  titles to overlap. This is separate from the subtitle rail and remains
  unresolved;
- subtitle display now has a tested structured reviewed-caption route, centred
  bilingual wrapping and native CJK punctuation rendering, but no further
  changes to this real package should be made until the user explicitly resumes
  the work and supplies or generates reviewed Chinese subtitle units.

The two locally re-rendered MP4s and their `render-report.json` files are kept
for comparison only. They reuse the existing WAV and do not imply a new Azure
TTS run.
The current workflow is:

```text
User-selected variants -> verified source package -> dual-host selected scripts
-> Azure DragonHD segment audio -> WordBoundary alignment and captions
-> static-slide video
```

## First Workflow Skill

Use `skills/economist-article-subtract/` as the completed first workflow step.
It locates a user-selected article locally from the PDF, then uses bounded
multimodal page reading to produce verified English Markdown, source images,
and audit evidence. Preserve whole-page layout context while reading
high-resolution article regions; request a high-resolution full page or stop
for review when any boundary or character remains uncertain. Never send an
entire magazine issue to the model or use extracted PDF text as final copy.

## Implemented Workflow Skills

- `skills/economist-article-subtract/` locates and verifies the selected article
  and produces `article.json` plus source evidence.
- `skills/economist-source-to-podcast-script/` initializes a variant-aware
  `production.json` and produces only the selected script.
- `skills/economist-azure-speech-media/` performs Azure Neural TTS, WordBoundary
  alignment, WAV concatenation, SRT/VTT generation, resumable segment caching,
  and one-session Azure Speech Translation for the `en-zh` variant. English
  defaults use the selected Ava/Andrew DragonHD pair and per-speaker SSML voice
  parameters.
- `skills/economist-static-slide-video/` validates a two-state
  `storyboard.json` and renders non-animated 16:9 or 9:16 MP4 outputs from the
  selected final WAV, canonical SRT, verified article package, issue cover and
  writing-stage guide-question payload. It never calls TTS, translation, OCR,
  image selection or a language model.

The current implementation has offline coverage for all completed skills plus
successful small real Azure checks for the `en` and `en-zh` paths. The video
renderer has an offline WAV/SRT fixture that verifies the two-state storyboard,
caption timing, asset failure behaviour, output addressing and rerun reuse.

## Future Orchestrated Production Request

After all workflow skills are complete, expose one top-level
`economist-podcast-studio-workflow` entrypoint. It must show a brief usage
description, collect all required information in one request, echo the frozen
request for confirmation, and then run automatically without intermediate
approval steps.

The request may select one or more values in each output dimension:

```json
{
  "requested_variants": ["en", "en-zh", "zh-CN"],
  "voice_profiles": ["default"],
  "aspect_ratios": ["16:9", "9:16"]
}
```

`requested_variants` controls which language/caption products are generated.
`voice_profiles` controls which approved primary/secondary voice pairings are
rendered. `aspect_ratios` controls which video layouts are rendered. The
orchestrator must deduplicate shared work: article extraction and scripts are
generated once, an English audio track is shared by `en` and `en-zh`, and a
Chinese audio track is generated only when `zh-CN` is requested.

The final production matrix is the requested variant × voice profile × aspect
ratio combination. Every combination must have an addressable artifact path;
one output must never overwrite another. `production.json` remains the sole
run configuration and state file, with per-variant, per-voice, and per-ratio
progress and artifact hashes. A rerun reuses completed combinations and only
rebuilds combinations invalidated by changed scripts, voices, audio, captions,
or layout settings.

## Original-Faithful Podcast v1

The current script/media skill boundary processes one variant at a time. The
future top-level workflow may request one or more of these variants and invoke
the corresponding branches with shared-artifact reuse:

- `en`: English audio with English-only captions.
- `en-zh`: English audio with one complete English sentence on the first line
  and its reviewed complete Chinese translation on the second line. Sentence
  units are source-linked before synthesis and projected onto WordBoundary
  timing; no Chinese audio script is generated for this variant.
- `zh-CN`: Chinese audio with Chinese captions.

The same verified article package can be reused for any requested combination;
the orchestrator never regenerates shared work unnecessarily.

Audience defaults remain:

- Chinese is for Chinese mainland general-knowledge adult listeners.
- English is for global English-speaking or proficient adult listeners.
- Use one primary host and one secondary host. Both may speak source-linked body
  paragraphs according to the deterministic paragraph-level speaker plan. Do
  not add questions, responses, commentary, conclusions or non-factual hand-offs.
- Target 8--12 minutes per language unless the user freezes another duration
  in the production request.

This is not a commentary, editorial-brief, factual-ledger or free-form
two-host dialogue workflow. The verified article already supplies the content.

### Spoken-Script Rules

Use the lightweight source-to-podcast-script skill after article verification.
It generates only the script required by the selected variant:

- English preserves article paragraph order, facts, numbers, attribution and
  judgments. It may only use `verbatim` and `sentence_split` segments. Final
  English `spoken_text` must not retain parentheses or square brackets:
  convert their content into natural spoken pauses without changing lexical
  content.
- Chinese is a paragraph-by-paragraph faithful spoken translation. It may
  split or merge sentences and reorder clauses within the same paragraph to
  sound natural in Chinese. Preserve every fact, number, attribution,
  condition and judgment; do not add explanation, context, examples, analysis
  or conclusions. Translate meaning rather than English word order, using
  short, clear spoken sentences and natural subjects and connectors.
- Chinese final `spoken_text` is read-as-written TTS copy. Prefer common
  Chinese names; a bare English proper name is permitted when natural, but
  never use Chinese-plus-English aliases, parentheses, bracketed notes or
  comma-wrapped names and currency conversions.
- Each script segment stores only `segment_id`, `speaker_id`, `kind`,
  `spoken_text` and `source_paragraph_ids`. Both speakers may deliver
  source-linked body text. Scripts contain no interaction or transition
  segments, and all segments from one source paragraph use the same speaker.
  For articles with at least two paragraphs, the deterministic plan uses both
  speakers at roughly a two-to-one paragraph ratio; a one-paragraph article is
  not padded just to force a second voice.
  Do not duplicate the full English article in scripts, briefs or prompts.
- The script validator checks complete paragraph coverage, legal segment kinds
  and source references automatically. It also rejects English brackets and
  Chinese brackets, repeated punctuation, and comma-wrapped aliases or money
  conversions. On a Chinese punctuation failure, retry only the affected source
  paragraphs once; a second failure blocks that language. It does not ask for
  an intermediate human review.

For `en-zh`, the writing stage supplies a reviewed, source-linked schema-2.0
sentence subtitle script. Azure Speech Translation phrase output is legacy
`machine_unreviewed` compatibility data only; it cannot establish sentence
pairs and cannot satisfy policy 5.0 publication or rendering requirements.

### Audio and Subtitle Route

Azure Speech Neural TTS is the v1 production provider. Give it only the frozen
source-linked script segments and language-specific voice configuration. Gemini,
ElevenLabs and CosyVoice are optional future adapters, not v1 dependencies.

- The Azure adapter, not an AI model, must XML-escape the frozen segment text
  and construct per-segment `<speak><voice>` SSML in memory. Do not persist
  SSML files or put SSML, voice IDs or secrets into the script JSON.

- English defaults to `en-US-Ava:DragonHDLatestNeural` for `primary` and
  `en-US-Andrew:DragonHDLatestNeural` with `temperature=1` for `secondary`.
  DragonHD synthesis uses the Python Speech SDK's `speak_ssml_async` API so
  WordBoundary alignment remains available. Its SSML must omit unsupported
  `mstts:express-as` and `<prosody>` controls; only approved `<voice>`
  parameters and structural tags may be emitted.

- Use the Python Azure Speech SDK to synthesize Chinese and English WAV audio.
- Set `SpeechServiceResponse_RequestWordBoundary=true` for each synthesis
  request. `WordBoundary` supplies `audio_offset`, `duration`, `text_offset`,
  `word_length` and `text`.
- Azure offsets are 100-nanosecond ticks. Convert them to seconds in the
  canonical alignment data.
- For `en` and `zh-CN`, subtitle text comes from the selected approved script,
  never from ASR. Use `text_offset` and `word_length` to select approved text
  spans, then group them into readable SRT/VTT cues.
- For `en-zh`, each English/Chinese SRT and VTT cue is one reviewed logical
  sentence pair. Its start and end come from the first and last approved
  English WordBoundary across its source spans. Visual line wrapping is never
  written into SRT/VTT. Legacy Azure Translation phrases remain readable only
  for pre-5.0 packages and retain their original text and timing unchanged.
- Generate `alignment.json` once, then derive both `captions.srt` and
  `captions.vtt` from it. Audio and video consumers must use that same timeline.
- Synthesize each spoken segment separately with the voice selected by its
  `speaker_id`, then concatenate audio and add
  the cumulative segment offset to its alignment entries.
- In the current Python SDK test, use `audio_config=None` and save
  `result.audio_data` as WAV. Direct file-output configuration did not deliver
  WordBoundary callbacks in that test; keep an integration test for this
  behavior when upgrading the SDK.
- Python `duration` may be a `timedelta`; convert it explicitly before doing
  arithmetic.
- Request WordBoundary by default. SentenceBoundary events may arrive after
  word events with an earlier offset; exclude sentence events from the word
  timeline or collect them separately before sorting. DragonHD zero-duration
  punctuation callbacks are also excluded from canonical alignment, because
  their offsets may be slightly non-monotonic; punctuation remains in the
  approved script used to build captions.
- If WordBoundary events are missing, offsets are non-monotonic, or caption
  validation fails, mark the language run `failed` and block final rendering.
  Never silently estimate formal subtitles.

The earlier route was verified with Jenny/Guy and Xiaoxiao/Yunxi test voices,
including a real 32-second English sample and a real bilingual
translation-caption sample. The current offline suite also verifies the Ava and
Andrew DragonHD SSML contract; an explicit credential-gated live smoke test
verifies both selected English voices and their WordBoundary events.

Voice IDs are configuration, not data-contract fields. A future production
request may select one or more approved voice profiles, each containing the
primary and secondary host voice for every requested language. Replacing or
adding a voice profile requires re-synthesizing only the affected segments and
regenerating that profile's alignment, SRT, VTT and video; never reuse
timestamps from a different voice profile.

The Free (F0) tier is the default cost target (about 500,000 Neural TTS
characters per month). Keep requests segmented and record the selected tier;
the user's temporary Azure credit is not a permanent free allowance.

### Minimal Production Package

Avoid duplicate intermediate data and prompts. Each selected branch has only
the canonical artifacts required for that variant:

```text
article.json
production.json
en:    script.en.json, audio/en/final.wav, alignment.en.json,
       captions.en.srt, captions.en.vtt
en-zh: script.en.json, subtitle-script.en-zh.json, audio/en/final.wav,
       alignment.en.json, caption-cues.en-zh.json, captions.en-zh.srt,
       captions.en-zh.vtt
zh-CN: script.zh-CN.json, audio/zh-CN/final.wav, alignment.zh-CN.json,
       captions.zh-CN.srt, captions.zh-CN.vtt
```

Artifact handoff is contract-preserving across the whole workflow:

```text
article.json
  -> script.*.json (source_paragraph_ids + speaker_id)
  -> alignment.*.json (same segment_id + speaker_id, cumulative timing)
  -> captions.*.srt/.vtt (same approved segment timeline)
  -> video/.../final.mp4 (selected final WAV + canonical captions)
```

The media stage must copy each script segment's `speaker_id` into alignment
data and resolve its voice from `speech.voices[language][speaker_id]`. A voice
entry may be a legacy name string or a structured `{name, parameters}` object;
the adapter normalizes either form before synthesis. Caption and video stages
must consume the resulting canonical segment timeline; they must not regenerate
scripts, reinterpret speaker assignments, or add dialogue content. `speaker_id`
remains the only speaker-routing field and no new intermediate file is required.

The video stage consumes `storyboard.json` and writes
`video/<variant>/<voice-profile>/<aspect-ratio-with-x>/final.mp4`. Audio and
caption artifacts must use the same voice-profile namespace when more than one
profile is requested.

`production.json` is the sole run configuration and state file. It stores
relative artifact paths, hashes, frozen user choices, provider/model/voice
identifiers, region and SDK/alignment method metadata, resumable segment progress
and non-sensitive failure reasons. For v1, record the provider as
`azure-speech`, the alignment method as `azure_word_boundary`, and the script
generation policy version as `5.0` for the two-host segmented narration
contract.
It must never contain a key, authorization header, signed URL or full secret
request log. State is only `queued`, `running`, `complete` or `failed`.

Credentials normally come from environment variables named `AZURE_SPEECH_KEY`
and `AZURE_SPEECH_REGION`. For local desktop production, the Azure adapter may
fall back to reading only `AZURE_SPEECH_KEY` from the workspace-root `.env`
file when the process environment does not provide it; it must not evaluate
shell syntax, persist the value, log it or copy it to an artifact. Environment
variables take precedence. Never write a key to project `.env` files, code,
configuration, logs, JSON, Markdown, or assistant messages. Never print a key
while testing. The region is supplied by the production request and must not be
hard-coded to a personal resource.

The user confirms the production request once before processing. Then the
orchestrator runs automatically, retries only transient provider failures and
resumes from verified segment artifacts. Use automated quality gates rather
than interactive approval steps.

### Video Boundary

The static-slide skill renders simple non-animated videos from verified article
assets, `storyboard.json`, final audio and the selected canonical caption
timeline. It supports 16:9 and 9:16 from shared content data and does not add
avatar video, dynamic video generation, background music, sound effects or
complex animation.

The v1 storyboard has two contiguous states: an opening metadata slide followed
by a concurrent two-question guide slide. The writing stage supplies the two
questions, their Chinese translations, optional display translations and any
source-paragraph links. The current image slot remains the verified issue cover
until a separate approved image-selection policy expands the storyboard.

The skill accepts `en`, `en-zh` or `zh-CN` from `production.json`, consumes only
that branch's completed audio/SRT artifacts, preserves their timeline, and
never reruns TTS or translation. Each voice profile and aspect ratio has a
separate addressable output and an input-hash reuse record in `production.json`.

### Shared Subtitle Rendering Contract

The shared subtitle renderer and both video entrypoints must apply the same
landscape bilingual caption rules. These rules are presentation-layer rules;
they do not change the upstream source-to-podcast-script wording or editorial
depth.

- English captions use Arial Bold and Chinese captions use Noto Sans SC Medium.
  Font selection performs glyph-coverage checks and records the resolved font
  path and weight in the render report; it must not silently route English
  text through a CJK regular font or fall back from bold without reporting it.
- English and Chinese are laid out as one centred bilingual vertical flow, not
  as two independently centred boxes. Each language may use at most two lines,
  with 105% intra-language line spacing and a fixed 6px gap between language
  blocks.
- Caption layout uses explicit vertical text insets `[6, 0, 6, 0]` in
  top/right/bottom/left order and descender-aware metrics for characters such
  as `g`, `y`, `p` and `q`. This padding is required so the lower parts of
  glyphs are never clipped by the caption region.
- `letter_spacing` is explicitly zero and alignment is centred; justification
  and tracking expansion are not permitted. Captions retain white text, no
  stroke, and the local dark underlay rather than restoring a full-width black
  subtitle bar.
- Long complete cues use balanced two-line wrapping and adaptive readable font
  sizing. The renderer must not truncate a sentence or move a tiny leftover
  tail into a synthetic following cue. If the complete cue cannot fit within
  the safe area at the minimum readable size, rendering fails with diagnostics.
- Caption text is preserved exactly from the approved cue. Code must never
  append a terminal full stop to every cue; punctuation is retained only when
  it is present in the approved source text.
- `preview_visual_system.py` and the legacy
  `render_static_slide_template.py` entrypoint share these font, fallback,
  wrapping, inset, spacing and punctuation constraints. Historical MP4s are
  not batch-rerendered; only the requested production package is regenerated.

### Reference Fixture

The verified `Hope v reality` package at
`output/new-hope/2026-07-04-print-hope-v-reality/` remains a reference fixture.
Its ElevenLabs audio/timing files prove an earlier timing route but do not
define the v1 provider, state model or data contract.

## Azure Speech Test Contract

The minimum offline/API integration fixture for the Azure adapter contains two
Chinese and two English host turns. It must verify:

- successful WAV synthesis for every segment;
- at least one WordBoundary event per segment;
- monotonic segment-local offsets after filtering non-word boundaries;
- correct cumulative offsets after audio concatenation;
- SRT/VTT generation with no overlaps or non-positive cues;
- caption text coverage from the frozen script;
- voice replacement invalidates only audio-dependent artifacts;
- structured DragonHD voice parameters serialize to safe `<voice>` attributes;
- both selected English speakers synthesize with WordBoundary timing;
- missing credentials and transient provider failures fail safely without
  leaking secrets.

The current offline suite covers all three variants, one-session bilingual
translation, invalid boundary failures, cache resume, voice replacement and
DragonHD parameter invalidation. The optional live smoke test runs only when
`RUN_AZURE_SPEECH_LIVE=1` and the Azure key and region environment variables
are present.

## Project Direction

This project will evolve through real productions. Reusable, validated steps
will become plugin skills, scripts, templates, test fixtures, and configuration.
Do not add workflow complexity until it solves a demonstrated production need.
