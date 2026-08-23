---
name: economist-podcast-studio-workflow
description: Run the complete Economist article-to-podcast-video workflow with a vertical-first, local-only execution path that reuses completed artifacts and renders the approved 9:16 template.
---

# Economist Podcast Studio Workflow

This is the top-level entrypoint for one frozen article production request. It
coordinates the existing extraction, writing, media and static-slide stages;
it does not replace their artifact contracts.

## Required startup confirmation

Before any article extraction, script generation, Azure request, caption build
or video render, confirm the complete production request with the user in the
Codex conversation. Present these multi-select choices:

- `中文播客`: Chinese audio with Chinese captions (`zh-CN`).
- `英文播客`: English audio with English captions (`en`).
- `中英字幕`: English audio with reviewed bilingual captions (`en-zh`).
- Aspect ratios: `9:16` and/or `16:9`.

Chinese captions are included in the Chinese podcast choice. Do not present
`仅英文字幕` as a separate user-facing product: it is the same visible
English-audio/English-caption output as `英文播客` in the current renderer.
Titles and descriptions are always part of the confirmed request. Generate a
release cover only for each selected aspect ratio; when both ratios are
selected, produce both matching covers.

Show the selected products, ratios, mandatory title/description output and
matching cover outputs in one summary. Do not begin any production stage until
the user explicitly confirms. If the user changes a choice, show the revised
summary; if the user cancels, stop without changing production state.

The default output is the approved 9:16 vertical template. A run may also
request 16:9 for comparison, but the vertical output is the canonical current
layout. The portrait renderer uses a contained image slot, reduced metadata,
source-linked bilingual captions, and a reserved bottom 10% platform-detail
safe area. The opening always uses the verified issue cover from PDF page one.
After the opening, the content layout rotates through verified article photos
and charts in source order, falling back to the issue cover only when no article
media exists. The two-question content page targets 20 seconds per image and
must remain within 18–22 seconds after even distribution. A short programme
shows every asset exactly once and records its exception. There are no crops,
animations or transitions. The opening has no read-time field. There are no top utility
labels or decorative divider lines.

## Local-first execution

Run the workflow with the bundled Python runtime:

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/economist-podcast-studio-workflow/scripts/economist_podcast_studio_workflow.py run \
  OUTPUT/articles/ARTICLE-DIRECTORY --local-only --variant en-zh --aspect-ratio 9:16
```

The local-only path validates and reuses verified article data, frozen scripts,
reviewed captions, existing WAV audio and editorial assets; it then rebuilds
the issue-cover opening plus article-media storyboard if needed and renders MP4 locally with ffmpeg. It
never calls Azure Speech, a translation provider, an image service or a
language model.

After confirmation, the workflow may execute more than one selected product.
It maps the choices to the existing `en`, `en-zh` and `zh-CN` stage contracts,
reuses the shared English script/audio for the two English products, and writes
an independent output for every product × aspect-ratio combination. The
Python entrypoint accepts repeated `--product` values and requires
`--confirmed` for this new matrix interface; the legacy single `--variant`
interface remains supported.

If canonical audio or aligned captions are missing, the workflow stops at the
media stage and writes a report naming the exact missing artifact. The current
media skill has no local TTS/alignment substitute, so synthesising or aligning
new audio remains the only externally dependent step. Existing completed media
can still be reused without any external call.

All language products require the same packaged opening/middle/ending music
rules. Before video rendering, the workflow verifies that the canonical mixed
audio differs from the voice track, every played music section is above
`-45 dBFS`, and no PCM clipping was recorded. `zh-CN` is not exempt. The video
renderer does not remix; it muxes this already-approved canonical track.

## Frozen budgets and gates

- Exactly two guide questions are required; each English question must contain
  8–22 words.
- English caption units must be no longer than 84 characters and Chinese units
  no longer than 48 characters.
- Each language renders in at most two complete visual lines. A cue that does
  not fit at the portrait minimum font size is rejected; it is never truncated
  or silently repartitioned.
- Every image is placed with `contain`, preserving the source aspect ratio.
- Every visible source image has a 3 px white border around the actual contained
  image bounds, not around any letterbox area.
- Existing article media must appear in strict source-order round-robin; any
  content-page issue-cover fallback is a failure when verified article media
  exists.

The workflow writes `workflow-report.json` in the article package. It records
the frozen request, local/external execution mode, reused artifacts, rendered
outputs and any blocking reason without storing credentials. Schema 1.1 also
records Chinese framing quality, background-music audibility and ducking
metrics, normalized media rotation, sequence and actual dwell range.
