# Static-Slide Storyboard Contract v2.0

`storyboard.json` is the only slide-plan input. Captions remain in canonical
caption artifacts and timing remains locked to the final WAV.

```json
{
  "format": "publication-static-slide-storyboard",
  "schema_version": "2.0.0",
  "content_mode": "short_issue",
  "publication": {"name": "City Ledger", "kind": "newspaper"},
  "content_units": [{"content_unit_id": "lead", "episode_order": 1}],
  "media_policy": {
    "opening": "front_page_required",
    "content": "alignment_chapters_with_unit_assets",
    "target_seconds_per_asset": 20.0,
    "fallback": "front_page_when_content_unit_has_no_assets"
  },
  "slides": [
    {"id": "opening", "template_role": "opening", "start_seconds": 0, "end_seconds": 8, "asset": {"role": "front_page", "file": "assets/front-page.png"}, "source_paragraph_ids": []},
    {"id": "lead-001", "template_role": "issue_item", "content_unit_id": "lead", "start_seconds": 8, "end_seconds": 28, "asset": {"role": "content_asset", "file": "assets/lead.png", "caption": "Verified source caption", "credit": "Source credit when present"}, "source_paragraph_ids": ["p001"]}
  ]
}
```

- Slides start at zero, are contiguous and end at the final audio duration.
- The opener uses the exact verified `front_page.file`.
- Article content roles are `guide_questions`; short-issue roles are
  `issue_item` and require `content_unit_id`.
- A short-issue content asset must belong to the same unit as its slide. The
  front page is legal only when that unit has no approved asset.
- Optional `caption` and `credit` fields are copied only when present in the
  verified source asset. The renderer displays those source fields and never
  invents an image attribution.
- Unit chapter boundaries come from source-linked canonical alignment segments
  in episode order. A segment cannot cross units and the script cannot return
  to a previous unit.
- `subtitle_mode=en-only` is a presentation-only compatibility projection and
  is invalid for `zh-CN`.
