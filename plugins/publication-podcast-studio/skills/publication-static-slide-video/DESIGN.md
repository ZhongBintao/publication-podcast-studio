# Publication Video Visual System v3 · Editorial Modern

The canonical visual follows the supplied Editorial Modern prototype: a warm
cream `#F4F1EC` page, deep ink `#161616`, red `#E3120B`, Georgia display type,
Helvetica utility type and Noto Sans SC for Chinese. It never crops, stretches
or generates source imagery. Source images use contain placement with a 1 px
radius and two soft shadows; there is no white border or dark image slot.

Portrait images fade into the paper panel with a vertical gradient. Content
image captions display only verified asset `caption`/`credit` text; empty
source fields produce no placeholder.

The underlying typography route is constraint-based rather than a collection
of independent fixed title boxes:

1. resolve the actual Latin and CJK font files and weights;
2. measure complete glyph runs, including descenders and CJK punctuation;
3. jointly fit and flow opener metadata inside one safe region;
4. solve guide questions and captions inside measured safe regions;
5. record actual line boxes and reject inter-layer collisions before ffmpeg.

No text is truncated. No model performs visual QA. Both ratios use the same
layout rules, and the bottom 10% of portrait remains reserved for platform
details.

Article content slides show the two approved guide questions with fixed red
`01` and `02` markers. Short-issue content slides use the same visual language
and opener treatment with the current item's metadata and unit-owned media.
Captions are transparent overlays with white text, a dark outline and a soft
shadow.
