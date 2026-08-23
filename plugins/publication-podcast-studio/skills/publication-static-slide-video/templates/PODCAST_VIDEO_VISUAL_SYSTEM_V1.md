# Publication Video Visual System v3

The machine-readable base geometry remains in
`podcast-video-visual-system.v1.json` for path compatibility. Rendering is no
longer a literal placement of independent text boxes: actual font metrics feed
the constraint-flow pass described in `../DESIGN.md`.

| Template | Canvas | Purpose |
|---|---:|---|
| `landscape_opening` | 1280 × 720 | Flowed bilingual metadata, source image and captions |
| `landscape_guide_questions` | 1280 × 720 | Two fitted bilingual guide questions and captions |
| `portrait_opening` | 405.33 × 720 | Flowed metadata above captions and the bottom safe area |
| `portrait_guide_questions` | 405.33 × 720 | Two fitted questions above captions and the bottom safe area |

Short-issue item slides render through the relevant opener geometry with the
current item's metadata. Article slides use the guide-question geometry. All
images use contain placement and a 3 px white border around the actual image
edge.

English captions use Arial Bold; Chinese captions use Noto Sans SC Medium.
Each language may occupy at most two complete lines. The renderer measures
descenders, keeps native CJK punctuation attached, uses zero letter spacing and
never appends punctuation or truncates text.
