---
name: economist-podcast-studio-workflow
description: Run the complete Economist article-to-podcast-video workflow with a vertical-first, local-only execution path that reuses completed artifacts and renders the approved 9:16 template.
---

# Economist Podcast Studio Workflow

This is the top-level entrypoint for one frozen article production request. It
coordinates the existing extraction, writing, media and static-slide stages;
it does not replace their artifact contracts.

The default output is the approved 9:16 vertical template. A run may also
request 16:9 for comparison, but the vertical output is the canonical current
layout. The portrait renderer uses a contained image slot, reduced metadata,
source-linked bilingual captions, and a reserved bottom 10% platform-detail
safe area. Verified article imagery is preferred over the issue cover, and the
opening has no read-time field. There are no top utility labels or decorative
divider lines.

## Local-first execution

Run the workflow with the bundled Python runtime:

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" skills/economist-podcast-studio-workflow/scripts/economist_podcast_studio_workflow.py run \
  OUTPUT/articles/ARTICLE-DIRECTORY --local-only --variant en-zh --aspect-ratio 9:16
```

The local-only path validates and reuses verified article data, frozen scripts,
reviewed captions, existing WAV audio and editorial assets; it then rebuilds
the two-state storyboard if needed and renders MP4 locally with ffmpeg. It
never calls Azure Speech, a translation provider, an image service or a
language model.

If canonical audio or aligned captions are missing, the workflow stops at the
media stage and writes a report naming the exact missing artifact. The current
media skill has no local TTS/alignment substitute, so synthesising or aligning
new audio remains the only externally dependent step. Existing completed media
can still be reused without any external call.

## Frozen budgets and gates

- Exactly two guide questions are required; each English question must contain
  8–22 words.
- English caption units must be no longer than 84 characters and Chinese units
  no longer than 48 characters.
- Each language renders in at most two complete visual lines. A cue that does
  not fit at the portrait minimum font size is rejected; it is never truncated
  or silently repartitioned.
- Every image is placed with `contain`, preserving the source aspect ratio.

The workflow writes `workflow-report.json` in the article package. It records
the frozen request, local/external execution mode, reused artifacts, rendered
outputs and any blocking reason without storing credentials.
