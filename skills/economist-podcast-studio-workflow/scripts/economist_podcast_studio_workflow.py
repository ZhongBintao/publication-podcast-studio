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
WORKFLOW_VERSION = "0.3.0"
SUPPORTED_VARIANTS = {"en", "en-zh", "zh-CN"}
SUPPORTED_ASPECT_RATIOS = {"16:9", "9:16"}
SUPPORTED_SUBTITLE_MODES = {"default", "en-only"}
PRODUCTS = {
    "zh-CN": {"label": "中文播客", "variant": "zh-CN", "subtitle_mode": "default"},
    "en": {"label": "英文播客", "variant": "en", "subtitle_mode": "default"},
    "en-zh": {"label": "中英字幕", "variant": "en-zh", "subtitle_mode": "default"},
}
MAX_GUIDE_QUESTION_WORDS = 22
MIN_GUIDE_QUESTION_WORDS = 8
MAX_ENGLISH_CAPTION_CHARS = 84
MAX_CHINESE_CAPTION_CHARS = 48
CHINESE_LINE_START_PUNCTUATION = tuple("，。！？；：、）》】〉〕〗」』")


class WorkflowError(ValueError):
    """A validation or local execution failure with a user-facing reason."""


class WorkflowBlocked(WorkflowError):
    """A stage needs a capability intentionally unavailable in local-only mode."""


def product_plan(product: str) -> dict[str, str]:
    """Resolve a user-facing product selection to the existing stage contract."""
    try:
        return {"id": product, **PRODUCTS[product]}
    except KeyError as error:
        raise WorkflowError(f"Unsupported video product: {product!r}.") from error


def resolve_product_plans(products: list[str] | None, variant: str | None) -> tuple[list[dict[str, str]], bool]:
    """Return product plans and whether the new confirmed matrix interface was used."""
    if products:
        if variant is not None:
            raise WorkflowError("Use --product or --variant, not both.")
        unique = list(dict.fromkeys(products))
        return [product_plan(product) for product in unique], True
    selected_variant = variant
    if selected_variant is None:
        return [], False
    if selected_variant not in SUPPORTED_VARIANTS:
        raise WorkflowError(f"Unsupported production variant: {selected_variant!r}.")
    subtitle_mode = "default"
    return [{"id": selected_variant, "label": selected_variant, "variant": selected_variant, "subtitle_mode": subtitle_mode}], False


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


def freeze_vertical_request(
    production: dict[str, Any],
    plans: list[dict[str, str]],
    ratios: list[str],
    voice_profile: str,
    local_only: bool,
    confirmed: bool,
) -> None:
    output = production.setdefault("output", {})
    existing = list(output.get("aspect_ratios", [])) if isinstance(output.get("aspect_ratios"), list) else []
    frozen = list(dict.fromkeys(ratios if confirmed else [*existing, *ratios]))
    output["aspect_ratios"] = frozen
    if len(plans) == 1:
        output["subtitle_mode"] = plans[0]["subtitle_mode"]
    request = {
        "products": [plan["id"] for plan in plans],
        "aspect_ratios": ratios,
        "voice_profile": voice_profile,
        "titles_and_description": True,
        "confirmation_status": "confirmed" if confirmed else "legacy_direct",
        "confirmed_at": utc_now() if confirmed else None,
    }
    if len(plans) == 1:
        request["variant"] = plans[0]["variant"]
        request["subtitle_mode"] = plans[0]["subtitle_mode"]
    production["workflow"] = {
        "name": WORKFLOW_NAME,
        "version": WORKFLOW_VERSION,
        "execution_mode": "local_only" if local_only else "local_reuse",
        "request": request,
        "updated_at": utc_now(),
    }


def run_workflow(
    package: Path,
    variant: str | None,
    ratios: list[str],
    voice_profile: str,
    local_only: bool,
    opening_duration: float,
    subtitle_mode: str | None = None,
    products: list[str] | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    started_at = utc_now()
    root = package_root(package)
    production_path = root / "production.json"
    production = read_json(production_path)
    plans, confirmed_matrix = resolve_product_plans(products, variant)
    if not plans:
        selected_variant = production.get("variant")
        if selected_variant not in SUPPORTED_VARIANTS:
            raise WorkflowError("A supported frozen variant is required.")
        plans = [product_plan(selected_variant)]
    if confirmed_matrix and not confirmed:
        raise WorkflowBlocked("The confirmed production request is required before video generation can start.")
    if not ratios:
        ratios = ["9:16"]
    if any(ratio not in SUPPORTED_ASPECT_RATIOS for ratio in ratios):
        raise WorkflowError("Only 16:9 and 9:16 outputs are supported.")
    ratios = list(dict.fromkeys(ratios))
    if subtitle_mode is not None:
        if confirmed_matrix:
            raise WorkflowError("--subtitle-mode is an internal compatibility option; choose a supported product instead.")
        if len(plans) != 1:
            raise WorkflowError("--subtitle-mode is only supported with the legacy single-variant interface.")
        try:
            plans[0]["subtitle_mode"] = storyboard.validate_subtitle_mode(subtitle_mode)
        except ValueError as error:
            raise WorkflowError(str(error)) from error
    for plan in plans:
        if plan["subtitle_mode"] not in SUPPORTED_SUBTITLE_MODES:
            raise WorkflowError(f"Unsupported subtitle mode: {plan['subtitle_mode']!r}.")
        if plan["subtitle_mode"] == "en-only" and plan["variant"] == "zh-CN":
            raise WorkflowError("subtitle_mode=en-only requires an English caption source.")
    original_variant = production.get("variant")
    original_subtitle_mode = production.get("output", {}).get("subtitle_mode")
    freeze_vertical_request(production, plans, ratios, voice_profile, local_only, confirmed_matrix and confirmed)
    write_json(production_path, production)

    rendered: list[dict[str, Any]] = []
    reused_artifacts: set[str] = set()
    storyboard_paths: dict[str, str] = {}
    product_states: dict[str, dict[str, Any]] = {}
    try:
        for plan in plans:
            selected_variant = plan["variant"]
            production["variant"] = selected_variant
            production.setdefault("output", {})["subtitle_mode"] = plan["subtitle_mode"]
            write_json(production_path, production)
            article, editorial, artifacts = validate_article(root, production, selected_variant)
            paths = validate_media(root, production, selected_variant, artifacts, local_only)
            reused_artifacts.update(str(path.relative_to(root)) for path in paths.values())
            questions_path = local_path(root, artifacts["editorial_assets"], "editorial assets")
            storyboard_path = root / "storyboard.json" if len(plans) == 1 else root / "storyboards" / f"{plan['id']}.json"
            storyboard.build_storyboard(production_path, questions_path, storyboard_path, opening_duration)
            storyboard_paths[plan["id"]] = str(storyboard_path.relative_to(root))
            product_states[plan["id"]] = {"state": "complete", "variant": selected_variant, "subtitle_mode": plan["subtitle_mode"]}
            for ratio in ratios:
                output_path, reused = storyboard.render_storyboard(production_path, storyboard_path, ratio, voice_profile, plan["subtitle_mode"])
                rendered.append({"product": plan["id"], "aspect_ratio": ratio, "path": str(output_path.relative_to(root)), "reused": reused})
            production = read_json(production_path)
    finally:
        production = read_json(production_path)
        if original_variant in SUPPORTED_VARIANTS:
            production["variant"] = original_variant
        elif plans:
            production["variant"] = plans[0]["variant"]
        if original_subtitle_mode is not None:
            production.setdefault("output", {})["subtitle_mode"] = original_subtitle_mode
        elif len(plans) != 1:
            production.setdefault("output", {}).pop("subtitle_mode", None)
        production.setdefault("workflow", {})["storyboards"] = storyboard_paths
        production.setdefault("workflow", {})["products"] = product_states
        write_json(production_path, production)

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
        "variant": plans[0]["variant"] if len(plans) == 1 else None,
        "products": [plan["id"] for plan in plans],
        "voice_profile": voice_profile,
        "subtitle_mode": plans[0]["subtitle_mode"] if len(plans) == 1 else None,
        "aspect_ratios": ratios,
        "reused_artifacts": sorted(reused_artifacts),
        "storyboards": storyboard_paths,
        "outputs": rendered,
        "limitations": [],
    }
    write_json(root / "workflow-report.json", report)
    report["report"] = str((root / "workflow-report.json").relative_to(root))
    return report


def write_blocked_report(
    package: Path,
    error: WorkflowError,
    variant: str | None,
    ratios: list[str],
    voice_profile: str,
    local_only: bool,
    subtitle_mode: str | None,
    products: list[str] | None = None,
) -> Path | None:
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
        "products": products or [],
        "voice_profile": voice_profile,
        "subtitle_mode": subtitle_mode or "default",
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
    run.add_argument("--product", choices=tuple(sorted(PRODUCTS)), action="append", dest="products", help="Confirmed user-facing video product; repeat for multiple products.")
    run.add_argument("--aspect-ratio", choices=tuple(sorted(SUPPORTED_ASPECT_RATIOS)), action="append", dest="ratios")
    run.add_argument("--voice-profile", default="default")
    run.add_argument("--subtitle-mode", choices=tuple(sorted(SUPPORTED_SUBTITLE_MODES)), default=None)
    run.add_argument("--opening-duration", type=float, default=8.0)
    run.add_argument("--local-only", action="store_true", default=False, help="Never call an external provider; reuse existing media or stop with a report.")
    run.add_argument("--confirmed", action="store_true", help="Assert that the Codex conversation has confirmed the frozen production request.")
    args = parser.parse_args()
    if args.command == "run":
        try:
            result = run_workflow(
                args.package, args.variant, args.ratios or ["9:16"], args.voice_profile,
                args.local_only, args.opening_duration, args.subtitle_mode,
                args.products, args.confirmed,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError, WorkflowError) as error:
            report_path = write_blocked_report(
                args.package, error, args.variant, args.ratios or ["9:16"], args.voice_profile,
                args.local_only, args.subtitle_mode, args.products,
            )
            payload = {"state": "blocked" if isinstance(error, WorkflowBlocked) else "failed", "error": str(error)}
            if report_path:
                payload["report"] = str(report_path)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 3 if isinstance(error, WorkflowBlocked) else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
