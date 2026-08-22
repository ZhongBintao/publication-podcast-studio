# Podcast Video Visual System v2 · vertical-first

## Style prompt

An Economist-adjacent editorial static-slide video system: restrained, spacious
and typographic. Every frame uses the same #262626 field and a contained
magazine-image slot that preserves the source aspect ratio. The vertical
opening is a compact free-flow stack; the opening metadata yields to two
bilingual guide questions without decorative dividers or top utility labels.
The verified article image is preferred over the issue cover when the package
contains one. The opening carries the publication mark, but no page or
read-time field.
No texture, gradient, decorative animation, shadow or generated imagery is
permitted.

## Colours

- Page background, both ratios: `#262626`
- Text: `#FFFFFF`
- Kicker: `#D71920`
- Subtitle rail: `#262626`
- English caption: `#FFFFFF`
- Chinese caption: `#FFFFFF`

## Typography

- English display: Times New Roman; Chinese display fallback: Noto Serif SC.
- English utility: Arial; English captions: Arial Bold.
- Chinese utility and captions: Noto Sans SC; landscape captions use the Medium
  variable-font instance.
- Captions use zero letter spacing, centred alignment and no text justification.
  In landscape, English and Chinese form one shared vertical flow with 105%
  intra-language line spacing, explicit vertical text insets for descenders and
  a fixed 6 px inter-language gap. Long cues use balanced two-line wrapping and
  adaptive sizing down to the portrait minimum; they are never truncated.
- Caption text is rendered exactly as supplied. The renderer never adds a
  sentence-final period.
- Chinese punctuation stays in the approved source text and uses native CJK
  glyphs. Closing punctuation is attached to the preceding character and may
  never begin a visual line.
- The portrait opening uses a contained image frame near the top, enlarged
  kicker/title/subtitle/byline sizes, and an unboxed two-language caption area.
  The caption area ends above the bottom 10% platform-detail safe area; captions
  are at most two complete lines per language.

## What not to do

- Do not use a white portrait panel or a warm cream replacement background.
- Do not overlay captions on source imagery.
- Do not add motion, music, sound effects, avatars or synthetic images.
- Do not crop, stretch or distort a source image; letterboxing is acceptable.
- Do not render top utility labels or decorative divider lines in portrait.
- Do not place captions or metadata in the bottom 10% platform-detail area.
- Do not derive captions from ASR; only render the approved canonical SRT.
