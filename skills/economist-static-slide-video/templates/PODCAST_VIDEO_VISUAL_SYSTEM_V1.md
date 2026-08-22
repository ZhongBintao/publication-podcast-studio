# Podcast Video Visual System v2 · vertical-first

Source: `Podcast Video Visual System v1.pptx` (SHA-256
`0eeafbb7a239c0b8bf29f34e711f46e6021cf3ed5b674d1ce292254c916d2c18`).
The full, machine-readable definition is
`podcast-video-visual-system.v1.json`.

## Visual system

The template uses one flat `#262626` background in both landscape and
portrait, white text (`#FFFFFF`), a single red kicker accent (`#D71920`) and
contained magazine imagery. Every image keeps its source aspect ratio; unused
space is letterboxed rather than cropped or stretched.

| Role | English font | Chinese font | Colour |
|---|---|---|---|
| Kicker | Arial | Noto Sans SC | `#D71920` |
| Headline / guide question | Times New Roman | Noto Serif SC | `#FFFFFF` |
| Subtitle / byline | Times New Roman or Arial | Noto Sans SC | `#FFFFFF` |
| English captions | Arial Bold | Noto Sans SC | `#FFFFFF` |
| Chinese captions | Arial Bold for Latin fallback | Noto Sans SC Medium | `#FFFFFF` |

Every paragraph uses the defined line spacing and alignment. Chinese
punctuation is rendered natively, with closing punctuation attached to the
preceding character. The source image uses contain placement and receives no
crop, stretch, rounded corner or shadow.

## Template inventory

| Template | Source slide | Canvas | Purpose |
|---|---:|---:|---|
| `landscape_opening` | 1 | 1280 × 720 | Kicker, bilingual title/subtitle, byline, cover and captions |
| `landscape_guide_questions` | 2 | 1280 × 720 | Two bilingual guide questions, cover and captions |
| `portrait_opening` | 3 | 405.33 × 720 | Contained image, compact bilingual metadata, byline and captions above a reserved bottom 10% platform-detail area |
| `portrait_guide_questions` | 4 | 405.33 × 720 | Two bilingual guide questions, cover and captions |

The `guide_questions` templates show both questions concurrently; they are not
two sequential cards in the source deck. In the landscape template, the
English question text is 24 pt with 110% line spacing, while the Chinese text
remains 18 pt with 125% line spacing. The question groups are shifted upward
and the cover begins at the same top baseline as the first question placeholder.
The opening uses the same top baseline for the red kicker and cover; its left
metadata group is shifted upward without changing internal relative positions.
The canonical positions, font sizes, z-order, fills and content bindings are in
the JSON definition.

## Portrait spacing

The opening uses a compact free-flow stack. The contained image sits near the
top, metadata begins around one third of the frame, and the caption rail ends
at 90% of the frame height. The final 10% remains empty for platform detail
articles or controls. The portrait guide-question state reuses the same image
and caption rail, with two numbered bilingual questions in the information
zone. No top utility text or divider line is rendered.

## Caption treatment

Landscape keeps a fixed caption rail and lays English and Chinese out as one
shared centred vertical flow. Each language has a two-line safe area, 105% line
spacing, zero letter spacing and a fixed 6 px inter-language gap. English uses
Arial Bold and Chinese uses Noto Sans SC Medium, with pure-white fill and no
outline. Caption underlays and all page rails use the same `#262626` background;
unused space therefore remains visually consistent. Portrait uses the same
font/color hierarchy, but its narrower unboxed caption area also caps each
language at two complete lines and adaptively reduces the font to the approved
minimum. The opening has no page or CUE utility markers; guide questions are
prefixed by red `01` and `02` labels, with slightly larger Chinese translations.
English always precedes Chinese.
