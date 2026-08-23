#!/usr/bin/env python3
"""Create and render the non-animated Economist static-slide storyboard.

The renderer consumes completed canonical audio and SRT captions. It never
calls TTS, translation, OCR, an image generator, or a language model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from preview_visual_system import read_definition, render_template, validate_subtitle_mode
from render_static_slide_template import audio_duration, concat_manifest, cue_text, parse_srt


ROOT = Path(__file__).parents[1]
TEMPLATE_PATH = ROOT / "templates" / "podcast-video-visual-system.v1.json"
STORYBOARD_FORMAT = "economist-static-slide-storyboard"
SUPPORTED_VARIANTS = {"en", "en-zh", "zh-CN"}
SUPPORTED_SUBTITLE_MODES = {"default", "en-only"}
ARTICLE_ASSET_ROLES = {"article_image", "article_chart"}
CONTENT_IMAGE_TARGET_SECONDS = 20.0
CONTENT_IMAGE_MIN_SECONDS = 18.0
CONTENT_IMAGE_MAX_SECONDS = 22.0


class StoryboardError(ValueError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_path(root: Path, value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_file():
        raise StoryboardError(f"{label} is missing: {path}")
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise StoryboardError(f"{label} must remain inside the production package: {path}") from error
    return path


def relative_path(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def resolve_article(production: dict[str, Any], root: Path) -> tuple[Path, dict[str, Any]]:
    article_ref = production.get("article", {}).get("path")
    if not isinstance(article_ref, str):
        raise StoryboardError("production.json needs article.path.")
    article_path = package_path(root, article_ref, "article.json")
    article = read_json(article_path)
    if article.get("review_status") != "verified":
        raise StoryboardError("article.json must have review_status=verified.")
    if not isinstance(article.get("article"), dict):
        raise StoryboardError("article.json needs article metadata.")
    return article_path, article


def artifact_key(variant: str, kind: str) -> str:
    suffix = "zh_cn" if variant == "zh-CN" else variant.replace("-", "_")
    if kind == "audio":
        return "audio_en" if variant in {"en", "en-zh"} else f"audio_{suffix}"
    return f"captions_{suffix}_srt"


def resolve_media(production: dict[str, Any], root: Path) -> tuple[str, Path, Path, Path | None]:
    variant = production.get("variant")
    if variant not in SUPPORTED_VARIANTS:
        raise StoryboardError("production.json needs one supported variant.")
    artifacts = production.get("artifacts", {})
    audio_ref = artifacts.get(artifact_key(variant, "audio"))
    captions_ref = artifacts.get(artifact_key(variant, "captions"))
    if not isinstance(audio_ref, str) or not isinstance(captions_ref, str):
        raise StoryboardError(f"production.json is missing completed audio/SRT artifacts for {variant}.")
    cue_ref = artifacts.get(f"caption_cues_{variant.replace('-', '_')}")
    cue_path = package_path(root, cue_ref, "structured caption cues") if isinstance(cue_ref, str) else None
    return variant, package_path(root, audio_ref, "final audio"), package_path(root, captions_ref, "canonical SRT"), cue_path


def question_payload(path: Path, article_source_sha256: str | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    payload = read_json(path)
    if isinstance(payload, list):
        questions, display = payload, {}
    elif isinstance(payload, dict):
        if payload.get("format") == "economist-editorial-assets":
            source_sha256 = payload.get("article_source_sha256")
            if article_source_sha256 and source_sha256 != article_source_sha256:
                raise StoryboardError("editorial-assets.json does not belong to the selected article source.")
        questions, display = payload.get("guide_questions"), payload.get("display", {})
    else:
        raise StoryboardError("Guide-question JSON must be an array or an object with guide_questions.")
    if not isinstance(questions, list) or len(questions) != 2:
        raise StoryboardError("Guide-question JSON needs exactly two questions.")
    normalised = []
    for index, item in enumerate(questions, start=1):
        if not isinstance(item, dict) or not all(isinstance(item.get(field), str) and item[field].strip() for field in ("question", "translation_zh")):
            raise StoryboardError(f"Guide question {index} needs non-empty question and translation_zh.")
        source_ids = item.get("source_paragraph_ids", [])
        if not isinstance(source_ids, list) or not all(isinstance(value, str) for value in source_ids):
            raise StoryboardError(f"Guide question {index} source_paragraph_ids must be a string array.")
        normalised.append({"question": item["question"].strip(), "translation_zh": item["translation_zh"].strip(), "source_paragraph_ids": source_ids})
    if not isinstance(display, dict):
        raise StoryboardError("Guide-question display must be an object when present.")
    return normalised, {field: str(display.get(field, "")).strip() for field in ("headline_zh", "subtitle_zh")}


def issue_cover(article: dict[str, Any], root: Path) -> str:
    cover_ref = article.get("issue_cover", {}).get("file")
    if not isinstance(cover_ref, str):
        raise StoryboardError("article.json needs issue_cover.file for the opening template.")
    cover = package_path(root, cover_ref, "issue cover")
    return relative_path(cover, root)


def approved_article_assets(article: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    """Return verified article media in stable source order, without duplicates."""
    approved: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates = [
        (source_index, asset)
        for source_index, asset in enumerate(article.get("assets", []))
        if isinstance(asset, dict)
    ]
    candidates.sort(key=lambda item: (
        item[1].get("order") if isinstance(item[1].get("order"), int) else item[0],
        item[0],
    ))
    for index, (source_index, asset) in enumerate(candidates, start=1):
        # Verified article packages historically store the asset discriminator
        # as `kind`; newer packages use `role`. Both identify the same
        # source-approved image/chart contract.
        article_role = asset.get("role") or asset.get("kind")
        asset_ref = asset.get("file")
        if article_role not in ARTICLE_ASSET_ROLES or not isinstance(asset_ref, str):
            continue
        image = package_path(root, asset_ref, f"approved {article_role}")
        asset_file = relative_path(image, root)
        if asset_file in seen:
            continue
        seen.add(asset_file)
        source_ids = asset.get("source_paragraph_ids", [])
        if not isinstance(source_ids, list) or not all(isinstance(value, str) for value in source_ids):
            source_ids = []
        approved.append({
            "role": "article_asset",
            "id": str(asset.get("id") or f"article-asset-{index:03d}"),
            "article_role": article_role,
            "file": asset_file,
            "source_order": source_index + 1,
            "source_paragraph_ids": list(dict.fromkeys(source_ids)),
        })
    return approved


def content_slot_plan(content_duration: float, asset_count: int) -> dict[str, Any]:
    selected_count = max(1, asset_count)
    if content_duration < CONTENT_IMAGE_MIN_SECONDS * selected_count:
        return {
            "slot_count": selected_count,
            "short_program_exception": True,
            "reason": "insufficient_duration_for_each_asset_at_minimum_dwell",
        }
    minimum_slots = max(selected_count, math.ceil(content_duration / CONTENT_IMAGE_MAX_SECONDS))
    maximum_slots = math.floor(content_duration / CONTENT_IMAGE_MIN_SECONDS)
    if minimum_slots > maximum_slots:
        raise StoryboardError(
            "Content duration cannot be partitioned into complete 18–22 second image slots."
        )
    candidates = range(minimum_slots, maximum_slots + 1)
    slot_count = min(candidates, key=lambda count: (abs(content_duration / count - CONTENT_IMAGE_TARGET_SECONDS), count))
    return {"slot_count": slot_count, "short_program_exception": False, "reason": None}


def content_slides(
    opening_end: float,
    duration: float,
    assets: list[dict[str, Any]],
    issue_cover_file: str,
    fallback_source_ids: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    content_duration = duration - opening_end
    if content_duration <= 0:
        return [], {
            "normalized_assets": assets,
            "sequence": [],
            "actual_dwell_seconds": {"minimum": None, "maximum": None, "values": []},
            "short_program_exception": True,
            "exception_reason": "no_content_duration",
        }
    selected = assets or [{
        "role": "issue_cover",
        "id": "issue-cover-fallback",
        "file": issue_cover_file,
        "source_paragraph_ids": [],
    }]
    plan = content_slot_plan(content_duration, len(selected))
    slot_count = plan["slot_count"]
    slot_duration = content_duration / slot_count
    slides: list[dict[str, Any]] = []
    sequence: list[dict[str, Any]] = []
    dwells: list[float] = []
    for index in range(slot_count):
        start = opening_end + index * slot_duration
        end = duration if index == slot_count - 1 else opening_end + (index + 1) * slot_duration
        selected_asset = selected[index % len(selected)]
        asset = {key: value for key, value in selected_asset.items() if key != "source_paragraph_ids"}
        source_ids = selected_asset.get("source_paragraph_ids") or fallback_source_ids
        slides.append({
            "id": f"content-{index + 1:03d}",
            "template_role": "guide_questions",
            "start_seconds": round(start, 3),
            "end_seconds": duration if index == slot_count - 1 else round(end, 3),
            "asset": asset,
            "source_paragraph_ids": list(source_ids),
        })
        dwell = round(end - start, 3)
        dwells.append(dwell)
        sequence.append({
            "slide_id": f"content-{index + 1:03d}",
            "asset_id": selected_asset["id"],
            "file": selected_asset["file"],
            "dwell_seconds": dwell,
        })
    return slides, {
        "normalized_assets": assets,
        "sequence": sequence,
        "actual_dwell_seconds": {
            "minimum": min(dwells),
            "maximum": max(dwells),
            "values": dwells,
        },
        "short_program_exception": plan["short_program_exception"],
        "exception_reason": plan["reason"],
    }


def build_storyboard(production_path: Path, questions_path: Path, storyboard_path: Path, opening_duration: float) -> dict[str, Any]:
    if opening_duration <= 0:
        raise StoryboardError("opening duration must be positive.")
    root = production_path.parent.resolve()
    production = read_json(production_path)
    _, article = resolve_article(production, root)
    _, audio, _, _ = resolve_media(production, root)
    duration = audio_duration(audio)
    if duration <= 1:
        raise StoryboardError("Final audio must be longer than one second for two template states.")
    questions, display = question_payload(questions_path, article.get("source_sha256"))
    opening_end = min(opening_duration, duration - 0.5)
    cover_file = issue_cover(article, root)
    article_assets = approved_article_assets(article, root)
    source_ids = sorted({source_id for question in questions for source_id in question["source_paragraph_ids"]})
    opening = {
        "id": "opening",
        "template_role": "opening",
        "start_seconds": 0,
        "end_seconds": round(opening_end, 3),
        "asset": {"role": "issue_cover", "id": "issue-cover", "file": cover_file},
        "source_paragraph_ids": [],
    }
    slides, rotation_report = content_slides(opening_end, duration, article_assets, cover_file, source_ids)
    storyboard = {
        "format": STORYBOARD_FORMAT,
        "schema_version": "1.1.0",
        "template_definition": "podcast-video-visual-system.v1.json",
        "article_source_sha256": article.get("source_sha256"),
        "display": display,
        "guide_questions": questions,
        "media_policy": {
            "opening": "issue_cover_required",
            "content": "approved_article_assets_round_robin",
            "target_seconds_per_asset": CONTENT_IMAGE_TARGET_SECONDS,
            "minimum_seconds_per_asset": CONTENT_IMAGE_MIN_SECONDS,
            "maximum_seconds_per_asset": CONTENT_IMAGE_MAX_SECONDS,
            "fallback": "issue_cover_when_no_article_assets",
            "animation": "none",
            "transition": "none",
            "image_fit": "contain_no_crop",
        },
        "media_rotation": rotation_report,
        "slides": [opening, *slides],
    }
    validate_storyboard(storyboard, duration)
    validate_storyboard_assets(storyboard, article, root)
    write_json(storyboard_path, storyboard)
    production.setdefault("artifacts", {})["storyboard"] = relative_path(storyboard_path, root)
    production.setdefault("video", {}).setdefault("image_rotation", {}).update({
        "opening_duration_seconds": round(opening_end, 3),
        "target_dwell_seconds": CONTENT_IMAGE_TARGET_SECONDS,
        "minimum_dwell_seconds": CONTENT_IMAGE_MIN_SECONDS,
        "maximum_dwell_seconds": CONTENT_IMAGE_MAX_SECONDS,
        "order": "source_round_robin",
        "normalized_assets": rotation_report["normalized_assets"],
        "actual_dwell_seconds": rotation_report["actual_dwell_seconds"],
        "short_program_exception": rotation_report["short_program_exception"],
    })
    write_json(production_path, production)
    return storyboard


def validate_storyboard(storyboard: dict[str, Any], duration: float) -> None:
    if storyboard.get("format") != STORYBOARD_FORMAT:
        raise StoryboardError(f"storyboard format must be {STORYBOARD_FORMAT}.")
    questions = storyboard.get("guide_questions")
    if not isinstance(questions, list) or len(questions) != 2:
        raise StoryboardError("storyboard needs exactly two guide questions.")
    slides = storyboard.get("slides")
    if not isinstance(slides, list) or len(slides) < 2:
        raise StoryboardError("storyboard needs at least opening and guide-question slides.")
    cursor = 0.0
    for index, slide in enumerate(slides):
        if slide.get("template_role") not in {"opening", "guide_questions"}:
            raise StoryboardError("storyboard only supports opening and guide_questions template roles.")
        if index == 0 and slide.get("template_role") != "opening":
            raise StoryboardError("The first storyboard slide must use the opening template role.")
        if index > 0 and slide.get("template_role") != "guide_questions":
            raise StoryboardError("Every content slide must use the guide_questions template role.")
        start, end = slide.get("start_seconds"), slide.get("end_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            raise StoryboardError("Every slide needs positive numeric start_seconds and end_seconds.")
        if abs(start - cursor) > 0.02:
            raise StoryboardError("Storyboard slides must be contiguous with no gaps or overlaps.")
        asset = slide.get("asset", {})
        if asset.get("role") not in {"issue_cover", "article_asset"} or not isinstance(asset.get("file"), str):
            raise StoryboardError("Every slide needs an approved issue_cover or article_asset file.")
        if index == 0 and asset.get("role") != "issue_cover":
            raise StoryboardError("The opening slide must use the verified issue cover.")
        cursor = float(end)
    if abs(cursor - duration) > 0.05:
        raise StoryboardError("Storyboard end_seconds must equal the final-audio duration.")


def validate_storyboard_assets(storyboard: dict[str, Any], article: dict[str, Any], root: Path) -> None:
    cover_file = issue_cover(article, root)
    approved_assets = approved_article_assets(article, root)
    approved_files = {asset["file"] for asset in approved_assets}
    content_slides = storyboard["slides"][1:]
    for index, slide in enumerate(storyboard["slides"]):
        asset = slide["asset"]
        asset_file = relative_path(package_path(root, asset["file"], f"asset for {slide['id']}"), root)
        if index == 0:
            if asset.get("role") != "issue_cover" or asset_file != cover_file:
                raise StoryboardError("The opening slide must use article.issue_cover.file.")
        elif approved_files:
            if asset.get("role") != "article_asset" or asset_file not in approved_files:
                raise StoryboardError("Content slides must use approved article images or charts.")
        elif asset.get("role") != "issue_cover" or asset_file != cover_file:
            raise StoryboardError("Content slides may use the issue cover only when no article assets exist.")

    if approved_assets:
        expected_files = [
            approved_assets[index % len(approved_assets)]["file"]
            for index in range(len(content_slides))
        ]
        actual_files = [slide["asset"]["file"] for slide in content_slides]
        if actual_files != expected_files:
            raise StoryboardError(
                "Content-slide assets must follow strict source-order round-robin rotation."
            )
    elif any(slide["asset"]["file"] != cover_file for slide in content_slides):
        raise StoryboardError("Issue-cover fallback must remain stable when no article assets exist.")

    content_duration = sum(float(slide["end_seconds"]) - float(slide["start_seconds"]) for slide in content_slides)
    selected_count = max(1, len(approved_assets))
    short_program = content_duration < CONTENT_IMAGE_MIN_SECONDS * selected_count
    if short_program:
        if len(content_slides) != selected_count:
            raise StoryboardError(
                "A short programme must show every approved article asset exactly once."
            )
    else:
        for slide in content_slides:
            dwell = float(slide["end_seconds"]) - float(slide["start_seconds"])
            if dwell < CONTENT_IMAGE_MIN_SECONDS - 0.01 or dwell > CONTENT_IMAGE_MAX_SECONDS + 0.01:
                raise StoryboardError("Every content image must dwell for 18–22 seconds.")

    rotation = storyboard.get("media_rotation")
    if not isinstance(rotation, dict):
        raise StoryboardError("storyboard media_rotation report is required.")
    normalized_files = [asset.get("file") for asset in rotation.get("normalized_assets", [])]
    if normalized_files != [asset["file"] for asset in approved_assets]:
        raise StoryboardError("storyboard media_rotation assets do not match the normalized article assets.")
    sequence_files = [item.get("file") for item in rotation.get("sequence", [])]
    if sequence_files != [slide["asset"]["file"] for slide in content_slides]:
        raise StoryboardError("storyboard media_rotation sequence does not match its content slides.")


def storyboard_asset_hashes(storyboard: dict[str, Any], root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for slide in storyboard["slides"]:
        asset_file = slide["asset"]["file"]
        if asset_file not in result:
            result[asset_file] = sha256_file(package_path(root, asset_file, f"asset for {slide['id']}"))
    return result


def display_content(article: dict[str, Any], storyboard: dict[str, Any], caption_en: str, caption_zh: str) -> dict[str, Any]:
    metadata = article["article"]
    display = storyboard.get("display", {})
    byline = metadata.get("byline") or ""
    dateline = metadata.get("dateline") or ""
    byline_dateline_issue = " · ".join(value for value in ("THE ECONOMIST", byline, dateline) if value)
    return {
        "article": {
            "kicker": metadata.get("kicker") or metadata.get("section") or "",
            "headline": metadata.get("headline") or "",
            "headline_zh": display.get("headline_zh", ""),
            "subtitle": metadata.get("subtitle") or "",
            "subtitle_zh": display.get("subtitle_zh", ""),
            "byline_dateline_issue": byline_dateline_issue,
        },
        "guide_questions": storyboard["guide_questions"],
        "caption": {"current": {"en": caption_en, "zh": caption_zh}},
    }


def structured_caption_cues(path: Path, variant: str) -> list[dict[str, Any]]:
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get("variant") != variant or not isinstance(payload.get("cues"), list):
        raise StoryboardError("Structured caption cues have an invalid contract.")
    normalized: list[dict[str, Any]] = []
    previous_end = -1.0
    for cue in payload["cues"]:
        if not isinstance(cue, dict):
            raise StoryboardError("Structured caption cue must be an object.")
        start, end = cue.get("start_seconds"), cue.get("end_seconds")
        english, chinese = str(cue.get("en_text", "")).strip(), str(cue.get("zh_text", "")).strip()
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start or start < previous_end - 0.0001:
            raise StoryboardError("Structured caption timing is invalid or overlaps.")
        if variant == "en-zh" and (not english or not chinese):
            raise StoryboardError("A structured bilingual cue needs complete English and Chinese text.")
        if variant == "en" and not english:
            raise StoryboardError("A structured English cue is empty.")
        if variant == "zh-CN" and not chinese:
            raise StoryboardError("A structured Chinese cue is empty.")
        normalized.append({"start": float(start), "end": float(end), "en_text": english, "zh_text": chinese})
        previous_end = float(end)
    if not normalized:
        raise StoryboardError("Structured caption cue payload is empty.")
    return normalized


def legacy_caption_cues(path: Path, variant: str) -> list[dict[str, Any]]:
    """Keep legacy SRT packages renderable without altering their text or timing."""
    result: list[dict[str, Any]] = []
    for cue in parse_srt(path):
        english, chinese = cue_text(cue, variant)
        result.append({"start": cue["start"], "end": cue["end"], "en_text": english, "zh_text": chinese})
    return result


def caption_fields(cue: dict[str, Any] | None, variant: str, subtitle_mode: str = "default") -> tuple[str, str]:
    try:
        subtitle_mode = validate_subtitle_mode(subtitle_mode)
    except ValueError as error:
        raise StoryboardError(str(error)) from error
    if subtitle_mode == "en-only" and variant == "zh-CN":
        raise StoryboardError("subtitle_mode=en-only requires an English caption source.")
    if cue is None:
        return "", ""
    if variant == "en":
        return str(cue.get("en_text", "")), ""
    if variant == "zh-CN":
        return "", str(cue.get("zh_text", ""))
    if subtitle_mode == "en-only":
        return str(cue.get("en_text", "")), ""
    return str(cue.get("en_text", "")), str(cue.get("zh_text", ""))


def validate_layout_diagnostics(items: list[dict[str, Any]]) -> None:
    for item in items:
        for layer in item.get("caption_layout", []):
            x, y, width, height = layer["safe_bbox"]
            if layer["layer"] == "caption_zh" and any(line.startswith(tuple("，。！？；：、）》】〉〕〗」』")) for line in layer.get("lines", [])):
                raise StoryboardError("A Chinese caption visual line begins with attached punctuation.")
            for line_x, line_y, line_width, line_height in layer["line_bboxes"]:
                if line_x < x or line_y < y or line_x + line_width > x + width or line_y + line_height > y + height:
                    raise StoryboardError(f"{layer['layer']} text exceeds its safe layout box.")


def timeline_intervals(storyboard: dict[str, Any], cues: list[dict[str, Any]], duration: float) -> list[tuple[float, float]]:
    points = {0.0, duration}
    for slide in storyboard["slides"]:
        points.update((float(slide["start_seconds"]), float(slide["end_seconds"])))
    for cue in cues:
        points.update((max(0.0, cue["start"]), min(duration, cue["end"])))
    ordered = sorted(points)
    return [(start, end) for start, end in zip(ordered, ordered[1:]) if end - start > 0.0001]


def active_item(items: list[dict[str, Any]], moment: float, start: str, end: str) -> dict[str, Any] | None:
    return next((item for item in items if float(item[start]) <= moment < float(item[end])), None)


def output_path(root: Path, variant: str, voice_profile: str, aspect_ratio: str, subtitle_mode: str = "default") -> Path:
    parts = ["video", variant, voice_profile]
    if subtitle_mode != "default":
        parts.append(subtitle_mode)
    parts.extend((aspect_ratio.replace(":", "x"), "final.mp4"))
    return root.joinpath(*parts)


def render_storyboard(
    production_path: Path,
    storyboard_path: Path,
    aspect_ratio: str,
    voice_profile: str = "default",
    subtitle_mode: str | None = None,
) -> tuple[Path, bool]:
    if not shutil.which("ffmpeg"):
        raise StoryboardError("ffmpeg is required to render static-slide video.")
    root = production_path.parent.resolve()
    production = read_json(production_path)
    try:
        subtitle_mode = validate_subtitle_mode(subtitle_mode or production.get("output", {}).get("subtitle_mode", "default"))
    except ValueError as error:
        raise StoryboardError(str(error)) from error
    permitted = production.get("output", {}).get("aspect_ratios", [])
    if aspect_ratio not in {"16:9", "9:16"} or aspect_ratio not in permitted:
        raise StoryboardError("The requested aspect ratio is not frozen in production.json output.aspect_ratios.")
    _, article = resolve_article(production, root)
    variant, audio, captions, structured_cues_path = resolve_media(production, root)
    if subtitle_mode == "en-only" and variant == "zh-CN":
        raise StoryboardError("subtitle_mode=en-only requires an English caption source.")
    duration = audio_duration(audio)
    storyboard = read_json(storyboard_path)
    validate_storyboard(storyboard, duration)
    validate_storyboard_assets(storyboard, article, root)
    definition = read_definition(TEMPLATE_PATH)
    destination = output_path(root, variant, voice_profile, aspect_ratio, subtitle_mode)
    fingerprint_inputs = {
        "template": sha256_file(TEMPLATE_PATH), "storyboard": sha256_file(storyboard_path), "audio": sha256_file(audio),
        "captions": sha256_file(captions), "structured_captions": sha256_file(structured_cues_path) if structured_cues_path else None,
        "renderer": sha256_file(Path(__file__)),
        "display_renderer": sha256_file(SCRIPT_DIR / "preview_visual_system.py"), "aspect_ratio": aspect_ratio,
        "subtitle_mode": subtitle_mode,
        "assets": storyboard_asset_hashes(storyboard, root),
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_inputs, sort_keys=True).encode()).hexdigest()
    output_key = f"{variant}/{voice_profile}/{aspect_ratio}" if subtitle_mode == "default" else f"{variant}/{voice_profile}/{subtitle_mode}/{aspect_ratio}"
    record = production.get("video", {}).get("outputs", {}).get(output_key, {})
    if destination.is_file() and record.get("state") == "complete" and record.get("input_sha256") == fingerprint:
        return destination, True

    cues = structured_caption_cues(structured_cues_path, variant) if structured_cues_path else legacy_caption_cues(captions, variant)
    destination.parent.mkdir(parents=True, exist_ok=True)
    render_diagnostics: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="economist-storyboard-") as temporary:
        temporary_path = Path(temporary)
        frames: list[tuple[Path, float]] = []
        template_names = definition["template_selection"][aspect_ratio]
        for index, (start, end) in enumerate(timeline_intervals(storyboard, cues, duration)):
            midpoint = (start + end) / 2
            slide = active_item(storyboard["slides"], midpoint, "start_seconds", "end_seconds")
            cue = active_item(cues, midpoint, "start", "end")
            if slide is None:
                raise StoryboardError(f"No storyboard slide is active at {midpoint:.3f}s.")
            caption_en, caption_zh = caption_fields(cue, variant, subtitle_mode)
            cover = package_path(root, slide["asset"]["file"], f"asset for {slide['id']}")
            caption_layout: list[dict[str, Any]] = []
            frame = render_template(
                definition,
                template_names[slide["template_role"]],
                cover,
                display_content(article, storyboard, caption_en, caption_zh),
                1080 if aspect_ratio == "16:9" else 1920,
                1920 if aspect_ratio == "16:9" else 1080,
                caption_layout,
                subtitle_mode,
            )
            render_diagnostics.append({
                "start_seconds": round(start, 7), "end_seconds": round(end, 7),
                "slide_id": slide["id"], "asset": slide["asset"], "caption_layout": caption_layout,
            })
            frame_path = temporary_path / f"frame-{index:05d}.png"
            frame.save(frame_path)
            frames.append((frame_path, end - start))
        manifest = temporary_path / "frames.txt"
        concat_manifest(manifest, frames)
        command = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-vf", "fps=30", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(destination),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
    validate_layout_diagnostics(render_diagnostics)
    report_path = destination.parent / "render-report.json"
    write_json(report_path, {
        "schema_version": "1.0", "variant": variant, "aspect_ratio": aspect_ratio, "subtitle_mode": subtitle_mode,
        "visible_caption_languages": ["en"] if subtitle_mode == "en-only" else (["zh"] if variant == "zh-CN" else ["en", "zh"]),
        "caption_source": "structured" if structured_cues_path else "legacy_srt",
        "asset_sha256": storyboard_asset_hashes(storyboard, root),
        "media_rotation": storyboard.get("media_rotation", {}),
        "image_frame": definition.get("design_tokens", {}).get("image_frame", {}),
        "frames": render_diagnostics,
    })
    outputs = production.setdefault("video", {}).setdefault("outputs", {})
    outputs[output_key] = {
        "state": "complete",
        "path": relative_path(destination, root),
        "sha256": sha256_file(destination),
        "input_sha256": fingerprint,
        "template": definition["name"],
        "storyboard": relative_path(storyboard_path, root),
        "render_report": relative_path(report_path, root),
        "render_report_sha256": sha256_file(report_path),
        "subtitle_mode": subtitle_mode,
    }
    write_json(production_path, production)
    return destination, False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-storyboard", help="Create the issue-cover opening and rotating article-media storyboard after audio and canonical SRT are complete.")
    init.add_argument("production_json", type=Path)
    init.add_argument("guide_questions_json", type=Path)
    init.add_argument("storyboard_json", type=Path)
    init.add_argument("--opening-duration", type=float, default=8.0)
    render = commands.add_parser("render", help="Render an addressable MP4 from frozen production media and storyboard.")
    render.add_argument("production_json", type=Path)
    render.add_argument("storyboard_json", type=Path)
    render.add_argument("--aspect-ratio", choices=("16:9", "9:16"), required=True)
    render.add_argument("--voice-profile", default="default")
    render.add_argument("--subtitle-mode", choices=tuple(sorted(SUPPORTED_SUBTITLE_MODES)))
    args = parser.parse_args()
    try:
        if args.command == "init-storyboard":
            storyboard = build_storyboard(args.production_json.resolve(), args.guide_questions_json.resolve(), args.storyboard_json.resolve(), args.opening_duration)
            print(json.dumps({"status": "complete", "storyboard": str(args.storyboard_json.resolve()), "slides": len(storyboard["slides"])}, ensure_ascii=False))
        else:
            destination, reused = render_storyboard(args.production_json.resolve(), args.storyboard_json.resolve(), args.aspect_ratio, args.voice_profile, args.subtitle_mode)
            print(json.dumps({"status": "complete", "output": str(destination), "reused": reused}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, StoryboardError) as error:
        message = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        print(f"error: {message}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
