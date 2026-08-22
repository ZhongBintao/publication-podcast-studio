#!/usr/bin/env python3
"""Create and validate source-linked Chinese Economist podcast scripts."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
ENGLISH_SCRIPT = ROOT / "skills" / "economist-source-to-podcast-script" / "scripts" / "source_to_podcast_script.py"
SPEC = importlib.util.spec_from_file_location("economist_source_to_podcast_script_shared", ENGLISH_SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Unable to load the shared source-to-podcast implementation.")
SHARED = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SHARED
SPEC.loader.exec_module(SHARED)


ALLOWED_FIELDS = {"segment_id", "speaker_id", "kind", "spoken_text", "source_paragraph_ids"}
SPEAKERS = {"primary", "secondary"}
FACTUAL_KINDS = {"verbatim", "sentence_split"}
INTERACTION_KINDS = {"reaction", "prompt"}
BODY_KINDS = FACTUAL_KINDS | INTERACTION_KINDS
WRAPPER_KINDS = {"opening", "closing"}
ALLOWED_KINDS = BODY_KINDS | WRAPPER_KINDS
MAX_SPOKEN_SEGMENT_CHARS = 96
MAX_CAPTION_UNIT_CHARS = 48
MAX_OPENING_CHARS = 120
MAX_CLOSING_CHARS = 120
MAX_CONSECUTIVE_SEGMENTS = 3
MAX_REACTION_CHARS = 24
MAX_PROMPT_CHARS = 36
MIN_BALANCED_CHARS = 400
MIN_WORD_SHARE = 0.40
MAX_WORD_SHARE = 0.60
SPOKEN_BRACKETS = re.compile(r"[()\[\]（）［］]")
REPEATED_CHINESE_PUNCTUATION = re.compile(r"([，。！？；：、])\1+")
COMMA_WRAPPED_LATIN = re.compile(r"，\s*[A-Za-z][A-Za-z0-9.&'’/\-]{1,}\s*，")
COMMA_WRAPPED_AMOUNT = re.compile(
    r"，\s*(?:[$¥￥]\s*)?\d[\d,]*(?:\.\d+)?\s*(?:亿美元|人民币|亿元|万元|美元|元|bn|trn|m|yuan|%)\s*，",
    re.IGNORECASE,
)
TERMINAL_PUNCTUATION = re.compile(r"[。！？.!?][”’'\"）)]*$")
UNLINKED_WRAPPER_FACT = re.compile(r"(?:\d|[%％$¥￥])")


CHINESE_STYLE_INSTRUCTIONS = """You are the Chinese writing stage for a source-bounded, two-host Economist podcast.

Translate and orally adapt each supplied verified English paragraph into natural spoken Chinese. Also write a concise, engaging opening and a natural closing for the programme. The result must sound like two prepared hosts talking through a reported story, not like a literal translation or a written article.

OUTPUT SHAPE

- Return only a JSON object with three arrays: opening, body and closing.
- Opening segments come first, body segments cover every supplied paragraph in order, and closing segments come last.
- Each opening and closing block should be a short coherent passage, normally no more than 120 readable Chinese characters. Use primary for opening and secondary for closing.
- A pure programme-framing segment may have an empty source_paragraph_ids array. If it states an article fact, number, judgment or concrete detail, cite one or more relevant source paragraph IDs.
- Opening and closing may create suspense, ask why the topic matters, bridge into the story, summarize the reported arc, and thank listeners. Do not add unsupported facts, analysis, recommendations, predictions, conclusions or future-episode promises.

SOURCE-BOUNDED ORAL ADAPTATION

- Translate meaning rather than English word order. Reorder clauses, split or merge sentences within one source paragraph, and simplify dense written syntax.
- Preserve every material fact, number, attribution, condition and judgment from the supplied paragraph.
- Never add a fact, explanation, example, prediction, conclusion, causal link, evaluation, host opinion or unsupported transition.
- Use light spoken connectors such as “其实”“问题是”“你会发现”“换句话说” only when they add no claim and do not appear mechanically in every segment.
- Avoid parenthetical notes, comma-wrapped definitions, written noun-plus-explanation fragments, and sentence pieces that are hard to read aloud.

HOST INTERACTION

- Both hosts must deliver substantive source-linked material when the article has enough paragraphs.
- You may use prompt and reaction segments to create natural rhythm. Every one must cite exactly one source paragraph.
- A prompt must be immediately followed by a factual answer from the other host.
- Reactions may acknowledge or frame the current source point, but may not introduce a viewpoint or new information.
- Keep the exchange natural while preserving the source paragraph order. Do not invent a free-form conversation.

TERMS AND MIXED ENGLISH

- Use a stable common Chinese translation when one is genuinely familiar.
- Keep OpenAI, Anthropic, official product names, acronyms and technical names in their original English when no reliable common Chinese name exists.
- Do not write Chinese-plus-English aliases, brackets, pinyin, pronunciation notes, or comma-wrapped abbreviations.
- Keep short English tokens read-as-written and avoid long English clauses inside Chinese speech.

OUTPUT

Every object must contain exactly segment_id, speaker_id, kind, spoken_text and source_paragraph_ids. Use kind opening or closing only in the corresponding wrapper array; use verbatim, sentence_split, reaction or prompt in body. The final spoken_text must be ready for TTS: no SSML, markdown, brackets, dangling punctuation or unsupported host commentary. Keep each factual segment within max_spoken_segment_chars and each captionable sentence within max_caption_unit_chars. Before returning, silently verify complete source coverage, source order, numeric preservation, natural Chinese rhythm, mixed-language readability, wrapper placement and two-host balance."""


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def paragraph_id(paragraph: dict[str, Any]) -> str:
    return SHARED.paragraph_id(paragraph)


def readable_length(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def source_number_tokens(value: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?", value)


def candidate_number_tokens(value: str) -> set[str]:
    return {token.replace(",", "") for token in source_number_tokens(value)}


def number_issues(paragraphs: list[dict[str, Any]], grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for paragraph in paragraphs:
        source_id = paragraph_id(paragraph)
        source_numbers = {token.replace(",", "") for token in source_number_tokens(paragraph["text"])}
        if not source_numbers:
            continue
        spoken_numbers = candidate_number_tokens(" ".join(item["spoken_text"] for item in grouped[source_id]))
        missing = sorted(source_numbers - spoken_numbers)
        if missing:
            issues.append({"source_paragraph_id": source_id, "reason": f"missing source number(s): {', '.join(missing)}"})
    return issues


def spoken_lint_reasons(text: str) -> list[str]:
    reasons: list[str] = []
    if SPOKEN_BRACKETS.search(text):
        reasons.append("parenthetical or bracketed content is not spoken text")
    if REPEATED_CHINESE_PUNCTUATION.search(text):
        reasons.append("repeated Chinese punctuation")
    if COMMA_WRAPPED_LATIN.search(text):
        reasons.append("comma-wrapped Latin abbreviation or name")
    if COMMA_WRAPPED_AMOUNT.search(text):
        reasons.append("comma-wrapped currency conversion")
    if text.endswith((",", "，", ":", "：", ";", "；", "—", "–", "-")):
        reasons.append("dangling spoken punctuation")
    if not TERMINAL_PUNCTUATION.search(text):
        reasons.append("segment must end with complete spoken punctuation")
    return reasons


def chinese_lint_issues(paragraphs: list[dict[str, Any]], grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for paragraph in paragraphs:
        source_id = paragraph_id(paragraph)
        for segment in grouped[source_id]:
            reasons = spoken_lint_reasons(segment["spoken_text"])
            if reasons:
                issues.append({"source_paragraph_id": source_id, "reason": "; ".join(reasons)})
    return issues


def candidate_sections(candidate: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return opening/body/closing while retaining the old body-array input."""
    if isinstance(candidate, list):
        return [], candidate, []
    if not isinstance(candidate, dict) or set(candidate) != {"opening", "body", "closing"}:
        raise ValueError("Chinese candidate must be a JSON object with opening, body and closing arrays.")
    sections = (candidate["opening"], candidate["body"], candidate["closing"])
    if any(not isinstance(section, list) for section in sections):
        raise ValueError("Chinese opening, body and closing sections must be arrays.")
    return sections


def wrapper_issues(
    block: list[dict[str, Any]],
    kind: str,
    paragraphs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Validate the creative wrapper without treating it as article body coverage."""
    if not block:
        raise ValueError(f"Chinese {kind} section must contain at least one segment.")
    known = [paragraph_id(item) for item in paragraphs]
    known_set = set(known)
    known_index = {source_id: position for position, source_id in enumerate(known)}
    source_name_tokens = {
        token for paragraph in paragraphs
        for token in re.findall(r"\b[A-Z][A-Za-z0-9.-]{2,}\b", paragraph["text"])
        if token not in {"The", "This", "That", "After", "First", "Second"}
    }
    expected_speaker = "primary" if kind == "opening" else "secondary"
    max_chars = MAX_OPENING_CHARS if kind == "opening" else MAX_CLOSING_CHARS
    total_chars = 0
    issues: list[dict[str, str]] = []
    for item in block:
        if not isinstance(item, dict) or set(item) != ALLOWED_FIELDS:
            raise ValueError("Every Chinese wrapper segment must contain exactly the five contract fields.")
        if item.get("speaker_id") != expected_speaker:
            raise ValueError(f"Chinese {kind} segments must use the {expected_speaker} speaker.")
        if item.get("kind") != kind:
            raise ValueError(f"Chinese {kind} section contains a different segment kind.")
        text = item.get("spoken_text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Every Chinese {kind} segment needs spoken text.")
        text = text.strip()
        if len(text) > MAX_SPOKEN_SEGMENT_CHARS:
            raise ValueError(f"Chinese spoken segments must be at most {MAX_SPOKEN_SEGMENT_CHARS} characters.")
        total_chars += readable_length(text)
        ids = item.get("source_paragraph_ids")
        if not isinstance(ids, list) or any(not isinstance(source_id, str) or source_id not in known_set for source_id in ids):
            raise ValueError(f"Chinese {kind} segments must reference known source paragraphs or an empty source list.")
        if len(ids) != len(set(ids)):
            raise ValueError(f"Chinese {kind} segments must not repeat source paragraph IDs.")
        positions = [known_index[source_id] for source_id in ids]
        if positions != sorted(positions):
            raise ValueError(f"Chinese {kind} source paragraph IDs must be in source order.")
        reasons = spoken_lint_reasons(text)
        if not ids:
            if UNLINKED_WRAPPER_FACT.search(text):
                reasons.append("unlinked opening/closing text must not contain numbers, percentages or currency")
            if any(re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", text) for token in source_name_tokens):
                reasons.append("unlinked opening/closing text must not introduce source-specific names")
        if reasons:
            issues.append({"section": kind, "reason": "; ".join(reasons)})
    if total_chars > max_chars:
        raise ValueError(f"Chinese {kind} must be at most {max_chars} readable characters.")
    return issues


def request_payload(article: dict[str, Any], paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_sha256": article["source_sha256"],
        "language": "zh-CN",
        "instructions": CHINESE_STYLE_INSTRUCTIONS,
        "speaker_balance": {
            "target_character_share": {speaker: 0.5 for speaker in sorted(SPEAKERS)},
            "acceptable_character_share": {"minimum": MIN_WORD_SHARE, "maximum": MAX_WORD_SHARE},
            "max_consecutive_segments": MAX_CONSECUTIVE_SEGMENTS,
            "interaction_policy": "Source-linked prompt/reaction segments are allowed; unsupported host commentary is forbidden.",
        },
        "framing": {
            "output_shape": "object with opening, body and closing arrays",
            "opening": {
                "speaker_id": "primary",
                "kind": "opening",
                "max_readable_characters": MAX_OPENING_CHARS,
                "source_policy": "Empty source links are allowed only for generic programme framing; article facts require one or more source paragraph IDs.",
            },
            "closing": {
                "speaker_id": "secondary",
                "kind": "closing",
                "max_readable_characters": MAX_CLOSING_CHARS,
                "source_policy": "Empty source links are allowed only for generic programme framing; article facts require one or more source paragraph IDs.",
            },
        },
        "mixed_language_policy": {
            "preserve_exact": "official brand names, product names, acronyms and technical names without a reliable common Chinese equivalent",
            "preserve_examples": ["OpenAI", "Anthropic"],
            "translate_when_common": "stable familiar Chinese names and terms",
            "forbid": ["SSML", "pinyin", "bracketed pronunciation", "Chinese-plus-English aliases", "long English clauses"],
        },
        "paragraphs": [
            {
                "source_paragraph_id": paragraph_id(item),
                "source_speaker_id": SHARED.speaker_for_paragraph(int(item["order"]), len(paragraphs)),
                "partner_speaker_id": SHARED.partner_for_speaker(SHARED.speaker_for_paragraph(int(item["order"]), len(paragraphs))),
                "max_spoken_segment_chars": MAX_SPOKEN_SEGMENT_CHARS,
                "max_caption_unit_chars": MAX_CAPTION_UNIT_CHARS,
                "source_text": SHARED.chinese_translation_source(item["text"]),
            }
            for item in paragraphs
        ],
    }


def grouped_candidate(paragraphs: list[dict[str, Any]], candidate: Any, allowed_ids: set[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(candidate, list) or not candidate:
        raise ValueError("Chinese candidate must be a non-empty JSON array.")
    known = [paragraph_id(item) for item in paragraphs]
    known_set = set(known)
    grouped = {source_id: [] for source_id in known}
    for item in candidate:
        if not isinstance(item, dict) or set(item) != ALLOWED_FIELDS:
            raise ValueError("Every Chinese candidate segment must contain exactly the five contract fields.")
        if item.get("speaker_id") not in SPEAKERS or item.get("kind") not in BODY_KINDS:
            raise ValueError("Chinese candidate contains an unsupported speaker or segment kind.")
        text = item.get("spoken_text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Every Chinese candidate segment needs spoken text.")
        if len(text.strip()) > MAX_SPOKEN_SEGMENT_CHARS:
            raise ValueError(f"Chinese spoken segments must be at most {MAX_SPOKEN_SEGMENT_CHARS} characters.")
        if SPOKEN_BRACKETS.search(text):
            raise ValueError("Chinese spoken text must not contain brackets or pronunciation notes.")
        ids = item.get("source_paragraph_ids")
        if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str) or ids[0] not in known_set:
            raise ValueError("Each Chinese segment must reference exactly one known source paragraph.")
        if allowed_ids is not None and ids[0] not in allowed_ids:
            raise ValueError("Chinese retry patch contains an unrequested source paragraph.")
        grouped[ids[0]].append(item)

    expected = allowed_ids if allowed_ids is not None else known_set
    missing = [source_id for source_id in known if source_id in expected and not grouped[source_id]]
    if missing:
        raise ValueError(f"Chinese candidate is missing source paragraphs: {', '.join(missing)}.")

    for source_id in known:
        if not grouped[source_id]:
            continue
        factual = [item for item in grouped[source_id] if item["kind"] in FACTUAL_KINDS]
        if not factual:
            raise ValueError(f"Chinese source paragraph {source_id} has no factual coverage.")
        for index, item in enumerate(grouped[source_id]):
            text = item["spoken_text"].strip()
            if item["kind"] == "reaction" and readable_length(text) > MAX_REACTION_CHARS:
                raise ValueError(f"Chinese reactions must be at most {MAX_REACTION_CHARS} readable characters.")
            if item["kind"] == "prompt":
                if readable_length(text) > MAX_PROMPT_CHARS:
                    raise ValueError(f"Chinese prompts must be at most {MAX_PROMPT_CHARS} readable characters.")
                if not text.endswith(("？", "?")):
                    raise ValueError("Chinese prompts must end with a question mark.")
                if index + 1 >= len(grouped[source_id]) or grouped[source_id][index + 1]["kind"] not in FACTUAL_KINDS:
                    raise ValueError("A Chinese prompt must be immediately followed by a factual answer.")
                if grouped[source_id][index + 1]["speaker_id"] == item["speaker_id"]:
                    raise ValueError("A Chinese prompt must be answered by the other speaker.")
    return grouped


def validate_sequence(paragraphs: list[dict[str, Any]], grouped: dict[str, list[dict[str, Any]]]) -> None:
    known = [paragraph_id(item) for item in paragraphs]
    completed: list[str] = []
    flattened: list[tuple[str, dict[str, Any]]] = []
    for source_id in known:
        for item in grouped[source_id]:
            flattened.append((source_id, item))
        if grouped[source_id]:
            completed.append(source_id)
    if completed != known:
        raise ValueError("Every source paragraph must be covered once in source order.")
    run: list[dict[str, Any]] = []
    for _, item in flattened:
        if run and run[-1]["speaker_id"] != item["speaker_id"]:
            run = [item]
        else:
            run.append(item)
        if len(run) > MAX_CONSECUTIVE_SEGMENTS:
            raise ValueError(f"Chinese script has more than {MAX_CONSECUTIVE_SEGMENTS} consecutive segments from one speaker.")
    factual = [item for _, item in flattened if item["kind"] in FACTUAL_KINDS]
    if len(factual) >= 2 and {item["speaker_id"] for item in factual} != SPEAKERS:
        raise ValueError("A multi-paragraph Chinese script must give both hosts substantive factual turns.")
    total_chars = sum(readable_length(item["spoken_text"]) for item in factual)
    if total_chars >= MIN_BALANCED_CHARS:
        counts = {speaker: sum(readable_length(item["spoken_text"]) for item in factual if item["speaker_id"] == speaker) for speaker in SPEAKERS}
        shares = {speaker: counts[speaker] / total_chars for speaker in SPEAKERS}
        if any(share < MIN_WORD_SHARE or share > MAX_WORD_SHARE for share in shares.values()):
            raise ValueError("Chinese host character balance failed: " + json.dumps({"counts": counts, "shares": shares}, ensure_ascii=False))


def validate_speaker_runs(items: list[dict[str, Any]]) -> None:
    run: list[dict[str, Any]] = []
    for item in items:
        if run and run[-1]["speaker_id"] != item["speaker_id"]:
            run = [item]
        else:
            run.append(item)
        if len(run) > MAX_CONSECUTIVE_SEGMENTS:
            raise ValueError(f"Chinese script has more than {MAX_CONSECUTIVE_SEGMENTS} consecutive segments from one speaker.")


def flattened_body(paragraphs: list[dict[str, Any]], grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [item for paragraph in paragraphs for item in grouped[paragraph_id(paragraph)]]


def split_final_script(script: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a canonical flat script into wrapper and body sections."""
    if not isinstance(script, list) or not script:
        raise ValueError("Chinese final script must be a non-empty JSON array.")
    for ordinal, item in enumerate(script, start=1):
        if not isinstance(item, dict) or set(item) != ALLOWED_FIELDS:
            raise ValueError("Every Chinese final segment must contain exactly the five contract fields.")
        if item.get("segment_id") != f"zh-CN-{ordinal:03d}":
            raise ValueError("Chinese final segment IDs must be consecutive and language-prefixed.")
        if item.get("kind") not in ALLOWED_KINDS:
            raise ValueError("Chinese final script contains an unsupported segment kind.")

    opening_end = 0
    while opening_end < len(script) and script[opening_end]["kind"] == "opening":
        opening_end += 1
    closing_start = len(script)
    while closing_start > opening_end and script[closing_start - 1]["kind"] == "closing":
        closing_start -= 1
    body = script[opening_end:closing_start]
    if any(item["kind"] in WRAPPER_KINDS for item in body):
        raise ValueError("Chinese opening and closing segments must surround the body.")
    opening = script[:opening_end]
    closing = script[closing_start:]
    if bool(opening) != bool(closing):
        raise ValueError("Chinese scripts with framing must contain both opening and closing sections.")
    return opening, body, closing


def finalize_chinese(paragraphs: list[dict[str, Any]], candidate: Any) -> list[dict[str, Any]]:
    opening, body, closing = candidate_sections(candidate)
    if bool(opening) != bool(closing):
        raise ValueError("Chinese candidates with framing must contain both opening and closing sections.")
    opening_issues: list[dict[str, str]] = []
    closing_issues: list[dict[str, str]] = []
    if opening:
        opening_issues = wrapper_issues(opening, "opening", paragraphs)
        closing_issues = wrapper_issues(closing, "closing", paragraphs)
    grouped = grouped_candidate(paragraphs, body)
    validate_sequence(paragraphs, grouped)
    validate_speaker_runs(opening + flattened_body(paragraphs, grouped) + closing)
    issues = opening_issues + closing_issues + chinese_lint_issues(paragraphs, grouped) + number_issues(paragraphs, grouped)
    if issues:
        raise ValueError("Chinese writing validation failed: " + json.dumps(issues, ensure_ascii=False))
    result: list[dict[str, Any]] = []
    ordinal = 1
    for item in opening:
        result.append({
            "segment_id": f"zh-CN-{ordinal:03d}",
            "speaker_id": item["speaker_id"],
            "kind": item["kind"],
            "spoken_text": item["spoken_text"].strip(),
            "source_paragraph_ids": list(item["source_paragraph_ids"]),
        })
        ordinal += 1
    for paragraph in paragraphs:
        for item in grouped[paragraph_id(paragraph)]:
            result.append({
                "segment_id": f"zh-CN-{ordinal:03d}",
                "speaker_id": item["speaker_id"],
                "kind": item["kind"],
                "spoken_text": item["spoken_text"].strip(),
                "source_paragraph_ids": [paragraph_id(paragraph)],
            })
            ordinal += 1
    for item in closing:
        result.append({
            "segment_id": f"zh-CN-{ordinal:03d}",
            "speaker_id": item["speaker_id"],
            "kind": item["kind"],
            "spoken_text": item["spoken_text"].strip(),
            "source_paragraph_ids": list(item["source_paragraph_ids"]),
        })
        ordinal += 1
    return result


def validate_final_script(article_path: Path, script_path: Path) -> dict[str, Any]:
    article, paragraphs = SHARED.load_article(article_path)
    script = read_json(script_path)
    opening, body, closing = split_final_script(script)
    expected_candidate: Any = script if not opening else {"opening": opening, "body": body, "closing": closing}
    expected = finalize_chinese(paragraphs, expected_candidate)
    if expected != script:
        raise ValueError("The Chinese script is not in canonical finalizer form.")
    characters = sum(len(item["spoken_text"]) for item in script)
    return {"status": "valid", "language": "zh-CN", "segments": len(script), "characters": characters, "estimated_seconds": round((characters / 260) * 60, 1), "source_sha256": article["source_sha256"]}


def retry_sections(script: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Accept canonical flat scripts and older body-only draft arrays."""
    if isinstance(script, list) and any(isinstance(item, dict) and item.get("kind") in WRAPPER_KINDS for item in script):
        return split_final_script(script)
    return candidate_sections(script)


def retry_issues(
    paragraphs: list[dict[str, Any]],
    opening: list[dict[str, Any]],
    body: list[dict[str, Any]],
    closing: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, str]]]:
    grouped = grouped_candidate(paragraphs, body)
    issues = chinese_lint_issues(paragraphs, grouped) + number_issues(paragraphs, grouped)
    if opening:
        issues.extend(wrapper_issues(opening, "opening", paragraphs))
        issues.extend(wrapper_issues(closing, "closing", paragraphs))
    return grouped, issues


def retry_payload(article: dict[str, Any], paragraphs: list[dict[str, Any]], script: Any, attempt: int) -> dict[str, Any]:
    if attempt != 1:
        raise ValueError("Automatic Chinese writing retry limit reached.")
    opening, body, closing = retry_sections(script)
    grouped, issues = retry_issues(paragraphs, opening, body, closing)
    if not issues:
        raise ValueError("Chinese script has no retryable issues.")
    failed_ids = list(dict.fromkeys(item["source_paragraph_id"] for item in issues if "source_paragraph_id" in item))
    failed_sections = list(dict.fromkeys(item["section"] for item in issues if "section" in item))
    source_by_id = {paragraph_id(item): item for item in paragraphs}
    payload: dict[str, Any] = {
        "source_sha256": article["source_sha256"],
        "language": "zh-CN",
        "attempt": attempt,
        "instructions": CHINESE_STYLE_INSTRUCTIONS + "\nRewrite only the requested wrapper sections or source paragraphs and preserve every source number.",
        "issues": issues,
        "paragraphs": [
            {"source_paragraph_id": source_id, "source_text": SHARED.chinese_translation_source(source_by_id[source_id]["text"])}
            for source_id in failed_ids
        ],
        "repair": {
            "opening": "opening" in failed_sections,
            "body_source_paragraph_ids": failed_ids,
            "closing": "closing" in failed_sections,
        },
    }
    if "opening" in failed_sections:
        payload["opening"] = {"current_segments": opening, "max_readable_characters": MAX_OPENING_CHARS}
    if "closing" in failed_sections:
        payload["closing"] = {"current_segments": closing, "max_readable_characters": MAX_CLOSING_CHARS}
    return payload


def retry_patch_sections(patch: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if isinstance(patch, list):
        return [], patch, []
    if not isinstance(patch, dict) or not set(patch).issubset({"opening", "body", "closing"}):
        raise ValueError("Chinese retry patch must contain only opening, body and closing arrays.")
    if any(not isinstance(patch[key], list) for key in patch):
        raise ValueError("Chinese retry patch sections must be arrays.")
    return patch.get("opening", []), patch.get("body", []), patch.get("closing", [])


def apply_retry(paragraphs: list[dict[str, Any]], script: Any, patch: Any) -> list[dict[str, Any]]:
    opening, body, closing = retry_sections(script)
    current, issues = retry_issues(paragraphs, opening, body, closing)
    failed_ids = {item["source_paragraph_id"] for item in issues if "source_paragraph_id" in item}
    failed_sections = {item["section"] for item in issues if "section" in item}
    if not failed_ids:
        if not failed_sections:
            raise ValueError("Chinese script has no retryable issues.")
    if isinstance(patch, list):
        if failed_sections or not failed_ids:
            raise ValueError("Wrapper retries must return a JSON object with the requested sections.")
        patch_opening, patch_body, patch_closing = [], patch, []
    else:
        patch_opening, patch_body, patch_closing = retry_patch_sections(patch)
    replacement = grouped_candidate(paragraphs, patch_body, failed_ids) if failed_ids else {}
    if "opening" in failed_sections:
        if not patch_opening:
            raise ValueError("Chinese opening retry patch is missing its opening section.")
    elif patch_opening:
        raise ValueError("Chinese retry patch contains an unrequested opening section.")
    if "closing" in failed_sections:
        if not patch_closing:
            raise ValueError("Chinese closing retry patch is missing its closing section.")
    elif patch_closing:
        raise ValueError("Chinese retry patch contains an unrequested closing section.")
    if not failed_ids and patch_body:
        raise ValueError("Chinese retry patch contains an unrequested body section.")
    combined_body: list[dict[str, Any]] = []
    for paragraph in paragraphs:
        source_id = paragraph_id(paragraph)
        combined_body.extend(replacement[source_id] if source_id in failed_ids else current[source_id])
    candidate: Any = combined_body
    if opening or closing:
        candidate = {
            "opening": patch_opening if "opening" in failed_sections else opening,
            "body": combined_body,
            "closing": patch_closing if "closing" in failed_sections else closing,
        }
    return finalize_chinese(paragraphs, candidate)


def chinese_editorial_request(article_path: Path) -> dict[str, Any]:
    payload = SHARED.editorial_request(article_path)
    payload["language"] = "zh-CN"
    payload["instructions"] = (
        "Return only the editorial draft JSON. The spoken and visible product is Chinese-first. "
        "Write natural Chinese display text, two Chinese guide-question translations, Chinese publication copy and three distinct Chinese cover lines. "
        "The English question fields are compatibility metadata only and must remain source-linked. "
        "Do not add facts, predictions, explanations or conclusions.\n\n"
        + payload["instructions"]
    )
    payload["draft_schema"]["publication"]["title_zh"] = "《经济学人》：… | 外刊播客 | 中文字幕"
    return payload


def init_production(article: Path, production: Path, region: str, aspect_ratios: list[str] | None) -> None:
    SHARED.init_production(article, production, "zh-CN", region, aspect_ratios)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-production")
    init.add_argument("article", type=Path)
    init.add_argument("production", type=Path)
    init.add_argument("--region", required=True)
    init.add_argument("--aspect-ratio", choices=("16:9", "9:16"), action="append", dest="aspect_ratios")
    request = commands.add_parser("chinese-request")
    request.add_argument("article", type=Path)
    finalize = commands.add_parser("finalize-chinese")
    finalize.add_argument("article", type=Path)
    finalize.add_argument("candidate", type=Path)
    finalize.add_argument("output", type=Path)
    validate = commands.add_parser("validate")
    validate.add_argument("article", type=Path)
    validate.add_argument("script", type=Path)
    retry = commands.add_parser("retry-request")
    retry.add_argument("article", type=Path)
    retry.add_argument("script", type=Path)
    retry.add_argument("--attempt", type=int, required=True)
    apply = commands.add_parser("apply-retry")
    apply.add_argument("article", type=Path)
    apply.add_argument("script", type=Path)
    apply.add_argument("patch", type=Path)
    apply.add_argument("output", type=Path)
    editorial_request_parser = commands.add_parser("chinese-editorial-request")
    editorial_request_parser.add_argument("article", type=Path)
    editorial_finalize = commands.add_parser("finalize-editorial")
    editorial_finalize.add_argument("article", type=Path)
    editorial_finalize.add_argument("draft", type=Path)
    editorial_finalize.add_argument("assets", type=Path)
    editorial_finalize.add_argument("--production", type=Path)
    editorial_validate = commands.add_parser("validate-editorial")
    editorial_validate.add_argument("article", type=Path)
    editorial_validate.add_argument("draft", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "init-production":
            init_production(args.article, args.production, args.region, args.aspect_ratios)
            result = {"status": "created", "production": str(args.production.resolve())}
        elif args.command == "chinese-request":
            article, paragraphs = SHARED.load_article(args.article)
            print(json.dumps(request_payload(article, paragraphs), ensure_ascii=False, indent=2))
            return 0
        elif args.command == "finalize-chinese":
            _, paragraphs = SHARED.load_article(args.article)
            segments = finalize_chinese(paragraphs, read_json(args.candidate))
            write_json(args.output, segments)
            result = {"status": "created", "script": str(args.output.resolve()), "segments": len(segments)}
        elif args.command == "validate":
            result = validate_final_script(args.article, args.script)
        elif args.command == "retry-request":
            article, paragraphs = SHARED.load_article(args.article)
            print(json.dumps(retry_payload(article, paragraphs, read_json(args.script), args.attempt), ensure_ascii=False, indent=2))
            return 0
        elif args.command == "apply-retry":
            _, paragraphs = SHARED.load_article(args.article)
            repaired = apply_retry(paragraphs, read_json(args.script), read_json(args.patch))
            write_json(args.output, repaired)
            result = {"status": "created", "script": str(args.output.resolve()), "segments": len(repaired)}
        elif args.command == "chinese-editorial-request":
            print(json.dumps(chinese_editorial_request(args.article), ensure_ascii=False, indent=2))
            return 0
        elif args.command == "validate-editorial":
            article, paragraphs = SHARED.load_editorial_article(args.article)
            result = SHARED.validate_editorial_draft(article, paragraphs, read_json(args.draft), "zh-CN")
            result = {"status": "valid", "language": "zh-CN", "guide_questions": len(result["guide_questions"]), "cover_lines": len(result["cover_text"])}
        else:
            assets = SHARED.finalise_editorial_assets(
                args.article, args.draft, args.assets, args.production, publication_variant="zh-CN",
            )
            result = {"status": "created", "editorial_assets": str(args.assets.resolve()), "cover_outputs": assets["cover_art"]["outputs"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
