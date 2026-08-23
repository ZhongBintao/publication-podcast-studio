---
name: economist-article-subtract
description: Extract one user-selected article from an Economist PDF into a verified source package. Use when a user identifies an article by title, subtitle, topic, opening text, section, or page hint and needs multimodal page reading, clean Markdown, source images, and audit evidence for downstream editorial production.
---

# Economist Article Subtract

Use this as the first production step. Keep article discovery local, then use multimodal page reading for the final transcription. Never send an entire issue to the model.

## Workflow

1. Locate candidates and create a compact visual review bundle:

   ```bash
   RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
   "$RUNTIME_PY" skills/economist-article-subtract/scripts/economist_article_subtract.py prepare ISSUE.pdf \
     --query "USER DESCRIPTION" --page-hint "OPTIONAL RANGE" --work-dir tmp/article-subtract
   ```

   If candidates remain ambiguous, present them and wait for the user to select one.

2. Perform the scope pass with Codex vision. Read the rendered candidate and boundary pages. Create `scope.json` from the manifest template. Include every article body column in reading order; explicitly exclude adjacent articles, adverts, contents panels, `ALSO IN THIS SECTION`, page furniture, and pull quotes. Do not infer a page boundary from matching words alone.

3. Materialise the article bundle:

   ```bash
   "$RUNTIME_PY" skills/economist-article-subtract/scripts/economist_article_subtract.py assemble REVIEW_MANIFEST.json scope.json
   ```

   This renders every confirmed article page and writes `source.raw.txt` as audit evidence. The bundle contains the extraction template for the next pass.

4. Perform the extraction pass with Codex vision. Read every `context_pages` image first for page structure, then read the ordered `region_images` for exact transcription. A page in `full_page` mode already provides its high-resolution reading image. Treat crops as text evidence, never as the sole proof of an article boundary. Fill `model-extraction.json` exactly as templated:

   - Transcribe paragraphs in natural reading order and rebuild visual paragraphs.
   - Correct only characters visibly supported by the page, including drop caps, line-break hyphens, cross-page hyphens, and words split by PDF layout.
   - Attach source region ids to every paragraph and correction.
   - Add image assets only when they belong to the article. Prefer a listed PDF image object; use a page crop for full-page artwork, vector graphics, or composite charts.
   - Put any unreadable text, uncertain boundary, or uncertain image attribution in `uncertain_spans` and set `review_status` to `needs_review`.

   If a low-resolution context image and the high-resolution crops cannot confirm a crop edge, cross-column continuation, paragraph ownership, character, or image attribution, create `visual-escalation.json` instead of guessing:

   ```json
   {"source_sha256": "...", "status": "needs_high_res_context", "pages": [47], "reasons": [{"page": 47, "reason": "The crop starts mid-sentence and the adjacent-column continuation is unclear."}]}
   ```

   Then render only the required full-resolution article pages and repeat this pass with the expanded request:

   ```bash
   "$RUNTIME_PY" skills/economist-article-subtract/scripts/economist_article_subtract.py expand EXTRACTION_REQUEST.json visual-escalation.json
   ```

   Never mark an extraction verified while an escalation is needed. If the added page remains unclear, use `needs_review`.

5. Finalise only a verified extraction:

   ```bash
   "$RUNTIME_PY" skills/economist-article-subtract/scripts/economist_article_subtract.py finalize EXTRACTION_REQUEST.json model-extraction.json
   ```

## Output Contract

Write `source.md` only from verified model paragraphs. Preserve `source.raw.txt`, rendered page evidence, `scope.json`, `model-extraction.json`, correction records, image provenance, and the source PDF hash in the article package.

The assembler also renders PDF page 1 once as the issue-cover asset and writes
it to `assets/issue-cover.png`. It is recorded separately as
`article.json.issue_cover`, not mixed into the article-image list. The
static-slide video opener consumes this fixed issue-level asset. New verified
article photo and chart records always write canonical `role` values
`article_image` or `article_chart`; downstream storyboards still accept the
legacy `kind` discriminator when reading older packages.

Treat `needs_review` as a successful safe stop, not an invitation to guess. Do not include terminal squares, continuation arrows, page headers, or excluded regions in formal Markdown.
