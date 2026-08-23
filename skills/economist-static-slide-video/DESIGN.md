# Podcast Video Visual System v2 · vertical-first

## Style prompt

An Economist-adjacent editorial static-slide video system: restrained, spacious
and typographic. Every frame uses the same #262626 field and a contained
magazine-image slot that preserves the source aspect ratio. The vertical
opening is a compact free-flow stack; the opening metadata yields to two
bilingual guide questions without decorative dividers or top utility labels.
The opening always uses the verified magazine issue cover. Content slides then
rotate through verified article photos and charts in strict source-order
round-robin at a 20-second target and normal 18–22 second dwell. Every image
has a 3 px white frame around its actual contained-image edge. The opening
carries the publication mark, but no page or read-time field.
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
  The renderer supports presentation-only `subtitle_mode=en-only` for English
  and bilingual audio products: the Chinese caption layer is not drawn and the
  English block is vertically centred in the complete caption rail. The default
  mode remains bilingual for `en-zh`.
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
- Do not draw the white image frame around the letterbox slot; frame the actual
  contained image.
- Do not render top utility labels or decorative divider lines in portrait.
- Do not place captions or metadata in the bottom 10% platform-detail area.
- Do not derive captions from ASR; only render the approved canonical SRT.
