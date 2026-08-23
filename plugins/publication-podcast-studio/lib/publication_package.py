"""Shared normalization and validation for verified publication source packages."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


CONTENT_MODES = {"article", "short_issue"}
PUBLICATION_KINDS = {"magazine", "newspaper", "other_periodical"}
SOURCE_SCHEMA_VERSION = "2.0.0"
LEGACY_PUBLICATION = {
    "name": "The Economist",
    "display_name": "经济学人",
    "kind": "magazine",
    "issue_date": None,
    "issue_number": None,
}


class PublicationPackageError(ValueError):
    """The verified publication package violates the shared source contract."""


def paragraph_id(paragraph: dict[str, Any]) -> str:
    value = paragraph.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    order = paragraph.get("order")
    if not isinstance(order, int) or order <= 0:
        raise PublicationPackageError("Every source paragraph needs a positive order or stable id.")
    return f"p{order:03d}"


def publication_display_name(publication: dict[str, Any]) -> str:
    value = publication.get("display_name") or publication.get("name")
    if not isinstance(value, str) or not value.strip():
        raise PublicationPackageError("Publication metadata needs a confirmed display name.")
    return value.strip()


def _normalise_publication(payload: dict[str, Any], legacy: bool) -> dict[str, Any]:
    raw = payload.get("publication")
    if raw is None and legacy:
        return deepcopy(LEGACY_PUBLICATION)
    if not isinstance(raw, dict):
        raise PublicationPackageError("Source package needs publication metadata.")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise PublicationPackageError("publication.name must be confirmed before production.")
    kind = raw.get("kind", "other_periodical")
    if kind not in PUBLICATION_KINDS:
        raise PublicationPackageError(f"Unsupported publication kind: {kind!r}.")
    display_name = raw.get("display_name") or name
    if not isinstance(display_name, str) or not display_name.strip():
        raise PublicationPackageError("publication.display_name must be non-empty when present.")
    result = {
        "name": name.strip(),
        "display_name": display_name.strip(),
        "kind": kind,
        "issue_date": raw.get("issue_date"),
        "issue_number": raw.get("issue_number"),
    }
    for field in ("issue_date", "issue_number"):
        if result[field] is not None and (not isinstance(result[field], str) or not result[field].strip()):
            raise PublicationPackageError(f"publication.{field} must be null or non-empty text.")
        if isinstance(result[field], str):
            result[field] = result[field].strip()
    return result


def _legacy_content_unit(payload: dict[str, Any], paragraphs: list[dict[str, Any]], assets: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = payload.get("article")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("headline"), str) or not metadata["headline"].strip():
        metadata = {"section": None, "kicker": None, "headline": "Verified source", "subtitle": None, "byline": None, "dateline": None}
    return {
        "content_unit_id": "item-001",
        "source_order": 1,
        "editorial_priority": 1,
        "episode_order": 1,
        "is_lead_story": True,
        "kind": "article",
        "metadata": deepcopy(metadata),
        "page_numbers": list(payload.get("article_pages", [])),
        "paragraph_ids": [paragraph_id(item) for item in paragraphs],
        "asset_ids": [str(item.get("id")) for item in assets if item.get("id")],
        "boundary_evidence": {},
    }


def _normalise_content_units(
    payload: dict[str, Any],
    mode: str,
    paragraphs: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    legacy: bool,
) -> list[dict[str, Any]]:
    raw_units = payload.get("content_units")
    if raw_units is None and legacy:
        raw_units = [_legacy_content_unit(payload, paragraphs, assets)]
    if not isinstance(raw_units, list) or not raw_units:
        raise PublicationPackageError("Source package needs one or more content_units.")
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_units, start=1):
        if not isinstance(raw, dict):
            raise PublicationPackageError("Every content unit must be an object.")
        unit_id = raw.get("content_unit_id") or raw.get("id")
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise PublicationPackageError("Every content unit needs content_unit_id.")
        metadata = raw.get("metadata")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("headline"), str) or not metadata["headline"].strip():
            raise PublicationPackageError(f"Content unit {unit_id!r} needs metadata.headline.")
        source_order = raw.get("source_order", index)
        editorial_priority = raw.get("editorial_priority", source_order)
        episode_order = raw.get("episode_order", index)
        if not isinstance(source_order, int) or source_order <= 0 or not isinstance(editorial_priority, int) or editorial_priority <= 0 or not isinstance(episode_order, int) or episode_order <= 0:
            raise PublicationPackageError("Content unit source_order, editorial_priority and episode_order must be positive integers.")
        result.append({
            "content_unit_id": unit_id.strip(),
            "source_order": source_order,
            "editorial_priority": editorial_priority,
            "episode_order": episode_order,
            "is_lead_story": bool(raw.get("is_lead_story", mode == "article" and index == 1)),
            "kind": str(raw.get("kind") or "article"),
            "metadata": deepcopy(metadata),
            "page_numbers": list(raw.get("page_numbers", [])),
            "paragraph_ids": list(raw.get("paragraph_ids", [])),
            "asset_ids": list(raw.get("asset_ids", [])),
            "boundary_evidence": deepcopy(raw.get("boundary_evidence", {})),
        })
    ids = [item["content_unit_id"] for item in result]
    if len(ids) != len(set(ids)):
        raise PublicationPackageError("Content unit ids must be unique.")
    if sorted(item["source_order"] for item in result) != list(range(1, len(result) + 1)):
        raise PublicationPackageError("Content unit source_order must be consecutive.")
    if sorted(item["editorial_priority"] for item in result) != list(range(1, len(result) + 1)):
        raise PublicationPackageError("Content unit editorial_priority must be consecutive.")
    if sorted(item["episode_order"] for item in result) != list(range(1, len(result) + 1)):
        raise PublicationPackageError("Content unit episode_order must be consecutive.")
    leads = [item for item in result if item["is_lead_story"]]
    if len(leads) != 1:
        raise PublicationPackageError("Source package must identify exactly one lead story.")
    if leads[0]["editorial_priority"] != 1:
        raise PublicationPackageError("The lead story must have editorial_priority=1.")
    if mode == "short_issue" and leads[0]["episode_order"] != 1:
        raise PublicationPackageError("The short-issue lead story must have episode_order=1.")
    if mode == "article" and len(result) != 1:
        raise PublicationPackageError("article mode must contain exactly one content unit.")
    return sorted(result, key=lambda item: item["episode_order"])


def normalise_source_package(
    payload: dict[str, Any], require_verified: bool = True, require_front_page: bool = False,
) -> dict[str, Any]:
    """Return a v2 view of a new or historical article.json package."""
    if not isinstance(payload, dict):
        raise PublicationPackageError("Source package must be a JSON object.")
    if require_verified and payload.get("review_status") != "verified":
        raise PublicationPackageError("Source package must have review_status=verified.")
    legacy = "content_mode" not in payload and "content_units" not in payload
    mode = payload.get("content_mode", "article")
    if mode not in CONTENT_MODES:
        raise PublicationPackageError(f"Unsupported content mode: {mode!r}.")
    source_language = payload.get("source_language", "en")
    if source_language != "en":
        raise PublicationPackageError("Publication Podcast Studio v1 accepts English source publications only.")
    raw_paragraphs = payload.get("paragraphs")
    if not isinstance(raw_paragraphs, list) or not raw_paragraphs:
        raise PublicationPackageError("Source package needs verified paragraphs.")
    raw_assets = payload.get("assets", [])
    if not isinstance(raw_assets, list):
        raise PublicationPackageError("Source package assets must be an array.")
    units = _normalise_content_units(payload, mode, raw_paragraphs, raw_assets, legacy)
    unit_ids = {item["content_unit_id"] for item in units}
    legacy_unit_id = units[0]["content_unit_id"]
    paragraphs: list[dict[str, Any]] = []
    seen_paragraph_ids: set[str] = set()
    for raw in raw_paragraphs:
        if not isinstance(raw, dict):
            raise PublicationPackageError("Every source paragraph must be an object.")
        item = deepcopy(raw)
        item["id"] = paragraph_id(item)
        item["content_unit_id"] = item.get("content_unit_id") or legacy_unit_id
        if item["id"] in seen_paragraph_ids:
            raise PublicationPackageError("Source paragraph ids must be unique.")
        if item["content_unit_id"] not in unit_ids:
            raise PublicationPackageError(f"Paragraph {item['id']} references an unknown content unit.")
        seen_paragraph_ids.add(item["id"])
        paragraphs.append(item)
    if [item.get("order") for item in paragraphs] != list(range(1, len(paragraphs) + 1)):
        raise PublicationPackageError("Source paragraph order must be consecutive.")
    assets: list[dict[str, Any]] = []
    for raw in raw_assets:
        if not isinstance(raw, dict):
            raise PublicationPackageError("Every source asset must be an object.")
        item = deepcopy(raw)
        item["content_unit_id"] = item.get("content_unit_id") or legacy_unit_id
        if item["content_unit_id"] not in unit_ids:
            raise PublicationPackageError("Source asset references an unknown content unit.")
        assets.append(item)
    paragraph_ids_by_unit = {
        unit_id: [item["id"] for item in paragraphs if item["content_unit_id"] == unit_id]
        for unit_id in unit_ids
    }
    for unit in units:
        expected = paragraph_ids_by_unit[unit["content_unit_id"]]
        if not expected:
            raise PublicationPackageError(f"Content unit {unit['content_unit_id']} has no verified paragraphs.")
        declared = unit["paragraph_ids"]
        if declared and declared != expected:
            raise PublicationPackageError(f"Content unit {unit['content_unit_id']} paragraph_ids do not match source order.")
        unit["paragraph_ids"] = expected
        unit["asset_ids"] = [
            str(item.get("id")) for item in assets
            if item.get("id") and item["content_unit_id"] == unit["content_unit_id"]
        ]
    front_page = payload.get("front_page") or payload.get("issue_cover")
    if require_front_page and (not isinstance(front_page, dict) or not isinstance(front_page.get("file"), str)):
        raise PublicationPackageError("Source package needs a verified front-page asset.")
    if front_page is None:
        front_page = {}
    result = deepcopy(payload)
    result.update({
        "schema_version": str(payload.get("schema_version") or ("1.0.0" if legacy else SOURCE_SCHEMA_VERSION)),
        "content_mode": mode,
        "source_language": source_language,
        "publication": _normalise_publication(payload, legacy),
        "front_page": deepcopy(front_page),
        "content_units": units,
        "paragraphs": paragraphs,
        "assets": assets,
    })
    return result


def load_source_package(
    path: Path, require_verified: bool = True, require_front_page: bool = False,
) -> dict[str, Any]:
    import json

    return normalise_source_package(
        json.loads(path.read_text(encoding="utf-8")),
        require_verified=require_verified,
        require_front_page=require_front_page,
    )


def content_unit_for_paragraph(source: dict[str, Any], source_paragraph_id: str) -> dict[str, Any]:
    paragraph = next((item for item in source["paragraphs"] if item["id"] == source_paragraph_id), None)
    if paragraph is None:
        raise PublicationPackageError(f"Unknown source paragraph: {source_paragraph_id}.")
    unit_id = paragraph["content_unit_id"]
    return next(item for item in source["content_units"] if item["content_unit_id"] == unit_id)


def source_display_metadata(source: dict[str, Any]) -> dict[str, Any]:
    """Metadata for an episode opener without pretending a short issue is one article."""
    if source["content_mode"] == "article":
        return deepcopy(source["content_units"][0]["metadata"])
    publication = source["publication"]
    issue_label = publication.get("issue_date") or publication.get("issue_number") or "Issue briefing"
    return {
        "section": publication.get("kind", "publication").replace("_", " ").title(),
        "kicker": publication_display_name(publication),
        "headline": str(issue_label),
        "subtitle": "Full edition briefing",
        "byline": None,
        "dateline": None,
    }
