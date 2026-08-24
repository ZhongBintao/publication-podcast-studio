#!/usr/bin/env python3
"""Prepare and package verified content from an English publication PDF.

Codex vision performs scope and text reconstruction. This script creates bounded
page bundles for one selected article or a complete short issue, preserves raw
PDF evidence, validates structured model results, and writes the source package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pdfplumber
from PIL import Image
from pypdf import PdfReader


METADATA_FIELDS = ("section", "kicker", "headline", "subtitle", "byline", "dateline")
CONTENT_MODES = {"article", "short_issue"}
PUBLICATION_KINDS = {"magazine", "newspaper", "other_periodical"}
SOURCE_SCHEMA_VERSION = "2.0.0"
SCOPE_DPI = 180
CONTEXT_DPI = 120
READING_DPI = 220
FRONT_PAGE_DPI = 300
CROP_MARGIN_POINTS = 12
# At this coverage, a 120dpi context page plus 220dpi crops is still cheaper
# than a 220dpi full page, with margin for image-encoding overhead.
MAX_SPLIT_READING_COVERAGE = 0.65


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def article_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(value)).strip("-")[:80] or "article"


def page_hint(value: str | None) -> tuple[int, int] | None:
    numbers = [int(item) for item in re.findall(r"\d+", value or "")]
    return (numbers[0], numbers[-1]) if numbers else None


def publication_metadata(args: argparse.Namespace) -> dict[str, Any]:
    name = str(getattr(args, "publication_name", "") or "").strip()
    if not name:
        raise ValueError("A confirmed --publication-name is required.")
    display_name = str(getattr(args, "publication_display_name", "") or name).strip()
    kind = getattr(args, "publication_kind", "other_periodical")
    if kind not in PUBLICATION_KINDS:
        raise ValueError(f"Unsupported publication kind: {kind!r}.")
    return {
        "name": name,
        "display_name": display_name,
        "kind": kind,
        "issue_date": str(getattr(args, "issue_date", "") or "").strip() or None,
        "issue_number": str(getattr(args, "issue_number", "") or "").strip() or None,
    }


def estimated_source_words(index: dict[str, Any]) -> int:
    return sum(len(re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)?", page.get("text", ""))) for page in index["pages"])


def render_page(pdf_path: Path, number: int, dpi: int, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = output.with_suffix("")
    subprocess.run(
        ["pdftoppm", "-f", str(number), "-l", str(number), "-r", str(dpi), "-png", "-singlefile", str(pdf_path), str(prefix)],
        check=True, capture_output=True, text=True,
    )
    return prefix.with_suffix(".png")


def clip_bbox(bbox: list[float], width: float, height: float) -> list[float]:
    x0, y0, x1, y1 = bbox
    return [max(0, x0), max(0, y0), min(width, x1), min(height, y1)]


def expanded_bbox(bbox: list[float], width: float, height: float, margin: float = CROP_MARGIN_POINTS) -> list[float]:
    return clip_bbox([bbox[0] - margin, bbox[1] - margin, bbox[2] + margin, bbox[3] + margin], width, height)


def crop_rendered_page(image_path: Path, width: float, height: float, bbox: list[float], destination: Path) -> None:
    with Image.open(image_path) as image:
        x0, y0, x1, y1 = bbox
        crop = image.crop((
            round(x0 / width * image.width), round(y0 / height * image.height),
            round(x1 / width * image.width), round(y1 / height * image.height),
        ))
        destination.parent.mkdir(parents=True, exist_ok=True)
        crop.save(destination)


def make_native_index(pdf_path: Path) -> dict[str, Any]:
    reader = PdfReader(str(pdf_path))
    pages: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            words = [
                {"text": word["text"], "x0": round(word["x0"], 2), "top": round(word["top"], 2), "x1": round(word["x1"], 2), "bottom": round(word["bottom"], 2)}
                for word in page.extract_words(use_text_flow=False)
            ]
            pages.append({
                "number": number,
                "width": page.width,
                "height": page.height,
                "text": " ".join(word["text"] for word in words),
                "words": words,
                "image_objects": [{"id": f"p{number}-image-{i}", "name": image.name} for i, image in enumerate(reader.pages[number - 1].images)],
                "image_boxes": [{"id": f"p{number}-bbox-{i}", "bbox": [round(image["x0"], 2), round(image["top"], 2), round(image["x1"], 2), round(image["bottom"], 2)]} for i, image in enumerate(page.images)],
            })
    return {"mode": "native", "pages": pages}


def make_ocr_index(pdf_path: Path, cache_dir: Path) -> dict[str, Any]:
    if not shutil.which("tesseract"):
        raise RuntimeError("This PDF has no usable text layer. Install Tesseract with English language data, then rerun.")
    with pdfplumber.open(pdf_path) as pdf:
        dimensions = [(page.width, page.height) for page in pdf.pages]
    pages = []
    for number, (width, height) in enumerate(dimensions, start=1):
        png = render_page(pdf_path, number, 300, cache_dir / "ocr" / f"page-{number}")
        result = subprocess.run(["tesseract", str(png), "stdout", "tsv", "-l", "eng"], check=True, capture_output=True, text=True)
        with Image.open(png) as image:
            sx, sy = width / image.width, height / image.height
        words = []
        for row in result.stdout.splitlines()[1:]:
            parts = row.split("\t")
            if len(parts) != 12 or parts[0] != "5" or not parts[11].strip():
                continue
            x, y, w, h = map(float, parts[6:10])
            words.append({"text": parts[11], "x0": round(x * sx, 2), "top": round(y * sy, 2), "x1": round((x + w) * sx, 2), "bottom": round((y + h) * sy, 2)})
        pages.append({"number": number, "width": width, "height": height, "text": " ".join(word["text"] for word in words), "words": words, "image_objects": [], "image_boxes": []})
    return {"mode": "ocr", "pages": pages}


def build_index(pdf_path: Path, cache_root: Path, refresh: bool) -> tuple[dict[str, Any], Path]:
    fingerprint = sha256(pdf_path)
    path = cache_root / fingerprint / "index.json"
    if path.exists() and not refresh:
        return read_json(path), path
    index = make_native_index(pdf_path)
    if sum(len(page["words"]) for page in index["pages"]) < max(20, len(index["pages"]) * 2):
        index = make_ocr_index(pdf_path, cache_root / fingerprint)
    index.update({"source_pdf": str(pdf_path.resolve()), "source_sha256": fingerprint})
    write_json(path, index)
    return index, path


def score_page(page: dict[str, Any], query: str, hint: tuple[int, int] | None) -> tuple[float, list[str]]:
    text, target = normalize(page["text"]), normalize(query)
    terms = [term for term in target.split() if len(term) > 2]
    score, evidence = 0.0, []
    if target and target in text:
        score += 70
        evidence.append("exact phrase")
    if len(target.replace(" ", "")) > 7 and target.replace(" ", "") in text.replace(" ", ""):
        score += 30
        evidence.append("exact phrase across PDF spacing")
    hits = sum(term in text for term in terms)
    if terms and hits:
        score += 25 * hits / len(terms)
        evidence.append(f"{hits}/{len(terms)} distinctive terms")
    if hint and hint[0] <= page["number"] <= hint[1]:
        score += 80
        evidence.append("within page hint")
    if page["number"] <= 6 and "contents" in text:
        score -= 50
        evidence.append("contents penalty")
    return score, evidence


def locate_candidates(index: dict[str, Any], query: str, hint: tuple[int, int] | None) -> list[dict[str, Any]]:
    hits = []
    for page in index["pages"]:
        score, evidence = score_page(page, query, hint)
        if score > 10:
            full_term_match = any((match := re.fullmatch(r"(\d+)/(\d+) distinctive terms", item)) and match.group(1) == match.group(2) for item in evidence)
            signature = "exact phrase" in evidence or "exact phrase across PDF spacing" in evidence
            hits.append({"page": page["number"], "score": round(score, 2), "evidence": evidence, "preview": re.sub(r"\s+", " ", page["text"])[:420], "signature": signature, "connector": signature or full_term_match})
    hits = [candidate for candidate in hits if "contents penalty" not in candidate["evidence"]] or hits
    groups: list[list[dict[str, Any]]] = []
    for hit in sorted(hits, key=lambda item: item["page"]):
        if groups and hit["connector"] and groups[-1][-1]["connector"] and hit["page"] == groups[-1][-1]["page"] + 1:
            groups[-1].append(hit)
        else:
            groups.append([hit])
    candidates = []
    for group in groups:
        best = max(group, key=lambda item: item["score"])
        candidates.append({
            "page": group[0]["page"], "page_end": group[-1]["page"], "matched_pages": [item["page"] for item in group],
            "score": round(best["score"] + min(12, 3 * len(group)), 2),
            "evidence": best["evidence"] + ([f"repeated signature on {len(group)} adjacent pages"] if len(group) > 1 else []), "preview": best["preview"],
        })
    return sorted(candidates, key=lambda candidate: (-candidate["score"], candidate["page"]))[:3]


def article_scope_template(index: dict[str, Any], candidate: dict[str, Any], publication: dict[str, Any]) -> dict[str, Any]:
    page = index["pages"][candidate["page"] - 1]
    return {
        "source_sha256": index["source_sha256"],
        "content_mode": "article",
        "publication": publication,
        "review_status": "needs_scope",
        "selected_candidate_page": candidate["page"],
        "article": {field: "" if field == "headline" else None for field in METADATA_FIELDS},
        "article_pages": [],
        "text_regions": [{"id": "replace-me", "page": candidate["page"], "order": 1, "bbox": [0, 0, page["width"], page["height"]], "role": "article_body"}],
        "excluded_regions": [],
        "assets": [],
        "boundary_evidence": {"start_reason": "", "end_reason": ""},
        "uncertain_spans": [],
        "reviewer_notes": "",
    }


def scope_template(index: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Historical helper retained for direct callers and legacy tests."""
    return article_scope_template(index, candidate, {
        "name": "The Economist", "display_name": "经济学人", "kind": "magazine",
        "issue_date": None, "issue_number": None,
    })


def short_issue_scope_template(index: dict[str, Any], publication: dict[str, Any]) -> dict[str, Any]:
    page = index["pages"][0]
    page_numbers = [item["number"] for item in index["pages"]]
    return {
        "source_sha256": index["source_sha256"],
        "content_mode": "short_issue",
        "publication": publication,
        "review_status": "needs_scope",
        "article_pages": page_numbers,
        "content_units": [{
            "content_unit_id": "replace-me",
            "source_order": 1,
            "editorial_priority": 1,
            "is_lead_story": True,
            "kind": "article",
            "metadata": {field: "" if field == "headline" else None for field in METADATA_FIELDS},
            "page_numbers": [1],
            "text_region_ids": ["replace-me"],
            "asset_ids": [],
            "boundary_evidence": {"start_reason": "", "end_reason": ""},
        }],
        "text_regions": [{
            "id": "replace-me", "page": 1, "order": 1,
            "bbox": [0, 0, page["width"], page["height"]],
            "role": "editorial_body", "content_unit_id": "replace-me",
        }],
        "excluded_regions": [],
        "assets": [],
        "page_audit": [
            {"page": number, "status": "needs_review", "included_region_ids": [], "excluded_region_ids": [], "notes": ""}
            for number in page_numbers
        ],
        "lead_selection_evidence": "",
        "uncertain_spans": [],
        "reviewer_notes": "",
    }


def review_page_numbers(candidates: list[dict[str, Any]], page_count: int) -> list[int]:
    """Include every locally matched page plus one visual boundary page either side."""
    numbers: set[int] = set()
    for candidate in candidates:
        matched = candidate["matched_pages"]
        numbers.update(matched)
        numbers.add(max(1, matched[0] - 1))
        numbers.add(min(page_count, matched[-1] + 1))
    return sorted(numbers)


def preflight(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    work_dir = Path(args.work_dir)
    index, index_path = build_index(pdf_path, work_dir / "cache", args.refresh_index)
    front_page = render_page(pdf_path, 1, SCOPE_DPI, work_dir / "preflight" / "front-page").resolve()
    words = estimated_source_words(index)
    payload = {
        "status": "needs_confirmation",
        "source_pdf": str(pdf_path),
        "source_sha256": index["source_sha256"],
        "page_count": len(index["pages"]),
        "extraction_mode": index["mode"],
        "estimated_source_words": words,
        "estimated_english_minutes_at_150_wpm": round(words / 150, 1),
        "front_page_preview": str(front_page),
        "index_path": str(index_path.resolve()),
        "recommended_request": {
            "content_mode": args.content_mode,
            "duration": {
                "mode": "target_cap",
                "target_minutes": 20 if args.content_mode == "short_issue" else 10,
                "max_minutes": 25 if args.content_mode == "short_issue" else 12,
            },
            "video_timing": {
                "opening_seconds": 8.0,
                "asset_dwell_target_seconds": 20.0,
                "final_duration": "audio_locked",
            },
        },
    }
    path = work_dir / "preflight-report.json"
    write_json(path, payload)
    print(json.dumps({**payload, "preflight_report": str(path.resolve())}, ensure_ascii=False, indent=2))
    return 0


def prepare(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    work_dir = Path(args.work_dir)
    index, index_path = build_index(pdf_path, work_dir / "cache", args.refresh_index)
    mode = args.content_mode
    publication = publication_metadata(args)
    if mode == "article":
        if not str(args.query or "").strip():
            raise ValueError("article mode requires --query.")
        candidates = locate_candidates(index, args.query, page_hint(args.page_hint))
        status = "not_found" if not candidates else ("candidate_ready" if len(candidates) == 1 or candidates[0]["score"] - candidates[1]["score"] >= 15 else "needs_user_selection")
        review_candidates = candidates if status == "needs_user_selection" else candidates[:1]
        review_numbers = review_page_numbers(review_candidates, len(index["pages"]))
        template = article_scope_template(index, candidates[0], publication) if candidates else None
    else:
        candidates = []
        status = "scope_ready"
        review_numbers = [page["number"] for page in index["pages"]]
        template = short_issue_scope_template(index, publication)
    bundle_dir = work_dir / "review-bundle"
    review_pages = [{"page": number, "file": str(render_page(pdf_path, number, SCOPE_DPI, bundle_dir / f"page-{number}").resolve()), "dpi": SCOPE_DPI} for number in review_numbers]
    manifest = {
        "status": status, "source_pdf": str(pdf_path), "source_sha256": index["source_sha256"], "extraction_mode": index["mode"],
        "content_mode": mode, "publication": publication,
        "query": args.query, "page_hint": args.page_hint, "index_path": str(index_path.resolve()), "output_dir": str(Path(args.output_dir).resolve()),
        "candidates": candidates, "review_pages": review_pages, "scope_template": template,
    }
    path = work_dir / "review-manifest.json"
    write_json(path, manifest)
    print(json.dumps({"status": status, "manifest": str(path.resolve()), "content_mode": mode, "candidates": candidates}, ensure_ascii=False, indent=2))
    return 0


def valid_bbox(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 4 and all(isinstance(item, (int, float)) for item in value) and value[0] < value[2] and value[1] < value[3]


def canonical_scope_units(scope: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    if mode == "article":
        metadata = scope.get("article")
        if not isinstance(metadata, dict) or not str(metadata.get("headline") or "").strip():
            raise ValueError("Article scope needs a headline.")
        return [{
            "content_unit_id": "item-001",
            "source_order": 1,
            "editorial_priority": 1,
            "episode_order": 1,
            "is_lead_story": True,
            "kind": "article",
            "metadata": metadata,
            "page_numbers": list(scope.get("article_pages", [])),
            "text_region_ids": [region.get("id") for region in scope.get("text_regions", [])],
            "asset_ids": [asset.get("id") for asset in scope.get("assets", [])],
            "boundary_evidence": scope.get("boundary_evidence", {}),
        }]
    units = scope.get("content_units")
    if not isinstance(units, list) or not units:
        raise ValueError("Short-issue scope needs content_units.")
    ids: set[str] = set()
    source_orders: list[int] = []
    editorial_priorities: list[int] = []
    result: list[dict[str, Any]] = []
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError("Every content unit must be an object.")
        unit_id = unit.get("content_unit_id")
        metadata = unit.get("metadata")
        if not isinstance(unit_id, str) or not unit_id.strip() or unit_id in ids:
            raise ValueError("Content unit ids must be unique non-empty strings.")
        if not isinstance(metadata, dict) or not str(metadata.get("headline") or "").strip():
            raise ValueError(f"Content unit {unit_id!r} needs metadata.headline.")
        source_order = unit.get("source_order")
        editorial_priority = unit.get("editorial_priority", source_order)
        if not isinstance(source_order, int) or source_order <= 0:
            raise ValueError("Content unit source_order must be a positive integer.")
        if not isinstance(editorial_priority, int) or editorial_priority <= 0:
            raise ValueError("Content unit editorial_priority must be a positive integer.")
        boundary = unit.get("boundary_evidence", {})
        if not boundary.get("start_reason") or not boundary.get("end_reason"):
            raise ValueError(f"Content unit {unit_id!r} needs visual start and end evidence.")
        ids.add(unit_id)
        source_orders.append(source_order)
        editorial_priorities.append(editorial_priority)
        result.append({**unit, "content_unit_id": unit_id.strip(), "editorial_priority": editorial_priority})
    if sorted(source_orders) != list(range(1, len(result) + 1)):
        raise ValueError("Content unit source_order must be consecutive.")
    if sorted(editorial_priorities) != list(range(1, len(result) + 1)):
        raise ValueError("Content unit editorial_priority must be consecutive.")
    leads = [unit for unit in result if unit.get("is_lead_story")]
    if len(leads) != 1:
        raise ValueError("Short-issue scope must identify exactly one lead story.")
    if leads[0]["editorial_priority"] != 1:
        raise ValueError("The lead story must have editorial_priority=1.")
    if not str(scope.get("lead_selection_evidence") or "").strip():
        raise ValueError("Short-issue scope needs lead-selection evidence.")
    ordered = [leads[0], *sorted((unit for unit in result if unit is not leads[0]), key=lambda item: item["source_order"])]
    return [{**unit, "episode_order": index} for index, unit in enumerate(ordered, start=1)]


def validate_scope(scope: dict[str, Any], manifest: dict[str, Any], index: dict[str, Any]) -> None:
    if scope.get("source_sha256") != manifest["source_sha256"]:
        raise ValueError("Scope belongs to a different source PDF.")
    if scope.get("review_status") != "verified" or scope.get("uncertain_spans"):
        raise ValueError("Scope must be visually verified with no uncertain spans.")
    mode = manifest.get("content_mode", "article")
    if scope.get("content_mode", mode) != mode or mode not in CONTENT_MODES:
        raise ValueError("Scope content mode does not match the confirmed request.")
    if scope.get("publication") != manifest.get("publication"):
        raise ValueError("Scope publication metadata does not match the confirmed request.")
    if not scope.get("article_pages"):
        raise ValueError("Scope needs publication pages.")
    if not all(isinstance(page, int) and 1 <= page <= len(index["pages"]) for page in scope["article_pages"]):
        raise ValueError("Scope contains an invalid publication page.")
    if mode == "short_issue" and scope["article_pages"] != list(range(1, len(index["pages"]) + 1)):
        raise ValueError("Short-issue mode must audit every PDF page in source order.")
    units = canonical_scope_units(scope, mode)
    unit_ids = {unit["content_unit_id"] for unit in units}
    regions = scope.get("text_regions", [])
    if not regions or len({region.get("id") for region in regions}) != len(regions):
        raise ValueError("Scope needs uniquely identified text regions.")
    for region in [*regions, *scope.get("excluded_regions", []), *scope.get("assets", [])]:
        if region.get("page") not in scope["article_pages"] or not valid_bbox(region.get("bbox")):
            raise ValueError("Every scope region must have a publication page and valid bounding box.")
    if mode == "article":
        boundary = scope.get("boundary_evidence", {})
        if not boundary.get("start_reason") or not boundary.get("end_reason"):
            raise ValueError("Article scope needs visual start and end evidence.")
        return
    for region in regions:
        if region.get("content_unit_id") not in unit_ids:
            raise ValueError("Every short-issue text region must belong to one content unit.")
    for asset in scope.get("assets", []):
        if asset.get("content_unit_id") not in unit_ids:
            raise ValueError("Every short-issue asset must belong to one content unit.")
    for unit in units:
        actual = [region["id"] for region in regions if region.get("content_unit_id") == unit["content_unit_id"]]
        if not actual or unit.get("text_region_ids") != actual:
            raise ValueError(f"Content unit {unit['content_unit_id']} text_region_ids must match reading order.")
    audits = scope.get("page_audit")
    if not isinstance(audits, list) or [item.get("page") for item in audits if isinstance(item, dict)] != scope["article_pages"]:
        raise ValueError("Short-issue scope needs one ordered page audit per PDF page.")
    included_ids = {region["id"] for region in regions}
    excluded_ids = {region.get("id") for region in scope.get("excluded_regions", [])}
    audited_included: list[str] = []
    audited_excluded: list[str] = []
    for audit in audits:
        if audit.get("status") != "reviewed":
            raise ValueError("Every short-issue page audit must be reviewed.")
        if not set(audit.get("included_region_ids", [])) <= included_ids or not set(audit.get("excluded_region_ids", [])) <= excluded_ids:
            raise ValueError("Page audit references an unknown included or excluded region.")
        audited_included.extend(audit.get("included_region_ids", []))
        audited_excluded.extend(audit.get("excluded_region_ids", []))
    if set(audited_included) != included_ids or len(audited_included) != len(included_ids) or set(audited_excluded) != excluded_ids or len(audited_excluded) != len(excluded_ids):
        raise ValueError("Every included and excluded short-issue region must appear in exactly one page audit.")


def word_inside(word: dict[str, Any], bbox: list[float]) -> bool:
    return bbox[0] <= (word["x0"] + word["x1"]) / 2 <= bbox[2] and bbox[1] <= (word["top"] + word["bottom"]) / 2 <= bbox[3]


def raw_text(index: dict[str, Any], regions: list[dict[str, Any]]) -> str:
    chunks = []
    for region in sorted(regions, key=lambda item: item["order"]):
        page = index["pages"][region["page"] - 1]
        words = sorted((word for word in page["words"] if word_inside(word, region["bbox"])), key=lambda item: (item["top"], item["x0"]))
        chunks.append(f"## {region['id']} (PDF page {region['page']})\n" + " ".join(word["text"] for word in words))
    return "\n\n".join(chunks) + "\n"


def page_visual_plan(index: dict[str, Any], scope: dict[str, Any]) -> list[dict[str, Any]]:
    """Choose full-page reading or context-plus-crops without increasing baseline pixels."""
    regions_by_page: dict[int, list[dict[str, Any]]] = {}
    for region in scope["text_regions"]:
        regions_by_page.setdefault(region["page"], []).append(region)
    plan = []
    for number in scope["article_pages"]:
        page = index["pages"][number - 1]
        width, height = page["width"], page["height"]
        regions = []
        for region in sorted(regions_by_page.get(number, []), key=lambda item: item["order"]):
            crop_bbox = expanded_bbox(region["bbox"], width, height)
            regions.append({"id": region["id"], "order": region["order"], "bbox": crop_bbox})
        crop_area = sum((item["bbox"][2] - item["bbox"][0]) * (item["bbox"][3] - item["bbox"][1]) for item in regions)
        coverage = crop_area / (width * height) if width and height else 1.0
        mode = "split_regions" if regions and coverage <= MAX_SPLIT_READING_COVERAGE else "full_page"
        baseline_pixels = round(width * height * (READING_DPI / 72) ** 2)
        planned_pixels = round(width * height * ((CONTEXT_DPI / 72) ** 2 + coverage * (READING_DPI / 72) ** 2)) if mode == "split_regions" else baseline_pixels
        plan.append({
            "page": number, "mode": mode, "regions": regions, "crop_coverage": round(coverage, 4),
            "baseline_reading_pixels": baseline_pixels, "planned_reading_pixels": planned_pixels,
        })
    return plan


def materialise_visual_plan(pdf_path: Path, output: Path, index: dict[str, Any], plan: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    context_pages, region_images, page_visuals = [], [], []
    with tempfile.TemporaryDirectory(prefix="article-subtract-reading-") as temporary:
        temporary_path = Path(temporary)
        for item in plan:
            number = item["page"]
            page = index["pages"][number - 1]
            if item["mode"] == "full_page":
                file = render_page(pdf_path, number, READING_DPI, output / "pages" / f"page-{number}").resolve()
                context_pages.append({"page": number, "file": str(file), "dpi": READING_DPI, "role": "high_resolution_full_page"})
                page_visuals.append({**item, "context_file": str(file), "context_dpi": READING_DPI})
                continue
            context_file = render_page(pdf_path, number, CONTEXT_DPI, output / "pages" / f"context-page-{number}").resolve()
            reading_file = render_page(pdf_path, number, READING_DPI, temporary_path / f"page-{number}")
            context_pages.append({"page": number, "file": str(context_file), "dpi": CONTEXT_DPI, "role": "layout_context"})
            page_visuals.append({**item, "context_file": str(context_file), "context_dpi": CONTEXT_DPI})
            for region in item["regions"]:
                target = output / "regions" / f"{region['id']}.png"
                crop_rendered_page(reading_file, page["width"], page["height"], region["bbox"], target)
                region_images.append({"id": region["id"], "page": number, "order": region["order"], "bbox": region["bbox"], "file": str(target.resolve()), "dpi": READING_DPI, "margin_points": CROP_MARGIN_POINTS})
    return context_pages, region_images, page_visuals


def materialise_front_page(pdf_path: Path, output: Path) -> dict[str, Any]:
    """Render the PDF's first page once as the publication-level source asset.

    The front page is not content-unit media and deliberately does not pass
    through the editorial-asset approval loop.
    """
    file = render_page(pdf_path, 1, FRONT_PAGE_DPI, output / "assets" / "front-page").resolve()
    return {
        "file": str(file.relative_to(output.resolve())),
        "source_page": 1,
        "dpi": FRONT_PAGE_DPI,
        "extraction_method": "rendered_pdf_page",
    }


def materialise_issue_cover(pdf_path: Path, output: Path) -> dict[str, Any]:
    """Historical alias retained for direct callers."""
    return materialise_front_page(pdf_path, output)


def assemble(args: argparse.Namespace) -> int:
    manifest, scope = read_json(Path(args.manifest)), read_json(Path(args.scope))
    index = read_json(Path(manifest["index_path"]))
    validate_scope(scope, manifest, index)
    mode = manifest.get("content_mode", "article")
    units = canonical_scope_units(scope, mode)
    source_stem = article_slug(Path(manifest["source_pdf"]).stem)
    package_label = units[0]["metadata"]["headline"] if mode == "article" else f"{manifest['publication']['name']}-short-issue"
    output = Path(manifest["output_dir"]) / f"{source_stem}-{article_slug(package_label)}"
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "scope.json", scope)
    (output / "source.raw.txt").write_text(raw_text(index, scope["text_regions"]))
    plan = page_visual_plan(index, scope)
    context_pages, region_images, page_visuals = materialise_visual_plan(Path(manifest["source_pdf"]), output, index, plan)
    front_page = materialise_front_page(Path(manifest["source_pdf"]), output)
    catalog = [asset for page in index["pages"] if page["number"] in scope["article_pages"] for asset in page["image_objects"]]
    request = {
        "source_pdf": manifest["source_pdf"], "source_sha256": manifest["source_sha256"], "scope_path": str((output / "scope.json").resolve()),
        "output_dir": str(output.resolve()), "content_mode": mode, "publication": manifest["publication"],
        "article_pages": context_pages, "content_units": units,
        "text_regions": scope["text_regions"], "excluded_regions": scope.get("excluded_regions", []), "asset_catalog": catalog,
        "context_pages": context_pages, "region_images": region_images, "page_visuals": page_visuals,
        "front_page": front_page,
        "visual_budget": {"baseline_reading_pixels": sum(item["baseline_reading_pixels"] for item in plan), "planned_reading_pixels": sum(item["planned_reading_pixels"] for item in plan)},
        "approved_assets": scope.get("assets", []),
        "model_extraction_template": {
            "source_sha256": manifest["source_sha256"], "content_mode": mode, "review_status": "needs_review",
            "paragraphs": [{
                "order": 1, "content_unit_id": units[0]["content_unit_id"], "text": "",
                "source_region_ids": [scope["text_regions"][0]["id"]],
            }],
            "assets": [], "corrections": [], "excluded_regions": scope.get("excluded_regions", []), "uncertain_spans": [], "reviewer_notes": "",
        },
    }
    if mode == "article":
        request["article"] = units[0]["metadata"]
        request["model_extraction_template"]["article"] = units[0]["metadata"]
    request_path = output / "extraction-request.json"
    write_json(request_path, request)
    print(json.dumps({"status": "ready_for_model", "output_dir": str(output.resolve()), "extraction_request": str(request_path.resolve()), "article_pages": scope["article_pages"], "visual_budget": request["visual_budget"]}, ensure_ascii=False, indent=2))
    return 0


def validate_escalation(escalation: dict[str, Any], request: dict[str, Any]) -> list[int]:
    if escalation.get("source_sha256") != request["source_sha256"]:
        raise ValueError("Visual escalation belongs to a different PDF.")
    if escalation.get("status") != "needs_high_res_context":
        raise ValueError("Visual escalation must request high-resolution context.")
    pages = escalation.get("pages", [])
    known_pages = {page["page"] for page in request["context_pages"]}
    split_pages = {page["page"] for page in request["page_visuals"] if page["mode"] == "split_regions"}
    if not pages or len(pages) != len(set(pages)) or not set(pages) <= known_pages:
        raise ValueError("Visual escalation needs unique, known article pages.")
    if not set(pages) <= split_pages:
        raise ValueError("Only split-region pages may request high-resolution context.")
    reasons = escalation.get("reasons", [])
    if not reasons or {reason.get("page") for reason in reasons} != set(pages) or any(not reason.get("reason", "").strip() for reason in reasons):
        raise ValueError("Visual escalation needs a reason for every requested page.")
    return pages


def expand(args: argparse.Namespace) -> int:
    request, escalation = read_json(Path(args.request)), read_json(Path(args.escalation))
    pages = validate_escalation(escalation, request)
    output = Path(request["output_dir"])
    existing = {page["page"] for page in request.get("high_res_context_pages", [])}
    additions = []
    for number in pages:
        if number not in existing:
            file = render_page(Path(request["source_pdf"]), number, READING_DPI, output / "pages" / f"high-page-{number}").resolve()
            additions.append({"page": number, "file": str(file), "dpi": READING_DPI, "role": "escalated_full_page"})
    expanded = {**request, "high_res_context_pages": [*request.get("high_res_context_pages", []), *additions], "visual_escalation": escalation}
    path = output / "extraction-request-expanded.json"
    write_json(path, expanded)
    print(json.dumps({"status": "ready_for_model", "extraction_request": str(path.resolve()), "escalated_pages": pages}, ensure_ascii=False, indent=2))
    return 0


def validate_model(model: dict[str, Any], request: dict[str, Any]) -> None:
    if model.get("source_sha256") != request["source_sha256"]:
        raise ValueError("Model extraction belongs to a different PDF.")
    if model.get("review_status") != "verified" or model.get("uncertain_spans"):
        raise ValueError("Model extraction must be verified with no uncertain spans.")
    mode = request.get("content_mode", "article")
    if model.get("content_mode", mode) != mode:
        raise ValueError("Model extraction content mode does not match the verified scope.")
    if mode == "article" and model.get("article", {}).get("headline") != request["article"]["headline"]:
        raise ValueError("Model headline must match the verified scope.")
    units = request.get("content_units") or [{"content_unit_id": "item-001"}]
    unit_ids = {unit["content_unit_id"] for unit in units}
    regions_by_id = {region["id"]: region for region in request["text_regions"]}
    known = set(regions_by_id)
    paragraphs = model.get("paragraphs", [])
    if not paragraphs or [paragraph.get("order") for paragraph in paragraphs] != list(range(1, len(paragraphs) + 1)):
        raise ValueError("Paragraphs must be non-empty and consecutively ordered.")
    for paragraph in paragraphs:
        source_ids = paragraph.get("source_region_ids", [])
        unit_id = paragraph.get("content_unit_id") or ("item-001" if mode == "article" else None)
        if not paragraph.get("text", "").strip() or not source_ids or not set(source_ids) <= known:
            raise ValueError("Every paragraph needs text and known source region ids.")
        if unit_id not in unit_ids:
            raise ValueError("Every paragraph must belong to a known content unit.")
        if mode == "short_issue" and any(regions_by_id[source_id].get("content_unit_id") != unit_id for source_id in source_ids):
            raise ValueError("A short-issue paragraph may only use regions from its own content unit.")
    body = "\n\n".join(paragraph["text"] for paragraph in paragraphs)
    if "■" in body:
        raise ValueError("Formal text contains an excluded marker or decoration.")
    covered_units = {paragraph.get("content_unit_id") or "item-001" for paragraph in paragraphs}
    if covered_units != unit_ids:
        raise ValueError("Model extraction must include at least one paragraph for every content unit.")
    for correction in model.get("corrections", []):
        if not correction.get("type") or not set(correction.get("source_region_ids", [])) <= known:
            raise ValueError("Every correction needs a type and known source region ids.")
    approved_assets = {asset.get("id"): asset for asset in request.get("approved_assets", [])}
    if any(asset.get("id") not in approved_assets for asset in model.get("assets", [])):
        raise ValueError("Every model asset must be approved in the visual scope.")
    if mode == "short_issue":
        for asset in model.get("assets", []):
            approved = approved_assets[asset["id"]]
            if (asset.get("content_unit_id") or approved.get("content_unit_id")) != approved.get("content_unit_id"):
                raise ValueError("A short-issue asset cannot change its verified content-unit attribution.")


def crop_region(pdf_path: Path, asset: dict[str, Any], destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="article-subtract-") as temporary:
        image_path = render_page(pdf_path, asset["page"], 300, Path(temporary) / "page")
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[asset["page"] - 1]
            crop_rendered_page(image_path, page.width, page.height, asset["bbox"], destination)


def extract_pdf_object(pdf_path: Path, asset: dict[str, Any], destination: Path) -> bool:
    name = asset.get("pdf_image_name")
    if not name:
        return False
    for image in PdfReader(str(pdf_path)).pages[asset["page"] - 1].images:
        if image.name == name:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(image.data)
            return True
    return False


def source_markdown(request: dict[str, Any], paragraphs: list[dict[str, Any]]) -> str:
    units = request["content_units"]
    if request["content_mode"] == "article":
        metadata = units[0]["metadata"]
        lines = [f"# {metadata['headline']}", ""]
        for field in ("section", "kicker", "subtitle", "byline", "dateline"):
            if metadata.get(field):
                lines.append(f"{field}: {metadata[field]}")
        lines.extend(("", "\n\n".join(item["text"].strip() for item in paragraphs), ""))
        return "\n".join(lines)
    publication = request["publication"]
    issue_label = publication.get("issue_date") or publication.get("issue_number") or "Short issue"
    lines = [f"# {publication['display_name']} — {issue_label}", ""]
    for unit in sorted(units, key=lambda item: item["episode_order"]):
        metadata = unit["metadata"]
        lines.extend((f"## {metadata['headline']}", ""))
        for field in ("section", "kicker", "subtitle", "byline", "dateline"):
            if metadata.get(field):
                lines.append(f"{field}: {metadata[field]}")
        unit_paragraphs = [item["text"].strip() for item in paragraphs if item["content_unit_id"] == unit["content_unit_id"]]
        lines.extend(("", "\n\n".join(unit_paragraphs), ""))
    return "\n".join(lines)


def finalize(args: argparse.Namespace) -> int:
    request, model = read_json(Path(args.request)), read_json(Path(args.model_extraction))
    validate_model(model, request)
    output, scope = Path(request["output_dir"]), read_json(Path(request["scope_path"]))
    write_json(output / "model-extraction.json", model)
    mode = request.get("content_mode", "article")
    units = request.get("content_units") or canonical_scope_units(scope, mode)
    paragraphs = []
    for index, raw in enumerate(model["paragraphs"], start=1):
        paragraphs.append({
            **raw,
            "id": raw.get("id") or f"p{index:03d}",
            "content_unit_id": raw.get("content_unit_id") or "item-001",
        })
    (output / "source.md").write_text(source_markdown({**request, "content_units": units}, paragraphs))
    assets = []
    approved_assets = {asset["id"]: asset for asset in request.get("approved_assets", [])}
    for number, model_asset in enumerate(model.get("assets", []), start=1):
        asset = {**approved_assets[model_asset["id"]], **model_asset}
        if asset.get("page") not in scope["article_pages"] or not valid_bbox(asset.get("bbox")):
            raise ValueError("Every asset needs an article page and valid bbox.")
        object_suffix = Path(asset.get("pdf_image_name", "")).suffix.lower()
        name = f"assets/{number:02d}-{article_slug(asset.get('kind', 'image'))}{object_suffix or '.png'}"
        target = output / name
        method = "pdf_object" if extract_pdf_object(Path(request["source_pdf"]), asset, target) else "page_crop"
        if method == "page_crop":
            target = target.with_suffix(".png")
            crop_region(Path(request["source_pdf"]), asset, target)
            name = str(Path(name).with_suffix(".png"))
        kind = str(asset.get("kind", "")).casefold()
        role = asset.get("role") if asset.get("role") in {"article_image", "article_chart"} else (
            "article_chart" if kind in {"chart", "map", "table", "diagram", "infographic"} else "article_image"
        )
        assets.append({
            **asset,
            "content_unit_id": asset.get("content_unit_id") or "item-001",
            "role": role,
            "file": name,
            "extraction_method": method,
        })
    final_units = []
    for unit in units:
        unit_id = unit["content_unit_id"]
        final_units.append({
            **unit,
            "paragraph_ids": [item["id"] for item in paragraphs if item["content_unit_id"] == unit_id],
            "asset_ids": [str(item["id"]) for item in assets if item.get("id") and item["content_unit_id"] == unit_id],
        })
    package = {
        "schema_version": SOURCE_SCHEMA_VERSION,
        "content_mode": mode,
        "source_language": "en",
        "publication": request["publication"],
        "source_pdf": request["source_pdf"], "source_sha256": request["source_sha256"], "review_status": "verified",
        "article_pages": scope["article_pages"], "text_regions": request["text_regions"], "excluded_regions": model.get("excluded_regions", scope.get("excluded_regions", [])),
        "content_units": final_units,
        "paragraphs": paragraphs, "corrections": model.get("corrections", []), "assets": assets, "reviewer_notes": model.get("reviewer_notes", ""),
        "front_page": request["front_page"],
    }
    if mode == "article":
        package["article"] = final_units[0]["metadata"]
    write_json(output / "article.json", package)
    label = final_units[0]["metadata"]["headline"] if mode == "article" else request["publication"]["display_name"]
    body = "\n\n".join(paragraph["text"].strip() for paragraph in paragraphs) + "\n"
    preview = f"# Verification preview\n\n- Content mode: {mode}\n- Publication: {request['publication']['display_name']}\n- Lead: {label}\n- Pages: {scope['article_pages']}\n- Content units: {len(final_units)}\n- Paragraphs: {len(paragraphs)}\n- Assets: {len(assets)}\n- Corrections: {len(model.get('corrections', []))}\n\n## Text preview\n\n{body[:1800]}"
    (output / "preview.md").write_text(preview)
    print(json.dumps({"status": "verified", "content_mode": mode, "output_dir": str(output.resolve()), "content_units": len(final_units), "paragraphs": len(paragraphs), "assets": len(assets)}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight_parser = commands.add_parser("preflight")
    preflight_parser.add_argument("pdf")
    preflight_parser.add_argument("--content-mode", choices=tuple(sorted(CONTENT_MODES)), required=True)
    preflight_parser.add_argument("--work-dir", default="tmp/publication-content-extract")
    preflight_parser.add_argument("--refresh-index", action="store_true")
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("pdf")
    prepare_parser.add_argument("--content-mode", choices=tuple(sorted(CONTENT_MODES)), required=True)
    prepare_parser.add_argument("--publication-name", required=True)
    prepare_parser.add_argument("--publication-display-name")
    prepare_parser.add_argument("--publication-kind", choices=tuple(sorted(PUBLICATION_KINDS)), required=True)
    prepare_parser.add_argument("--issue-date")
    prepare_parser.add_argument("--issue-number")
    prepare_parser.add_argument("--query")
    prepare_parser.add_argument("--page-hint")
    prepare_parser.add_argument("--work-dir", default="tmp/publication-content-extract")
    prepare_parser.add_argument("--output-dir", default="output/publications")
    prepare_parser.add_argument("--refresh-index", action="store_true")
    assemble_parser = commands.add_parser("assemble")
    assemble_parser.add_argument("manifest")
    assemble_parser.add_argument("scope")
    finalize_parser = commands.add_parser("finalize")
    finalize_parser.add_argument("request")
    finalize_parser.add_argument("model_extraction")
    expand_parser = commands.add_parser("expand")
    expand_parser.add_argument("request")
    expand_parser.add_argument("escalation")
    args = parser.parse_args()
    try:
        return {"preflight": preflight, "prepare": prepare, "assemble": assemble, "expand": expand, "finalize": finalize}[args.command](args)
    except (FileNotFoundError, RuntimeError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
