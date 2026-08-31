# Publication Podcast Studio

Repository-local Codex plugin for turning a verified English-language
publication package into source-linked podcast scripts, aligned media and
static-slide videos.

The canonical plugin lives in
[`plugins/publication-podcast-studio`](plugins/publication-podcast-studio).
Its top-level workflow supports one selected article or a complete short
issue, with `en`, `en-zh` and `zh-CN` products and `9:16` or `16:9` video
outputs. Historical Economist packages remain readable through the existing
compatibility layer.

## Confirmed video output

After a confirmed product matrix succeeds, the workflow creates a compact
`release/video-publish-package/` folder containing only:

- `publish-copy.md`
- selected release covers under `covers/`
- finished videos under `videos/<product>/<voice-profile>/`
- `package.json` with file hashes and sizes

The package is independently copied and atomically promoted after verification.
The default `safe` finalisation removes only selected variants' owned media
stage cache and abandoned package staging directories; canonical video outputs,
unselected variants and shared external work are preserved. The JSON result and
`workflow-report.json` include a directly clickable absolute package link.

To retry packaging without rerendering:

```bash
RUNTIME_PY=/Users/zhongbintao/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
"$RUNTIME_PY" plugins/publication-podcast-studio/skills/publication-podcast-studio-workflow/scripts/publication_podcast_studio_workflow.py finalize \
  output/publications/PACKAGE --cleanup-policy safe
```

## Development

Run the offline test suite from the plugin directory:

```bash
cd plugins/publication-podcast-studio
"$RUNTIME_PY" -m unittest discover -s tests -p 'test_*.py'
```

The plugin is installed from this repository's Codex marketplace manifest and
is identified as `publication-podcast-studio@publication-podcast-studio`.
