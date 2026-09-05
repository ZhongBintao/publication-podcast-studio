#!/usr/bin/env python3
"""Deterministic renderer for the Publication Podcast Studio visual system.

The renderer is shared by the preview utility, the formal storyboard video
path and the legacy one-frame CLI. It keeps layout decisions in the JSON
template definition, measures real fonts, contains source images without
cropping, and raises when complete text cannot fit.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont


SKILL_ROOT = Path(__file__).parents[1]
DEFAULT_DEFINITION = SKILL_ROOT / "templates" / "podcast-video-visual-system.v1.json"

# The prototype calls for Georgia and Helvetica. Arial is retained as a
# deterministic fallback on machines where the Helvetica TTC is unavailable.
GEORGIA = "/System/Library/Fonts/Supplemental/Georgia.ttf"
GEORGIA_BOLD = "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"
GEORGIA_ITALIC = "/System/Library/Fonts/Supplemental/Georgia Italic.ttf"
GEORGIA_BOLD_ITALIC = "/System/Library/Fonts/Supplemental/Georgia Bold Italic.ttf"
HELVETICA = "/System/Library/Fonts/Helvetica.ttc"
HELVETICA_NEUE = "/System/Library/Fonts/HelveticaNeue.ttc"
ARIAL = "/System/Library/Fonts/Supplemental/Arial.ttf"
ARIAL_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
ARIAL_ITALIC = "/System/Library/Fonts/Supplemental/Arial Italic.ttf"
ARIAL_BOLD_ITALIC = "/System/Library/Fonts/Supplemental/Arial Bold Italic.ttf"
TIMES = "/System/Library/Fonts/Supplemental/Times New Roman.ttf"
TIMES_BOLD = "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"
SONGTI = "/System/Library/Fonts/Supplemental/Songti.ttc"
HEITI = "/System/Library/Fonts/STHeiti Medium.ttc"
NOTO_SANS_SC = "/Users/zhongbintao/Library/Fonts/NOTOSANSSC-VF.TTF"
NOTO_SERIF_SC = "/Users/zhongbintao/Library/Fonts/NOTOSERIFSC-VF.TTF"
SIMHEI = "/Users/zhongbintao/Library/Fonts/SIMHEI.TTF"

SAMPLE_CONTENT = {
    "article": {
        "kicker": "TECHNOLOGY FINANCE",
        "headline": "The future of capital",
        "headline_zh": "未来如何融资",
        "subtitle": "Long-term capital meets technological ambition.",
        "subtitle_zh": "长期资本与科技雄心相遇。",
        "metadata_parts": ["The Economist", "JULY 11–17TH 2026", "BY THE EDITORS", "SHANGHAI"],
        "image_caption": "A sample verified source image",
    },
    "guide_questions": [
        {"question": "Who funds the future?", "translation_zh": "谁为未来融资？"},
        {"question": "Can markets adapt?", "translation_zh": "市场能适应吗？"},
    ],
    "caption": {"current": {"en": "Long-term capital is needed.", "zh": "需要长期资本。"}},
}

SUBTITLE_MODES = {"default", "en-only"}
ATTACHED_CJK_PUNCTUATION = set("，。！？；：、）》】〉〕〗」』〉》）］｝】")


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


def _font_for_path(path: str, size: int, weight: str, style: str = "regular") -> ImageFont.FreeTypeFont:
    index = None
    if Path(path) == Path(HELVETICA):
        index = {"regular": 0, "bold": 1, "medium": 0, "light": 4}.get(weight, 0)
        if style == "italic":
            index = 3 if weight == "bold" else 2
    elif Path(path) == Path(HELVETICA_NEUE):
        index = {"regular": 0, "bold": 1, "medium": 0, "light": 5}.get(weight, 0)
        if style == "italic":
            index = 3 if weight == "bold" else 2
    face = ImageFont.truetype(path, max(1, int(size)), index=index or 0)
    if Path(path) in {Path(NOTO_SANS_SC), Path(NOTO_SERIF_SC)}:
        variation = {"bold": "Bold", "medium": "Medium", "light": "Light", "regular": "Regular"}.get(weight, "Regular")
        try:
            face.set_variation_by_name(variation)
        except OSError:
            pass
    return face


def font_supports_text(path: str, text: str, *, weight: str = "regular") -> bool:
    """Reject fonts which render a missing glyph as the tofu square."""
    if not text or not text.strip():
        return True
    try:
        face = _font_for_path(path, 32, weight)
        tofu = bytes(face.getmask("\u25a1"))
        for character in set(text):
            if character.isspace() or character == "\u25a1":
                continue
            if bytes(face.getmask(character)) == tofu:
                return False
        return True
    except (OSError, ValueError, AttributeError):
        return False


def _requested_font_name(font_value: Any, cjk: bool) -> str:
    if isinstance(font_value, dict):
        return str(font_value.get("east_asian" if cjk else "latin", ""))
    return str(font_value or "")


def _font_candidates(requested: str, weight: str, italic: bool, cjk: bool, sans: bool) -> tuple[str, ...]:
    lowered = requested.casefold()
    if cjk:
        if "serif" in lowered or "song" in lowered or "宋" in requested:
            return (NOTO_SERIF_SC, SONGTI, NOTO_SANS_SC, HEITI)
        if "simhei" in lowered or "黑体" in requested:
            return (SIMHEI, NOTO_SANS_SC, HEITI, SONGTI)
        return (NOTO_SANS_SC, HEITI, SONGTI, NOTO_SERIF_SC)

    if "georgia" in lowered:
        if weight == "bold" and italic:
            return (GEORGIA_BOLD_ITALIC, GEORGIA_BOLD, GEORGIA_ITALIC, GEORGIA)
        if weight == "bold":
            return (GEORGIA_BOLD, GEORGIA, TIMES_BOLD, TIMES)
        if italic:
            return (GEORGIA_ITALIC, GEORGIA, TIMES)
        return (GEORGIA, TIMES, ARIAL)
    if "times" in lowered or "baskerville" in lowered:
        return (TIMES_BOLD, TIMES) if weight == "bold" else (TIMES, ARIAL)
    if "helvetica" in lowered:
        if weight == "bold" and italic:
            return (HELVETICA, HELVETICA_NEUE, ARIAL_BOLD_ITALIC, ARIAL_BOLD)
        if weight == "bold":
            return (HELVETICA, HELVETICA_NEUE, ARIAL_BOLD, ARIAL)
        if italic:
            return (HELVETICA, HELVETICA_NEUE, ARIAL_ITALIC, ARIAL)
        return (HELVETICA, HELVETICA_NEUE, ARIAL)
    if "arial" in lowered or sans or not requested:
        if weight == "bold" and italic:
            return (ARIAL_BOLD_ITALIC, ARIAL_BOLD, ARIAL)
        if weight == "bold":
            return (ARIAL_BOLD, ARIAL)
        if italic:
            return (ARIAL_ITALIC, ARIAL)
        return (ARIAL, ARIAL_BOLD)
    return (ARIAL_BOLD, ARIAL) if weight == "bold" else (ARIAL, TIMES)


def font_path(
    *, bold: bool, cjk: bool, sans: bool, font_value: Any = None,
    font_weight: Any = None, text: str = "", italic: bool = False,
) -> str:
    requested = _requested_font_name(font_value, cjk)
    weight = normalize_font_weight(font_weight, bold=bold, cjk=cjk)
    candidates = _font_candidates(requested, weight, italic, cjk, sans)
    for candidate in candidates:
        if Path(candidate).is_file() and font_supports_text(candidate, text, weight=weight):
            return candidate
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("No usable system font was found for the template renderer.")


def typeface(
    size_pt: float,
    *, bold: bool = False, cjk: bool = False, sans: bool = False,
    font_value: Any = None, font_weight: Any = None, text: str = "",
    scale: float = 1.0, italic: bool = False, size_px: float | None = None,
) -> ImageFont.FreeTypeFont:
    """Load a real font. ``size_px`` is the v3 source-canvas unit."""
    weight = normalize_font_weight(font_weight, bold=bold, cjk=cjk)
    path = font_path(bold=bold, cjk=cjk, sans=sans, font_value=font_value, font_weight=weight, text=text, italic=italic)
    pixels = float(size_px) if size_px is not None else float(size_pt) * 96 / 72
    face = _font_for_path(path, round(pixels * scale), weight, "italic" if italic else "regular")
    setattr(face, "_codex_font_weight", weight)
    setattr(face, "_codex_font_path", path)
    setattr(face, "_codex_font_family", _requested_font_name(font_value, cjk) or Path(path).stem)
    setattr(face, "_codex_font_style", "italic" if italic else "regular")
    return face


def _size_from_style(block: dict[str, Any], style: dict[str, Any], key: str, default: float) -> tuple[float, bool]:
    value = block.get(key, style.get(key))
    if value is None:
        return default, False
    return float(value), key.endswith("_px")


def _font_from_block(block: dict[str, Any], style: dict[str, Any], value: str, scale: float) -> ImageFont.FreeTypeFont:
    if "font_size_px" in block or "font_size_px" in style:
        size_px = float(block.get("font_size_px", style.get("font_size_px")))
        size_pt = 12
    else:
        size_px = None
        size_pt = float(block.get("font_size_pt", style.get("font_size_pt", 12)))
    font_value = block.get("font", style.get("font"))
    return typeface(
        size_pt,
        bold=bool(block.get("bold", style.get("bold", False))),
        cjk=has_cjk(value),
        sans=is_sans(font_value),
        font_value=font_value,
        font_weight=block.get("font_weight", style.get("font_weight")),
        text=value,
        scale=scale,
        italic=bool(block.get("italic", style.get("italic", False))) or str(block.get("font_style", style.get("font_style", ""))).lower() == "italic",
        size_px=size_px,
    )


def scaled_box(box: list[float], scale: float) -> tuple[int, int, int, int]:
    return tuple(round(float(value) * scale) for value in box)  # type: ignore[return-value]


def has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff\u3040-\u30ff]", value))


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
    value = str(font_value or "").casefold()
    return any(name in value for name in ("arial", "helvetica", "noto sans", "microsoft yahei", "simhei", "黑体", "heiti"))


def _letter_spacing(style: dict[str, Any]) -> float:
    try:
        return float(style.get("letter_spacing", style.get("letter_spacing_px", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _text_bbox_tracked(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.FreeTypeFont, spacing: float = 0, stroke_width: int = 0) -> tuple[int, int, int, int]:
    if not value:
        return draw.textbbox((0, 0), " ", font=face, stroke_width=stroke_width)
    if not spacing:
        return draw.textbbox((0, 0), value, font=face, stroke_width=stroke_width)
    cursor = 0.0
    boxes: list[tuple[int, int, int, int]] = []
    for character in value:
        left, top, right, bottom = draw.textbbox((round(cursor), 0), character, font=face, stroke_width=stroke_width)
        boxes.append((left, top, right, bottom))
        cursor += float(draw.textlength(character, font=face)) + spacing
    return min(item[0] for item in boxes), min(item[1] for item in boxes), max(item[2] for item in boxes), max(item[3] for item in boxes)


def measure(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.FreeTypeFont, letter_spacing: float = 0) -> tuple[int, int]:
    left, top, right, bottom = _text_bbox_tracked(draw, value or " ", face, letter_spacing)
    return right - left, bottom - top


def glyph_height(draw: ImageDraw.ImageDraw, face: ImageFont.FreeTypeFont) -> int:
    """Measure ascenders and descenders, including g/y/j/p/q."""
    return measure(draw, "Agjpqy汉字", face)[1]


def cjk_wrap_tokens(value: str) -> list[str]:
    """Keep closing punctuation with the preceding CJK character."""
    tokens: list[str] = []
    for character in value:
        if character in ATTACHED_CJK_PUNCTUATION and tokens:
            tokens[-1] += character
        else:
            tokens.append(character)
    return tokens


def _split_token(draw: ImageDraw.ImageDraw, token: str, face: ImageFont.FreeTypeFont, width: int, spacing: float = 0) -> list[str]:
    parts: list[str] = []
    current = ""
    for character in token:
        candidate = current + character
        if current and measure(draw, candidate, face, spacing)[0] > width:
            parts.append(current)
            current = character
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts or [token]


def wrap(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.FreeTypeFont, width: int, letter_spacing: float = 0) -> list[str]:
    if not value:
        return []
    lines: list[str] = []
    for paragraph in value.splitlines() or [value]:
        tokens = paragraph.split() if " " in paragraph else cjk_wrap_tokens(paragraph)
        separator = " " if " " in paragraph else ""
        current = ""
        for token in tokens:
            if not current and measure(draw, token, face, letter_spacing)[0] > width:
                pieces = _split_token(draw, token, face, width, letter_spacing)
                lines.extend(pieces[:-1])
                current = pieces[-1]
                continue
            candidate = token if not current else f"{current}{separator}{token}"
            if current and measure(draw, candidate, face, letter_spacing)[0] > width:
                lines.append(current)
                if measure(draw, token, face, letter_spacing)[0] > width:
                    pieces = _split_token(draw, token, face, width, letter_spacing)
                    lines.extend(pieces[:-1])
                    current = pieces[-1]
                else:
                    current = token
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def balanced_wrap(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.FreeTypeFont, width: int, max_lines: int | None, letter_spacing: float = 0) -> list[str]:
    """Prefer balanced complete lines when a two-line cue is possible."""
    greedy = wrap(draw, value, face, width, letter_spacing)
    if max_lines != 2 or len(greedy) <= 1 or "\n" in value:
        return greedy
    paragraph = " ".join(value.split())
    tokens = paragraph.split(" ") if " " in paragraph else cjk_wrap_tokens(paragraph)
    separator = " " if " " in paragraph else ""
    # A long cue can contain hundreds of tokens.  Measure each candidate near
    # the half-way point rather than repeatedly measuring every growing prefix
    # (the result is the same balanced split, without quadratic font calls).
    token_widths = [measure(draw, token, face, letter_spacing)[0] for token in tokens]
    separator_width = measure(draw, separator, face, letter_spacing)[0] if separator else 0
    total_width = sum(token_widths) + separator_width * max(0, len(tokens) - 1)
    cumulative = 0
    nearest = 1
    best_distance = float("inf")
    for index, token_width in enumerate(token_widths[:-1], start=1):
        cumulative += token_width + separator_width
        distance = abs(cumulative - total_width / 2)
        if distance < best_distance:
            nearest, best_distance = index, distance
    candidate_indices = range(max(1, nearest - 8), min(len(tokens), nearest + 9))
    candidates: list[tuple[float, list[str]]] = []
    for index in candidate_indices:
        left, right = separator.join(tokens[:index]), separator.join(tokens[index:])
        if measure(draw, left, face, letter_spacing)[0] <= width and measure(draw, right, face, letter_spacing)[0] <= width:
            score = abs(measure(draw, left, face, letter_spacing)[0] - measure(draw, right, face, letter_spacing)[0])
            candidates.append((score, [left, right]))
    return min(candidates, key=lambda item: item[0])[1] if candidates else greedy


def text_insets(style: dict[str, Any], scale: float) -> tuple[int, int]:
    values = style.get("text_insets_px", [0, 0, 0, 0])
    if not isinstance(values, list) or len(values) != 4:
        return 0, 0
    return round(float(values[0]) * scale), round(float(values[2]) * scale)


def _line_spacing(style: dict[str, Any], block: dict[str, Any] | None = None, default: float = 115) -> float:
    block = block or {}
    try:
        return float(block.get("line_spacing_percent", style.get("line_spacing_percent", default)))
    except (TypeError, ValueError):
        return default


def fitted_adaptive_lines(
    draw: ImageDraw.ImageDraw, value: str, block: dict[str, Any], style: dict[str, Any],
    width: int, height: int, scale: float,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    max_lines = None if block.get("unbounded_lines", style.get("unbounded_lines", False)) else int(block.get("max_lines", style.get("max_lines", 2)))
    spacing_percent = _line_spacing(style, block)
    letter_spacing = _letter_spacing({**style, **block})
    fixed_px = block.get("fixed_font_size_px", style.get("fixed_font_size_px"))
    fixed_pt = block.get("fixed_font_size_pt", style.get("fixed_font_size_pt"))
    if fixed_px is not None or fixed_pt is not None:
        requested = float(fixed_px if fixed_px is not None else fixed_pt)
        fields = {"font_size_px": requested} if fixed_px is not None else {"font_size_pt": requested}
        face = _font_from_block({**block, **fields}, style, value, scale)
        lines = balanced_wrap(draw, value, face, width, max_lines, letter_spacing)
        line_height = round(glyph_height(draw, face) * spacing_percent / 100)
        if max_lines is not None and len(lines) > max_lines:
            raise RuntimeError("Fixed text box cannot fit the complete cue without truncation.")
        if len(lines) * line_height > height:
            raise RuntimeError("Fixed text box cannot fit the complete cue without truncation.")
        return face, lines, line_height

    maximum, maximum_px = _size_from_style(block, style, "font_size_px", 0)
    if not maximum:
        maximum, maximum_px = _size_from_style(block, style, "font_size_pt", 12)
    minimum_key = "min_font_size_px" if maximum_px else "min_font_size_pt"
    minimum = float(block.get(minimum_key, style.get(minimum_key, maximum * 0.6)))
    steps = max(0, round((maximum - minimum) * 2))
    for step in range(steps + 1):
        requested = maximum - step / 2
        fields = {"font_size_px": requested} if maximum_px else {"font_size_pt": requested}
        face = _font_from_block({**block, **fields}, style, value, scale)
        lines = balanced_wrap(draw, value, face, width, max_lines, letter_spacing)
        line_height = round(glyph_height(draw, face) * spacing_percent / 100)
        if (max_lines is None or len(lines) <= max_lines) and len(lines) * line_height <= height:
            return face, lines, line_height
    raise RuntimeError("Text cannot fit inside its safe area without truncation.")


def resolve(binding: Any, content: dict[str, Any]) -> Any:
    """Resolve dotted bindings while retaining list values for metadata."""
    if isinstance(binding, list):
        return [resolve(item, content) for item in binding]
    if not isinstance(binding, str) or not binding.strip():
        return ""
    value: Any = content
    for name, index in re.findall(r"([A-Za-z_]+)(?:\[(\d+)\])?", binding):
        if not isinstance(value, dict) or name not in value:
            return ""
        value = value[name]
        if index:
            if not isinstance(value, list) or int(index) >= len(value):
                return ""
            value = value[int(index)]
    return value


def binding_text(binding: Any, content: dict[str, Any], separator: str = " · ") -> str:
    value = resolve(binding, content)
    if isinstance(value, list):
        return separator.join(str(item).strip() for item in value if str(item).strip())
    if value is None:
        return ""
    return str(value)


def layer_map(definition: dict[str, Any], template_name: str) -> dict[str, dict[str, Any]]:
    template = definition["templates"][template_name]
    layers = {layer["id"]: dict(layer) for layer in template.get("layers", [])}
    for parent_ref in template.get("inherits", []):
        parent_name, layer_id = parent_ref.split(".", 1)
        parent = layer_map(definition, parent_name)[layer_id]
        layers.setdefault(layer_id, dict(parent))
    return layers


def _layer_value(layer: dict[str, Any], block: dict[str, Any], content: dict[str, Any]) -> str:
    binding = block.get("binding", layer.get("content_binding", ""))
    if not binding and layer.get("text") is not None:
        return str(layer.get("text", ""))
    value = binding_text(binding, content, str(block.get("separator", layer.get("separator", " · "))))
    return value.strip()


def _flow_text_layer(
    draw: ImageDraw.ImageDraw, source: dict[str, Any], content: dict[str, Any],
    scale: float, shrink_step: int, honor_max_lines: bool = True,
) -> tuple[dict[str, Any], int] | None:
    """Measure a text layer and return a complete, fitted block."""
    layer = dict(source)
    width = round(float(source["bbox"][2]) * scale)
    blocks = source.get("paragraphs") or [dict(source.get("style", {}), binding=source.get("content_binding", ""))]
    prepared_blocks: list[dict[str, Any]] = []
    total_height = 0
    for raw_block in blocks:
        block = dict(raw_block)
        value = _layer_value(source, block, content)
        if not value:
            continue
        style = {**source.get("style", {}), **block}
        if style.get("text_transform") == "uppercase":
            value = value.upper()
        size_key = "font_size_px" if "font_size_px" in style else "font_size_pt"
        base = float(style.get(size_key, 12))
        minimum = float(style.get("min_font_size_px" if size_key == "font_size_px" else "min_font_size_pt", max(5, base * 0.6)))
        size = max(minimum, base - shrink_step / 2)
        block[size_key] = size
        face = _font_from_block(block, source.get("style", {}), value, scale)
        letter_spacing = _letter_spacing(style)
        requested_wrap = source.get("wrap", source.get("style", {}).get("wrap", "square"))
        max_lines = block.get("max_lines", source.get("style", {}).get("max_lines"))
        lines = [value] if requested_wrap == "none" and measure(draw, value, face, letter_spacing)[0] <= width else wrap(draw, value, face, width, letter_spacing)
        if honor_max_lines and max_lines is not None and len(lines) > int(max_lines):
            return None
        if any(measure(draw, line, face, letter_spacing)[0] > width for line in lines):
            return None
        prepared_blocks.append(block)
        total_height += len(lines) * round(glyph_height(draw, face) * _line_spacing(style, block) / 100)
    if not prepared_blocks:
        layer["bbox"] = [source["bbox"][0], source["bbox"][1], source["bbox"][2], 0]
        return layer, 0
    if source.get("paragraphs"):
        layer["paragraphs"] = prepared_blocks
    else:
        style = dict(source.get("style", {}))
        style.update({key: value for key, value in prepared_blocks[0].items() if key.startswith("font_size") or key.startswith("min_font_size")})
        layer["style"] = style
    layer["bbox"] = [source["bbox"][0], source["bbox"][1], source["bbox"][2], total_height / scale]
    layer["vertical_alignment"] = "top"
    return layer, total_height


def prepare_portrait_opening_layers(
    draw: ImageDraw.ImageDraw, template: dict[str, Any], layers: dict[str, dict[str, Any]],
    content: dict[str, Any], scale: float,
) -> dict[str, dict[str, Any]]:
    """Flow portrait metadata so long verified titles never overlap captions."""
    flow_ids = tuple(name for name in ("kicker", "article_page", "headline", "headline_zh", "subtitle", "subtitle_zh", "byline_dateline", "metadata") if name in layers)
    if template.get("canvas", {}).get("aspect_ratio") != "9:16" or not flow_ids or "subtitle_rail" not in layers:
        return layers
    original = {name: layers[name] for name in flow_ids}
    image_bottom = 0
    if "issue_cover" in layers:
        _, image_y, _, image_height = scaled_box(layers["issue_cover"]["bbox"], scale)
        image_bottom = image_y + image_height
    rail_y = scaled_box(layers["subtitle_rail"]["bbox"], scale)[1]
    start_y = max(min(scaled_box(layer["bbox"], scale)[1] for layer in original.values()), image_bottom + round(12 * scale))
    bottom_limit = rail_y - round(10 * scale)
    max_steps = 30
    for step in range(max_steps + 1):
        prepared: dict[str, dict[str, Any]] = {}
        measured: dict[str, int] = {}
        for name, source in original.items():
            fitted = _flow_text_layer(draw, source, content, scale, step, honor_max_lines=False)
            if fitted is None:
                break
            prepared[name], measured[name] = fitted
        else:
            cursor = start_y
            placed = False
            gaps = {"headline": 10, "headline_zh": 7, "subtitle": 12, "subtitle_zh": 5, "byline_dateline": 10, "metadata": 8, "article_page": 6}
            for name in flow_ids:
                height = measured.get(name, 0)
                if not height:
                    continue
                if placed:
                    cursor += round(gaps.get(name, 7) * scale)
                prepared[name]["bbox"][1] = cursor / scale
                prepared[name]["bbox"][3] = height / scale
                cursor += height
                placed = True
            if cursor <= bottom_limit:
                layers.update(prepared)
                return layers
    raise RuntimeError("Opening metadata cannot fit the measured text safe area without overlap.")


def prepare_bounded_text_layers(
    draw: ImageDraw.ImageDraw, layers: dict[str, dict[str, Any]], content: dict[str, Any], scale: float,
) -> dict[str, dict[str, Any]]:
    """Fit guide-question layers to their declared safe boxes."""
    for layer_id, source in list(layers.items()):
        if not layer_id.startswith("guide_question_") or layer_id.endswith("_number"):
            continue
        blocks = source.get("paragraphs") or [source.get("style", {})]
        max_steps = max(0, round(max((float(block.get("font_size_px", block.get("font_size_pt", 12))) - float(block.get("min_font_size_px", block.get("min_font_size_pt", 7))) for block in blocks), default=0) * 2))
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
    draw: ImageDraw.ImageDraw, template: dict[str, Any], layers: dict[str, dict[str, Any]],
    content: dict[str, Any], scale: float, subtitle_mode: str = "default",
) -> dict[str, dict[str, Any]]:
    """Prepare one centred English/Chinese caption flow with strict limits."""
    subtitle_mode = validate_subtitle_mode(subtitle_mode)
    caption_ids = ("caption_en", "caption_zh")
    visible = ("caption_en",) if subtitle_mode == "en-only" else caption_ids
    for name in caption_ids:
        layers[name] = {**layers[name], "visible": name in visible}
    if "subtitle_rail" not in layers:
        return layers
    rail_x, rail_y, rail_width, rail_height = scaled_box(layers["subtitle_rail"]["bbox"], scale)
    prepared: list[tuple[str, list[str], int, int, int]] = []
    padding = round(float(layers["subtitle_rail"].get("padding_px", 0)) * scale)
    language_gap = round(float(layers["subtitle_rail"].get("language_gap_px", 6)) * scale)
    for name in caption_ids:
        layer = dict(layers[name])
        style = dict(layer.get("style", {}))
        style.update({"alignment": "center", "max_lines": int(style.get("max_lines", 2)), "unbounded_lines": False})
        layer["style"] = style
        value = normalize_caption_text(binding_text(layer.get("content_binding", ""), content))
        if name not in visible or not value:
            layer["bbox"] = [layer["bbox"][0], layers["caption_zh"]["bbox"][1], layer["bbox"][2], 0]
            layers[name] = layer
            continue
        _, _, width, _ = scaled_box(layer["bbox"], scale)
        available = max(1, rail_height - 2 * padding)
        face, lines, line_height = fitted_adaptive_lines(draw, value, style, style, width, available, scale)
        inset_top, inset_bottom = text_insets(style, scale)
        prepared.append((name, lines, line_height, inset_top, inset_bottom))
        layers[name] = layer
    total = 2 * padding + sum(len(lines) * line_height + top + bottom for _, lines, line_height, top, bottom in prepared)
    if len(prepared) > 1:
        total += language_gap * (len(prepared) - 1)
    if total > rail_height:
        raise RuntimeError("Caption cannot fit inside its safe area without truncation.")
    cursor = rail_y + max(0, (rail_height - total) // 2) + padding
    prepared_by_name = {name: (lines, line_height, top, bottom) for name, lines, line_height, top, bottom in prepared}
    for name in caption_ids:
        layer = layers[name]
        lines, line_height, top, bottom = prepared_by_name.get(name, ([], 0, 0, 0))
        layer["bbox"] = [layer["bbox"][0], cursor / scale, layer["bbox"][2], (len(lines) * line_height + top + bottom) / scale]
        if lines:
            cursor += len(lines) * line_height + top + bottom + language_gap
        layers[name] = layer
    return layers


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(character * 2 for character in value)
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def rgba(value: Any, opacity: float | None = None) -> tuple[int, int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) in {3, 4}:
        channels = [int(item) for item in value]
        return channels[0], channels[1], channels[2], channels[3] if len(channels) == 4 else round((opacity if opacity is not None else 1) * 255)
    text = str(value or "#000000")
    match = re.fullmatch(r"rgba?\(([^)]+)\)", text.strip(), re.IGNORECASE)
    if match:
        values = [item.strip() for item in match.group(1).split(",")]
        rgb = tuple(round(float(item)) for item in values[:3])
        alpha = float(values[3]) if len(values) > 3 else (opacity if opacity is not None else 1)
        if alpha <= 1:
            alpha *= 255
        return rgb[0], rgb[1], rgb[2], max(0, min(255, round(alpha)))
    return (*hex_rgb(text), max(0, min(255, round((opacity if opacity is not None else 1) * 255))))


def _pil_color(value: Any) -> Any:
    """Return a Pillow-compatible RGB/greyscale colour for direct drawing."""
    if isinstance(value, str) and value.strip().lower().startswith("rgba"):
        return rgba(value)[:3]
    return value


def _draw_tracked(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, face: ImageFont.FreeTypeFont, fill: Any, spacing: float, stroke_width: int = 0, stroke_fill: Any = None) -> None:
    fill = _pil_color(fill)
    stroke_fill = _pil_color(stroke_fill)
    if not spacing:
        draw.text(xy, value, font=face, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        return
    cursor = float(xy[0])
    for character in value:
        draw.text((round(cursor), xy[1]), character, font=face, fill=fill, stroke_width=stroke_width, stroke_fill=stroke_fill)
        cursor += float(draw.textlength(character, font=face)) + spacing


def _font_label(face: ImageFont.FreeTypeFont) -> str:
    family = getattr(face, "_codex_font_family", "")
    return f"{family or Path(getattr(face, '_codex_font_path', '')).stem}/{getattr(face, '_codex_font_weight', 'regular')}"


def draw_text(
    canvas: Image.Image, layer: dict[str, Any], content: dict[str, Any], scale: float,
    diagnostics: list[dict[str, Any]] | None = None,
) -> None:
    if layer.get("visible", True) is False:
        return
    draw = ImageDraw.Draw(canvas)
    x, y, width, height = scaled_box(layer["bbox"], scale)
    style_base = dict(layer.get("style", {}))
    raw_blocks = layer.get("paragraphs") or [dict(style_base, binding=layer.get("content_binding", ""))]
    rendered: list[tuple[str, ImageFont.FreeTypeFont, Any, int, float]] = []
    for raw in raw_blocks:
        block = dict(raw)
        value = _layer_value(layer, block, content)
        if not value:
            continue
        style = {**style_base, **block}
        if style.get("text_transform") == "uppercase":
            value = value.upper()
        letter_spacing = _letter_spacing(style)
        if style.get("wrap") in {"adaptive", "balanced"}:
            face, lines, line_height = fitted_adaptive_lines(draw, value, block, style, width, height, scale)
        else:
            face = _font_from_block(block, style, value, scale)
            if style.get("wrap") == "none":
                if measure(draw, value, face, letter_spacing)[0] > width:
                    raise RuntimeError(f"{layer['id']} cannot fit its measured text safe area without truncation.")
                lines = [value]
            else:
                lines = wrap(draw, value, face, width, letter_spacing)
            line_height = round(glyph_height(draw, face) * _line_spacing(style, block, 125) / 100)
        rendered.extend((line, face, style.get("color", "#161616"), line_height, letter_spacing) for line in lines)

    if not rendered:
        return
    total_height = sum(item[3] for item in rendered)
    inset_top, inset_bottom = text_insets(style_base, scale)
    inner_height = max(0, height - inset_top - inset_bottom)
    if total_height > inner_height + max(2, round(2 * scale)):
        raise RuntimeError(f"{layer['id']} exceeds its measured text safe area.")
    cursor_y = y + inset_top if layer.get("vertical_alignment", "center") == "top" else y + inset_top + max(0, (inner_height - total_height) // 2)
    alignment = style_base.get("alignment", layer.get("alignment", "left"))
    stroke_width = max(0, round(float(style_base.get("stroke_width_px", 0)) * scale))
    stroke_fill = style_base.get("stroke_color", "#000000")
    shadow = style_base.get("shadow") or {}
    if not isinstance(shadow, dict):
        shadow = {}
    placements: list[tuple[str, ImageFont.FreeTypeFont, Any, int, float, int, int, int, int]] = []
    for line, face, color, line_height, letter_spacing in rendered:
        left, top, right, bottom = _text_bbox_tracked(draw, line, face, letter_spacing, stroke_width)
        line_width, line_box_height = right - left, bottom - top
        if alignment == "center":
            line_x = x + max(0, (width - line_width) // 2) - left
        elif alignment == "right":
            line_x = x + max(0, width - line_width) - left
        else:
            line_x = x - left
        text_y = round(cursor_y - top)
        placements.append((line, face, color, line_height, letter_spacing, line_x, text_y, line_width, line_box_height))
        cursor_y += line_height

    if shadow and placements:
        shadow_color = rgba(shadow.get("color", "#000000"), float(shadow.get("opacity", 0.55)))
        offset_x = round(float(shadow.get("offset_x_px", 0)) * scale)
        offset_y = round(float(shadow.get("offset_y_px", 2)) * scale)
        blur = max(0, round(float(shadow.get("blur_px", 8)) * scale))
        paint_left = min(item[5] for item in placements)
        paint_top = min(item[6] for item in placements)
        paint_right = max(item[5] + item[7] for item in placements)
        paint_bottom = max(item[6] + item[8] for item in placements)
        pad = blur * 3 + max(abs(offset_x), abs(offset_y)) + 2
        left = max(0, paint_left - pad)
        top = max(0, paint_top - pad)
        right = min(canvas.width, paint_right + pad)
        bottom = min(canvas.height, paint_bottom + pad)
        shadow_layer = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        for line, face, _, _, letter_spacing, line_x, text_y, _, _ in placements:
            _draw_tracked(shadow_draw, (line_x + offset_x - left, text_y + offset_y - top), line, face, shadow_color, letter_spacing, stroke_width, shadow_color)
        if blur:
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur))
        canvas.paste(Image.alpha_composite(canvas.crop((left, top, right, bottom)).convert("RGBA"), shadow_layer).convert("RGB"), (left, top))
        draw = ImageDraw.Draw(canvas)

    for line, face, color, _, letter_spacing, line_x, text_y, _, _ in placements:
        _draw_tracked(draw, (line_x, text_y), line, face, color, letter_spacing, stroke_width, stroke_fill)

    if diagnostics is not None:
        line_boxes = []
        for line, face, _, _, letter_spacing, line_x, text_y, line_width, line_box_height in placements:
            raw_left, raw_top, raw_right, raw_bottom = _text_bbox_tracked(draw, line, face, letter_spacing, stroke_width)
            line_boxes.append([line_x + raw_left, text_y + raw_top, raw_right - raw_left, raw_bottom - raw_top])
        diagnostic_y = min(box[1] for box in line_boxes)
        diagnostic_bottom = max(box[1] + box[3] for box in line_boxes)
        diagnostics.append({
            "kind": "text", "layer": layer["id"], "safe_bbox": [x, y, width, height],
            "paint_bbox": [min(box[0] for box in line_boxes), diagnostic_y, max(box[0] + box[2] for box in line_boxes) - min(box[0] for box in line_boxes), diagnostic_bottom - diagnostic_y],
            "line_bboxes": line_boxes, "font": _font_label(placements[0][1]),
            "font_path": getattr(placements[0][1], "_codex_font_path", ""),
            "font_weight": getattr(placements[0][1], "_codex_font_weight", "regular"),
            "font_style": getattr(placements[0][1], "_codex_font_style", "regular"),
            "font_size_px": placements[0][1].size, "line_count": len(placements),
            "lines": [item[0] for item in placements], "alignment": alignment,
            "letter_spacing": style_base.get("letter_spacing", 0), "text_justification": "none",
            "text_insets_px": style_base.get("text_insets_px", [0, 0, 0, 0]),
            "stroke_width_px": stroke_width, "stroke_color": stroke_fill,
            "shadow": shadow or None, "background_color": style_base.get("background_color"),
            "background_opacity": style_base.get("background_opacity"),
        })


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=max(0, radius), fill=255)
    return mask


def draw_image(
    canvas: Image.Image, layer: dict[str, Any], cover_path: Path, scale: float,
    diagnostics: list[dict[str, Any]] | None = None,
) -> None:
    x, y, width, height = scaled_box(layer["bbox"], scale)
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Image layer {layer.get('id', '')} has no usable area.")
    with Image.open(cover_path) as source:
        image = source.convert("RGB")
        fit = layer.get("fit", "contain")
        ratio = (max if fit == "crop" else min)(width / image.width, height / image.height)
        resized = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))), Image.Resampling.LANCZOS)
    if fit == "crop":
        offset_x, offset_y = max(0, (resized.width - width) // 2), max(0, (resized.height - height) // 2)
        placed = resized.crop((offset_x, offset_y, offset_x + width, offset_y + height))
        image_x, image_y = x, y
    else:
        image_x, image_y = x + (width - resized.width) // 2, y + (height - resized.height) // 2
        placed = resized
    actual_bbox = (image_x, image_y, image_x + placed.width, image_y + placed.height)
    style = layer.get("style", {})
    radius = round(float(style.get("corner_radius_px", 1)) * scale)
    shadows = style.get("shadows") or ([] if not style.get("shadow") else [style["shadow"]])
    for shadow in shadows:
        if not isinstance(shadow, dict):
            continue
        sx = round(float(shadow.get("offset_x_px", 0)) * scale)
        sy = round(float(shadow.get("offset_y_px", 0)) * scale)
        fill = rgba(shadow.get("color", "#000000"), float(shadow.get("opacity", 0.2)))
        blur = max(0, round(float(shadow.get("blur_px", 8)) * scale))
        pad = blur * 3 + max(abs(sx), abs(sy)) + 2
        left = max(0, actual_bbox[0] - pad)
        top = max(0, actual_bbox[1] - pad)
        right = min(canvas.width, actual_bbox[2] + pad)
        bottom = min(canvas.height, actual_bbox[3] + pad)
        overlay = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle((actual_bbox[0] + sx - left, actual_bbox[1] + sy - top, actual_bbox[2] + sx - left, actual_bbox[3] + sy - top), radius=max(0, radius), fill=fill)
        if blur:
            overlay = overlay.filter(ImageFilter.GaussianBlur(blur))
        canvas.paste(Image.alpha_composite(canvas.crop((left, top, right, bottom)).convert("RGBA"), overlay).convert("RGB"), (left, top))
    if radius:
        canvas.paste(placed, (image_x, image_y), _rounded_mask(placed.size, radius))
    else:
        canvas.paste(placed, (image_x, image_y))
    if diagnostics is not None:
        diagnostics.append({
            "kind": "image", "layer": layer["id"], "safe_bbox": [x, y, width, height],
            "image_bbox": [actual_bbox[0], actual_bbox[1], actual_bbox[2] - actual_bbox[0], actual_bbox[3] - actual_bbox[1]],
            "fit": fit, "corner_radius_px": radius, "stroke": style.get("stroke", "none"), "shadows": shadows,
        })


def _draw_gradient(canvas: Image.Image, bbox: tuple[int, int, int, int], layer: dict[str, Any]) -> None:
    x, y, width, height = bbox
    if width <= 0 or height <= 0:
        return
    top = rgba(layer.get("gradient_top", layer.get("fill", "#F4F1EC")), float(layer.get("gradient_top_opacity", 0)))
    bottom = rgba(layer.get("gradient_bottom", layer.get("fill", "#F4F1EC")), float(layer.get("gradient_bottom_opacity", 1)))
    gradient = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gradient_draw = ImageDraw.Draw(gradient)
    for row in range(height):
        ratio = row / max(1, height - 1)
        color = tuple(round(top[channel] * (1 - ratio) + bottom[channel] * ratio) for channel in range(4))
        gradient_draw.line((0, row, width, row), fill=color)
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay.paste(gradient, (x, y), gradient)
    canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB"))


def _draw_shape(canvas: Image.Image, layer: dict[str, Any], scale: float) -> None:
    draw = ImageDraw.Draw(canvas)
    x, y, width, height = scaled_box(layer["bbox"], scale)
    geometry = str(layer.get("geometry", "rect")).casefold()
    if "gradient" in geometry:
        _draw_gradient(canvas, (x, y, width, height), layer)
        return
    fill = layer.get("fill")
    outline = layer.get("stroke") if layer.get("stroke") not in {None, "none", "transparent"} else None
    outline_width = max(1, round(float(layer.get("stroke_width_px", 1)) * scale)) if outline else 1
    if fill is None and outline is None:
        return
    if "line" in geometry or geometry in {"rule", "horizontal_rule"}:
        draw.line((x, y + height // 2, x + width, y + height // 2), fill=fill or outline, width=max(1, round(float(layer.get("line_width_px", layer.get("stroke_width_px", 1))) * scale)))
    elif "circle" in geometry or "ellipse" in geometry or geometry == "dot":
        draw.ellipse((x, y, x + width, y + height), fill=fill, outline=outline, width=outline_width)
    elif "round" in geometry:
        radius = round(float(layer.get("corner_radius_px", 0)) * scale)
        draw.rounded_rectangle((x, y, x + width, y + height), radius=radius, fill=fill, outline=outline, width=outline_width)
    else:
        draw.rectangle((x, y, x + width, y + height), fill=fill, outline=outline, width=outline_width)


def render_template(
    definition: dict[str, Any], template_name: str, cover_path: Path, content: dict[str, Any],
    output_height: int, output_width: int | None = None, diagnostics: list[dict[str, Any]] | None = None,
    subtitle_mode: str = "default",
) -> Image.Image:
    subtitle_mode = validate_subtitle_mode(subtitle_mode)
    content = {**content, "design_tokens": definition.get("design_tokens", {})}
    template = definition["templates"][template_name]
    scale = output_height / float(template["canvas"]["height"])
    colors = definition.get("design_tokens", {}).get("colors", {})
    canvas = Image.new("RGB", (round(template["canvas"]["width"] * scale), output_height), colors.get("page_background", "#F4F1EC"))
    layers = layer_map(definition, template_name)
    draw = ImageDraw.Draw(canvas)
    layers = prepare_portrait_opening_layers(draw, template, layers, content, scale)
    layers = prepare_bounded_text_layers(draw, layers, content, scale)
    layers = caption_layers_for_frame(draw, template, layers, content, scale, subtitle_mode)
    for layer_id in template["source_layer_order"]:
        layer = layers[layer_id]
        if layer.get("visible", True) is False:
            continue
        if layer["kind"] == "shape":
            _draw_shape(canvas, layer, scale)
        elif layer["kind"] == "image":
            draw_image(canvas, layer, cover_path, scale, diagnostics)
        else:
            draw_text(canvas, layer, content, scale, diagnostics)
    if output_width and canvas.width != output_width:
        canvas = canvas.resize((output_width, output_height), Image.Resampling.LANCZOS)
    return canvas


def make_contact_sheet(frames: list[tuple[str, Image.Image]]) -> Image.Image:
    paper = "#F4F1EC"
    title_face = typeface(16, bold=True, sans=True, font_value="Helvetica", scale=1.0)
    sheet = Image.new("RGB", (2400, 1900), paper)
    draw = ImageDraw.Draw(sheet)
    slots = [(60, 70), (1240, 70), (60, 1020), (1240, 1020)]
    for (title, frame), (x, y) in zip(frames, slots):
        thumbnail = frame.copy()
        thumbnail.thumbnail((1060, 780), Image.Resampling.LANCZOS)
        draw.text((x, y), title, font=title_face, fill="#161616")
        sheet.paste(thumbnail, (x, y + 52))
    return sheet


def render_all(definition_path: Path, cover_path: Path, output_dir: Path) -> dict[str, Path]:
    definition = read_definition(definition_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[str, Image.Image]] = []
    outputs: dict[str, Path] = {}
    states = [
        ("01-landscape-opening", "landscape_opening", 1080, 1920),
        ("02-landscape-guide-questions", "landscape_guide_questions", 1080, 1920),
        ("03-portrait-opening", "portrait_opening", 1920, 1080),
        ("04-portrait-guide-questions", "portrait_guide_questions", 1920, 1080),
    ]
    for filename, template_name, output_height, output_width in states:
        frame = render_template(definition, template_name, cover_path, SAMPLE_CONTENT, output_height, output_width)
        destination = output_dir / f"{filename}.png"
        frame.save(destination)
        outputs[filename] = destination
        frames.append((filename.replace("-", " ").upper(), frame))
    contact_sheet = output_dir / "contact-sheet.png"
    make_contact_sheet(frames).save(contact_sheet)
    outputs["contact_sheet"] = contact_sheet
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the Publication Video Visual System v3 as four review images.")
    parser.add_argument("--cover", required=True, type=Path, help="Verified issue or article image to place in the selected media slot.")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory for generated PNG previews.")
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION, help="Template definition JSON.")
    args = parser.parse_args()
    if not args.cover.is_file():
        raise SystemExit(f"Cover image is missing: {args.cover}")
    for name, path in render_all(args.definition, args.cover, args.out_dir).items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
