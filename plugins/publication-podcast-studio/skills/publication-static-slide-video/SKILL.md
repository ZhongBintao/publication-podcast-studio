---
name: publication-static-slide-video
description: Build and render collision-safe 9:16 or 16:9 static-slide podcast videos for one publication article or a complete short issue, using frozen audio, alignment, captions, front-page evidence, and unit-owned media.
---

# Publication Static-Slide Video

Use only after canonical audio, alignment, captions and
`editorial-assets.json` exist. This stage is local and deterministic; it never
calls a model, TTS, OCR or translation provider.

## Storyboard modes

- `article`: show the verified front page for the opener, then rotate approved
  article images/charts with the two editorial guide questions.
- `short_issue`: use canonical alignment to create one contiguous chapter per
  content unit in frozen episode order. Each chapter shows the current item's
  metadata and only that item's media. When that item has no media, use the
  front page; never borrow an image from another item.

Opening duration and asset dwell come from frozen `production.video_timing`.
The final duration is always the audio duration.

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/publication-static-slide-video/scripts/static_slide_storyboard.py init-storyboard \
  production.json editorial-assets.json storyboard.json
"$RUNTIME_PY" skills/publication-static-slide-video/scripts/static_slide_storyboard.py render \
  production.json storyboard.json --aspect-ratio 9:16
```

## Collision-safe typography

The renderer does not trust independent fixed title boxes. It loads the real
resolved fonts, measures every glyph, wraps complete text, jointly shrinks
opening metadata, and flows title/Chinese title/standfirst/byline through one
shared safe region. Guide questions are solved inside their own measured safe
regions. Captions use the same font-aware adaptive layout.

Every generated frame records actual glyph boxes. A local geometry gate rejects
out-of-bounds text or any intersection between different text layers before
ffmpeg runs. This is part of the first render pass and uses no model tokens.
Text is never truncated or repaired after video generation.

Outputs remain addressable at
`video/<variant>/<voice-profile>/<aspect-ratio-with-x>/final.mp4` (or the
`en-only` namespace for that compatibility projection). Hashes include the
template, storyboard, audio, captions, renderer and every visual asset.
