---
name: economist-azure-speech-media
description: Produce exactly one selected Economist podcast audio and subtitle variant with Azure Speech. Supports English captions, English-Chinese bilingual captions, or Chinese captions after the source-to-podcast-script step.
---

# Economist Azure Speech Media

Run this skill after the selected source-to-podcast writing skill, including
`economist-chinese-source-to-podcast-script` for `zh-CN`. The selected
`production.json` variant is the only source of truth; never synthesize an
unselected language or caption variant.

## Prerequisites

The adapter first reads `AZURE_SPEECH_KEY` from the runtime environment. When
it is absent, it safely reads only that key from the workspace-root `.env`
file, without evaluating shell syntax or logging the value. This makes local
desktop runs work without an application restart. Runtime environment variables
take precedence. Do not put credentials in scripts, JSON, SSML, logs, or prompts:

```bash
export AZURE_SPEECH_KEY='...'
```

The local `.env` fallback is for this workspace only; do not pass or copy it to
production artifacts, source control, prompts or external tools.

The Azure region is frozen in `production.json` by the preceding skill. Install
the SDK in the active Python runtime before a live production:

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" -m pip install -r skills/economist-azure-speech-media/requirements.txt
```

## Run

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/economist-azure-speech-media/scripts/azure_speech_media.py production.json
```

## Behaviour

- `en`: synthesizes `script.en.json`, records Azure WordBoundary alignment, and
  writes `audio/en/final.wav`, `alignment.en.json`, `captions.en.srt`, and
  `captions.en.vtt`.
- English `opening` and `closing` segments are accepted around the usual body
  kinds. They use the same ordered TTS, WordBoundary, alignment and caption
  timeline. Their source links may be empty only for generic programme framing;
  English body segments still require exactly one source paragraph.
- `en-zh`: synthesizes the same English script and projects the reviewed,
  source-linked, captionable-unit `subtitle-script.en-zh.json` onto English
  WordBoundary timing.
  It writes `caption-cues.en-zh.json`, `captions.en-zh.srt`, and
  `captions.en-zh.vtt`. Structured cue fields retain separate English and
  Chinese logical text, so video rendering never guesses language identity
  from SRT line count. New packages require subtitle-script schema 3.0 before
  synthesis; no machine phrase is promoted to a reviewed caption pair. Existing
  pre-5.0 packages retain the Azure Speech Translation route only as
  `machine_unreviewed` and `review_required` compatibility output, with each
  original phrase kept intact.
- `zh-CN`: synthesizes `script.zh-CN.json`, records WordBoundary alignment, and
  writes `audio/zh-CN/final.wav`, `alignment.zh-CN.json`,
  `captions.zh-CN.srt`, and `captions.zh-CN.vtt`.

Chinese scripts may contain `opening` and `closing` segments around the usual
source-linked body kinds. They are synthesized in the same ordered segment
loop, routed through the configured primary/secondary voices, and included in
the same alignment and caption timeline. Body segments still require one
source paragraph; wrapper source links may be empty only for generic programme
framing.

The adapter XML-escapes each frozen segment and builds SSML in memory with the
Python Speech SDK's `speak_ssml_async` API. Segment WAVs and WordBoundary
responses are resumable, noncanonical cache data under `.work/`; the final
WAV, alignment, captions, and any translation result are the production
artifacts.

## Default background music

Every successful TTS media run automatically applies the skill's packaged
three-part background-music bed. No extra user command is required. The
default mix keeps the original voice content at full level and uses independent
background gains of `+8 dB` for opening, `+10 dB` for middle and `+8 dB` for
ending. The middle section is intentionally slightly more present than the
opening and ending. If their combination with the voice would clip, peak protection
attenuates only the background and records the applied gains. If a packaged
asset is missing or cannot be decoded, the media run fails instead of silently
producing a video without music.

The default entrypoint is still:

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/economist-azure-speech-media/scripts/azure_speech_media.py \
  OUTPUT/production.json
```

The skill stores its default source files in
`assets/background-music/{opening.mp3,middle-loop.mp3,ending.mp3}`. The
timeline is applied after voice synthesis and before alignment/caption
generation, so the canonical `audio/<language>/final.wav` is the mixed track
consumed by the video renderer. Captions and WordBoundary alignment are
shifted by the six-second voice lead-in and remain on the same absolute clock.

For an explicit rebuild with alternate local music, the post-process command
remains available:

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/economist-azure-speech-media/scripts/azure_speech_media.py \
  OUTPUT/production.json --add-background-music \
  --opening MUSIC_OPENING --middle MUSIC_MIDDLE --ending MUSIC_ENDING \
  --language en
```

The module writes these timeline-aligned tracks:

- `audio/<language>/voice-track.wav`: the human voice padded with six seconds
  of leading silence and any trailing silence needed to share the background
  track's absolute clock.
- `audio/<language>/background-music.wav`: one PCM background track assembled
  from the three supplied files.
- `audio/<language>/final.wav`: the voice and section-gained background tracks
  mixed with voice-preserving peak protection; this is the canonical video
  audio input.
- `audio/<language>/voice-only.wav`: the original concatenated TTS output kept
  for audit and rerun comparison.
- `background-music.<language>.json`: frame-level placements, loop count,
  input hashes, output hashes, requested and applied section gains, and peak
  protection details. Old packages with one `gain_db` remain supported as a
  uniform-gain fallback.

The timing contract is exact at the output sample rate: opening music starts at
frame zero and is cut at six seconds; the middle track starts five seconds
after the voice starts and loops until the ending track starts; the ending
track starts three seconds before the voice ends and may continue after the
voice. Gaps are silence. Input files are normalized to the completed voice
WAV's PCM format; non-WAV inputs require local `ffmpeg`. The static-slide
renderer already consumes the canonical mixed `final.wav`, so every successful
video render carries the background music in its audio stream.

Speech delivery may be configured per language and speaker under
`production.json.speech.delivery`. English defaults use structured DragonHD
voice configuration: Ava is `primary`; Andrew is `secondary` with
`parameters.temperature: 1.0`. DragonHD requests emit only supported voice
parameters and the configured structure; they reject `express-as` and prosody
controls. Legacy string voice configuration and non-DragonHD delivery controls
remain supported. Voice name, voice parameters and delivery settings are all in
the segment fingerprint, so a change rebuilds only affected audio and timing.

Chinese defaults use structured DragonHD voice configuration: Xiaochen is the
`primary` host with `zh-CN-Xiaochen:DragonHDLatestNeural`, and Yunxiao is the
`secondary` host with `zh-CN-Yunxiao:DragonHDFlashLatestNeural`. Both use
`parameters.temperature: 1.0`. Their Azure voice IDs may be retained in
`production.json` as audit metadata, but only the voice name and supported
parameters are sent to SSML. DragonHD and DragonHD Flash accept a temperature
from 0 to 1; this skill does not send Dragon HD Omni-only parameters.

If a required WordBoundary is missing, offsets are non-monotonic, translation
phrases are empty, or cues overlap, the selected run becomes `failed` and no
successful video stage may consume it.

## Local bilingual-caption rebuild

After a reviewed subtitle script is finalised, regenerate bilingual caption
artifacts without Azure TTS or Speech Translation. This uses the existing
English WAV and `alignment.en.json` only:

```bash
"$RUNTIME_PY" skills/economist-azure-speech-media/scripts/azure_speech_media.py \
  OUTPUT/production.json --rebuild-captions
```

The rebuild rejects missing source coverage, timing overlap, invalid source
spans, an incomplete English sentence or captionable clause, or an English
clause embedded in Chinese. It never appends terminal punctuation, truncates
text, divides a reviewed unit, or assigns synthetic equal-duration cue timings.

## Voice comparison

Use the controlled A/B helper only with a runtime-injected Azure credential;
it queries the configured region's live voice list before synthesizing the
same frozen `en-001` sample for every eligible candidate. It writes only
noncanonical comparison WAVs and a scoring report under `.work/`:

```bash
"$RUNTIME_PY" skills/economist-azure-speech-media/scripts/voice_ab.py \
  --region southeastasia --script OUTPUT/script.en.json --out-dir OUTPUT/.work/voice-ab
```

The Aria comparison is a legacy diagnostic only; it does not alter the selected
DragonHD production voices:

```bash
"$RUNTIME_PY" skills/economist-azure-speech-media/scripts/voice_ab.py \
  --mode aria --region southeastasia --script OUTPUT/script.en.json \
  --out-dir OUTPUT/.work/aria-ab
```
