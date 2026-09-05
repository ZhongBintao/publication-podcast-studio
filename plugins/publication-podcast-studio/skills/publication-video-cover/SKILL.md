---
name: publication-video-cover
description: Generate publication release covers from finished video first frames with a source-linked three-line Chinese text overlay.
---

# Publication Video Cover

Use this stage only after the static-slide video outputs exist. It is local and
deterministic: it extracts the first frame of each selected finished video and
composites the approved three-line `cover_text` as one transparent text layer.
It never creates a second background, recolours the frame, crops the frame or
calls a model, OCR, TTS or translation provider.

The default frame time is `0` seconds. When several products exist, the source
video is selected in this order for each aspect ratio: `en-zh`, `en`, then
`zh-CN`. The extracted frame must already have the requested 16:9 or 9:16
dimensions; no scaling or padding is applied.

The text treatment follows the approved reference style:

- exactly three existing `cover_text` lines;
- line 1: bright yellow `#FFE500`;
- lines 2 and 3: cyan `#12D9FF`;
- heavy Chinese sans-serif face, centred as one vertical stack;
- black outline sized relative to the measured font;
- no background panel behind the text.

Run it directly when re-covering a completed package:

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/publication-video-cover/scripts/publication_video_cover.py render \
  production.json workflow-report.json --frame-seconds 0
```

The stage writes `release/covers/cover-9x16.png` and/or
`release/covers/cover-16x9.png`, updates `editorial-assets.json` and
`production.json` hashes, and returns provenance including the source video
hash, frame time, palette, font and actual overlay line boxes.
