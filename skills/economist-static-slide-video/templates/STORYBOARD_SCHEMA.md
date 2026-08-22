# Static-Slide Storyboard Contract v1

`storyboard.json` is the only slide-plan input to the renderer. Timed captions
remain in the canonical SRT; they are not duplicated here.

`production.json.output.subtitle_mode` may be `default` or `en-only`. The
default mode preserves the variant's normal caption projection. `en-only`
renders only the approved English caption field for `en` and `en-zh`; it does
not rewrite the SRT or structured caption cues and is invalid for `zh-CN`.

```json
{
  "format": "economist-static-slide-storyboard",
  "schema_version": "1.0.0",
  "template_definition": "podcast-video-visual-system.v1.json",
  "article_source_sha256": "<verified source hash>",
  "display": {"headline_zh": "可选标题翻译", "subtitle_zh": "可选副标题翻译"},
  "guide_questions": [
    {"question": "English question", "translation_zh": "中文翻译", "source_paragraph_ids": ["p001"]},
    {"question": "English question", "translation_zh": "中文翻译", "source_paragraph_ids": ["p002"]}
  ],
  "slides": [
    {"id": "opening", "template_role": "opening", "start_seconds": 0, "end_seconds": 8, "asset": {"role": "issue_cover", "file": "assets/issue-cover.png"}, "source_paragraph_ids": []},
    {"id": "guide-questions", "template_role": "guide_questions", "start_seconds": 8, "end_seconds": 605.3, "asset": {"role": "issue_cover", "file": "assets/issue-cover.png"}, "source_paragraph_ids": ["p001", "p002"]}
  ]
}
```

- Exactly two guide questions are required; their text must already be approved
  by the writing stage.
- Current v1 supports only `opening` and `guide_questions` roles. Future
  source-image slides will add an explicit role rather than overloading these.
- Slides begin at zero, are contiguous, have positive duration and end at the
  final WAV duration (within 0.05 s).
- Every `asset.file` is package-relative and remains inside the production
  package. Only `issue_cover` and approved `article_asset` roles are legal.
- Display translations may be empty; the vertical renderer keeps the compact
  information stack without restoring the removed utility labels or divider
  lines. All slide images use contain placement and preserve their original
  aspect ratio. The final 10% of a 9:16 frame is reserved for platform detail
  overlays.
