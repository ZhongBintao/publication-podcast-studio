---
name: economist-static-slide-video
description: Create a source-linked two-state storyboard and render non-animated 16:9 or 9:16 Economist static-slide MP4 files from completed Azure audio and canonical captions.
---

# Economist Static-Slide Video

Use this skill only after the selected `production.json` has completed its
canonical audio WAV and SRT captions. It consumes those frozen artifacts and a
two-question payload from the writing stage; it never regenerates speech,
translation, captions or article images.

## Inputs

- Verified `article.json`, including `issue_cover.file`.
- Completed `production.json` with exactly one selected variant and the
  requested aspect ratio under `output.aspect_ratios`.
- The selected final WAV and matching canonical SRT declared in
  `production.artifacts`. For reviewed `en-zh` packages, also consume
  `caption-cues.en-zh.json`, the authoritative language-separated cue payload.
- The writing-stage `editorial-assets.json`. It is the authoritative source
  for exactly two English guide questions, their Chinese translations and the
  display translations. The legacy guide-question JSON remains supported for
  existing packages. Optional `source_paragraph_ids` retain audit links.

```json
{
  "display": {
    "headline_zh": "如何为未来融资",
    "subtitle_zh": "中国资本市场正在承担习近平的科技雄心"
  },
  "guide_questions": [
    {"question": "Who funds the future?", "translation_zh": "谁为未来融资？", "source_paragraph_ids": ["p001"]},
    {"question": "Can markets adapt?", "translation_zh": "市场能适应吗？", "source_paragraph_ids": ["p002"]}
  ]
}
```

The writing stage owns the wording of the two questions and title translations.
This skill only validates and renders them; it never invents copy.

## Build the storyboard

Run after the final audio exists, because the audio duration is the storyboard
clock. The opening shows first; at the fixed boundary it is replaced by the
two-question slide, which holds through the final audio until a future approved
image-selection policy expands the storyboard.

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/economist-static-slide-video/scripts/static_slide_storyboard.py init-storyboard \
  OUTPUT/production.json OUTPUT/editorial-assets.json OUTPUT/storyboard.json --opening-duration 8
```

The resulting `storyboard.json` requires contiguous `start_seconds` and
`end_seconds`, an approved image asset for every slide, and source paragraph IDs
for any guide-question links supplied by the writing stage. See
`templates/STORYBOARD_SCHEMA.md` for the complete contract.

## Render an MP4

```bash
"$RUNTIME_PY" skills/economist-static-slide-video/scripts/static_slide_storyboard.py render \
  OUTPUT/production.json OUTPUT/storyboard.json --aspect-ratio 9:16
```

The final artifact is deterministic and addressable at
`OUTPUT/video/<variant>/<voice-profile>/<aspect-ratio-with-x>/final.mp4`.
A rerun compares the template, storyboard, audio and SRT hashes and reuses a
valid final MP4.

## Safety and quality gates

- Reject missing audio, captions, article cover, storyboard asset, unsupported
  ratio, invalid cue timeline or non-contiguous slide timing.
- Structured cue timestamps drive reviewed bilingual caption-frame changes.
  `en-zh` renders English above Chinese in one shared centred vertical flow;
  each language independently wraps to complete visual lines. In the 16:9
  layout, the caption rail is fixed while the two language blocks use compact
  105% line spacing and a fixed 6 px inter-language gap. English uses Arial
  Bold and Chinese uses Noto Sans SC Medium, with a maximum of two lines per
  language, zero letter spacing and no justification. The renderer uses a
  16–20 pt adaptive range and balanced two-line wrapping for long cues; it
  never truncates a complete cue or moves its tail into a synthetic next cue.
  White text has no outline, and the caption underlay uses the same #262626 background as the page while the
  unused rail area stays the page background. One-line and two-line cues preserve
  descenders with explicit vertical text insets and do not restore a full-width
  black band. A cue that cannot fit two complete lines at the minimum readable
  size is rejected safely rather than truncated or split. The 16:9
  cover slot is shortened to keep it above the caption area, and the guide
  question pair uses a tighter vertical gap. The portrait layout retains its
  existing adaptive caption behaviour. Legacy SRT packages remain supported
  with their original text and timing, but are never re-partitioned.
- Chinese uses native full-width punctuation in Noto Sans SC Regular, with
  STHeiti Medium fallback. Closing punctuation is bound to its preceding
  character and may never begin a rendered line. Each video writes
  `render-report.json` with actual font, caption line boxes and safe-layout
  validation, recorded with a hash in `production.json`.
- Caption generation preserves approved cue text exactly. It never appends a
  full stop or other terminal punctuation; punctuation is present only when it
  is present in the approved source/caption text.
- The renderer uses no external services and writes no credentials.
- The implementation is intentionally non-animated: no avatar footage,
  background music, sound effects, generated imagery or transitions.
