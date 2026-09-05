# Changelog

All notable changes to this plugin are documented here. Versions follow
[Semantic Versioning](https://semver.org/).

## 1.4.0 - 2026-09-05

- Replaced the default static-slide template with the supplied Editorial Modern
  visual system while keeping the stable template path and CLI contracts.
- Unified formal production, preview renders and the legacy frame entrypoint on
  cream paper, Georgia/Helvetica/Noto Sans SC typography, red question markers,
  contained images with two soft shadows and transparent outlined captions.
- Added source-driven metadata ordering, verified asset caption/credit display,
  short-issue item styling, image geometry diagnostics and strict no-truncation
  failures for unfit text.

## 1.3.0 - 2026-08-31

- Added a confirmed-run finalisation stage that atomically builds an
  independently copied `release/video-publish-package/` containing publish
  copy, selected covers and finished videos.
- Added SHA-256/size verification, a retryable `finalize` command and a
  clickable absolute package link in the workflow report and JSON result.
- Added bounded `safe` cleanup for selected media-stage caches and abandoned
  staging directories while preserving canonical outputs and shared work.
- Registered publish-copy and release-cover artifacts in `production.json`.

## 1.2.0 - 2026-08-24

- Localised English magnitude numbers in Chinese spoken scripts while
  preserving exact values, decimal precision, ranges and named currencies.
- Added normalised numeric validation for `bn`, `million`, `trillion` and
  Chinese `万` / `亿` / `万亿` expressions, with legacy-package compatibility.
- Added source-media kind compatibility for `photo`, `chart` and `map` assets.
- Added local-only caption rebuilding for English and Chinese variants and
  preserved Azure credentials lookup at the production workspace boundary.

## 1.1.0 - 2026-08-23

- Upgraded English and Chinese script policy to 5.3 with a source-anchored
  hook, listening-value handoff, source-supported payoff, opening callback and
  source-free natural sign-off.
- Added deterministic wrapper-arc validation for both article and short-issue
  modes without phrase matching or topic-specific templates.
- Added one bounded English wrapper-only retry and extended the Chinese retry
  route to repair opening or closing without regenerating the body.
- Preserved validation compatibility for existing policy-5.2 Chinese scripts.

## 1.0.0 - 2026-08-23

- Created an independent `publication-podcast-studio` plugin from the proven
  single-article workflow.
- Added generic publication identity and `article` / `short_issue` source
  modes with historical single-article compatibility.
- Added full-page short-issue scoping, one lead story, deterministic episode
  order, complete paragraph coverage and content-unit-owned media.
- Added frozen target/cap or unbounded duration policies with one bounded
  source-preserving compression retry.
- Changed Chinese headline, standfirst and guide-question copy to
  meaning-first editorial transcreation.
- Added alignment-derived short-issue video chapters.
- Replaced independent metadata text boxes with font-measured flow layout and
  first-pass geometric collision validation.
