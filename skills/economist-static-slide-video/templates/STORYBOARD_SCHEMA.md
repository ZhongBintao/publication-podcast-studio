# Static-Slide Storyboard Contract v1.1

`storyboard.json` is the only slide-plan input to the renderer. Timed captions
remain in the canonical SRT; they are not duplicated here.

`production.json.output.subtitle_mode` may be `default` or `en-only`. The
default mode preserves the variant's normal caption projection. `en-only`
renders only the approved English caption field for `en` and `en-zh`; it does
not rewrite the SRT or structured caption cues and is invalid for `zh-CN`.

```json
{
  "format": "economist-static-slide-storyboard",
  "schema_version": "1.1.0",
  "template_definition": "podcast-video-visual-system.v1.json",
  "article_source_sha256": "<verified source hash>",
  "display": {"headline_zh": "可选标题翻译", "subtitle_zh": "可选副标题翻译"},
  "guide_questions": [
    {"question": "English question", "translation_zh": "中文翻译", "source_paragraph_ids": ["p001"]},
    {"question": "English question", "translation_zh": "中文翻译", "source_paragraph_ids": ["p002"]}
  ],
  "media_policy": {
    "opening": "issue_cover_required",
    "content": "approved_article_assets_round_robin",
    "target_seconds_per_asset": 20.0,
    "minimum_seconds_per_asset": 18.0,
    "maximum_seconds_per_asset": 22.0,
    "fallback": "issue_cover_when_no_article_assets",
    "animation": "none",
    "transition": "none",
    "image_fit": "contain_no_crop"
  },
  "media_rotation": {
    "normalized_assets": [],
    "sequence": [],
    "actual_dwell_seconds": {"minimum": 20.0, "maximum": 20.0, "values": [20.0]},
    "short_program_exception": false,
    "exception_reason": null
  },
  "slides": [
    {"id": "opening", "template_role": "opening", "start_seconds": 0, "end_seconds": 8, "asset": {"role": "issue_cover", "id": "issue-cover", "file": "assets/issue-cover.png"}, "source_paragraph_ids": []},
    {"id": "content-001", "template_role": "guide_questions", "start_seconds": 8, "end_seconds": 28, "asset": {"role": "article_asset", "id": "photo-1", "article_role": "article_image", "file": "assets/01-photograph.jpg"}, "source_paragraph_ids": ["p001"]},
    {"id": "content-002", "template_role": "guide_questions", "start_seconds": 28, "end_seconds": 48, "asset": {"role": "article_asset", "id": "chart-1", "article_role": "article_chart", "file": "assets/02-chart.png"}, "source_paragraph_ids": ["p002"]}
  ]
}
```

- Exactly two guide questions are required; their text must already be approved
  by the writing stage.
- The first slide must use `opening` and the exact `article.issue_cover.file`.
  Every later slide uses the `guide_questions` content layout and rotates
  through approved article photos and charts in source order. Reusing the issue
  cover after the opening is legal only when the article has no approved media.
- Normal content dwell is 18–22 seconds with a 20-second target. If the content
  duration cannot give every approved asset 18 seconds, each asset appears once
  in source order, time is divided evenly and `short_program_exception` records
  the reason. All other sequences must be strict source-order round-robin.
- Slides begin at zero, are contiguous, have positive duration and end at the
  final WAV duration (within 0.05 s).
- Every `asset.file` is package-relative and remains inside the production
  package. Only `issue_cover` and approved `article_asset` roles are legal.
- Display translations may be empty; the vertical renderer keeps the compact
  information stack without restoring the removed utility labels or divider
  lines. All slide images use contain placement, preserve their original aspect
  ratio and receive a 3 px white border around the actual contained-image edge.
  The final 10% of a 9:16 frame is reserved for platform detail overlays.
