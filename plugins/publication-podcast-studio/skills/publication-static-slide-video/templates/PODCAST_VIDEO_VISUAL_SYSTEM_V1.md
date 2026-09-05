# Publication Video Visual System v3 · Editorial Modern

The machine-readable base geometry remains in
`podcast-video-visual-system.v1.json` for path compatibility. Its internal
definition is schema `3.1.0`; actual font metrics feed the constraint-flow pass
described in `../DESIGN.md`.

| Template | Canvas | Purpose |
|---|---:|---|
| `landscape_opening` | 896 × 504 | Editorial Modern metadata, contained source image and captions |
| `landscape_guide_questions` | 896 × 504 | Two red-numbered bilingual questions and unit media |
| `portrait_opening` | 360 × 640 | Upper cover, flowed metadata and platform-safe captions |
| `portrait_guide_questions` | 360 × 640 | Upper unit media, two red-numbered questions and captions |

Short-issue item slides render through the relevant opener geometry with the
current item's metadata and its own source media. Article slides use the
guide-question geometry. All images use contain placement, two soft shadows and
no border.

English captions use Helvetica Bold; Chinese captions use Noto Sans SC Bold.
Each language may occupy at most two complete lines. The renderer measures
descenders, keeps native CJK punctuation attached, preserves approved
punctuation, and never truncates text or inserts an ellipsis. If the minimum
readable size cannot fit, the render fails with diagnostics.
