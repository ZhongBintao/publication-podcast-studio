# Podcast Video Visual System v1.1

## Style prompt

An Economist-adjacent editorial static-slide video system: restrained, spacious
and typographic. Every frame uses the same #262626 field, one fixed
magazine-cover slot with a white border and a stable bilingual-caption rail. The only change
over time is content: the opening metadata yields to two bilingual guide
questions. No texture, gradient, decorative animation, shadow or generated
imagery is permitted.

## Colours

- Page background, both ratios: `#262626`
- Text: `#FFFFFF`
- Kicker: `#D71920`
- Subtitle rail: `#262626`
- English caption: `#FFFFFF`
- Chinese caption: `#FFFFFF`

## Typography

- English display: Times New Roman; Chinese display fallback: Noto Serif SC.
- English utility: Arial; English landscape captions: Arial Bold.
- Chinese utility and captions: Noto Sans SC; landscape captions use the Medium
  variable-font instance.
- Captions use zero letter spacing, centred alignment and no text justification.
  In landscape, English and Chinese form one shared vertical flow with 105%
  intra-language line spacing, explicit vertical text insets for descenders and
  a fixed 6 px inter-language gap. Long cues use balanced two-line wrapping and
  adaptive 16–20 pt sizing; they are never truncated.
- Caption text is rendered exactly as supplied. The renderer never adds a
  sentence-final period.
- Chinese full stops (`。`) render at 70% of surrounding size, lowered by 0.2
  em. They must never read as an optically centred dot.
- The portrait opening always reserves an English title, 16 pt Chinese title
  translation, English subtitle and 14 pt Chinese subtitle translation as
  distinct vertical bands. The title pair uses a compact gap matching the
  horizontal rhythm; the subtitle pair follows the same rhythm. Preserve these
  bands even when a translation is empty.

## What not to do

- Do not use a white portrait panel or a warm cream replacement background.
- Do not overlay captions on source imagery.
- Do not add motion, music, sound effects, avatars or synthetic images.
- Do not move later portrait text bands upward to fill an empty translation
  slot.
- Do not derive captions from ASR; only render the approved canonical SRT.
