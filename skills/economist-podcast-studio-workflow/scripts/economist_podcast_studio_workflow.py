#!/usr/bin/env python3
"""Run one frozen Economist production request with a local-first policy.

The workflow intentionally never invokes a network client. It can reuse media
that was produced earlier by the Azure skill, but it refuses to synthesize or
align missing media in local-only mode and reports that boundary explicitly.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parents[2]
STATIC_SCRIPT = SCRIPT_ROOT / "economist-static-slide-video" / "scripts" / "static_slide_storyboard.py"
if str(STATIC_SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(STATIC_SCRIPT.parent))

import static_slide_storyboard as storyboard  # type: ignore  # noqa: E402


WORKFLOW_NAME = "economist-podcast-studio-workflow"
WORKFLOW_VERSION = "0.2.0"
SUPPORTED_VARIANTS = {"en", "en-zh", "zh-CN"}
SUPPORTED_ASPECT_RATIOS = {"16:9", "9:16"}
MAX_GUIDE_QUESTION_WORDS = 22
MIN_GUIDE_QUESTION_WORDS = 8
MAX_ENGLISH_CAPTION_CHARS = 84
MAX_CHINESE_CAPTION_CHARS = 48
CHINESE_LINE_START_PUNCTUATION = tuple("，。！？；：、）》】〉〕〗」』")


class WorkflowError(ValueError):
    """A validation or local execution failure with a user-facing reason."""


class WorkflowBlocked(WorkflowError):
    """A stage needs a capability intentionally unavailable in local-only mode."""


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def package_root(value: Path) -> Path:
    resolved = value.expanduser().resolve()
    if resolved.is_dir():
        root = resolved
    elif resolved.name == "article.json":
        root = resolved.parent
    else:
        raise WorkflowError("The input must be an article package directory or its article.json file.")
    production = root / "production.json"
    if not production.is_file():
        raise WorkflowError(f"production.json is missing from the article package: {production}")
    return root


def local_path(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError(f"{label} is not declared in production.json.")
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise WorkflowError(f"{label} must remain inside the article package: {path}") from error
    if not path.is_file():
        raise WorkflowError(f"{label} is missing: {path}")
    return path


def word_count(value: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", value))


def artifact_map(production: dict[str, Any], variant: str) -> dict[str, str]:
    artifacts = production.get("artifacts", {})
    suffix = "zh_cn" if variant == "zh-CN" else variant.replace("-", "_")
    audio_key = "audio_en" if variant in {"en", "en-zh"} else f"audio_{suffix}"
    captions_key = f"captions_{suffix}_srt"
    required = {
        "script": "script_en" if variant in {"en", "en-zh"} else "script_zh_cn",
        "audio": audio_key,
        "captions": captions_key,
        "editorial_assets": "editorial_assets",
    }
    if variant == "en-zh":
        required.update({"subtitle_script": "subtitle_script_en_zh", "caption_cues": "caption_cues_en_zh"})
    result: dict[str, str] = {}
    for label, key in required.items():
        value = artifacts.get(key)
        if not isinstance(value, str):
            raise WorkflowError(f"production.json is missing the {label} artifact declaration ({key}).")
        result[label] = value
    return result


def validate_article(root: Path, production: dict[str, Any], variant: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    if production.get("state") not in {"queued", "running", "complete"}:
        raise WorkflowError("production.json has an unsupported state.")
    if production.get("variant") != variant:
        raise WorkflowError(f"Frozen production variant is {production.get('variant')!r}, not {variant!r}.")
    article_path, article = storyboard.resolve_article(production, root)
    if not article_path.is_file() or article.get("review_status") != "verified":
        raise WorkflowError("The selected article must be a verified local article.json.")
    if not article.get("issue_cover", {}).get("file"):
        raise WorkflowError("The verified article has no issue-cover image.")
    artifacts = artifact_map(production, variant)
    # The guide-question payload is also required to rebuild a deterministic
    # storyboard; it is checked before any media or video work starts.
    editorial_path = local_path(root, artifacts["editorial_assets"], "editorial assets")
    questions, _ = storyboard.question_payload(editorial_path, article.get("source_sha256"))
    for index, question in enumerate(questions, start=1):
        count = word_count(question["question"])
        if not MIN_GUIDE_QUESTION_WORDS <= count <= MAX_GUIDE_QUESTION_WORDS:
            raise WorkflowError(f"Guide question {index} has {count} English words; the allowed range is 8–22.")
    return article, read_json(editorial_path), artifacts


def validate_media(root: Path, production: dict[str, Any], variant: str, artifacts: dict[str, str], local_only: bool) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    missing: list[str] = []
    for label in ("script", "audio", "captions", "subtitle_script", "caption_cues"):
        if label not in artifacts:
            continue
        try:
            paths[label] = local_path(root, artifacts[label], label)
        except WorkflowError:
            missing.append(label)
    if missing:
        if local_only:
            raise WorkflowBlocked(
                "speech-media: canonical local media is incomplete (missing "
                + ", ".join(missing)
                + "). The current media skill requires Azure Speech for new TTS and WordBoundary alignment; "
                "local-only mode made no external API call and cannot synthesize the missing artifacts."
            )
        raise WorkflowError("speech-media: missing canonical media: " + ", ".join(missing))
    if variant == "en-zh":
        payload = read_json(paths["caption_cues"])
        if payload.get("variant") != variant or not isinstance(payload.get("cues"), list):
            raise WorkflowError("caption-cues.en-zh.json does not match the frozen bilingual caption contract.")
        for index, cue in enumerate(payload["cues"], start=1):
            english = str(cue.get("en_text", ""))
            chinese = str(cue.get("zh_text", ""))
            if len(english) > MAX_ENGLISH_CAPTION_CHARS:
                raise WorkflowError(f"Caption cue {index} has {len(english)} English characters; maximum is 84.")
            if len(chinese) > MAX_CHINESE_CAPTION_CHARS:
                raise WorkflowError(f"Caption cue {index} has {len(chinese)} Chinese characters; maximum is 48.")
            if chinese and any(line.startswith(CHINESE_LINE_START_PUNCTUATION) for line in chinese.splitlines()):
                raise WorkflowError(f"Caption cue {index} starts a visual Chinese line with attached punctuation.")
    return paths


def freeze_vertical_request(production: dict[str, Any], variant: str, ratios: list[str], voice_profile: str, local_only: bool) -> None:
    output = production.setdefault("output", {})
    frozen = list(output.get("aspect_ratios", [])) if isinstance(output.get("aspect_ratios"), list) else []
    for ratio in ratios:
        if ratio not in frozen:
            frozen.append(ratio)
    output["aspect_ratios"] = frozen
    production["workflow"] = {
        "name": WORKFLOW_NAME,
        "version": WORKFLOW_VERSION,
        "execution_mode": "local_only" if local_only else "local_reuse",
        "request": {"variant": variant, "voice_profile": voice_profile, "aspect_ratios": ratios},
        "updated_at": utc_now(),
    }


def run_workflow(package: Path, variant: str | None, ratios: list[str], voice_profile: str, local_only: bool, opening_duration: float) -> dict[str, Any]:
    started_at = utc_now()
    root = package_root(package)
    production_path = root / "production.json"
    production = read_json(production_path)
    selected_variant = variant or production.get("variant")
    if selected_variant not in SUPPORTED_VARIANTS:
        raise WorkflowError("A supported frozen variant is required.")
    if not ratios:
        ratios = ["9:16"]
    if any(ratio not in SUPPORTED_ASPECT_RATIOS for ratio in ratios):
        raise WorkflowError("Only 16:9 and 9:16 outputs are supported.")
    ratios = list(dict.fromkeys(ratios))
    article, editorial, artifacts = validate_article(root, production, selected_variant)
    paths = validate_media(root, production, selected_variant, artifacts, local_only)
    freeze_vertical_request(production, selected_variant, ratios, voice_profile, local_only)
    write_json(production_path, production)

    storyboard_path = root / "storyboard.json"
    questions_path = local_path(root, artifacts["editorial_assets"], "editorial assets")
    storyboard_data = storyboard.build_storyboard(production_path, questions_path, storyboard_path, opening_duration)
    rendered: list[dict[str, Any]] = []
    for ratio in ratios:
        output_path, reused = storyboard.render_storyboard(production_path, storyboard_path, ratio, voice_profile)
        rendered.append({"aspect_ratio": ratio, "path": str(output_path.relative_to(root)), "reused": reused})

    production = read_json(production_path)
    production.setdefault("workflow", {}).update({
        "state": "complete",
        "media": "reused_local_artifacts",
        "stages": {"article": "validated", "scripts": "validated", "media": "reused", "storyboard": "complete", "video": "complete"},
        "updated_at": utc_now(),
    })
    write_json(production_path, production)
    report = {
        "schema_version": "1.0.0",
        "workflow": WORKFLOW_NAME,
        "workflow_version": WORKFLOW_VERSION,
        "state": "complete",
        "started_at": started_at,
        "finished_at": utc_now(),
        "execution_mode": "local_only" if local_only else "local_reuse",
        "external_api_calls": [],
        "article": {"path": str((root / production.get("article", {}).get("path", "article.json")).relative_to(root)), "headline": article.get("article", {}).get("headline", "")},
        "variant": selected_variant,
        "voice_profile": voice_profile,
        "aspect_ratios": ratios,
        "reused_artifacts": sorted(str(path.relative_to(root)) for path in paths.values()),
        "storyboard": str(storyboard_path.relative_to(root)),
        "outputs": rendered,
        "limitations": [],
    }
    write_json(root / "workflow-report.json", report)
    report["report"] = str((root / "workflow-report.json").relative_to(root))
    return report


def write_blocked_report(package: Path, error: WorkflowError, variant: str | None, ratios: list[str], voice_profile: str, local_only: bool) -> Path | None:
    try:
        root = package_root(package)
    except WorkflowError:
        return None
    report_path = root / "workflow-report.json"
    write_json(report_path, {
        "schema_version": "1.0.0",
        "workflow": WORKFLOW_NAME,
        "workflow_version": WORKFLOW_VERSION,
        "state": "blocked" if isinstance(error, WorkflowBlocked) else "failed",
        "finished_at": utc_now(),
        "execution_mode": "local_only" if local_only else "local_reuse",
        "external_api_calls": [],
        "variant": variant,
        "voice_profile": voice_profile,
        "aspect_ratios": ratios or ["9:16"],
        "limitations": [str(error)],
    })
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Validate one package and render its frozen local artifacts.")
    run.add_argument("package", type=Path)
    run.add_argument("--variant", choices=tuple(sorted(SUPPORTED_VARIANTS)))
    run.add_argument("--aspect-ratio", choices=tuple(sorted(SUPPORTED_ASPECT_RATIOS)), action="append", dest="ratios")
    run.add_argument("--voice-profile", default="default")
    run.add_argument("--opening-duration", type=float, default=8.0)
    run.add_argument("--local-only", action="store_true", default=False, help="Never call an external provider; reuse existing media or stop with a report.")
    args = parser.parse_args()
    if args.command == "run":
        try:
            result = run_workflow(args.package, args.variant, args.ratios or ["9:16"], args.voice_profile, args.local_only, args.opening_duration)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError, WorkflowError) as error:
            report_path = write_blocked_report(args.package, error, args.variant, args.ratios or ["9:16"], args.voice_profile, args.local_only)
            payload = {"state": "blocked" if isinstance(error, WorkflowBlocked) else "failed", "error": str(error)}
            if report_path:
                payload["report"] = str(report_path)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 3 if isinstance(error, WorkflowBlocked) else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
