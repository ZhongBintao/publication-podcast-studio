# Publication Podcast Studio

Repository-local Codex plugin for turning an English-language magazine or
newspaper PDF into a source-linked bilingual podcast-video package.

Version 1.1 supports two source modes:

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

## Version policy

The manifest uses semantic versioning. Contract-breaking source-package or
artifact changes increment the major version; backward-compatible workflow
features increment the minor version; fixes increment the patch version.
Release changes are recorded in `CHANGELOG.md`. Packaged development builds may
append a `+codex.<timestamp>` build identifier without changing precedence.
