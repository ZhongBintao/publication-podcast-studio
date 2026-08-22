#!/usr/bin/env python3
"""Create and render the non-animated Economist static-slide storyboard.

The renderer consumes completed canonical audio and SRT captions. It never
calls TTS, translation, OCR, an image generator, or a language model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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


def approved_slide_asset(article: dict[str, Any], root: Path) -> tuple[str, str]:
    """Prefer the verified article image while retaining fixture compatibility."""
    for asset in article.get("assets", []):
        if not isinstance(asset, dict) or asset.get("role") != "article_image":
            continue
        asset_ref = asset.get("file")
        if isinstance(asset_ref, str):
            image = package_path(root, asset_ref, "article image")
            return "article_asset", relative_path(image, root)
    return "issue_cover", issue_cover(article, root)


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
    asset_role, asset_file = approved_slide_asset(article, root)
    source_ids = sorted({source_id for question in questions for source_id in question["source_paragraph_ids"]})
    storyboard = {
        "format": STORYBOARD_FORMAT,
        "schema_version": "1.0.0",
        "template_definition": "podcast-video-visual-system.v1.json",
        "article_source_sha256": article.get("source_sha256"),
        "display": display,
        "guide_questions": questions,
        "slides": [
            {"id": "opening", "template_role": "opening", "start_seconds": 0, "end_seconds": round(opening_end, 3), "asset": {"role": asset_role, "file": asset_file}, "source_paragraph_ids": []},
            {"id": "guide-questions", "template_role": "guide_questions", "start_seconds": round(opening_end, 3), "end_seconds": duration, "asset": {"role": asset_role, "file": asset_file}, "source_paragraph_ids": source_ids},
        ],
    }
    validate_storyboard(storyboard, duration)
    write_json(storyboard_path, storyboard)
    production.setdefault("artifacts", {})["storyboard"] = relative_path(storyboard_path, root)
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
    for slide in slides:
        if slide.get("template_role") not in {"opening", "guide_questions"}:
            raise StoryboardError("storyboard only supports opening and guide_questions template roles.")
        start, end = slide.get("start_seconds"), slide.get("end_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            raise StoryboardError("Every slide needs positive numeric start_seconds and end_seconds.")
        if abs(start - cursor) > 0.02:
            raise StoryboardError("Storyboard slides must be contiguous with no gaps or overlaps.")
        asset = slide.get("asset", {})
        if asset.get("role") not in {"issue_cover", "article_asset"} or not isinstance(asset.get("file"), str):
            raise StoryboardError("Every slide needs an approved issue_cover or article_asset file.")
        cursor = float(end)
    if abs(cursor - duration) > 0.05:
        raise StoryboardError("Storyboard end_seconds must equal the final-audio duration.")


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
    definition = read_definition(TEMPLATE_PATH)
    destination = output_path(root, variant, voice_profile, aspect_ratio, subtitle_mode)
    fingerprint_inputs = {
        "template": sha256_file(TEMPLATE_PATH), "storyboard": sha256_file(storyboard_path), "audio": sha256_file(audio),
        "captions": sha256_file(captions), "structured_captions": sha256_file(structured_cues_path) if structured_cues_path else None,
        "renderer": sha256_file(Path(__file__)),
        "display_renderer": sha256_file(SCRIPT_DIR / "preview_visual_system.py"), "aspect_ratio": aspect_ratio,
        "subtitle_mode": subtitle_mode,
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
                "start_seconds": round(start, 7), "end_seconds": round(end, 7), "caption_layout": caption_layout,
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
        "caption_source": "structured" if structured_cues_path else "legacy_srt", "frames": render_diagnostics,
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
    init = commands.add_parser("init-storyboard", help="Create the two-state storyboard after audio and canonical SRT are complete.")
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
