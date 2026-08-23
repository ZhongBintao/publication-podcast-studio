# Publication Video Visual System v3

The visual system is restrained, publication-neutral and source-led. It uses a
dark `#262626` field, white text, a red kicker accent and contained source
images with a 3 px white frame. It never crops, stretches or generates source
imagery.

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

Article content slides show the two approved guide questions. Short-issue
content slides reuse the opener layout with the current item's metadata, so the
listener always sees the item being spoken. Captions never overlay source
imagery.
