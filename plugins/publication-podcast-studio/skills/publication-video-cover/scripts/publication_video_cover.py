#!/usr/bin/env python3
"""Create release covers from finished publication-video frames."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


SKILL_ROOT = Path(__file__).resolve().parents[1]
STATIC_RENDERER = SKILL_ROOT.parent / "publication-static-slide-video" / "scripts"
if str(STATIC_RENDERER) not in sys.path:
    sys.path.insert(0, str(STATIC_RENDERER))
import preview_visual_system as visual  # type: ignore  # noqa: E402


COVER_SCHEMA_VERSION = "1.0.0"
COVER_STYLE_VERSION = "reference-pop-v1"
DEFAULT_FRAME_SECONDS = 0.0
SUPPORTED_RATIOS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
PRODUCT_PRIORITY = {"en-zh": 0, "en": 1, "zh-CN": 2}
PALETTE = {
    "line_1": "#FFE500",
    "line_2": "#12D9FF",
    "line_3": "#12D9FF",
    "outline": "#000000",
}
FONT_REQUEST = "Noto Sans SC"


class VideoCoverError(ValueError):
    """A finished-video cover cannot be generated safely."""


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


def sha256_value(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _inside(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise VideoCoverError(f"{label} is not declared.")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.expanduser().resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise VideoCoverError(f"{label} must remain inside the publication package: {candidate}") from error
    if not candidate.is_file():
        raise VideoCoverError(f"{label} is missing: {candidate}")
    return candidate


def _editorial_path(root: Path, production: dict[str, Any]) -> Path:
    artifacts = production.get("artifacts")
    reference = artifacts.get("editorial_assets") if isinstance(artifacts, dict) else None
    return _inside(root, reference, "editorial assets")


def _select_video(root: Path, rendered: list[dict[str, Any]], ratio: str) -> Path:
    if ratio not in SUPPORTED_RATIOS:
        raise VideoCoverError(f"Unsupported cover aspect ratio: {ratio!r}.")
    candidates: list[tuple[int, int, Path, str]] = []
    for index, item in enumerate(rendered):
        if not isinstance(item, dict) or str(item.get("aspect_ratio", "")) != ratio:
            continue
        path = item.get("path")
        if not isinstance(path, str):
            continue
        product = str(item.get("product", ""))
        video = _inside(root, path, f"finished video for {ratio}")
        candidates.append((PRODUCT_PRIORITY.get(product, 99), index, video, product))
    if not candidates:
        raise VideoCoverError(f"No finished video output is available for cover {ratio}.")
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def _cover_lines(editorial: dict[str, Any]) -> list[dict[str, Any]]:
    cover_art = editorial.get("cover_art") if isinstance(editorial.get("cover_art"), dict) else {}
    raw = cover_art.get("text_lines")
    if not isinstance(raw, list) or len(raw) != 3:
        raise VideoCoverError("editorial-assets.json must contain exactly three cover_text lines.")
    expected = ("top", "middle", "bottom")
    lines: list[dict[str, Any]] = []
    for position, item in zip(expected, raw):
        if not isinstance(item, dict) or item.get("position") != position:
            raise VideoCoverError("cover_text positions must be top, middle, bottom in order.")
        text = str(item.get("text", "")).strip()
        if not text:
            raise VideoCoverError(f"cover_text.{position} must not be empty.")
        lines.append({"position": position, "text": text, "source_paragraph_ids": item.get("source_paragraph_ids", [])})
    return lines


def _font(size: int, text: str) -> ImageFont.FreeTypeFont:
    try:
        return visual.typeface(
            size,
            bold=True,
            cjk=True,
            sans=True,
            font_value=FONT_REQUEST,
            font_weight="bold",
            text=text,
            size_px=size,
        )
    except (OSError, RuntimeError, ValueError):
        candidates = (
            "/Users/zhongbintao/Library/Fonts/NOTOSANSSC-VF.TTF",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        )
        for candidate in candidates:
            if Path(candidate).is_file():
                try:
                    face = ImageFont.truetype(candidate, max(1, int(size)))
                    setattr(face, "_codex_font_path", candidate)
                    setattr(face, "_codex_font_weight", "bold")
                    setattr(face, "_codex_font_family", FONT_REQUEST)
                    return face
                except OSError:
                    continue
    raise VideoCoverError("No usable bold Chinese cover font was found.")


def _region(size: tuple[int, int], ratio: str) -> tuple[int, int, int, int, int, int]:
    width, height = size
    if ratio == "16:9":
        # The reference copy sits over the upper half of the frame and leaves
        # the lower subtitle area readable.
        return (round(width * 0.035), round(height * 0.045), round(width * 0.93), round(height * 0.42), round(height * 0.105), round(height * 0.035))
    return (round(width * 0.04), round(height * 0.035), round(width * 0.92), round(height * 0.42), round(width * 0.115), round(width * 0.04))


def _measure_line(draw: ImageDraw.ImageDraw, text: str, face: ImageFont.FreeTypeFont, stroke: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=face, stroke_width=stroke)
    return left, top, right, bottom


def _fit_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[dict[str, Any]],
    region_width: int,
    region_height: int,
    maximum: int,
    minimum: int,
) -> tuple[list[dict[str, Any]], int, int]:
    for base_size in range(maximum, minimum - 1, -2):
        measured: list[dict[str, Any]] = []
        gap = max(4, round(base_size * 0.10))
        total_height = 0
        fits = True
        for index, line in enumerate(lines):
            size = round(base_size * (1.12 if index == 0 else 1.0))
            face = _font(size, line["text"])
            stroke = max(2, round(size * 0.10))
            left, top, right, bottom = _measure_line(draw, line["text"], face, stroke)
            line_width, line_height = right - left, bottom - top
            if line_width > region_width:
                fits = False
                break
            measured.append({"face": face, "stroke": stroke, "size": size, "bbox": (left, top, right, bottom), "width": line_width, "height": line_height})
            total_height += line_height
        total_height += gap * (len(lines) - 1)
        if fits and total_height <= region_height:
            return measured, total_height, gap
    raise VideoCoverError("Cover text cannot fit the reference safe area without truncation.")


def _draw_overlay(frame: Image.Image, lines: list[dict[str, Any]], ratio: str) -> dict[str, Any]:
    width, height = frame.size
    x, y, region_width, region_height, maximum, minimum = _region(frame.size, ratio)
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    measured, total_height, gap = _fit_lines(draw, lines, region_width, region_height, maximum, minimum)
    cursor = y + max(0, (region_height - total_height) // 2)
    line_records: list[dict[str, Any]] = []
    font_paths: list[str] = []
    for index, (line, metrics) in enumerate(zip(lines, measured)):
        centre_x = x + region_width // 2
        centre_y = cursor + metrics["height"] // 2
        draw.text(
            (centre_x, centre_y), line["text"], font=metrics["face"], fill=PALETTE[f"line_{index + 1}"],
            stroke_width=metrics["stroke"], stroke_fill=PALETTE["outline"], anchor="mm",
        )
        # Query the same anchored box used by Pillow for a record that follows
        # the painted pixels exactly, including the outline.
        actual_bbox = draw.textbbox(
            (centre_x, centre_y), line["text"], font=metrics["face"],
            stroke_width=metrics["stroke"], anchor="mm",
        )
        actual = (
            actual_bbox[0], actual_bbox[1],
            actual_bbox[2] - actual_bbox[0], actual_bbox[3] - actual_bbox[1],
        )
        line_records.append({
            "position": line["position"], "text": line["text"], "bbox": list(actual),
            "font_size_px": metrics["size"], "stroke_width_px": metrics["stroke"],
            "fill": PALETTE[f"line_{index + 1}"], "stroke_fill": PALETTE["outline"],
        })
        font_path = str(getattr(metrics["face"], "_codex_font_path", ""))
        if font_path:
            font_paths.append(font_path)
        cursor += metrics["height"] + gap
    frame.alpha_composite(overlay)
    paint_left = min(item["bbox"][0] for item in line_records)
    paint_top = min(item["bbox"][1] for item in line_records)
    paint_right = max(item["bbox"][0] + item["bbox"][2] for item in line_records)
    paint_bottom = max(item["bbox"][1] + item["bbox"][3] for item in line_records)
    return {
        "kind": "text_overlay",
        "layer_id": "release_cover_text",
        "enabled": True,
        "layer": "release_cover_text",
        "style_version": COVER_STYLE_VERSION,
        "bbox": [paint_left, paint_top, paint_right - paint_left, paint_bottom - paint_top],
        "safe_bbox": [x, y, region_width, region_height],
        "alignment": "center",
        "font_family": FONT_REQUEST,
        "font_path": font_paths[0] if font_paths else "",
        "font_weight": "bold",
        "palette": dict(PALETTE),
        "lines": line_records,
    }


def _extract_frame(video: Path, frame_seconds: float, destination: Path) -> dict[str, int]:
    if not shutil.which("ffmpeg"):
        raise VideoCoverError("ffmpeg is required to extract the finished video frame.")
    temporary = destination.with_name(f".{destination.name}.frame-{uuid.uuid4().hex}.png")
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, frame_seconds):.3f}",
                "-i", str(video), "-frames:v", "1", "-f", "image2", str(temporary),
            ],
            check=False, capture_output=True, text=True,
        )
        if result.returncode != 0 or not temporary.is_file():
            raise VideoCoverError(f"Could not extract a frame from {video}: {result.stderr.strip() or 'ffmpeg failed'}")
        with Image.open(temporary) as image:
            frame = image.convert("RGBA")
            dimensions = (frame.width, frame.height)
            frame.save(destination, format="PNG")
        return {"width": dimensions[0], "height": dimensions[1]}
    finally:
        temporary.unlink(missing_ok=True)


def _write_publish_copy(root: Path, editorial_path: Path, assets: dict[str, Any]) -> None:
    publish_copy = editorial_path.parent / "publish-copy.md"
    if not publish_copy.is_file():
        return
    text = publish_copy.read_text(encoding="utf-8")
    lines = ["## 发布封面", ""]
    outputs = assets.get("cover_art", {}).get("outputs", {}) if isinstance(assets.get("cover_art"), dict) else {}
    for ratio in ("16:9", "9:16"):
        output = outputs.get(ratio) if isinstance(outputs, dict) else None
        if not isinstance(output, dict) or output.get("state") != "complete":
            continue
        label = "横屏" if ratio == "16:9" else "竖屏"
        lines.append(f"- {label}：{output['path']}")
    replacement = "\n".join(lines).rstrip() + "\n"
    marker = "## 发布封面"
    if marker in text:
        before, after = text.split(marker, 1)
        next_section = after.find("\n## ")
        tail = after[next_section + 1:] if next_section >= 0 else ""
        text = before.rstrip() + "\n\n" + replacement + ("\n" + tail if tail else "")
    else:
        text = text.rstrip() + "\n\n" + replacement
    publish_copy.write_text(text, encoding="utf-8")


def _same_frame_time(value: Any, expected: float) -> bool:
    try:
        return float(value) == round(float(expected), 3)
    except (TypeError, ValueError):
        return False


def materialize_video_covers(
    root: Path,
    production: dict[str, Any],
    rendered: list[dict[str, Any]],
    ratios: list[str],
    frame_seconds: float = DEFAULT_FRAME_SECONDS,
) -> dict[str, Any]:
    """Create or reuse one frame-based cover for every selected ratio."""
    root = root.resolve()
    if frame_seconds < 0:
        raise VideoCoverError("frame_seconds must be non-negative.")
    editorial_path = _editorial_path(root, production)
    editorial = read_json(editorial_path)
    if not isinstance(editorial, dict):
        raise VideoCoverError("editorial-assets.json must be a JSON object.")
    lines = _cover_lines(editorial)
    cover_art = editorial.get("cover_art") if isinstance(editorial.get("cover_art"), dict) else {}
    outputs = cover_art.get("outputs") if isinstance(cover_art.get("outputs"), dict) else {}
    cover_text_hash = sha256_value([{key: value for key, value in line.items() if key != "source_paragraph_ids"} for line in lines])
    generated: dict[str, dict[str, Any]] = {}
    for ratio in list(dict.fromkeys(str(value) for value in ratios)):
        video = _select_video(root, rendered, ratio)
        source_hash = sha256_file(video)
        destination = root / "release" / "covers" / f"cover-{ratio.replace(':', 'x')}.png"
        existing = outputs.get(ratio) if isinstance(outputs, dict) else None
        reusable = (
            isinstance(existing, dict)
            and existing.get("state") == "complete"
            and existing.get("source_kind") == "finished_video_frame"
            and existing.get("source_video_sha256") == source_hash
            and _same_frame_time(existing.get("frame_time_seconds"), frame_seconds)
            and existing.get("cover_text_sha256") == cover_text_hash
            and existing.get("style_version") == COVER_STYLE_VERSION
            and destination.is_file()
            and existing.get("sha256") == sha256_file(destination)
        )
        if reusable:
            record = dict(existing)
            record["reused"] = True
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.render-{uuid.uuid4().hex}.png")
            try:
                dimensions = _extract_frame(video, frame_seconds, temporary)
                expected = SUPPORTED_RATIOS[ratio]
                if (dimensions["width"], dimensions["height"]) != expected:
                    raise VideoCoverError(
                        f"Finished video {video} has {dimensions['width']}x{dimensions['height']}; "
                        f"cover {ratio} requires {expected[0]}x{expected[1]} without scaling."
                    )
                with Image.open(temporary) as extracted:
                    frame = extracted.convert("RGBA")
                overlay = _draw_overlay(frame, lines, ratio)
                frame.convert("RGB").save(temporary, format="PNG")
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
            record = {
                "state": "complete",
                "path": str(destination.relative_to(root).as_posix()),
                "sha256": sha256_file(destination),
                "dimensions": dimensions,
                "template": "video_frame_cover",
                "source_kind": "finished_video_frame",
                "source_video": str(video.relative_to(root).as_posix()),
                "source_video_sha256": source_hash,
                "frame_time_seconds": round(float(frame_seconds), 3),
                "style_version": COVER_STYLE_VERSION,
                "cover_text_sha256": cover_text_hash,
                "overlay": overlay,
                "reused": False,
            }
        generated[ratio] = record

    cover_art = dict(cover_art)
    cover_art.update({
        "state": "complete",
        "background_source": {
            "mode": "finished_video_frame",
            "frame_time_seconds": round(float(frame_seconds), 3),
            "selection_priority": ["en-zh", "en", "zh-CN"],
            "videos": {
                ratio: {
                    "path": record.get("source_video"),
                    "sha256": record.get("source_video_sha256"),
                }
                for ratio, record in generated.items()
            },
        },
        "style_version": COVER_STYLE_VERSION,
        "style": {
            "font_family": FONT_REQUEST,
            "font_weight": "bold",
            "line_1_fill": PALETTE["line_1"],
            "line_2_fill": PALETTE["line_2"],
            "line_3_fill": PALETTE["line_3"],
            "outline": PALETTE["outline"],
            "stroke_fill": PALETTE["outline"],
            "font_preference": FONT_REQUEST,
            "no_background_panel": True,
        },
        "outputs": {**outputs, **generated},
    })
    editorial["cover_art"] = cover_art
    write_json(editorial_path, editorial)
    _write_publish_copy(root, editorial_path, editorial)

    production.setdefault("artifacts", {})
    production.setdefault("artifact_hashes", {})
    for key in list(production["artifacts"]):
        if key.startswith("cover_"):
            production["artifacts"].pop(key, None)
            production["artifact_hashes"].pop(key, None)
    for ratio, record in generated.items():
        key = f"cover_{ratio.replace(':', 'x')}"
        production["artifacts"][key] = record["path"]
        production["artifact_hashes"][key] = record["sha256"]
    editorial_relative = str(editorial_path.relative_to(root).as_posix())
    production["artifacts"]["editorial_assets"] = editorial_relative
    production["artifact_hashes"]["editorial_assets"] = sha256_file(editorial_path)
    publish_copy = editorial_path.parent / "publish-copy.md"
    if publish_copy.is_file():
        production["artifacts"]["publish_copy"] = str(publish_copy.relative_to(root).as_posix())
        production["artifact_hashes"]["publish_copy"] = sha256_file(publish_copy)
    production_path = root / "production.json"
    if production_path.is_file():
        write_json(production_path, production)
    result = {
        "state": "complete",
        "schema_version": COVER_SCHEMA_VERSION,
        "frame_time_seconds": round(float(frame_seconds), 3),
        "selection_priority": ["en-zh", "en", "zh-CN"],
        "outputs": generated,
    }
    # Keep ratio records addressable at the report root for compatibility with
    # the original workflow-report contract while making ``outputs`` the
    # canonical collection for new callers.
    result.update(generated)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render = commands.add_parser("render", help="Generate finished-video-frame release covers.")
    render.add_argument("production", type=Path)
    render.add_argument("workflow_report", type=Path)
    render.add_argument("--aspect-ratio", action="append", dest="ratios")
    render.add_argument("--frame-seconds", type=float, default=DEFAULT_FRAME_SECONDS)
    args = parser.parse_args()
    try:
        if args.command != "render":
            raise VideoCoverError(f"Unsupported command: {args.command}")
        production_path = args.production.resolve()
        production = read_json(production_path)
        report = read_json(args.workflow_report.resolve())
        if report.get("state") != "complete":
            raise VideoCoverError("The workflow report is not a completed video run.")
        ratios = args.ratios or report.get("aspect_ratios")
        rendered = report.get("outputs")
        if not isinstance(ratios, list) or not ratios:
            raise VideoCoverError("No cover aspect ratios were supplied or recorded in the workflow report.")
        if not isinstance(rendered, list) or not rendered:
            raise VideoCoverError("The workflow report has no finished video outputs.")
        result = materialize_video_covers(production_path.parent, production, rendered, [str(value) for value in ratios], args.frame_seconds)
        write_json(production_path, production)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, VideoCoverError) as error:
        print(json.dumps({"state": "failed", "reason": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
