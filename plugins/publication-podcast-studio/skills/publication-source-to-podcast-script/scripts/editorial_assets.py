#!/usr/bin/env python3
"""Validate and materialise source-linked editorial assets for a publication episode."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parents[2]
LIB_DIR = PLUGIN_ROOT / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from publication_package import load_source_package, paragraph_id, publication_display_name, source_display_metadata

EDITORIAL_FORMAT = "publication-editorial-assets"
LEGACY_EDITORIAL_FORMAT = "economist-editorial-assets"
LEGACY_TITLE_PREFIX = "《经济学人》："
TITLE_SUFFIXES = {
    "en-zh": " | 外刊播客 | 中英字幕",
    "zh-CN": " | 外刊播客 | 中文字幕",
}
MONTHS = "JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER"
DATE_RE = re.compile(
    rf"\b(?:{MONTHS})\s+\d{{1,2}}(?:ST|ND|RD|TH)?(?:\s*[–—-]\s*\d{{1,2}}(?:ST|ND|RD|TH)?)?(?:\s*,?\s*\d{{4}})\b",
    re.IGNORECASE,
)
SERIAL_RE = re.compile(r"\b(?:(?:ISSUE|NO\.?|NUMBER)\s*[:#]?\s*[A-Z0-9][A-Z0-9./-]*|VOL(?:UME)?\.?\s*[A-Z0-9][A-Z0-9./-]*)\b", re.IGNORECASE)
MIN_OCR_CONFIDENCE = 55.0


class EditorialAssetsError(ValueError):
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


def load_article(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        article = load_source_package(path)
    except ValueError as error:
        raise EditorialAssetsError(str(error)) from error
    return article, article["paragraphs"]


def source_ids(value: Any, known: set[str], label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item in known for item in value):
        raise EditorialAssetsError(f"{label} needs one or more known source paragraph IDs.")
    return list(dict.fromkeys(value))


def chinese_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or not re.search(r"[\u3400-\u9fff]", value):
        raise EditorialAssetsError(f"{label} must be non-empty Chinese text.")
    if "\n" in value or "\r" in value:
        raise EditorialAssetsError(f"{label} must be one line.")
    return value.strip()


def optional_chinese_text(value: Any, label: str) -> str:
    if value in (None, ""):
        return ""
    return chinese_text(value, label)


def bounded_chinese_text(value: Any, label: str, maximum: int, optional: bool = False) -> str:
    text = optional_chinese_text(value, label) if optional else chinese_text(value, label)
    readable = re.sub(r"\s+", "", text)
    if len(readable) > maximum:
        raise EditorialAssetsError(f"{label} must contain at most {maximum} visible characters for deterministic layout.")
    return text


def all_chinese_text(value: Any, label: str) -> str:
    value = chinese_text(value, label)
    if re.search(r"[A-Za-z]", value):
        raise EditorialAssetsError(f"{label} must not contain Latin text.")
    return value


def publication_suffix(publication_variant: str) -> str:
    try:
        return TITLE_SUFFIXES[publication_variant]
    except KeyError as error:
        raise EditorialAssetsError(f"Unsupported editorial publication variant: {publication_variant}") from error


def title_signature(value: str) -> str:
    return re.sub(r"[^\u3400-\u9fff0-9]", "", value)


def publication_title_prefix(article: dict[str, Any]) -> str:
    return f"《{publication_display_name(article['publication'])}》："


def publication_title_body(publication: dict[str, Any], title_suffix: str, title_prefix: str = LEGACY_TITLE_PREFIX) -> str:
    if "title_body_zh" in publication:
        return all_chinese_text(publication.get("title_body_zh"), "publication.title_body_zh")
    legacy_title = chinese_text(publication.get("title_zh"), "publication.title_zh")
    matched_prefix = next((prefix for prefix in (title_prefix, LEGACY_TITLE_PREFIX) if legacy_title.startswith(prefix)), None)
    if matched_prefix is None or not legacy_title.endswith(title_suffix):
        raise EditorialAssetsError("Publication title must use the confirmed publication podcast wrapper.")
    body = legacy_title[len(matched_prefix):-len(title_suffix)].strip()
    return all_chinese_text(body, "publication title body")


def validate_publication_title_body(body: str, display_headline: str) -> str:
    signature = title_signature(body)
    display_signature = title_signature(display_headline)
    if display_signature:
        similarity = SequenceMatcher(None, signature, display_signature).ratio()
        if signature == display_signature or similarity >= 0.88:
            raise EditorialAssetsError("Publication title body must distill the article, not repeat or directly translate its display headline.")
    if not 12 <= len(signature) <= 28:
        raise EditorialAssetsError("Publication title body must contain 12 to 28 Chinese characters or digits.")
    return body


def editorial_request(article_path: Path, publication_variant: str = "en-zh") -> dict[str, Any]:
    article, paragraphs = load_article(article_path)
    units = article["content_units"]
    lead = next(item for item in units if item["is_lead_story"])
    non_leads = [item for item in units if not item["is_lead_story"]]
    secondary = min(non_leads, key=lambda item: (item.get("editorial_priority", item["source_order"]), item["source_order"])) if non_leads else lead
    return {
        "source_sha256": article["source_sha256"],
        "content_mode": article["content_mode"],
        "source_publication": article["publication"],
        "translation_policy": {
            "mode": "meaning_first_chinese_transcreation",
            "preserve": ["core meaning", "facts", "stance", "degree of certainty"],
            "allow": ["reorder clauses", "compress wording", "replace idioms", "use natural Chinese subjects"],
            "forbid": ["word-for-word imitation", "new facts", "stronger claims", "changed causality"],
        },
        "instructions": (
            "Return only the editorial draft JSON. Every claim must be supported by the cited source paragraphs. "
            "Treat every Chinese headline, standfirst and guide-question translation as Chinese editorial transcreation, not literal translation. "
            "Preserve the source's core meaning, facts, stance and degree of certainty, but freely reorder clauses, compress wording, replace English idioms, "
            "and use natural Chinese information order. The copy should read as if written by a skilled Chinese-language editor. Do not mirror English syntax, "
            "retain awkward nominalisations, or add facts, stronger claims, causal links or conclusions. Silently compare at least two natural Chinese phrasings and return only the best. "
            "Keep each Chinese display headline within 64 visible characters, each standfirst within 96, and each Chinese guide-question rendering within 64. "
            "Write exactly two distinct, curiosity-provoking English guide questions with natural, meaning-equivalent Chinese renderings. "
            "Each question must be 8 to 22 English words, use an article-specific mechanism, actor, contrast or consequence, "
            "and not be a generic yes-or-no slogan. Question one must expose the article's central change or mechanism; "
            "question two must explore its implication, trade-off or unresolved consequence. Do not add facts, predictions, "
            "explanations, or conclusions. For the publication title, silently draft three Chinese title-body candidates, compare them for "
            "factual fidelity, article specificity, information gain and natural Chinese, then return only the strongest title_body_zh. "
            "It must be 12 to 28 Chinese characters or digits, distil the article's central change or mechanism plus its tension or stakes, "
            "and must not merely translate or lightly expand the lead headline. Do not include the publication prefix "
            "or podcast/subtitle suffix; the finaliser adds the confirmed publication name. In short_issue mode, question one must cite the lead item, "
            "question two must cite the supplied secondary item, every content unit needs its own concise Chinese editorial display copy, and the publication description must represent every content unit. "
            "Avoid generic phrases such as 深度解读、背后真相 or 发生了什么. Cite at least two supporting paragraphs when the source has two or more paragraphs. Cover text must contain exactly "
            "three distinct Chinese lines, ordered top, middle, bottom: conflict or surprise, article mechanism, then stakes. "
            "Before returning, silently check that every question and cover line is specific to the cited paragraphs."
        ),
        "article": source_display_metadata(article),
        "content_units": [{
            "content_unit_id": item["content_unit_id"],
            "episode_order": item["episode_order"],
            "is_lead_story": item["is_lead_story"],
            "kind": item["kind"],
            "metadata": item["metadata"],
            "paragraph_ids": item["paragraph_ids"],
        } for item in units],
        "guide_question_policy": {
            "question_1_content_unit_id": lead["content_unit_id"],
            "question_2_content_unit_id": secondary["content_unit_id"],
        },
        "paragraphs": [{
            "source_paragraph_id": paragraph_id(item),
            "content_unit_id": item["content_unit_id"],
            "source_text": item["text"],
        } for item in paragraphs],
        "draft_schema": {
            "source_sha256": article["source_sha256"],
            "display": {"headline_zh": "", "subtitle_zh": "", "source_paragraph_ids": []},
            "content_unit_display": [{
                "content_unit_id": item["content_unit_id"],
                "headline_zh": "",
                "subtitle_zh": "",
                "source_paragraph_ids": [],
            } for item in units],
            "guide_questions": [
                {"question": "", "translation_zh": "", "source_paragraph_ids": []},
                {"question": "", "translation_zh": "", "source_paragraph_ids": []},
            ],
            "publication": {"title_body_zh": "", "description_zh": "", "source_paragraph_ids": []},
            "cover_text": [
                {"position": "top", "text": "", "source_paragraph_ids": []},
                {"position": "middle", "text": "", "source_paragraph_ids": []},
                {"position": "bottom", "text": "", "source_paragraph_ids": []},
            ],
        },
    }


def validate_draft(
    article: dict[str, Any], paragraphs: list[dict[str, Any]], draft: Any, publication_variant: str = "en-zh"
) -> dict[str, Any]:
    if not isinstance(draft, dict):
        raise EditorialAssetsError("Editorial draft must be a JSON object.")
    if draft.get("source_sha256") != article["source_sha256"]:
        raise EditorialAssetsError("Editorial draft does not belong to the selected article source.")
    known = {paragraph_id(item) for item in paragraphs}
    paragraph_units = {paragraph_id(item): item["content_unit_id"] for item in paragraphs}
    units = article["content_units"]
    unit_ids = [item["content_unit_id"] for item in units]
    lead = next(item for item in units if item["is_lead_story"])
    non_leads = [item for item in units if not item["is_lead_story"]]
    secondary = min(non_leads, key=lambda item: (item.get("editorial_priority", item["source_order"]), item["source_order"])) if non_leads else lead
    display = draft.get("display")
    if not isinstance(display, dict):
        raise EditorialAssetsError("Editorial draft needs display.")
    display_metadata = source_display_metadata(article)
    result_display = {
        "headline_zh": bounded_chinese_text(display.get("headline_zh"), "display.headline_zh", 64),
        "subtitle_zh": (
            bounded_chinese_text(display.get("subtitle_zh"), "display.subtitle_zh", 96)
            if display_metadata.get("subtitle") else bounded_chinese_text(display.get("subtitle_zh"), "display.subtitle_zh", 96, optional=True)
        ),
        "source_paragraph_ids": source_ids(display.get("source_paragraph_ids"), known, "display"),
    }
    raw_unit_display = draft.get("content_unit_display")
    if raw_unit_display is None and article["content_mode"] == "article":
        raw_unit_display = [{"content_unit_id": unit_ids[0], **result_display}]
    if not isinstance(raw_unit_display, list) or len(raw_unit_display) != len(units):
        raise EditorialAssetsError("Editorial draft needs one content_unit_display entry per content unit.")
    result_unit_display = []
    for expected_unit, item in zip(units, raw_unit_display):
        if not isinstance(item, dict) or item.get("content_unit_id") != expected_unit["content_unit_id"]:
            raise EditorialAssetsError("content_unit_display entries must follow episode order.")
        ids = source_ids(item.get("source_paragraph_ids"), known, f"content_unit_display.{expected_unit['content_unit_id']}")
        if any(paragraph_units[source_id] != expected_unit["content_unit_id"] for source_id in ids):
            raise EditorialAssetsError("A content-unit display translation may only cite its own paragraphs.")
        result_unit_display.append({
            "content_unit_id": expected_unit["content_unit_id"],
            "headline_zh": bounded_chinese_text(item.get("headline_zh"), f"content_unit_display.{expected_unit['content_unit_id']}.headline_zh", 64),
            "subtitle_zh": bounded_chinese_text(item.get("subtitle_zh"), f"content_unit_display.{expected_unit['content_unit_id']}.subtitle_zh", 96, optional=True),
            "source_paragraph_ids": ids,
        })
    questions = draft.get("guide_questions")
    if not isinstance(questions, list) or len(questions) != 2:
        raise EditorialAssetsError("Editorial draft needs exactly two guide questions.")
    result_questions = []
    question_signatures: list[set[str]] = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict) or not isinstance(question.get("question"), str) or not re.search(r"[A-Za-z]", question["question"]):
            raise EditorialAssetsError(f"Guide question {index} needs non-empty English question text.")
        question_text = question["question"].strip()
        if not question_text.endswith("?"):
            raise EditorialAssetsError(f"Guide question {index} must end with a question mark.")
        words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", question_text)
        if not 8 <= len(words) <= 22:
            raise EditorialAssetsError(f"Guide question {index} must contain 8 to 22 English words.")
        signature = {word.casefold() for word in words if len(word) > 2}
        question_signatures.append(signature)
        result_questions.append({
            "question": question_text,
            "translation_zh": bounded_chinese_text(question.get("translation_zh"), f"Guide question {index} translation_zh", 64),
            "source_paragraph_ids": source_ids(question.get("source_paragraph_ids"), known, f"Guide question {index}"),
        })
    expected_question_units = (lead["content_unit_id"], secondary["content_unit_id"])
    for index, (question, expected_unit_id) in enumerate(zip(result_questions, expected_question_units), start=1):
        if any(paragraph_units[source_id] != expected_unit_id for source_id in question["source_paragraph_ids"]):
            raise EditorialAssetsError(f"Guide question {index} must cite only its assigned content unit.")
    if len(question_signatures) == 2:
        overlap = len(question_signatures[0] & question_signatures[1])
        union = len(question_signatures[0] | question_signatures[1])
        if union and overlap / union >= 0.7:
            raise EditorialAssetsError("Guide questions must use distinct editorial angles.")
    publication = draft.get("publication")
    if not isinstance(publication, dict):
        raise EditorialAssetsError("Editorial draft needs publication.")
    title_suffix = publication_suffix(publication_variant)
    title_prefix = publication_title_prefix(article)
    lead_display = next(item for item in result_unit_display if item["content_unit_id"] == lead["content_unit_id"])
    title_body = validate_publication_title_body(
        publication_title_body(publication, title_suffix, title_prefix), lead_display["headline_zh"]
    )
    publication_source_ids = source_ids(publication.get("source_paragraph_ids"), known, "publication")
    if len(known) >= 2 and len(publication_source_ids) < 2:
        raise EditorialAssetsError("Publication title and description must cite at least two supporting source paragraphs.")
    if article["content_mode"] == "short_issue" and {paragraph_units[source_id] for source_id in publication_source_ids} != set(unit_ids):
        raise EditorialAssetsError("Short-issue publication copy must cite every content unit.")
    result_publication = {
        "title_body_zh": title_body,
        "title_zh": f"{title_prefix}{title_body}{title_suffix}",
        "description_zh": all_chinese_text(publication.get("description_zh"), "publication.description_zh"),
        "source_paragraph_ids": publication_source_ids,
    }
    lines = draft.get("cover_text")
    if not isinstance(lines, list) or len(lines) != 3:
        raise EditorialAssetsError("Cover text needs exactly three lines.")
    expected_positions = ("top", "middle", "bottom")
    result_lines = []
    for expected, line in zip(expected_positions, lines):
        if not isinstance(line, dict) or line.get("position") != expected:
            raise EditorialAssetsError("Cover text positions must be top, middle, bottom in order.")
        text = all_chinese_text(line.get("text"), f"cover_text.{expected}")
        if not 4 <= len(text) <= 18:
            raise EditorialAssetsError(f"cover_text.{expected} must contain 4 to 18 Chinese characters.")
        result_lines.append({
            "position": expected,
            "text": text,
            "source_paragraph_ids": source_ids(line.get("source_paragraph_ids"), known, f"cover_text.{expected}"),
        })
    if len({line["text"] for line in result_lines}) != 3:
        raise EditorialAssetsError("Cover text lines must be distinct.")
    return {"display": result_display, "content_unit_display": result_unit_display, "guide_questions": result_questions, "publication": result_publication, "cover_text": result_lines}


def tsv_lines(value: str) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in csv.DictReader(value.splitlines(), delimiter="\t"):
        text = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf", "-1"))
        except ValueError:
            confidence = -1
        if not text or confidence < 0:
            continue
        key = tuple(row.get(field, "") for field in ("page_num", "block_num", "par_num", "line_num"))
        try:
            groups[key].append({"text": text, "confidence": confidence, "left": int(row["left"]), "top": int(row["top"]), "width": int(row["width"]), "height": int(row["height"])})
        except (KeyError, ValueError):
            continue
    lines = []
    for words in groups.values():
        left = min(word["left"] for word in words)
        top = min(word["top"] for word in words)
        right = max(word["left"] + word["width"] for word in words)
        bottom = max(word["top"] + word["height"] for word in words)
        lines.append({
            "text": " ".join(word["text"] for word in words),
            "confidence": round(sum(word["confidence"] for word in words) / len(words), 1),
            "bounding_box": {"left": left, "top": top, "width": right - left, "height": bottom - top},
        })
    return lines


def normalise_cover_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).replace("—", "–").upper()


def extract_cover_issue_info(cover_path: Path) -> dict[str, Any]:
    """Extract only cover identity fields with local Tesseract; never invoke a model."""
    if not cover_path.is_file():
        raise EditorialAssetsError(f"Issue cover is missing: {cover_path}")
    if not shutil.which("tesseract"):
        return {"status": "unavailable", "extraction_method": "local_tesseract_sparse_text", "source_page": 1, "fields": [], "reason": "tesseract is not installed"}
    result = subprocess.run(
        ["tesseract", str(cover_path), "stdout", "--psm", "11", "-l", "eng", "tsv"],
        check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {"status": "unavailable", "extraction_method": "local_tesseract_sparse_text", "source_page": 1, "fields": [], "reason": "local OCR failed"}
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in tsv_lines(result.stdout):
        if line["confidence"] < MIN_OCR_CONFIDENCE:
            continue
        for kind, pattern in (("issue_number", SERIAL_RE), ("cover_date", DATE_RE)):
            for match in pattern.finditer(line["text"]):
                candidates[kind].append({
                    "field_type": kind,
                    "display_text": match.group(0),
                    "normalized_value": normalise_cover_value(match.group(0)),
                    "confidence": line["confidence"],
                    "bounding_box": line["bounding_box"],
                })
    fields = []
    for kind in ("issue_number", "cover_date"):
        unique = {item["normalized_value"]: item for item in candidates[kind]}
        if len(unique) == 1:
            fields.append(next(iter(unique.values())))
        elif len(unique) > 1:
            return {"status": "unavailable", "extraction_method": "local_tesseract_sparse_text", "source_page": 1, "fields": [], "reason": f"multiple {kind} candidates"}
    if not fields:
        return {"status": "unavailable", "extraction_method": "local_tesseract_sparse_text", "source_page": 1, "fields": [], "reason": "no confident cover identity field found"}
    return {"status": "complete", "extraction_method": "local_tesseract_sparse_text", "source_page": 1, "fields": fields}


def rect_overlap(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    """Return whether two x/y/width/height boxes intersect."""
    left_x, left_y, left_width, left_height = left
    right_x, right_y, right_width, right_height = right
    return not (
        left_x + left_width <= right_x
        or right_x + right_width <= left_x
        or left_y + left_height <= right_y
        or right_y + right_height <= left_y
    )


def publish_markdown(assets: dict[str, Any]) -> str:
    issue = assets["front_page_info"]
    issue_lines = [f"- {field['field_type']}: {field['display_text']}" for field in issue.get("fields", [])]
    if not issue_lines:
        issue_lines = [f"- {issue.get('reason', 'unavailable')}" ]
    covers = assets["cover_art"]["outputs"]
    cover_lines = []
    for ratio in ("16:9", "9:16"):
        output = covers.get(ratio)
        if isinstance(output, dict) and output.get("state") == "complete":
            label = "横屏" if ratio == "16:9" else "竖屏"
            cover_lines.append(f"- {label}：{output['path']}")
    if not cover_lines:
        cover_lines.append("- 成片渲染完成后由 publication-video-cover 从视频 0 秒首帧生成")
    return "\n".join([
        "# 发布素材", "", "## 标题", "", assets["publication"]["title_zh"], "", "## 简介", "", assets["publication"]["description_zh"], "", "## 首页刊号类信息", "",
        *issue_lines, "", "## 发布封面", "", *cover_lines, "",
    ])


def register_production(production_path: Path, assets_path: Path) -> None:
    production = read_json(production_path)
    root = production_path.parent.resolve()
    try:
        relative = str(assets_path.resolve().relative_to(root))
    except ValueError as error:
        raise EditorialAssetsError("editorial-assets.json must remain in the production package.") from error
    production.setdefault("artifacts", {})["editorial_assets"] = relative
    production.setdefault("artifact_hashes", {})["editorial_assets"] = sha256_file(assets_path)
    publish_copy_path = (assets_path.parent / "publish-copy.md").resolve()
    if publish_copy_path.is_file():
        production["artifacts"]["publish_copy"] = str(publish_copy_path.relative_to(root))
        production.setdefault("artifact_hashes", {})["publish_copy"] = sha256_file(publish_copy_path)
    assets = read_json(assets_path)
    cover_outputs = assets.get("cover_art", {}).get("outputs", {}) if isinstance(assets.get("cover_art"), dict) else {}
    for key in list(production["artifacts"]):
        if key.startswith("cover_"):
            production["artifacts"].pop(key, None)
            production.setdefault("artifact_hashes", {}).pop(key, None)
    for ratio, output in cover_outputs.items() if isinstance(cover_outputs, dict) else []:
        key = f"cover_{ratio.replace(':', 'x')}"
        if not isinstance(output, dict) or output.get("state") != "complete" or output.get("source_kind") != "finished_video_frame":
            production["artifacts"].pop(key, None)
            production.setdefault("artifact_hashes", {}).pop(key, None)
            continue
        reference = output.get("path")
        if not isinstance(reference, str):
            production["artifacts"].pop(key, None)
            production.setdefault("artifact_hashes", {}).pop(key, None)
            continue
        cover_path = (root / reference).resolve()
        if not cover_path.is_file():
            production["artifacts"].pop(key, None)
            production.setdefault("artifact_hashes", {}).pop(key, None)
            continue
        production["artifacts"][key] = str(cover_path.relative_to(root))
        production.setdefault("artifact_hashes", {})[key] = sha256_file(cover_path)
    write_json(production_path, production)


def finalise(
    article_path: Path,
    draft_path: Path,
    assets_path: Path,
    production_path: Path | None = None,
    publication_variant: str = "en-zh",
    aspect_ratios: list[str] | None = None,
) -> dict[str, Any]:
    article, paragraphs = load_article(article_path)
    payload = validate_draft(article, paragraphs, read_json(draft_path), publication_variant)
    root = assets_path.parent.resolve()
    if aspect_ratios is None and production_path:
        production = read_json(production_path)
        request = production.get("workflow", {}).get("request", {})
        configured = request.get("aspect_ratios") or production.get("output", {}).get("aspect_ratios")
        if isinstance(configured, list) and configured:
            aspect_ratios = configured
    selected_ratios = list(dict.fromkeys(aspect_ratios or ["16:9", "9:16"]))
    if not selected_ratios or any(ratio not in {"16:9", "9:16"} for ratio in selected_ratios):
        raise EditorialAssetsError("Editorial cover aspect ratios must be 16:9 and/or 9:16.")
    cover_outputs = {
        ratio: {
            "state": "pending_video_frame",
            "path": str((root / "release" / "covers" / f"cover-{ratio.replace(':', 'x')}.png").relative_to(root).as_posix()),
            "template": "video_frame_cover",
            "source_kind": "pending_video_frame",
            "frame_time_seconds": 0.0,
        }
        for ratio in selected_ratios
    }
    cover_ref = article.get("front_page", {}).get("file")
    if not isinstance(cover_ref, str):
        raise EditorialAssetsError("article.json needs front_page.file.")
    issue_info = extract_cover_issue_info((root / cover_ref).resolve())
    assets = {
        "format": EDITORIAL_FORMAT,
        "schema_version": "2.0.0",
        "publication_variant": publication_variant,
        "article_source_sha256": article["source_sha256"],
        "content_mode": article["content_mode"],
        "source_publication": article["publication"],
        "translation_policy": "meaning_first_chinese_transcreation",
        "display": payload["display"],
        "content_unit_display": payload["content_unit_display"],
        "guide_questions": payload["guide_questions"],
        "front_page_info": issue_info,
        "publication": payload["publication"],
        "cover_art": {
            "text_lines": payload["cover_text"],
            "state": "pending_video_frame",
            "background_source": {
                "mode": "finished_video_frame",
                "frame_time_seconds": 0.0,
                "selection_priority": ["en-zh", "en", "zh-CN"],
            },
            "style_version": "reference-pop-v1",
            "style": {
                "font_family": "Noto Sans SC",
                "font_weight": "bold",
                "line_1_fill": "#FFE500",
                "line_2_fill": "#12D9FF",
                "line_3_fill": "#12D9FF",
                "outline": "#000000",
                "stroke_fill": "#000000",
                "font_preference": "Noto Sans SC",
                "no_background_panel": True,
            },
            "outputs": cover_outputs,
        },
    }
    write_json(assets_path, assets)
    markdown_path = assets_path.parent / "publish-copy.md"
    markdown_path.write_text(publish_markdown(assets), encoding="utf-8")
    if production_path:
        register_production(production_path, assets_path)
    return assets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser("editorial-request", help="Print a compact, source-linked request for AI editorial copy.")
    request.add_argument("article", type=Path)
    request.add_argument("--variant", choices=tuple(sorted(TITLE_SUFFIXES)), default="en-zh")
    finalise_parser = commands.add_parser("finalize-editorial", help="Validate an AI editorial draft and write publishing assets.")
    finalise_parser.add_argument("article", type=Path)
    finalise_parser.add_argument("draft", type=Path)
    finalise_parser.add_argument("assets", type=Path)
    finalise_parser.add_argument("--production", type=Path)
    finalise_parser.add_argument("--aspect-ratio", choices=("16:9", "9:16"), action="append", dest="aspect_ratios")
    finalise_parser.add_argument("--variant", choices=tuple(sorted(TITLE_SUFFIXES)), default="en-zh")
    validate = commands.add_parser("validate-editorial", help="Validate an editorial draft without writing assets.")
    validate.add_argument("article", type=Path)
    validate.add_argument("draft", type=Path)
    validate.add_argument("--variant", choices=tuple(sorted(TITLE_SUFFIXES)), default="en-zh")
    args = parser.parse_args()
    try:
        if args.command == "editorial-request":
            print(json.dumps(editorial_request(args.article, args.variant), ensure_ascii=False, indent=2))
        elif args.command == "validate-editorial":
            article, paragraphs = load_article(args.article)
            validate_draft(article, paragraphs, read_json(args.draft), args.variant)
            print(json.dumps({"status": "valid"}, ensure_ascii=False))
        else:
            assets = finalise(args.article, args.draft, args.assets, args.production, args.variant, args.aspect_ratios)
            print(json.dumps({"status": "created", "editorial_assets": str(args.assets.resolve()), "cover_outputs": assets["cover_art"]["outputs"]}, ensure_ascii=False))
    except (OSError, EditorialAssetsError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
