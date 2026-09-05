#!/usr/bin/env python3
"""Build the user-facing video release package and perform bounded cleanup.

The release package is deliberately a copy of canonical outputs.  A later
rerender can therefore never mutate a package that has already been shared in
the chat.  Cleanup only removes directories owned by the selected media stage
and abandoned package staging directories; it never scans the whole package
for files that merely look temporary. Release covers are materialised from the
finished video frame immediately before packaging, then receive one editorial
text overlay layer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


PACKAGE_RELATIVE_PATH = Path("release") / "video-publish-package"
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
VIDEO_FRAME_COVER_SECONDS = 0.0
VIDEO_FRAME_COVER_FONT_PATHS = (
    "/Library/Fonts/Microsoft YaHei Bold.ttf",
    "/Library/Fonts/Microsoft YaHei.ttf",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
)


class ReleasePackageError(ValueError):
    """A release package cannot be built or verified safely."""


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _inside(root: Path, path: Path, label: str) -> Path:
    root = root.resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ReleasePackageError(f"{label} must remain inside the publication package: {resolved}") from error
    return resolved


def _source_file(root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ReleasePackageError(f"{label} is not declared.")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = _inside(root, candidate, label)
    if not candidate.is_file():
        raise ReleasePackageError(f"{label} is missing: {candidate}")
    return candidate


def _safe_component(value: Any, fallback: str) -> str:
    component = _SAFE_COMPONENT.sub("_", str(value or "")).strip("._")
    return component or fallback


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _video_for_ratio(root: Path, rendered: list[dict[str, Any]], ratio: str) -> Path:
    """Choose one finished video frame source for a cover deterministically."""
    priority = {"en-zh": 0, "en": 1, "zh-CN": 2}
    candidates: list[tuple[int, int, Path]] = []
    for index, item in enumerate(rendered):
        if not isinstance(item, dict) or str(item.get("aspect_ratio", "")) != ratio:
            continue
        path = item.get("path")
        if not isinstance(path, str):
            continue
        product = str(item.get("product", ""))
        candidates.append((priority.get(product, 99), index, _source_file(root, path, f"video output for cover {ratio}")))
    if not candidates:
        raise ReleasePackageError(f"No finished video output is available for cover {ratio}.")
    return min(candidates, key=lambda item: (item[0], item[1]))[2]


def _cover_font(size: int) -> tuple[ImageFont.FreeTypeFont, str, str]:
    for candidate in VIDEO_FRAME_COVER_FONT_PATHS:
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            face = ImageFont.truetype(str(path), size)
            return face, path.stem, str(path)
        except OSError:
            continue
    return ImageFont.load_default(), "Pillow default", ""


def _overlay_lines(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        position = str(item.get("position", "")).strip()
        if text and position in {"top", "middle", "bottom"}:
            result.append({"position": position, "text": text})
    return result


def _fit_overlay_face(draw: ImageDraw.ImageDraw, text: str, width: int, maximum: int, minimum: int) -> ImageFont.FreeTypeFont:
    for size in range(maximum, minimum - 1, -2):
        face, _family, _path = _cover_font(size)
        left, _top, right, _bottom = draw.textbbox((0, 0), text, font=face, stroke_width=max(2, round(size * 0.055)))
        if right - left <= width:
            return face
    face, _family, _path = _cover_font(minimum)
    return face


def _overlay_cover_text(frame: Image.Image, lines: list[dict[str, str]], aspect_ratio: str) -> dict[str, Any]:
    """Composite the existing editorial cover copy as one transparent text layer."""
    if not lines:
        return {"enabled": False, "lines": [], "bbox": None, "font_path": ""}
    width, height = frame.size
    if aspect_ratio == "16:9":
        # Keep the overlay in the image/text side of the opening frame. The
        # background itself is the extracted frame; no replacement panel is
        # painted behind it.
        region = (round(width * 0.56), round(height * 0.18), round(width * 0.37), round(height * 0.48))
        maximum, minimum = round(height * 0.085), max(22, round(height * 0.035))
    else:
        region = (round(width * 0.08), round(height * 0.12), round(width * 0.84), round(height * 0.42))
        maximum, minimum = round(width * 0.11), max(22, round(width * 0.045))
    x, y, region_width, region_height = region
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    gap = max(8, round(region_height * 0.06))
    line_records: list[dict[str, Any]] = []
    cursor = y
    palette = {"top": "#FFD400", "middle": "#E60012", "bottom": "#FFD400"}
    for item in lines:
        face = _fit_overlay_face(draw, item["text"], region_width, maximum, minimum)
        stroke = max(2, round(getattr(face, "size", minimum) * 0.055))
        left, top, right, bottom = draw.textbbox((0, 0), item["text"], font=face, stroke_width=stroke)
        text_width, text_height = right - left, bottom - top
        centre_x = x + region_width // 2
        centre_y = cursor + text_height // 2
        draw.text(
            (centre_x, centre_y), item["text"], font=face, fill=palette[item["position"]],
            stroke_width=stroke, stroke_fill="#000000", anchor="mm",
        )
        line_records.append({
            "position": item["position"], "text": item["text"],
            "bbox": [centre_x - text_width // 2, centre_y - text_height // 2, text_width, text_height],
            "font_size_px": getattr(face, "size", minimum), "stroke_width_px": stroke,
            "fill": palette[item["position"]],
        })
        cursor += text_height + gap
    frame.alpha_composite(overlay)
    used_bottom = max((record["bbox"][1] + record["bbox"][3] for record in line_records), default=y)
    font_path = ""
    if line_records:
        _face, _family, font_path = _cover_font(int(line_records[0]["font_size_px"]))
    return {
        "enabled": True, "layer": "release_cover_text", "bbox": [x, y, region_width, max(0, used_bottom - y)],
        "font_path": font_path, "lines": line_records,
    }


def _extract_video_frame(video: Path, destination: Path, frame_seconds: float) -> dict[str, Any]:
    if not shutil.which("ffmpeg"):
        raise ReleasePackageError("ffmpeg is required to extract a release-cover frame from the finished video.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp.png"
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0.0, frame_seconds):.3f}",
                "-i", str(video), "-frames:v", "1", "-f", "image2", str(temporary),
            ],
            check=False, capture_output=True, text=True,
        )
        if result.returncode != 0 or not temporary.is_file():
            raise ReleasePackageError(f"Could not extract a frame from finished video {video}: {result.stderr.strip() or 'ffmpeg failed'}")
        with Image.open(temporary) as extracted:
            frame = extracted.convert("RGBA")
            frame.save(destination, format="PNG")
            dimensions = {"width": frame.width, "height": frame.height}
        return dimensions
    finally:
        temporary.unlink(missing_ok=True)


def materialize_video_frame_covers(
    root: Path,
    production: dict[str, Any],
    rendered: list[dict[str, Any]],
    ratios: list[str],
    frame_seconds: float = VIDEO_FRAME_COVER_SECONDS,
) -> dict[str, dict[str, Any]]:
    """Build canonical release covers from finished-video frames.

    The first video frame is the complete background. Existing editorial
    ``cover_text`` is painted on one transparent overlay layer. This keeps the
    release cover visually identical to the selected Editorial Modern video
    instead of maintaining a second, unrelated dark-cover renderer.
    """
    root = root.resolve()
    editorial_path: Path | None = None
    artifacts = production.get("artifacts", {})
    editorial_ref = artifacts.get("editorial_assets") if isinstance(artifacts, dict) else None
    if isinstance(editorial_ref, str):
        candidate = (root / editorial_ref).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            candidate = None
        if candidate is not None and candidate.is_file():
            editorial_path = candidate
    editorial: dict[str, Any] = {}
    if editorial_path:
        try:
            payload = read_json(editorial_path)
            if isinstance(payload, dict):
                editorial = payload
        except (OSError, ValueError):
            editorial = {}
    cover_art = editorial.get("cover_art") if isinstance(editorial.get("cover_art"), dict) else {}
    lines = _overlay_lines(cover_art.get("text_lines"))
    results: dict[str, dict[str, Any]] = {}
    outputs: dict[str, Any] = {}
    if editorial_path:
        if not isinstance(editorial.get("cover_art"), dict):
            editorial["cover_art"] = {}
        if not isinstance(editorial["cover_art"].get("outputs"), dict):
            editorial["cover_art"]["outputs"] = {}
        outputs = editorial["cover_art"]["outputs"]
    for ratio in list(dict.fromkeys(str(item) for item in ratios)):
        video = _video_for_ratio(root, rendered, ratio)
        destination = root / "release" / "covers" / f"cover-{ratio.replace(':', 'x')}.png"
        dimensions = _extract_video_frame(video, destination, frame_seconds)
        with Image.open(destination) as extracted:
            frame = extracted.convert("RGBA")
        overlay = _overlay_cover_text(frame, lines, ratio)
        frame.convert("RGB").save(destination, format="PNG")
        record = {
            "path": str(destination.relative_to(root).as_posix()),
            "sha256": sha256_file(destination),
            "dimensions": dimensions,
            "template": "video_frame_overlay",
            "base_template": "Editorial Modern opening frame",
            "source_kind": "finished_video_frame",
            "source_video": str(video.relative_to(root).as_posix()),
            "source_video_sha256": sha256_file(video),
            "frame_time_seconds": round(float(frame_seconds), 3),
            "overlay": overlay,
        }
        results[ratio] = record
        if editorial_path:
            existing = outputs.get(ratio) if isinstance(outputs, dict) else None
            if not isinstance(existing, dict):
                existing = {}
            outputs[ratio] = {**existing, **record}

    if editorial_path:
        editorial.setdefault("cover_art", {})["background_source"] = {
            "mode": "finished_video_frame", "frame_time_seconds": round(float(frame_seconds), 3),
        }
        _write_json(editorial_path, editorial)
    production.setdefault("artifacts", {})
    production.setdefault("artifact_hashes", {})
    for ratio, record in results.items():
        key = f"cover_{ratio.replace(':', 'x')}"
        production["artifacts"][key] = record["path"]
        production["artifact_hashes"][key] = record["sha256"]
    if editorial_path:
        relative = str(editorial_path.relative_to(root).as_posix())
        production["artifacts"]["editorial_assets"] = relative
        production["artifact_hashes"]["editorial_assets"] = sha256_file(editorial_path)
    production_path = root / "production.json"
    if production_path.is_file():
        _write_json(production_path, production)
    return results


def _cover_sources(root: Path, production: dict[str, Any], ratios: list[str]) -> list[tuple[str, Path]]:
    artifacts = production.get("artifacts", {})
    editorial_ref = artifacts.get("editorial_assets") if isinstance(artifacts, dict) else None
    outputs: dict[str, Any] = {}
    if isinstance(editorial_ref, str):
        editorial_path = root / editorial_ref
        if editorial_path.is_file():
            try:
                editorial = read_json(editorial_path)
            except (OSError, ValueError):
                editorial = {}
            cover_art = editorial.get("cover_art", {}) if isinstance(editorial, dict) else {}
            outputs = cover_art.get("outputs", {}) if isinstance(cover_art, dict) else {}

    result: list[tuple[str, Path]] = []
    for ratio in ratios:
        output = outputs.get(ratio) if isinstance(outputs, dict) else None
        reference = output.get("path") if isinstance(output, dict) else None
        if not isinstance(reference, str):
            reference = f"release/covers/cover-{ratio.replace(':', 'x')}.png"
        result.append((ratio, _source_file(root, reference, f"release cover for {ratio}")))
    return result


def _publish_copy_source(root: Path, production: dict[str, Any]) -> Path:
    artifacts = production.get("artifacts", {})
    reference = artifacts.get("publish_copy") if isinstance(artifacts, dict) else None
    if not isinstance(reference, str):
        reference = "publish-copy.md"
    return _source_file(root, reference, "publish copy")


def _rewrite_publish_copy(text: str, root: Path, covers: list[tuple[str, Path]]) -> str:
    rewritten = text
    selected_names = {source.name for _ratio, source in covers}
    filtered_lines: list[str] = []
    for line in rewritten.splitlines(keepends=True):
        cover_names = re.findall(r"cover-\d+x\d+\.png", line)
        if cover_names and not any(name in selected_names for name in cover_names):
            continue
        filtered_lines.append(line)
    rewritten = "".join(filtered_lines)
    for _ratio, source in covers:
        relative = source.relative_to(root).as_posix()
        package_relative = f"covers/{source.name}"
        rewritten = rewritten.replace(relative, package_relative)
        rewritten = rewritten.replace(str(source), package_relative)
        rewritten = rewritten.replace(relative.replace("/", "\\"), package_relative)
    return rewritten


def _copy_record(source: Path, destination: Path, root: Path, source_label: str) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    source_hash = sha256_file(source)
    destination_hash = sha256_file(destination)
    if source_hash != destination_hash or destination.stat().st_size != source.stat().st_size:
        raise ReleasePackageError(f"Release package verification failed for {source_label}.")
    return {
        "path": str(destination.relative_to(root).as_posix()),
        "sha256": destination_hash,
        "bytes": destination.stat().st_size,
    }


def _file_record(path: Path, manifest_path: str, source_path: Path, root: Path, source_label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ReleasePackageError(f"Release package verification failed for {source_label}.")
    return {
        "path": manifest_path,
        "source_path": str(source_path.relative_to(root).as_posix()),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def build_release_package(
    root: Path,
    production: dict[str, Any],
    rendered: list[dict[str, Any]],
    ratios: list[str],
    voice_profile: str,
    cover_records: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build and verify a compact, independently copied release package."""
    root = root.resolve()
    release_dir = root / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    destination = root / PACKAGE_RELATIVE_PATH
    staging = Path(tempfile.mkdtemp(prefix=".video-publish-package.staging-", dir=str(release_dir)))
    package_files: list[dict[str, Any]] = []
    try:
        covers = _cover_sources(root, production, ratios)
        publish_copy = _publish_copy_source(root, production)
        publish_copy_destination = staging / "publish-copy.md"
        publish_copy_destination.parent.mkdir(parents=True, exist_ok=True)
        publish_copy_destination.write_text(
            _rewrite_publish_copy(publish_copy.read_text(encoding="utf-8"), root, covers),
            encoding="utf-8",
        )
        package_files.append(_file_record(
            publish_copy_destination,
            "release/video-publish-package/publish-copy.md",
            publish_copy,
            root,
            "publish copy",
        ))

        for ratio, source in covers:
            staged_cover = staging / "covers" / source.name
            record = _copy_record(source, staged_cover, staging, f"cover {ratio}")
            record["path"] = f"release/video-publish-package/covers/{source.name}"
            record["source_path"] = str(source.relative_to(root).as_posix())
            record["aspect_ratio"] = ratio
            provenance = (cover_records or {}).get(ratio)
            if isinstance(provenance, dict):
                for key in ("source_kind", "source_video", "source_video_sha256", "frame_time_seconds", "overlay"):
                    if key in provenance:
                        record[key] = provenance[key]
            package_files.append(record)

        for item in rendered:
            if not isinstance(item, dict):
                raise ReleasePackageError("Rendered output metadata is invalid.")
            source = _source_file(root, item.get("path"), f"video output {item.get('product', '')}")
            product = _safe_component(item.get("product"), "product")
            voice = _safe_component(voice_profile, "default")
            ratio = str(item.get("aspect_ratio", "")).strip()
            if ratio not in ratios:
                raise ReleasePackageError(f"Rendered output has an unexpected aspect ratio: {ratio!r}.")
            staged_video = staging / "videos" / product / voice / f"{ratio.replace(':', 'x')}.mp4"
            record = _copy_record(source, staged_video, staging, f"video {product} {ratio}")
            record["path"] = str((PACKAGE_RELATIVE_PATH / "videos" / product / voice / f"{ratio.replace(':', 'x')}.mp4").as_posix())
            record["source_path"] = str(source.relative_to(root).as_posix())
            record["product"] = item.get("product")
            record["aspect_ratio"] = ratio
            package_files.append(record)

        manifest = {
            "schema_version": "1.0.0",
            "package_type": "video-publish-package",
            "files": package_files,
            "file_count": len(package_files),
            "total_bytes": sum(int(item["bytes"]) for item in package_files),
        }
        (staging / "package.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not (staging / "package.json").is_file():
            raise ReleasePackageError("Release package manifest was not written.")

        backup: Path | None = None
        if destination.exists():
            backup = release_dir / f".video-publish-package.previous-{uuid.uuid4().hex}"
            destination.rename(backup)
        try:
            staging.rename(destination)
        except OSError:
            if backup and backup.exists() and not destination.exists():
                backup.rename(destination)
            raise
        if backup and backup.exists():
            shutil.rmtree(backup)
        return {
            "state": "complete",
            "path": str(PACKAGE_RELATIVE_PATH.as_posix()),
            "absolute_path": str(destination),
            "file_count": manifest["file_count"],
            "total_bytes": manifest["total_bytes"],
            "files": manifest["files"],
        }
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def safe_cleanup(root: Path, selected_variants: list[str], production: dict[str, Any]) -> dict[str, Any]:
    """Remove only owned selected-stage caches and abandoned package staging."""
    root = root.resolve()
    removed: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    candidates = [root / ".work" / "azure-speech-media" / variant for variant in dict.fromkeys(selected_variants)]
    release_dir = root / "release"
    if release_dir.is_dir():
        candidates.extend(sorted(release_dir.glob(".video-publish-package.staging-*")))
        candidates.extend(sorted(release_dir.glob(".video-publish-package.previous-*")))

    for candidate in candidates:
        if not candidate.exists():
            continue
        if candidate.is_symlink() or not candidate.is_dir():
            skipped.append({"path": str(candidate.relative_to(root)), "reason": "not_a_directory"})
            continue
        size = directory_size(candidate)
        try:
            candidate.relative_to(root / ".work" / "azure-speech-media")
            owner = "selected_media_stage"
        except ValueError:
            try:
                candidate.relative_to(release_dir)
                owner = "abandoned_release_staging"
            except ValueError:
                skipped.append({"path": str(candidate.relative_to(root)), "reason": "outside_cleanup_scope"})
                continue
        shutil.rmtree(candidate)
        removed.append({"path": str(candidate.relative_to(root).as_posix()), "bytes": size, "owner": owner})

    # Child processes are awaited by the existing render/media stages.  This
    # collection releases Python-side buffers held by the coordinator too.
    import gc

    gc.collect()
    return {
        "policy": "safe",
        "state": "complete",
        "removed": removed,
        "skipped": skipped,
        "removed_count": len(removed),
        "reclaimed_bytes": sum(item["bytes"] for item in removed),
        "external_shared_work": "preserved",
    }


def finalize_release_package(
    root: Path,
    production: dict[str, Any],
    report: dict[str, Any],
    cleanup_policy: str = "safe",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Package an already completed report; useful for a safe retry."""
    if cleanup_policy not in {"safe", "none"}:
        raise ReleasePackageError("cleanup_policy must be 'safe' or 'none'.")
    if report.get("state") != "complete":
        raise ReleasePackageError("Only a completed video workflow can be finalised.")
    outputs = report.get("outputs")
    ratios = report.get("aspect_ratios")
    voice_profile = report.get("voice_profile", "default")
    if not isinstance(outputs, list) or not outputs:
        raise ReleasePackageError("The completed workflow has no rendered video outputs.")
    if not isinstance(ratios, list) or not ratios:
        raise ReleasePackageError("The completed workflow has no aspect-ratio selection.")
    selected_ratios = [str(ratio) for ratio in ratios]
    cover_generation = materialize_video_frame_covers(root, production, outputs, selected_ratios)
    package = build_release_package(root, production, outputs, selected_ratios, str(voice_profile), cover_generation)
    package["cover_generation"] = cover_generation
    selected_variants = []
    request = production.get("workflow", {}).get("request", {})
    products = request.get("products") if isinstance(request, dict) else None
    product_variants = {"en": "en", "en-zh": "en-zh", "zh-CN": "zh-CN"}
    if isinstance(products, list):
        selected_variants = [product_variants[item] for item in products if item in product_variants]
    if not selected_variants:
        selected_variants = [str(report.get("variant"))] if report.get("variant") else []
    cleanup = (
        safe_cleanup(root, selected_variants, production)
        if cleanup_policy == "safe"
        else {"policy": "none", "state": "skipped", "removed": [], "removed_count": 0, "reclaimed_bytes": 0}
    )
    return package, cleanup
