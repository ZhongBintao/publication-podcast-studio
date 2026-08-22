#!/usr/bin/env python3
"""Render the fixed editorial opening frame used by the static-slide video skill.

This is intentionally a layout renderer, not a storyboard planner. It draws one
frame from verified article metadata and one approved media slot. Storyboard
logic will later decide which article image occupies the slot at each timestamp.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


CANVASES = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
PAPER = "#262626"
LANDSCAPE_PAPER = "#262626"
INK = "#FFFFFF"
RED = "#E3121A"
CAPTION = "#FFFFFF"
SERIF_FONTS = (
    "/System/Library/Fonts/Supplemental/Baskerville.ttc",
    "/Library/Fonts/Baskerville.ttc",
)
SANS_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/ArialHB.ttc",
)
ARIAL_BOLD_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/ArialHB.ttc",
)
CJK_FONTS = (
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
)
NOTO_SANS_SC_FONTS = (
    "/Users/zhongbintao/Library/Fonts/NOTOSANSSC-VF.TTF",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
)
class TemplateError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_caption_text(value: str) -> str:
    """Use a universally covered visual equivalent for fragile dash glyphs."""
    return value.replace("\u2011", "-").replace("\u00ad", "-")


def _supports_text(typeface: ImageFont.FreeTypeFont, value: str) -> bool:
    if not value.strip():
        return True
    tofu = bytes(typeface.getmask("\u25a1"))
    return all(character.isspace() or character == "\u25a1" or bytes(typeface.getmask(character)) != tofu for character in set(value))


def font(paths: tuple[str, ...], size: int, *, weight: str = "regular", text: str = "") -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in paths:
        if Path(candidate).exists():
            try:
                typeface = ImageFont.truetype(candidate, size)
                if Path(candidate).name == "NOTOSANSSC-VF.TTF":
                    try:
                        typeface.set_variation_by_name({"medium": "Medium", "bold": "Bold", "regular": "Regular"}.get(weight, "Regular"))
                    except OSError:
                        pass
                if _supports_text(typeface, text):
                    return typeface
            except OSError:
                continue
    for candidate in paths:
        if Path(candidate).exists():
            try:
                typeface = ImageFont.truetype(candidate, size)
                if Path(candidate).name == "NOTOSANSSC-VF.TTF":
                    try:
                        typeface.set_variation_by_name({"medium": "Medium", "bold": "Bold", "regular": "Regular"}.get(weight, "Regular"))
                    except OSError:
                        pass
                return typeface
            except OSError:
                continue
    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, value: str, typeface: ImageFont.ImageFont) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), value or " ", font=typeface)
    return right - left, bottom - top


def glyph_height(draw: ImageDraw.ImageDraw, typeface: ImageFont.ImageFont) -> int:
    return text_size(draw, "Agjpqy汉字", typeface)[1]


def split_long_token(draw: ImageDraw.ImageDraw, token: str, typeface: ImageFont.ImageFont, width: int) -> list[str]:
    parts, current = [], ""
    for character in token:
        if current and text_size(draw, current + character, typeface)[0] > width:
            parts.append(current)
            current = character
        else:
            current += character
    if current:
        parts.append(current)
    return parts or [token]


def cjk_wrap_tokens(value: str) -> list[str]:
    attached = set("，。！？；：、）》】〉〕〗」』")
    tokens: list[str] = []
    for character in value:
        if character in attached and tokens:
            tokens[-1] += character
        else:
            tokens.append(character)
    return tokens


def wrap_text(draw: ImageDraw.ImageDraw, value: str, typeface: ImageFont.ImageFont, width: int) -> list[str]:
    value = " ".join(value.split())
    if not value:
        return []
    tokens = value.split(" ") if " " in value else cjk_wrap_tokens(value)
    lines: list[str] = []
    current = ""
    separator = " " if " " in value else ""
    for token in tokens:
        proposed = token if not current else current + separator + token
        if current and text_size(draw, proposed, typeface)[0] > width:
            lines.append(current)
            if text_size(draw, token, typeface)[0] > width:
                pieces = split_long_token(draw, token, typeface, width)
                lines.extend(pieces[:-1])
                current = pieces[-1]
            else:
                current = token
        else:
            current = proposed
    if current:
        lines.append(current)
    return lines


def balanced_wrap_text(draw: ImageDraw.ImageDraw, value: str, typeface: ImageFont.ImageFont, width: int, max_lines: int) -> list[str]:
    greedy = wrap_text(draw, value, typeface, width)
    if max_lines != 2 or len(greedy) <= 1:
        return greedy
    paragraph = " ".join(value.split())
    spaced = " " in paragraph
    tokens = paragraph.split(" ") if spaced else cjk_wrap_tokens(paragraph)
    candidates: list[tuple[int, list[str]]] = []
    for index in range(1, len(tokens)):
        left = " ".join(tokens[:index]) if spaced else "".join(tokens[:index])
        right = " ".join(tokens[index:]) if spaced else "".join(tokens[index:])
        if text_size(draw, left, typeface)[0] <= width and text_size(draw, right, typeface)[0] <= width:
            candidates.append((abs(text_size(draw, left, typeface)[0] - text_size(draw, right, typeface)[0]), [left, right]))
    return min(candidates, key=lambda item: item[0])[1] if candidates else greedy


def fitted_text(draw: ImageDraw.ImageDraw, value: str, paths: tuple[str, ...], max_size: int, min_size: int, width: int, max_lines: int, *, weight: str = "regular", allow_truncation: bool = True, balance: bool = False) -> tuple[ImageFont.ImageFont, list[str]]:
    for size in range(max_size, min_size - 1, -2):
        typeface = font(paths, size, weight=weight, text=value)
        lines = balanced_wrap_text(draw, value, typeface, width, max_lines) if balance else wrap_text(draw, value, typeface, width)
        if len(lines) <= max_lines:
            return typeface, lines
    typeface = font(paths, min_size, weight=weight, text=value)
    lines = balanced_wrap_text(draw, value, typeface, width, max_lines) if balance else wrap_text(draw, value, typeface, width)
    if not allow_truncation and len(lines) > max_lines:
        raise TemplateError("Caption cannot fit in two complete lines without truncation.")
    return typeface, lines[:max_lines] if allow_truncation else lines


def draw_lines(draw: ImageDraw.ImageDraw, xy: tuple[int, int], lines: list[str], typeface: ImageFont.ImageFont, fill: str, line_gap: int) -> int:
    x, y = xy
    line_height = glyph_height(draw, typeface)
    for line in lines:
        draw.text((x, y), line, font=typeface, fill=fill)
        y += line_height + line_gap
    return y


def draw_caption_lines(canvas: Image.Image, x: int, y: int, width: int, lines: list[str], typeface: ImageFont.ImageFont, line_gap: int) -> None:
    """Draw horizontal movie-style captions with a compact translucent underlay."""
    draw = ImageDraw.Draw(canvas)
    stroke_width = 0
    line_height = glyph_height(draw, typeface)
    placements: list[tuple[str, int, int, int, int]] = []
    cursor_y = y + 6
    for line in lines:
        left, top, right, bottom = draw.textbbox((0, 0), line, font=typeface, stroke_width=stroke_width)
        line_width, line_box_height = right - left, bottom - top
        line_x = x + max(0, (width - line_width) // 2)
        text_y = cursor_y - top
        placements.append((line, line_x, text_y, line_width, line_box_height))
        cursor_y += line_height + line_gap

    if placements:
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        for _, line_x, text_y, line_width, line_box_height in placements:
            overlay_draw.rectangle((line_x - 12, text_y - 6, line_x + line_width + 12, text_y + line_box_height + 6), fill=(38, 38, 38, 255))
        canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB"))
        draw = ImageDraw.Draw(canvas)

    for line, line_x, text_y, _, _ in placements:
        draw.text((line_x, text_y), line, font=typeface, fill="#FFFFFF", stroke_width=stroke_width, stroke_fill="#FFFFFF")


def place_media(canvas: Image.Image, image_path: Path, box: tuple[int, int, int, int], fit: str) -> None:
    x, y, width, height = box
    frame = Image.new("RGB", (width, height), "#262626")
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        scale = (max if fit == "crop" else min)(width / image.width, height / image.height)
        resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS)
        if fit == "crop":
            offset = ((resized.width - width) // 2, (resized.height - height) // 2)
            frame.paste(resized.crop((offset[0], offset[1], offset[0] + width, offset[1] + height)))
        else:
            frame.paste(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
    shadow = Image.new("RGBA", (width + 32, height + 32), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((16, 16, width + 15, height + 15), fill=(23, 23, 22, 64))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.paste(shadow, (x - 16, y - 16), shadow)
    canvas.paste(frame, (x, y))
    ImageDraw.Draw(canvas).rectangle((x, y, x + width - 1, y + height - 1), outline="#FFFFFF", width=3)


def issue_media_path(article_path: Path, article: dict[str, Any], override: str | None) -> Path:
    if override:
        path = Path(override).expanduser().resolve()
    else:
        cover = article.get("issue_cover", {})
        file = cover.get("file")
        if not file:
            raise TemplateError("article.json has no issue_cover; pass --image for a historical package.")
        path = (article_path.parent / file).resolve()
    if not path.is_file():
        raise TemplateError(f"Media slot image is missing: {path}")
    return path


def metadata_line(article: dict[str, Any]) -> str:
    parts = [article.get("byline"), article.get("dateline")]
    return " · ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def srt_seconds(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
    if not match:
        raise TemplateError(f"Invalid SRT timestamp: {value}")
    hours, minutes, seconds, milliseconds = (int(item) for item in match.groups())
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def parse_srt(path: Path) -> list[dict[str, Any]]:
    """Read only the canonical caption text and timestamps, never ASR text."""
    blocks = re.split(r"\r?\n\s*\r?\n", path.read_text(encoding="utf-8").strip())
    cues = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        start_text, end_text = (part.strip() for part in lines[timing_index].split("-->", 1))
        start, end = srt_seconds(start_text), srt_seconds(end_text)
        if end <= start:
            raise TemplateError("SRT contains a non-positive caption cue.")
        cues.append({"start": start, "end": end, "lines": lines[timing_index + 1 :]})
    if not cues:
        raise TemplateError("SRT has no usable caption cues.")
    if any(next_cue["start"] < cue["end"] for cue, next_cue in zip(cues, cues[1:])):
        raise TemplateError("SRT caption cues overlap.")
    return cues


def cue_text(cue: dict[str, Any] | None, variant: str) -> tuple[str, str]:
    if cue is None:
        return "", ""
    lines = cue["lines"]
    if variant == "en":
        return " ".join(lines), ""
    if variant == "zh-CN":
        return "", "".join(lines)
    if variant == "en-zh":
        if len(lines) < 2:
            raise TemplateError("An en-zh SRT cue needs English and Chinese lines.")
        return lines[0], "".join(lines[1:])
    raise TemplateError(f"Unsupported caption variant: {variant}")


def audio_duration(audio_path: Path) -> float:
    if not shutil.which("ffprobe"):
        raise TemplateError("ffprobe is required to use an audio timeline.")
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(audio_path)],
        check=True, capture_output=True, text=True,
    )
    duration = float(json.loads(result.stdout)["format"]["duration"])
    if duration <= 0:
        raise TemplateError("Audio duration must be positive.")
    return duration


def render_editorial_frame(article_path: Path, aspect_ratio: str, caption_en: str, caption_zh: str, image_override: str | None = None, media_role: str = "issue_cover") -> Image.Image:
    if aspect_ratio not in CANVASES:
        raise TemplateError(f"Unsupported aspect ratio: {aspect_ratio}")
    caption_en = normalize_caption_text(caption_en)
    caption_zh = normalize_caption_text(caption_zh)
    package = read_json(article_path)
    article = package.get("article", {})
    if not article.get("headline"):
        raise TemplateError("article.json needs article.headline.")
    image_path = issue_media_path(article_path, package, image_override)
    canvas = Image.new("RGB", CANVASES[aspect_ratio], LANDSCAPE_PAPER if aspect_ratio == "16:9" else PAPER)
    draw = ImageDraw.Draw(canvas)
    # Vertical and horizontal source images are always contained. The template
    # may leave letterboxing, but it must never crop or distort verified art.
    fit = "contain"
    kicker = (article.get("kicker") or article.get("section") or "").upper()
    subtitle = article.get("subtitle") or ""
    attribution = metadata_line(article)

    if aspect_ratio == "16:9":
        rail_y, rail_height = 856, 224
        place_media(canvas, image_path, (1110, 45, 595, 795), fit)
        kicker_font = font(SANS_FONTS, 21)
        draw.text((116, 127), kicker, font=kicker_font, fill=RED)
        title_font, title_lines = fitted_text(draw, article["headline"], SERIF_FONTS, 78, 54, 820, 3)
        title_bottom = draw_lines(draw, (116, 240), title_lines, title_font, INK, 12)
        subtitle_font, subtitle_lines = fitted_text(draw, subtitle, SANS_FONTS, 31, 24, 750, 3)
        subtitle_y = max(445, title_bottom + 80)
        subtitle_bottom = draw_lines(draw, (116, subtitle_y), subtitle_lines, subtitle_font, INK, 10)
        if attribution:
            draw.text((116, max(585, subtitle_bottom + 45)), attribution, font=font(SANS_FONTS, 24), fill=INK)
        caption_x, caption_y, caption_width = 140, 900, 1620
        en_max = zh_max = 32
    else:
        # The formal portrait template is a compact free-flow stack. The last
        # 10% of the frame is intentionally left empty for platform details;
        # captions end above that boundary and never enter it.
        place_media(canvas, image_path, (140, 80, 800, 480), fit)
        kicker_font = font(SANS_FONTS, 21)
        draw.text((42, 615), kicker, font=kicker_font, fill=RED)
        title_font, title_lines = fitted_text(draw, article["headline"], SERIF_FONTS, 62, 42, 960, 3)
        title_bottom = draw_lines(draw, (42, 665), title_lines, title_font, INK, 10)
        subtitle_font, subtitle_lines = fitted_text(draw, subtitle, SANS_FONTS, 27, 20, 940, 2)
        subtitle_bottom = draw_lines(draw, (42, max(885, title_bottom + 35)), subtitle_lines, subtitle_font, INK, 7)
        if attribution and subtitle_bottom < 1240:
            draw.text((42, min(1240, subtitle_bottom + 24)), attribution, font=font(SANS_FONTS, 19), fill=INK)
        caption_x, caption_y, caption_width = 54, 1415, 972
        en_max, zh_max = 30, 28

    if aspect_ratio == "16:9":
        en_font, en_lines = fitted_text(draw, caption_en, ARIAL_BOLD_FONTS, en_max, 18, caption_width, 2, weight="bold", allow_truncation=False, balance=True)
        zh_font, zh_lines = fitted_text(draw, caption_zh, NOTO_SANS_SC_FONTS, zh_max, 18, caption_width, 2, weight="medium", allow_truncation=False, balance=True)
        en_height = glyph_height(draw, en_font)
        zh_height = glyph_height(draw, zh_font)
        en_gap = max(0, round(en_height * 0.05))
        zh_gap = max(0, round(zh_height * 0.05))
        draw_caption_lines(canvas, caption_x, caption_y, caption_width, en_lines, en_font, en_gap)
        draw_caption_lines(canvas, caption_x, caption_y + round((en_height + en_gap) * len(en_lines)) + 6, caption_width, zh_lines, zh_font, zh_gap)
    else:
        en_font, en_lines = fitted_text(draw, caption_en, ARIAL_BOLD_FONTS, en_max, 18, caption_width, 2, weight="bold", allow_truncation=False, balance=True)
        zh_font, zh_lines = fitted_text(draw, caption_zh, NOTO_SANS_SC_FONTS, zh_max, 18, caption_width, 2, weight="medium", allow_truncation=False, balance=True)
        en_gap = max(0, round(glyph_height(draw, en_font) * 0.05))
        zh_gap = max(0, round(glyph_height(draw, zh_font) * 0.05))
        next_y = draw_lines(draw, (caption_x, caption_y), en_lines, en_font, CAPTION, en_gap)
        draw_lines(draw, (caption_x, next_y + 6), zh_lines, zh_font, CAPTION, zh_gap)
    return canvas


def concat_manifest(path: Path, frames: list[tuple[Path, float]]) -> None:
    lines = []
    for frame, duration in frames:
        escaped = str(frame).replace("'", "'\\''")
        lines.extend([f"file '{escaped}'", f"duration {duration:.6f}"])
    # The concat demuxer applies the final duration only when there is a later
    # file. Repeating the final still preserves the final cue exactly.
    escaped = str(frames[-1][0]).replace("'", "'\\''")
    lines.append(f"file '{escaped}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def caption_segments(cues: list[dict[str, Any]], duration: float) -> list[tuple[float, float, dict[str, Any] | None]]:
    boundaries = {0.0, duration}
    for cue in cues:
        boundaries.add(max(0.0, min(duration, cue["start"])))
        boundaries.add(max(0.0, min(duration, cue["end"])))
    ordered = sorted(boundaries)
    segments = []
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        midpoint = (start + end) / 2
        active = next((cue for cue in cues if cue["start"] <= midpoint < cue["end"]), None)
        segments.append((start, end, active))
    return segments


def render_video_frames(article_path: Path, output: Path, aspect_ratio: str, duration: float, caption_en: str, caption_zh: str, image_override: str | None, media_role: str, audio: Path | None = None, captions: Path | None = None, variant: str | None = None) -> None:
    if duration <= 0:
        raise TemplateError("Video duration must be positive.")
    if not shutil.which("ffmpeg"):
        raise TemplateError("ffmpeg is required to render an MP4 preview.")
    output.parent.mkdir(parents=True, exist_ok=True)
    cues = parse_srt(captions) if captions else []
    with tempfile.TemporaryDirectory(prefix="economist-static-slide-video-") as temporary:
        temporary_path = Path(temporary)
        frame_specs = []
        if cues:
            if not variant:
                raise TemplateError("--variant is required when --captions is used.")
            for index, (start, end, cue) in enumerate(caption_segments(cues, duration)):
                current_en, current_zh = cue_text(cue, variant)
                frame = render_editorial_frame(article_path, aspect_ratio, current_en, current_zh, image_override, media_role)
                path = temporary_path / f"frame-{index:04d}.png"
                frame.save(path)
                frame_specs.append((path, end - start))
        else:
            frame = render_editorial_frame(article_path, aspect_ratio, caption_en, caption_zh, image_override, media_role)
            path = temporary_path / "frame-0000.png"
            frame.save(path)
            frame_specs.append((path, duration))
        if cues:
            manifest = temporary_path / "frames.txt"
            concat_manifest(manifest, frame_specs)
            command = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest)]
        else:
            command = ["ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-i", str(frame_specs[0][0]), "-t", f"{duration:.3f}"]
        if audio:
            command.extend(["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0"])
        else:
            command.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{duration:.3f}"])
        if cues:
            command.extend(["-vf", "fps=30"])
        command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(output)])
        subprocess.run(command, check=True, capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "video"):
        command = commands.add_parser(name)
        command.add_argument("article_json")
        command.add_argument("output")
        command.add_argument("--aspect-ratio", choices=CANVASES, required=True)
        command.add_argument("--caption-en", default="")
        command.add_argument("--caption-zh", default="")
        command.add_argument("--image")
        command.add_argument("--media-role", choices=("issue_cover", "article_asset"), default="issue_cover")
        if name == "video":
            command.add_argument("--duration", type=float)
            command.add_argument("--audio")
            command.add_argument("--captions", help="Canonical SRT generated by the Azure media skill.")
            command.add_argument("--variant", choices=("en", "en-zh", "zh-CN"))
    args = parser.parse_args()
    try:
        article_path = Path(args.article_json).resolve()
        output = Path(args.output).resolve()
        frame = render_editorial_frame(article_path, args.aspect_ratio, args.caption_en, args.caption_zh, args.image, args.media_role)
        if args.command == "preview":
            output.parent.mkdir(parents=True, exist_ok=True)
            frame.save(output)
        else:
            audio = Path(args.audio).resolve() if args.audio else None
            if audio and not audio.is_file():
                raise TemplateError(f"Audio is missing: {audio}")
            duration = audio_duration(audio) if audio else args.duration
            if duration is None:
                raise TemplateError("video needs --duration or --audio.")
            captions = Path(args.captions).resolve() if args.captions else None
            if captions and not captions.is_file():
                raise TemplateError(f"Captions are missing: {captions}")
            render_video_frames(article_path, output, args.aspect_ratio, duration, args.caption_en, args.caption_zh, args.image, args.media_role, audio, captions, args.variant)
        print(json.dumps({"status": "complete", "output": str(output), "aspect_ratio": args.aspect_ratio, "media_role": args.media_role}, ensure_ascii=False))
        return 0
    except subprocess.CalledProcessError as error:
        print(f"error: {error.stderr.strip() or error}")
        return 2
    except (FileNotFoundError, OSError, TemplateError) as error:
        print(f"error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
