#!/usr/bin/env python3
"""Render a visual verification preview for Podcast Video Visual System v1.

This is deliberately a review utility: it reads the extracted PowerPoint
template definition and renders its four content states with fixture content.
It does not replace the production storyboard or video renderer.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


SKILL_ROOT = Path(__file__).parents[1]
DEFAULT_DEFINITION = SKILL_ROOT / "templates" / "podcast-video-visual-system.v1.json"
TIMES = "/System/Library/Fonts/Supplemental/Times New Roman.ttf"
TIMES_BOLD = "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"
ARIAL = "/System/Library/Fonts/Supplemental/Arial.ttf"
ARIAL_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
SONGTI = "/System/Library/Fonts/Supplemental/Songti.ttc"
HEITI = "/System/Library/Fonts/STHeiti Medium.ttc"
NOTO_SANS_SC = "/Users/zhongbintao/Library/Fonts/NOTOSANSSC-VF.TTF"
SIMHEI = "/Users/zhongbintao/Library/Fonts/SIMHEI.TTF"

SAMPLE_CONTENT = {
    "article": {
        "kicker": "KICKER",
        "headline": "The future",
        "headline_zh": "未来如何融资",
        "subtitle": "Long-term capital meets technological ambition.",
        "subtitle_zh": "长期资本与科技雄心相遇。",
        "byline_dateline_issue": "SHANGHAI · JULY 11–17TH 2026",
    },
    "guide_questions": [
        {
            "question": "Who funds the future?",
            "translation_zh": "谁为未来融资？",
        },
        {
            "question": "Can markets adapt?",
            "translation_zh": "市场能适应吗？",
        },
    ],
    "caption": {
        "current": {
            "en": "Long-term capital is needed.",
            "zh": "需要长期资本。",
        }
    },
}

SUBTITLE_MODES = {"default", "en-only"}


def read_definition(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_font_weight(value: Any, *, bold: bool = False, cjk: bool = False) -> str:
    requested = str(value or "").strip().lower()
    if requested in {"bold", "700", "semibold", "demibold"}:
        return "bold"
    if requested in {"medium", "500"}:
        return "medium"
    if requested in {"light", "300", "thin", "100"}:
        return "light"
    return "medium" if cjk and bold else ("bold" if bold else "regular")


def _font_for_path(path: str, size: int, weight: str) -> ImageFont.FreeTypeFont:
    face = ImageFont.truetype(path, size)
    if Path(path) == Path(NOTO_SANS_SC):
        variation = {"bold": "Bold", "medium": "Medium", "light": "Light", "regular": "Regular"}.get(weight, "Regular")
        try:
            face.set_variation_by_name(variation)
        except OSError:
            pass
    return face


def font_supports_text(path: str, text: str, *, weight: str = "regular") -> bool:
    """Reject fonts that render a missing glyph as the tofu square."""
    if not text.strip():
        return True
    try:
        face = _font_for_path(path, 32, weight)
        tofu = bytes(face.getmask("\u25a1"))
        for character in set(text):
            if character.isspace() or character == "\u25a1":
                continue
            mask = bytes(face.getmask(character))
            if mask == tofu:
                return False
        return True
    except (OSError, ValueError):
        return False


def font_path(*, bold: bool, cjk: bool, sans: bool, font_value: Any = None, font_weight: Any = None, text: str = "") -> str:
    requested_latin = str(font_value.get("latin", "") if isinstance(font_value, dict) else font_value or "")
    requested_east_asian = str(font_value.get("east_asian", "") if isinstance(font_value, dict) else font_value or "")
    weight = normalize_font_weight(font_weight, bold=bold, cjk=cjk)
    requested = requested_east_asian if cjk else requested_latin
    if cjk:
        if "Noto Sans SC" in requested or sans:
            candidates = (NOTO_SANS_SC, HEITI, SONGTI)
        elif "SimHei" in requested or "黑体" in requested:
            candidates = (SIMHEI, NOTO_SANS_SC, HEITI, SONGTI)
        else:
            candidates = (NOTO_SANS_SC, HEITI, SONGTI)
    elif "SimHei" in requested or "黑体" in requested or "Arial" in requested or sans:
        candidates = (ARIAL_BOLD, ARIAL, TIMES) if weight == "bold" else (ARIAL, ARIAL_BOLD, TIMES)
    else:
        candidates = (TIMES_BOLD, ARIAL_BOLD, ARIAL) if weight == "bold" else (TIMES, ARIAL, ARIAL_BOLD)
    for candidate in candidates:
        if Path(candidate).is_file() and font_supports_text(candidate, text, weight=weight):
            return candidate
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("No usable system font was found for the template preview.")


def typeface(size_pt: float, *, bold: bool = False, cjk: bool = False, sans: bool = False, font_value: Any = None, font_weight: Any = None, text: str = "", scale: float = 1.0) -> ImageFont.FreeTypeFont:
    weight = normalize_font_weight(font_weight, bold=bold, cjk=cjk)
    path = font_path(bold=bold, cjk=cjk, sans=sans, font_value=font_value, font_weight=weight, text=text)
    face = _font_for_path(path, max(1, round(size_pt * 96 / 72 * scale)), weight)
    setattr(face, "_codex_font_weight", weight)
    setattr(face, "_codex_font_path", path)
    return face


def scaled_box(box: list[float], scale: float) -> tuple[int, int, int, int]:
    return tuple(round(value * scale) for value in box)  # type: ignore[return-value]


def has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", value))


def normalize_caption_text(value: str) -> str:
    """Use a universally covered visual equivalent for fragile dash glyphs."""
    return value.replace("\u2011", "-").replace("\u00ad", "-")


def validate_subtitle_mode(value: str) -> str:
    mode = str(value or "default").strip().lower()
    if mode not in SUBTITLE_MODES:
        raise ValueError(f"Unsupported subtitle mode: {value}")
    return mode


def is_sans(font_value: Any) -> bool:
    if isinstance(font_value, dict):
        font_value = font_value.get("latin", "")
    return any(name in str(font_value) for name in ("Arial", "Noto Sans", "Microsoft YaHei", "SimHei", "黑体", "Heiti"))


def measure(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.FreeTypeFont) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), value or " ", font=face)
    return right - left, bottom - top


def glyph_height(draw: ImageDraw.ImageDraw, face: ImageFont.FreeTypeFont) -> int:
    """Measure ascenders and descenders, including g/y/j/p/q, not just capitals."""
    return measure(draw, "Agjpqy汉字", face)[1]


def wrap(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.FreeTypeFont, width: int) -> list[str]:
    if not value:
        return []
    lines: list[str] = []
    for paragraph in value.splitlines() or [value]:
        tokens = paragraph.split() if " " in paragraph else cjk_wrap_tokens(paragraph)
        separator = " " if " " in paragraph else ""
        current = ""
        for token in tokens:
            if not current and measure(draw, token, face)[0] > width:
                fragment = ""
                for character in token:
                    candidate = f"{fragment}{character}"
                    if fragment and measure(draw, candidate, face)[0] > width:
                        lines.append(fragment)
                        fragment = character
                    else:
                        fragment = candidate
                current = fragment
                continue
            candidate = token if not current else f"{current}{separator}{token}"
            if current and measure(draw, candidate, face)[0] > width:
                lines.append(current)
                current = token
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def balanced_wrap(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.FreeTypeFont, width: int, max_lines: int | None) -> list[str]:
    """Use two balanced lines when possible instead of leaving a short tail."""
    greedy = wrap(draw, value, face, width)
    if max_lines != 2 or len(greedy) <= 1 or "\n" in value:
        return greedy
    paragraph = " ".join(value.split())
    tokens = paragraph.split(" ") if " " in paragraph else cjk_wrap_tokens(paragraph)
    separator = " " if " " in paragraph else ""
    candidates: list[tuple[int, list[str]]] = []
    for index in range(1, len(tokens)):
        left = separator.join(tokens[:index])
        right = separator.join(tokens[index:])
        if measure(draw, left, face)[0] <= width and measure(draw, right, face)[0] <= width:
            score = abs(measure(draw, left, face)[0] - measure(draw, right, face)[0])
            candidates.append((score, [left, right]))
    return min(candidates, key=lambda item: item[0])[1] if candidates else greedy


def text_insets(style: dict[str, Any], scale: float) -> tuple[int, int]:
    values = style.get("text_insets_px", [0, 0, 0, 0])
    if not isinstance(values, list) or len(values) != 4:
        return 0, 0
    return round(float(values[0]) * scale), round(float(values[2]) * scale)


def cjk_wrap_tokens(value: str) -> list[str]:
    """Keep Chinese closing punctuation with the character that precedes it."""
    attached = set("，。！？；：、）》】〉〕〗」』")
    tokens: list[str] = []
    for character in value:
        if character in attached and tokens:
            tokens[-1] += character
        else:
            tokens.append(character)
    return tokens


def fitted_adaptive_lines(
    draw: ImageDraw.ImageDraw,
    value: str,
    block: dict[str, Any],
    style: dict[str, Any],
    width: int,
    height: int,
    scale: float,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    max_lines = None if block.get("unbounded_lines", style.get("unbounded_lines", False)) else int(block.get("max_lines", style.get("max_lines", 2)))
    spacing = int(block.get("line_spacing_percent", style.get("line_spacing_percent", 115)))
    fixed_size = block.get("fixed_font_size_pt")
    if fixed_size is not None:
        size = int(fixed_size)
        face = typeface(
            size,
            bold=block.get("bold", style.get("bold", False)),
            cjk=has_cjk(value),
            sans=is_sans(block.get("font", style.get("font"))),
            font_value=block.get("font", style.get("font")),
            font_weight=block.get("font_weight", style.get("font_weight")),
            text=value,
            scale=scale,
        )
        lines = balanced_wrap(draw, value, face, width, max_lines)
        line_height = round(glyph_height(draw, face) * spacing / 100)
        if max_lines is not None and len(lines) > max_lines:
            raise RuntimeError("Fixed caption box cannot fit the complete cue without changing font size.")
        if len(lines) * line_height > height:
            raise RuntimeError("Fixed caption box cannot fit the complete cue without changing font size.")
        return face, lines, line_height

    maximum = int(block["font_size_pt"])
    minimum = int(block.get("min_font_size_pt", style.get("min_font_size_pt", maximum)))
    for size in range(maximum, minimum - 1, -1):
        face = typeface(
            size,
            bold=block.get("bold", style.get("bold", False)),
            cjk=has_cjk(value),
            sans=is_sans(block.get("font", style.get("font"))),
            font_value=block.get("font", style.get("font")),
            font_weight=block.get("font_weight", style.get("font_weight")),
            text=value,
            scale=scale,
        )
        lines = balanced_wrap(draw, value, face, width, max_lines)
        line_height = round(glyph_height(draw, face) * spacing / 100)
        if (max_lines is None or len(lines) <= max_lines) and len(lines) * line_height <= height:
            return face, lines, line_height
    raise RuntimeError("Caption cannot fit inside its safe area without truncation.")


def resolve(binding: str, content: dict[str, Any]) -> str:
    value: Any = content
    for name, index in re.findall(r"([A-Za-z_]+)(?:\[(\d+)\])?", binding):
        if not isinstance(value, dict) or name not in value:
            return ""
        value = value[name]
        if index:
            if not isinstance(value, list) or int(index) >= len(value):
                return ""
            value = value[int(index)]
    return str(value)


def layer_map(definition: dict[str, Any], template_name: str) -> dict[str, dict[str, Any]]:
    template = definition["templates"][template_name]
    layers = {layer["id"]: layer for layer in template["layers"]}
    for parent_ref in template.get("inherits", []):
        parent_name, layer_id = parent_ref.split(".", 1)
        parent = layer_map(definition, parent_name)[layer_id]
        layers[layer_id] = parent
    return layers


def _flow_text_layer(
    draw: ImageDraw.ImageDraw,
    source: dict[str, Any],
    content: dict[str, Any],
    scale: float,
    shrink_step: int,
    honor_max_lines: bool = True,
) -> tuple[dict[str, Any], int] | None:
    """Measure one layer with real fonts and return a complete, fitted block."""
    layer = dict(source)
    width = round(float(source["bbox"][2]) * scale)
    blocks = source.get("paragraphs") or [dict(source.get("style", {}), binding=source.get("content_binding", ""))]
    prepared_blocks: list[dict[str, Any]] = []
    total_height = 0
    for raw_block in blocks:
        block = dict(raw_block)
        value = resolve(str(block.get("binding", "")), content).strip() if block.get("binding") else str(source.get("text", "")).strip()
        if not value:
            continue
        base_size = int(block.get("font_size_pt", source.get("style", {}).get("font_size_pt", 12)))
        minimum = int(block.get("min_font_size_pt", source.get("style", {}).get("min_font_size_pt", max(7, round(base_size * 0.6)))))
        size = max(minimum, base_size - shrink_step)
        block["font_size_pt"] = size
        face = typeface(
            size,
            bold=block.get("bold", source.get("style", {}).get("bold", False)),
            cjk=has_cjk(value),
            sans=is_sans(block.get("font", source.get("style", {}).get("font"))),
            font_value=block.get("font", source.get("style", {}).get("font")),
            font_weight=block.get("font_weight", source.get("style", {}).get("font_weight")),
            text=value,
            scale=scale,
        )
        requested_wrap = source.get("wrap", source.get("style", {}).get("wrap", "square"))
        lines = [value] if requested_wrap == "none" and measure(draw, value, face)[0] <= width else wrap(draw, value, face, width)
        max_lines = block.get("max_lines", source.get("style", {}).get("max_lines"))
        if honor_max_lines and max_lines is not None and len(lines) > int(max_lines):
            return None
        if any(measure(draw, line, face)[0] > width for line in lines):
            return None
        spacing = int(block.get("line_spacing_percent", source.get("line_spacing_percent", source.get("style", {}).get("line_spacing_percent", 115))))
        total_height += len(lines) * round(glyph_height(draw, face) * spacing / 100)
        prepared_blocks.append(block)
    if not prepared_blocks:
        layer["bbox"] = [source["bbox"][0], 0, source["bbox"][2], 0]
        return layer, 0
    if source.get("paragraphs"):
        layer["paragraphs"] = prepared_blocks
        layer["wrap"] = "square"
    else:
        style = dict(source.get("style", {}))
        style["font_size_pt"] = prepared_blocks[0]["font_size_pt"]
        style["min_font_size_pt"] = prepared_blocks[0]["font_size_pt"]
        if requested_wrap == "none" and len(lines) > 1:
            style["wrap"] = "square"
        layer["style"] = style
    layer["bbox"] = [source["bbox"][0], 0, source["bbox"][2], total_height / scale]
    layer["vertical_alignment"] = "top"
    return layer, total_height


def prepare_portrait_opening_layers(
    draw: ImageDraw.ImageDraw,
    template: dict[str, Any],
    layers: dict[str, dict[str, Any]],
    content: dict[str, Any],
    scale: float,
) -> dict[str, dict[str, Any]]:
    """Constraint-flow all opening metadata so no fixed text boxes can overlap."""
    if "headline" not in layers:
        return layers

    opening_ids = ("kicker", "article_page", "headline", "headline_zh", "subtitle", "subtitle_zh", "byline_dateline")
    original = {name: layers[name] for name in opening_ids if name in layers}
    all_blocks = [block for layer in original.values() for block in (layer.get("paragraphs") or [layer.get("style", {})])]
    max_steps = max((int(block.get("font_size_pt", 12)) - int(block.get("min_font_size_pt", max(7, round(int(block.get("font_size_pt", 12)) * 0.6)))) for block in all_blocks), default=0)
    image_bottom = 0
    if "issue_cover" in layers:
        _, image_y, _, image_height = scaled_box(layers["issue_cover"]["bbox"], scale)
        image_bottom = image_y + image_height
    portrait = template["canvas"].get("aspect_ratio") == "9:16"
    original_start = min(round(float(layer["bbox"][1]) * scale) for layer in original.values())
    start_y = max(original_start, image_bottom + round(20 * scale)) if portrait else original_start
    if "subtitle_rail" not in layers:
        raise RuntimeError("Opening template needs a subtitle rail to establish the text safe area.")
    _, rail_y, _, _ = scaled_box(layers["subtitle_rail"]["bbox"], scale)
    bottom_limit = rail_y - round(12 * scale)

    for step in range(max_steps + 1):
        prepared: dict[str, dict[str, Any]] = {}
        measured_height: dict[str, int] = {}
        failed = False
        for name, source in original.items():
            fitted = _flow_text_layer(draw, source, content, scale, step, honor_max_lines=False)
            if fitted is None:
                failed = True
                break
            prepared[name], measured_height[name] = fitted

        if failed:
            continue

        cursor = start_y
        placed = False

        # The kicker and page marker form one aligned metadata row.
        row_height = max(measured_height.get("kicker", 0), measured_height.get("article_page", 0))
        if row_height:
            for name in ("kicker", "article_page"):
                if name in prepared and measured_height.get(name, 0):
                    prepared[name]["bbox"][1] = cursor / scale
                    prepared[name]["bbox"][3] = measured_height[name] / scale
            cursor += row_height
            placed = True

        for name, gap in (("headline", 10), ("headline_zh", 7), ("subtitle", 12), ("subtitle_zh", 5), ("byline_dateline", 12)):
            height = measured_height.get(name, 0)
            if not height:
                continue
            if placed:
                cursor += round(gap * scale)
            prepared[name]["bbox"][1] = cursor / scale
            prepared[name]["bbox"][3] = height / scale
            cursor += height
            placed = True

        # If there is no metadata, retain an empty layer map without inventing space.
        if not placed:
            return layers
        if cursor <= bottom_limit:
            layers.update(prepared)
            return layers

    raise RuntimeError("Opening metadata cannot fit the measured text safe area without overlap.")


def prepare_bounded_text_layers(
    draw: ImageDraw.ImageDraw,
    layers: dict[str, dict[str, Any]],
    content: dict[str, Any],
    scale: float,
) -> dict[str, dict[str, Any]]:
    """Fit question blocks to their real boxes once, without truncation or post-render review."""
    for layer_id, source in list(layers.items()):
        if not layer_id.startswith("guide_question_") or layer_id.endswith("_number"):
            continue
        blocks = source.get("paragraphs") or [source.get("style", {})]
        max_steps = max((int(block.get("font_size_pt", 12)) - int(block.get("min_font_size_pt", max(7, round(int(block.get("font_size_pt", 12)) * 0.6)))) for block in blocks), default=0)
        allowed_height = round(float(source["bbox"][3]) * scale)
        for step in range(max_steps + 1):
            fitted = _flow_text_layer(draw, source, content, scale, step)
            if fitted is None:
                continue
            layer, measured_height = fitted
            if measured_height <= allowed_height:
                layer["bbox"] = list(source["bbox"])
                layers[layer_id] = layer
                break
        else:
            raise RuntimeError(f"{layer_id} cannot fit its measured text safe area without truncation.")
    return layers


def caption_layers_for_frame(
    draw: ImageDraw.ImageDraw,
    template: dict[str, Any],
    layers: dict[str, dict[str, Any]],
    content: dict[str, Any],
    scale: float,
    subtitle_mode: str = "default",
) -> dict[str, dict[str, Any]]:
    """Prepare captions while preserving the prototype card and safe area."""
    subtitle_mode = validate_subtitle_mode(subtitle_mode)
    caption_ids = ("caption_en", "caption_zh")
    visible_caption_ids = ("caption_en",) if subtitle_mode == "en-only" else caption_ids
    for name in caption_ids:
        layers[name] = {**layers[name], "visible": name in visible_caption_ids}
    if "subtitle_rail" not in layers or not any(resolve(layers[name]["content_binding"], content).strip() for name in visible_caption_ids):
        return layers

    # Keep the landscape rail fixed, but flow the two languages as one compact
    # group. Each language follows the standard two-line subtitle limit.
    if template["canvas"].get("aspect_ratio") == "16:9":
        rail = layers["subtitle_rail"]
        rail_x, rail_y, rail_width, rail_height = scaled_box(rail["bbox"], scale)
        padding = round(8 * scale)
        language_gap = round(6 * scale)
        prepared: list[tuple[str, int, int, int, int]] = []
        for name in visible_caption_ids:
            layer = dict(layers[name])
            layer["style"] = dict(layer.get("style", {}))
            layer["style"]["min_font_size_pt"] = int(layer["style"].get("min_font_size_pt", 16))
            layer["style"]["unbounded_lines"] = False
            layer["style"]["max_lines"] = int(layer["style"].get("max_lines", 2))
            layer["style"]["letter_spacing"] = 0
            layer["style"]["alignment"] = "center"
            value = normalize_caption_text(resolve(layer["content_binding"], content))
            if value.strip():
                _, _, caption_width, _ = scaled_box(layer["bbox"], scale)
                _, lines, line_height = fitted_adaptive_lines(draw, value, layer["style"], layer["style"], caption_width, rail_height, scale)
                inset_top, inset_bottom = text_insets(layer["style"], scale)
                prepared.append((name, len(lines), line_height, inset_top, inset_bottom))
            layers[name] = layer
        total_height = padding * 2 + sum(line_count * line_height + inset_top + inset_bottom for _, line_count, line_height, inset_top, inset_bottom in prepared)
        if len(prepared) > 1:
            total_height += language_gap * (len(prepared) - 1)
        cursor_y = rail_y + max(0, (rail_height - total_height) // 2) + padding
        prepared_by_name = {name: (line_count, line_height, inset_top, inset_bottom) for name, line_count, line_height, inset_top, inset_bottom in prepared}
        for name in caption_ids:
            layer = layers[name]
            line_count, line_height, inset_top, inset_bottom = prepared_by_name.get(name, (0, 0, 0, 0))
            layer["bbox"] = [layer["bbox"][0], cursor_y / scale, layer["bbox"][2], (line_count * line_height + inset_top + inset_bottom) / scale]
            if line_count:
                cursor_y += line_count * line_height + inset_top + inset_bottom + language_gap
        return layers

    canvas_height = round(template["canvas"]["height"] * scale)
    protected_bottom = 0
    for layer_id in template["source_layer_order"]:
        if layer_id in {*caption_ids, "subtitle_rail", "caption_label", "caption_cue", "caption_number"}:
            continue
        layer = layers[layer_id]
        if layer["kind"] not in {"text", "multilingual_text", "image"}:
            continue
        _, y, _, height = scaled_box(layer["bbox"], scale)
        protected_bottom = max(protected_bottom, y + height)
    rail = dict(layers["subtitle_rail"])
    rail_x, rail_y, rail_width, rail_height = scaled_box(rail["bbox"], scale)
    safe_bottom_percent = float(template.get("platform_safe_bottom_percent", 0))
    safe_bottom = canvas_height - round(canvas_height * safe_bottom_percent / 100)
    if rail_y < protected_bottom + round(8 * scale) or rail_y + rail_height > safe_bottom:
        raise RuntimeError("Portrait caption card collides with protected content or the platform safe zone.")
    layers["subtitle_rail"] = rail

    if subtitle_mode == "en-only":
        layer = dict(layers["caption_en"])
        style = dict(layer.get("style", {}))
        style["unbounded_lines"] = False
        style["max_lines"] = int(style.get("max_lines", 2))
        style["letter_spacing"] = 0
        style["alignment"] = "center"
        value = normalize_caption_text(resolve(layer["content_binding"], content))
        if value.strip():
            _, _, width, _ = scaled_box(layer["bbox"], scale)
            _, lines, line_height = fitted_adaptive_lines(draw, value, style, style, width, rail_height, scale)
            inset_top, inset_bottom = text_insets(style, scale)
            total_height = len(lines) * line_height + inset_top + inset_bottom
            layer["bbox"] = [
                layer["bbox"][0],
                (rail_y + max(0, (rail_height - total_height) // 2)) / scale,
                layer["bbox"][2],
                total_height / scale,
            ]
        layer["style"] = style
        layers["caption_en"] = layer
        layers["caption_zh"]["bbox"] = [layers["caption_zh"]["bbox"][0], rail_y / scale, layers["caption_zh"]["bbox"][2], 0]
        return layers

    for name in caption_ids:
        layer = dict(layers[name])
        style = dict(layer.get("style", {}))
        style["unbounded_lines"] = False
        style["max_lines"] = int(style.get("max_lines", 2))
        style["letter_spacing"] = 0
        style["alignment"] = "center"
        value = normalize_caption_text(resolve(layer["content_binding"], content))
        if value.strip():
            _, _, width, height = scaled_box(layer["bbox"], scale)
            fitted_adaptive_lines(draw, value, style, style, width, height, scale)
        layer["style"] = style
        layers[name] = layer
    return layers


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def draw_text(canvas: Image.Image, layer: dict[str, Any], content: dict[str, Any], scale: float, diagnostics: list[dict[str, Any]] | None = None) -> None:
    if layer.get("visible", True) is False:
        return
    draw = ImageDraw.Draw(canvas)
    x, y, width, height = scaled_box(layer["bbox"], scale)
    style_blocks = layer.get("paragraphs") or [dict(layer["style"], binding=layer.get("content_binding", ""))]
    rendered: list[tuple[str, ImageFont.FreeTypeFont, str, int]] = []
    for block in style_blocks:
        value = resolve(block["binding"], content) if block.get("binding") else str(layer.get("text", ""))
        if not value.strip():
            continue
        if layer["id"] in {"caption_en", "caption_zh"}:
            value = normalize_caption_text(value)
        style = dict(layer.get("style", block))
        for key in ("wrap", "alignment", "line_spacing_percent"):
            if key not in style and key in layer:
                style[key] = layer[key]
        if style.get("wrap") == "adaptive":
            face, lines, line_height = fitted_adaptive_lines(draw, value, block, style, width, height, scale)
        else:
            face = typeface(
                block["font_size_pt"],
                bold=block.get("bold", style.get("bold", False)),
                cjk=has_cjk(value),
                sans=is_sans(block.get("font", style.get("font"))),
                font_value=block.get("font", style.get("font")),
                font_weight=block.get("font_weight", style.get("font_weight")),
                text=value,
                scale=scale,
            )
            lines = [value] if style.get("wrap") == "none" else wrap(draw, value, face, width)
            line_height = round(glyph_height(draw, face) * (block.get("line_spacing_percent", layer.get("line_spacing_percent", style.get("line_spacing_percent", 125))) / 100))
        rendered.extend((line, face, block["color"], line_height) for line in lines)

    total_height = sum(line_height for _, _, _, line_height in rendered)
    inset_top, inset_bottom = text_insets(layer.get("style", {}), scale)
    inner_height = max(0, height - inset_top - inset_bottom)
    if total_height > inner_height + max(2, round(2 * scale)):
        raise RuntimeError(f"{layer['id']} exceeds its measured text safe area.")
    if layer.get("vertical_alignment", "center") == "top":
        cursor_y = y + inset_top
    else:
        cursor_y = y + inset_top + max(0, (inner_height - total_height) // 2)
    alignment = layer.get("style", {}).get("alignment", layer.get("alignment", "left"))
    stroke_width = round(float(layer.get("style", {}).get("stroke_width_px", 0)) * scale)
    stroke_fill = layer.get("style", {}).get("stroke_color", "#FFFFFF")
    placements: list[tuple[str, ImageFont.FreeTypeFont, str, int, int, int, int, int]] = []
    for line, face, color, line_height in rendered:
        left, top, right, bottom = draw.textbbox((0, 0), line, font=face, stroke_width=stroke_width)
        line_width, line_box_height = right - left, bottom - top
        if alignment == "center":
            line_x = x + max(0, (width - line_width) // 2)
        elif alignment == "right":
            line_x = x + max(0, width - line_width)
        else:
            line_x = x
        text_y = cursor_y - top
        placements.append((line, face, color, line_height, line_x, text_y, line_width, line_box_height))
        cursor_y += line_height

    line_boxes = [[line_x, text_y, line_width, line_box_height] for _, _, _, _, line_x, text_y, line_width, line_box_height in placements]
    if layer["id"] in {"caption_en", "caption_zh"} and placements:
        style = layer.get("style", {})
        background_color = style.get("background_color")
        if background_color:
            padding_x, padding_y = (int(value * scale) for value in style.get("background_padding_px", [12, 6]))
            overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            fill = (*hex_rgb(background_color), round(float(style.get("background_opacity", 0.78)) * 255))
            for _, _, _, _, line_x, text_y, line_width, line_box_height in placements:
                overlay_draw.rectangle(
                    (line_x - padding_x, text_y - padding_y, line_x + line_width + padding_x, text_y + line_box_height + padding_y),
                    fill=fill,
                )
            canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB"))
            draw = ImageDraw.Draw(canvas)

    for line, face, color, _, line_x, text_y, _, _ in placements:
        draw.text((line_x, text_y), line, font=face, fill=color, stroke_width=stroke_width, stroke_fill=stroke_fill)

    if diagnostics is not None and rendered:
        diagnostic_y = min((box[1] for box in line_boxes), default=y)
        diagnostic_bottom = max((box[1] + box[3] for box in line_boxes), default=y + height)
        if rendered:
            font_path_value = getattr(rendered[0][1], "_codex_font_path", "")
            font_name = "Noto Sans SC" if Path(font_path_value) == Path(NOTO_SANS_SC) else ("Arial Bold" if Path(font_path_value) == Path(ARIAL_BOLD) else ("Arial" if Path(font_path_value) == Path(ARIAL) else rendered[0][1].getname()[0]))
            font_label = f"{font_name}/{getattr(rendered[0][1], '_codex_font_weight', 'regular')}"
        else:
            font_path_value = ""
            font_label = ""
        diagnostics.append({
            "layer": layer["id"], "safe_bbox": [x, diagnostic_y, width, diagnostic_bottom - diagnostic_y], "line_bboxes": line_boxes,
            "font": font_label, "font_path": font_path_value, "font_weight": getattr(rendered[0][1], "_codex_font_weight", "regular") if rendered else "", "font_size_px": rendered[0][1].size if rendered else 0,
            "line_count": len(rendered), "lines": [line for line, _, _, _ in rendered], "alignment": alignment,
            "letter_spacing": layer.get("style", {}).get("letter_spacing", 0), "text_justification": "none",
            "text_insets_px": layer.get("style", {}).get("text_insets_px", [0, 0, 0, 0]),
            "stroke_width_px": stroke_width, "stroke_color": stroke_fill,
            "background_color": layer.get("style", {}).get("background_color"),
            "background_opacity": layer.get("style", {}).get("background_opacity"),
        })


def draw_image(canvas: Image.Image, layer: dict[str, Any], cover_path: Path, scale: float) -> None:
    x, y, width, height = scaled_box(layer["bbox"], scale)
    frame = Image.new("RGB", (width, height), "#262626")
    image_bbox = (x, y, x + width - 1, y + height - 1)
    with Image.open(cover_path) as source:
        image = source.convert("RGB")
        fit = layer.get("fit", "contain")
        ratio = (max if fit == "crop" else min)(width / image.width, height / image.height)
        resized = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))), Image.Resampling.LANCZOS)
        if fit == "crop":
            offset_x = max(0, (resized.width - width) // 2)
            offset_y = max(0, (resized.height - height) // 2)
            frame.paste(resized.crop((offset_x, offset_y, offset_x + width, offset_y + height)))
        else:
            offset_x = (width - resized.width) // 2
            offset_y = (height - resized.height) // 2
            frame.paste(resized, (offset_x, offset_y))
            image_bbox = (x + offset_x, y + offset_y, x + offset_x + resized.width - 1, y + offset_y + resized.height - 1)
    canvas.paste(frame, (x, y))
    style = layer.get("style", {})
    if style.get("stroke", "none") != "none":
        border_color = style.get("border_color", "#FFFFFF")
        if "border_width_output_px" in style:
            border_width = max(1, round(float(style["border_width_output_px"])))
        else:
            border_width = max(1, round(float(style.get("border_width_px", 2)) * scale))
        ImageDraw.Draw(canvas).rectangle(image_bbox, outline=border_color, width=border_width)


def render_template(
    definition: dict[str, Any],
    template_name: str,
    cover_path: Path,
    content: dict[str, Any],
    output_height: int,
    output_width: int | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    subtitle_mode: str = "default",
) -> Image.Image:
    subtitle_mode = validate_subtitle_mode(subtitle_mode)
    content = {**content, "design_tokens": definition["design_tokens"]}
    template = definition["templates"][template_name]
    canvas_width = template["canvas"]["width"]
    canvas_height = template["canvas"]["height"]
    scale = output_height / canvas_height
    canvas = Image.new("RGB", (round(canvas_width * scale), output_height), definition["design_tokens"]["colors"]["page_background"])
    draw = ImageDraw.Draw(canvas)
    layers = layer_map(definition, template_name)
    layers = prepare_portrait_opening_layers(draw, template, layers, content, scale)
    layers = prepare_bounded_text_layers(draw, layers, content, scale)
    layers = caption_layers_for_frame(draw, template, layers, content, scale, subtitle_mode)
    for layer_id in template["source_layer_order"]:
        layer = layers[layer_id]
        if layer.get("visible", True) is False:
            continue
        if layer["kind"] == "shape":
            x, y, width, height = scaled_box(layer["bbox"], scale)
            stroke = layer.get("stroke", "none")
            outline = None if stroke == "none" else stroke
            outline_width = max(1, round(float(layer.get("stroke_width_px", 1)) * scale)) if outline else 1
            geometry = str(layer.get("geometry", ""))
            if "round" in geometry:
                radius = round(float(layer.get("corner_radius_px", 0)) * scale)
                draw.rounded_rectangle((x, y, x + width, y + height), radius=radius, fill=layer.get("fill"), outline=outline, width=outline_width)
            else:
                draw.rectangle((x, y, x + width, y + height), fill=layer.get("fill"), outline=outline, width=outline_width)
        elif layer["kind"] == "image":
            draw_image(canvas, layer, cover_path, scale)
        else:
            draw_text(canvas, layer, content, scale, diagnostics)
    if output_width and canvas.width != output_width:
        return canvas.resize((output_width, output_height), Image.Resampling.LANCZOS)
    return canvas


def make_contact_sheet(frames: list[tuple[str, Image.Image]]) -> Image.Image:
    paper = "#262626"
    title_face = typeface(16, bold=True, scale=1.0)
    sheet = Image.new("RGB", (2400, 1900), paper)
    draw = ImageDraw.Draw(sheet)
    slots = [(60, 70), (1240, 70), (60, 1020), (1240, 1020)]
    for (title, frame), (x, y) in zip(frames, slots):
        thumbnail = frame.copy()
        thumbnail.thumbnail((1060, 780), Image.Resampling.LANCZOS)
        draw.text((x, y), title, font=title_face, fill="#FFFFFF")
        sheet.paste(thumbnail, (x, y + 52))
    return sheet


def render_all(definition_path: Path, cover_path: Path, output_dir: Path) -> dict[str, Path]:
    definition = read_definition(definition_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[str, Image.Image]] = []
    outputs: dict[str, Path] = {}
    states = [
        ("01-landscape-opening", "landscape_opening", 1080),
        ("02-landscape-guide-questions", "landscape_guide_questions", 1080),
        ("03-portrait-opening", "portrait_opening", 1920),
        ("04-portrait-guide-questions", "portrait_guide_questions", 1920),
    ]
    for filename, template_name, output_height in states:
        frame = render_template(definition, template_name, cover_path, SAMPLE_CONTENT, output_height, 1920 if output_height == 1080 else 1080)
        destination = output_dir / f"{filename}.png"
        frame.save(destination)
        outputs[filename] = destination
        frames.append((filename.replace("-", " ").upper(), frame))
    contact_sheet = output_dir / "contact-sheet.png"
    make_contact_sheet(frames).save(contact_sheet)
    outputs["contact_sheet"] = contact_sheet
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the extracted Podcast Video Visual System v1 as four review images.")
    parser.add_argument("--cover", required=True, type=Path, help="Magazine cover image to place in the extracted fixed slot.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory for the generated PNG previews.")
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION, help="Extracted template definition JSON.")
    args = parser.parse_args()
    if not args.cover.is_file():
        raise SystemExit(f"Cover image is missing: {args.cover}")
    for name, path in render_all(args.definition, args.cover, args.out_dir).items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
