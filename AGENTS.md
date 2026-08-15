# Economist Podcast Studio

## Project Goal

This project turns one Economist article selected by the user from a PDF issue
into a complete podcast-video production package.

The user reads the issue and chooses the article. AI then locates the article
in the PDF, extracts and verifies its source material, creates editorial
content, produces narration and subtitles, and renders a video using a fixed
visual template.

## Product

Input:

- An Economist PDF issue.
- A user-selected article, identified by its title, topic, or visual location.

Output:

- Verified article metadata: section or column, kicker, headline, subtitle,
  byline or dateline when present.
- Verified English source text and selected article images.
- Chinese editorial guidance, narration script, and subtitles.
- Audio and a finished podcast-video artifact.

## Core Principles

1. Human editorial judgment comes first. The user chooses the article and
   remains the final authority on its suitability.
2. The PDF is the source of truth for English text and source images.
3. Use multimodal reasoning to locate, read, and verify the selected article.
4. Keep source material separate from generated translations, explanations,
   narration, and subtitles.
5. Preserve enough source evidence to inspect and correct a result later.
6. Optimise for one excellent article-to-video workflow, not for processing an
   entire magazine issue automatically.

## Current Focus

Prove a reliable end-to-end workflow for a user-selected article:

```text
Selected article -> verified source material -> editorial plan -> narration
and subtitles -> fixed-template video
```

## First Workflow Skill

Use `skills/economist-article-subtract/` as the completed first workflow step.
It locates a user-selected article locally from the PDF, then uses bounded
multimodal page reading to produce verified English Markdown, source images,
and audit evidence. Preserve whole-page layout context while reading
high-resolution article regions; request a high-resolution full page or stop
for review when any boundary or character remains uncertain. Never send an
entire magazine issue to the model or use extracted PDF text as final copy.

## Project Direction

This project will evolve through real productions. Reusable, validated steps
will become plugin skills, scripts, templates, test fixtures, and configuration.
Do not add workflow complexity until it solves a demonstrated production need.
