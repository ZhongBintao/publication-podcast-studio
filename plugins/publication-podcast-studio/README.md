# Publication Podcast Studio

Repository-local Codex plugin for turning an English-language magazine or
newspaper PDF into a source-linked bilingual podcast-video package.

Version 1.4 supports two source modes and the Editorial Modern static-slide
template:

- `article`: one user-selected article from any publication;
- `short_issue`: every editorial item in a small issue, ordered lead first and
  then by source order.

The six skills under `skills/` form the production pipeline. The canonical
entrypoint is `publication-podcast-studio-workflow`; the other skills remain
independently callable stages.

The plugin preserves compatibility with historical Economist single-article
packages through `lib/publication_package.py`. Compatibility is read-only: old
packages are normalised in memory and are not rewritten.

New English and Chinese scripts use a source-anchored opening and closing arc
with one wrapper-only repair attempt. Existing policy-5.2 production packages
remain readable and are not rewritten.

After a confirmed video matrix succeeds, the workflow creates the compact
`release/video-publish-package/` folder containing the publish copy, selected
release covers and finished videos. Each release cover is taken from the first
frame of the corresponding finished video and then receives the editorial
cover-text overlay, so its background is exactly the selected Editorial Modern
video frame rather than a second hand-built dark canvas. It verifies
independent file copies before atomically promoting the folder, then performs
bounded `safe` cleanup of only selected media-stage caches. The JSON report and
the chat result include a clickable absolute link to the package. Legacy
`--variant` runs keep the old output behavior and skip automatic cleanup unless
explicitly finalized.

## Version policy

The manifest uses semantic versioning. Contract-breaking source-package or
artifact changes increment the major version; backward-compatible workflow
features increment the minor version; fixes increment the patch version.
Release changes are recorded in `CHANGELOG.md`. Packaged development builds may
append a `+codex.<timestamp>` build identifier without changing precedence.
