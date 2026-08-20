# Podcast Video Visual System v1

Source: `Podcast Video Visual System v1.pptx` (SHA-256
`0eeafbb7a239c0b8bf29f34e711f46e6021cf3ed5b674d1ce292254c916d2c18`).
The full, machine-readable definition is
`podcast-video-visual-system.v1.json`.

## Visual system

The template uses one flat `#262626` background in both landscape and
portrait, white text (`#FFFFFF`), a single red kicker accent (`#D71920`) and
white-bordered magazine cover imagery. It uses transparent text boxes with no
outlines.

| Role | English font | Chinese font | Colour |
|---|---|---|---|
| Kicker | Arial | Noto Sans SC | `#D71920` |
| Headline / guide question | Times New Roman | Noto Serif SC | `#FFFFFF` |
| Subtitle / byline | Times New Roman or Arial | Noto Sans SC | `#FFFFFF` |
| English captions | Arial Bold | Noto Sans SC | `#FFFFFF` |
| Chinese captions | Arial Bold for Latin fallback | Noto Sans SC Medium | `#FFFFFF` |

Every paragraph uses 125% line spacing and left alignment. Chinese full stops
(`。`) are rendered as a 70%-size subscript glyph, lowered by 0.2 em rather
than centred on the Chinese baseline. The source image uses PowerPoint stretch
fill and its supplied aspect ratio; do not apply a frame, rounded corners or
shadow. The preview adds a white image border without changing the image slot.

## Template inventory

| Template | Source slide | Canvas | Purpose |
|---|---:|---:|---|
| `landscape_opening` | 1 | 1280 × 720 | Kicker, bilingual title/subtitle, byline, cover and captions |
| `landscape_guide_questions` | 2 | 1280 × 720 | Two bilingual guide questions, cover and captions |
| `portrait_opening` | 3 | 405.33 × 720 | Cover, kicker, English title plus 16 pt Chinese title translation, English subtitle plus 14 pt Chinese subtitle translation, byline and captions |
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

The opening template reserves fixed bands after the cover: kicker starts at
y=326, English title at y=370, Chinese title translation at y=416, English
subtitle at y=464, Chinese subtitle translation at y=507 and byline at y=544.
The title pair now uses a compact gap aligned with the horizontal title pair;
the subtitle pair follows the same compact rhythm while retaining a clear gap
between the two bilingual groups. A renderer may reduce text size to fit its
own box, but may not move a later band upward to consume this spacing.

## Caption treatment

Landscape keeps a fixed caption rail and lays English and Chinese out as one
shared centred vertical flow. Each language has a two-line safe area, 105% line
spacing, zero letter spacing and a fixed 6 px inter-language gap. English uses
Arial Bold and Chinese uses Noto Sans SC Medium, with pure-white fill and no
outline. Caption underlays and all page rails use the same `#262626` background;
unused space therefore remains visually consistent. Portrait retains its
original adaptive caption rail. English always precedes Chinese.
