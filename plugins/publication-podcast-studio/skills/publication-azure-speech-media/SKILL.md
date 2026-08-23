---
name: publication-azure-speech-media
description: Synthesize one frozen publication podcast variant with Azure Speech, WordBoundary alignment, canonical captions, resumable segment caching, and the packaged background-music mix.
---

# Publication Azure Speech Media

Run after the selected writing skill. `production.json` is the sole routing
contract; never synthesize an unselected variant.

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" -m pip install -r skills/publication-azure-speech-media/requirements.txt
"$RUNTIME_PY" skills/publication-azure-speech-media/scripts/azure_speech_media.py production.json
```

Read `AZURE_SPEECH_KEY` from the environment, or only that key from the
workspace-root `.env` fallback. Never print, persist or copy it. The region and
voice profile come from the frozen request.

- `en` produces English audio, WordBoundary alignment and English captions.
- `en-zh` shares English audio and projects reviewed schema-3.0 sentence pairs
  onto the same alignment.
- `zh-CN` produces Chinese audio, alignment and Chinese captions.

Synthesize each segment separately, copy its `speaker_id`, then concatenate
with cumulative offsets. Exclude sentence callbacks and zero-duration
punctuation events from the word timeline. Missing or non-monotonic word
boundaries fail the run; never estimate canonical subtitles.

Every successful run preserves the voice-only WAV, creates aligned voice and
background stems, mixes the packaged three-source music at -18 dB and writes
the canonical `audio/<language>/final.wav`. Segment cache data is resumable and
noncanonical. Short-issue chapter timing is derived later from this same
alignment, so scripts must remain grouped in frozen content-unit order.
