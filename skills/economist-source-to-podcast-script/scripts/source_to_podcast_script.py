#!/usr/bin/env python3
"""Create and validate source-linked, conversational podcast scripts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from editorial_assets import editorial_request, finalise as finalise_editorial_assets, load_article as load_editorial_article, read_json as read_editorial_json, validate_draft as validate_editorial_draft


ALLOWED_FIELDS = {"segment_id", "speaker_id", "kind", "spoken_text", "source_paragraph_ids"}
SPEAKERS = {"primary", "secondary"}
FACTUAL_KINDS = {"verbatim", "sentence_split"}
INTERACTION_KINDS = {"reaction", "prompt"}
ALLOWED_KINDS = FACTUAL_KINDS | INTERACTION_KINDS
BODY_KINDS = ALLOWED_KINDS
VISUAL_REFERENCE = re.compile(
    r"\s*\(\s*(?:see|see also)\s+(?:the\s+)?(?:chart|table|figure|next article|next page)[^)]*\)",
    re.IGNORECASE,
)
ABBREVIATIONS = {"Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "St.", "vs.", "etc.", "e.g.", "i.e."}
REPEATED_CHINESE_PUNCTUATION = re.compile(r"([，。！？；：、])\1+")
COMMA_WRAPPED_LATIN = re.compile(r"，\s*[A-Za-z][A-Za-z0-9.&'’/\-]{1,}\s*，")
COMMA_WRAPPED_AMOUNT = re.compile(
    r"，\s*(?:[$¥￥]\s*)?\d[\d,]*(?:\.\d+)?\s*(?:亿美元|人民币|亿元|万元|美元|元|bn|trn|m|yuan|%)\s*，",
    re.IGNORECASE,
)
BRACKET_PAIRS = {"(": ")", "（": "）", "[": "]", "［": "］"}
SPOKEN_BRACKETS = re.compile(r"[()\[\]（）［］]")
MAX_ENGLISH_SEGMENT_CHARS = 220
MAX_CAPTION_UNIT_CHARS = 84
MAX_CHINESE_CAPTION_CHARS = 48
MIN_BALANCED_ENGLISH_WORDS = 120
MIN_INTERACTION_FACTUAL_SEGMENTS = 8
MIN_INTERACTION_SEGMENTS = 2
MAX_CONSECUTIVE_ENGLISH_SEGMENTS = 3
MIN_ENGLISH_WORD_SHARE = 0.40
MAX_ENGLISH_WORD_SHARE = 0.60
TARGET_ENGLISH_WORD_SHARE = 0.50
MAX_REACTION_WORDS = 12
MAX_PROMPT_WORDS = 16
APPROVED_ENGLISH_FILLER_TOKENS = {
    "actually", "basically", "exactly", "honestly", "look", "okay", "right",
    "so", "sure", "well",
}
APPROVED_ENGLISH_FILLER_PHRASES = (
    ("of", "course"),
    ("you", "know"),
    ("i", "mean"),
)
CONTRACTION_EXPANSIONS = {
    "can't": ("can", "not"), "cannot": ("can", "not"), "couldn't": ("could", "not"),
    "didn't": ("did", "not"), "doesn't": ("does", "not"), "don't": ("do", "not"),
    "hadn't": ("had", "not"), "hasn't": ("has", "not"), "haven't": ("have", "not"),
    "i'd": ("i", "would"), "i'll": ("i", "will"), "i'm": ("i", "am"),
    "i've": ("i", "have"), "isn't": ("is", "not"), "it'd": ("it", "would"),
    "it'll": ("it", "will"), "it's": ("it", "is"), "let's": ("let", "us"),
    "mustn't": ("must", "not"), "shouldn't": ("should", "not"), "that's": ("that", "is"),
    "there's": ("there", "is"), "they'd": ("they", "would"), "they're": ("they", "are"),
    "they've": ("they", "have"), "wasn't": ("was", "not"), "we'd": ("we", "would"),
    "we'll": ("we", "will"), "we're": ("we", "are"), "we've": ("we", "have"),
    "weren't": ("were", "not"), "won't": ("will", "not"), "wouldn't": ("would", "not"),
    "you'd": ("you", "would"), "you'll": ("you", "will"), "you're": ("you", "are"),
    "you've": ("you", "have"), "gonna": ("going", "to"),
}
ENGLISH_STYLE_INSTRUCTIONS = """You are the English writing stage for a source-bounded, two-host Economist podcast.

Turn each supplied verified source paragraph into a natural spoken exchange. The supplied paragraphs define the evidence boundary, not a wording template. The result should sound like two attentive hosts talking through a reported story, never like an article being read aloud.

SOURCE-BOUNDED ADAPTATION

- You may freely paraphrase, condense, reorder related clauses within the supplied paragraph, merge or split sentences, simplify nominalisations, and replace formal written syntax with natural spoken English.
- Do not invent any factual proposition, sentence, quotation, number, attribution, causal link, evaluation, example, prediction, analogy, conclusion, or host viewpoint that is not supported by the supplied paragraph.
- Do not create a disagreement, personal experience, guest opinion, or broad generalisation that the source does not support.
- Do not treat source wording, punctuation, sentence order, or every source token as mandatory. Do not restore omitted wording merely to imitate the article.
- Do not use generic praise, exaggerated reactions, or filler-heavy performance. A light conversational tone is useful only when it keeps the exchange natural and source-bounded.

HOST ROLES AND BALANCE

- source_speaker_id and partner_speaker_id are suggested host roles for the paragraph, not fixed speaker assignments. Either host may deliver factual units, and one source paragraph may contain factual turns from both hosts.
- Share substantive narration between primary and secondary. Aim for 45%--55% of total English words per host; stay within 40%--60% for a normal-length script. Do not make one host a question-only or reaction-only voice.
- Use short turns, natural questions, answers, and responses. Avoid more than three consecutive segments by the same host unless a single idea genuinely needs two adjacent units.
- For a script with at least eight factual segments, include at least two useful interactions and give both hosts an interaction opportunity. Do not insert an interaction after every sentence.
- A prompt must be spoken by one host and be immediately followed by a factual answer from the other host. A reaction may acknowledge or frame the current source point, but must not add a claim or viewpoint.

ORAL STYLE AND TOPIC PROGRESSION

- Prefer direct verbs, short clauses, contractions, concrete subjects, and natural pauses.
- Avoid the written pattern “noun, explanatory phrase;” or “noun, short definition,” especially when it creates a dangling subtitle unit. When context is needed, integrate it into a complete spoken clause or use two natural sentences.
- Do not stack appositives, parentheticals, nominalisations, or long modifier chains after a noun.
- Use light markers such as well, so, right, you know, I mean, actually, honestly, exactly, okay, look, sure, of course, and basically sparingly. They must not carry facts or disguise a missing sentence.
- Keep necessary professional terms, but simplify the surrounding sentence rather than adding an outside definition.
- Move between source paragraphs with a short source-linked bridge only when it improves listener orientation.

LONG-SENTENCE AND CAPTION ADAPTATION

- Rewrite long written sentences before splitting them. Do not mechanically cut a sentence at the character limit.
- Split at a complete semantic boundary: contrast, cause, condition, attribution, list boundary, time shift, or consequence.
- Every segment must be understandable when heard once and must be a complete sentence or self-contained spoken clause.
- Never end a segment with a comma, colon, dash, or dangling semicolon. Do not use a synthetic semicolon to turn a fragment into a caption unit.
- Every spoken segment must be no longer than max_spoken_segment_chars. Every captionable unit must be no longer than max_caption_unit_chars.
- Treat these limits as hard production constraints. If a written sentence cannot fit naturally, rewrite it into shorter complete spoken sentences before returning the draft.

OUTPUT CONTRACT

Return only a JSON array. Every object must contain exactly: segment_id, speaker_id, kind, spoken_text, and source_paragraph_ids.

Use these kinds:

- verbatim: a concise source-bounded factual unit that may still be lightly reworded
- sentence_split: a source-bounded factual unit created by oralising or splitting a longer written sentence
- reaction: a short, natural, source-linked response with no new claim or viewpoint
- prompt: a short, natural, source-linked question that the immediately following factual unit answers

Every segment must reference exactly one supplied paragraph ID. Factual segments may use either speaker. Interaction segments may use either speaker, but a prompt must be followed immediately by a factual segment from the other speaker. Keep reactions to 12 English words or fewer and prompts to 16 English words or fewer. Use normal conversational punctuation and do not end any segment with a comma, colon, dash, or semicolon.

Before returning, silently verify: all supplied paragraphs are covered in original order; no unsupported fact or viewpoint has been added; every long sentence has been rewritten into subtitle-safe spoken units; both hosts have substantive opportunities; the word balance is near 50/50 when the script is long enough; no segment exceeds its supplied budget; and the result sounds like a composed two-host conversation."""
RETRY_INSTRUCTIONS = (
    "Rewrite only these zh-CN source paragraphs. Preserve facts, numbers, attribution and order. "
    "Write natural spoken Chinese: use common Chinese names first, keep a bare English proper name only when it is natural, "
    "and never use parentheses, bracketed aliases, or comma-wrapped names or currency conversions. "
    "Return only source-linked body segments and preserve the supplied speaker_id for each paragraph."
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()


def relative_path(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def paragraph_id(paragraph: dict[str, Any]) -> str:
    if isinstance(paragraph.get("id"), str) and paragraph["id"].strip():
        return paragraph["id"]
    return f"p{int(paragraph['order']):03d}"


def load_article(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    article = read_json(path)
    if article.get("review_status") != "verified":
        raise ValueError("Article package must be verified.")
    paragraphs = article.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        raise ValueError("Article package needs verified paragraphs.")
    if [item.get("order") for item in paragraphs] != list(range(1, len(paragraphs) + 1)):
        raise ValueError("Article paragraphs must have consecutive order values.")
    for paragraph in paragraphs:
        if not isinstance(paragraph.get("text"), str) or not paragraph["text"].strip():
            raise ValueError("Every article paragraph needs text.")
    return article, paragraphs


def base_source(text: str) -> str:
    """Remove paper-only navigation while retaining the article's language and punctuation."""
    text = unicodedata.normalize("NFC", text)
    text = VISUAL_REFERENCE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,;:.!?])", r"\1", text)
    return text.strip()


def english_spoken_source(text: str) -> str:
    """Normalise verified English for compact source-linked request payloads."""
    text = base_source(text)
    text = re.sub(r"\b(?:ie|i\.e)\s*,", "i.e.,", text, flags=re.IGNORECASE)
    text = text.replace("—", ", ")
    text = text.replace("(", ", ").replace(")", ", ")
    text = text.replace("[", ", ").replace("]", ", ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,;:.!?])", r"\1", text)
    text = re.sub(r"([,;:!?])(?=[A-Za-z“‘])", r"\1 ", text)
    text = re.sub(r",\s*,+", ",", text)
    text = re.sub(r";\s*;+", ";", text)
    text = re.sub(r",\s*;", ";", text)
    text = re.sub(r";\s*,", ";", text)
    text = re.sub(r"[,;]\s*([.!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def chinese_translation_source(text: str) -> str:
    """Give Chinese translation the verified punctuation, not English TTS punctuation."""
    return base_source(text)


# Preserve the previous public helper name for callers that use it for English.
spoken_source = english_spoken_source


def lexical_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[\w]+(?:[’'][\w]+)?", unicodedata.normalize("NFC", text).casefold()):
        token = token.replace("’", "'")
        tokens.extend(CONTRACTION_EXPANSIONS.get(token, (token,)))
    return tokens


def source_tokens_with_delivery_fillers_removed(source: list[str], candidate: list[str]) -> list[str]:
    """Remove only approved discourse markers while matching source tokens in order."""
    result: list[str] = []
    cursor = 0
    index = 0
    while index < len(candidate):
        token = candidate[index]
        if cursor < len(source) and token == source[cursor]:
            result.append(token)
            cursor += 1
            index += 1
            continue
        if token in APPROVED_ENGLISH_FILLER_TOKENS:
            index += 1
            continue
        matched_phrase = next(
            (phrase for phrase in APPROVED_ENGLISH_FILLER_PHRASES
             if tuple(candidate[index:index + len(phrase)]) == phrase),
            None,
        )
        if matched_phrase:
            index += len(matched_phrase)
            continue
        result.append(token)
        index += 1
    return result


def sentence_boundaries(text: str) -> list[int]:
    boundaries: list[int] = []
    for match in re.finditer(r"[.!?;]", text):
        if match.group(0) == "." and match.start() > 0 and match.start() + 1 < len(text):
            if text[match.start() - 1].isdigit() and text[match.start() + 1].isdigit():
                continue
        token = text[max(0, match.start() - 12): match.end()]
        if any(token.endswith(abbrev) for abbrev in ABBREVIATIONS):
            continue
        boundaries.append(match.end())
    return boundaries


def split_for_speech(text: str, maximum: int) -> list[str]:
    result: list[str] = []
    sentence_start = 0
    sentence_ends = sentence_boundaries(text)
    if not sentence_ends or sentence_ends[-1] != len(text):
        sentence_ends.append(len(text))
    for sentence_end in sentence_ends:
        remaining = text[sentence_start:sentence_end].strip()
        sentence_start = sentence_end
        while len(remaining) > maximum:
            candidates = [match.end() for match in re.finditer(r"[,;:]", remaining) if maximum // 3 <= match.end() <= maximum]
            cut = candidates[-1] if candidates else remaining.rfind(" ", 0, maximum)
            if cut <= 0 or not candidates:
                raise ValueError(
                    "Cannot split an overlong English sentence into a complete spoken unit; "
                    "rewrite the sentence before applying the segment budget."
                )
            unit = remaining[:cut].strip()
            unit = unit.rstrip(",;:").rstrip()
            if not unit or unit[-1] not in ".!?":
                raise ValueError(
                    "Cannot split an overlong English sentence without creating a dangling clause; "
                    "rewrite the sentence before applying the segment budget."
                )
            result.append(unit)
            remaining = remaining[cut:].strip()
        if remaining:
            result.append(remaining)
    return result


def speaker_for_paragraph(order: int, total: int) -> str:
    """Assign whole source paragraphs to the two hosts without synthetic dialogue turns."""
    if total < 2:
        return "primary"
    if total == 2:
        return "primary" if order == 1 else "secondary"
    return "secondary" if (order - 1) % 3 == 2 else "primary"


def partner_for_speaker(speaker_id: str) -> str:
    return "secondary" if speaker_id == "primary" else "primary"


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:[’'][A-Za-z]+)?", text))


def validate_interaction(segment: dict[str, Any]) -> None:
    """Keep non-factual host turns bounded and unable to bypass source coverage."""
    kind = segment["kind"]
    text = segment["spoken_text"].strip()
    if text.endswith((",", ":", ";", "—", "–", "-")):
        raise ValueError("English interactions must not end with dangling punctuation.")
    if not text.endswith((".", "!", "?")):
        raise ValueError("English interactions must be complete spoken sentences.")
    if kind == "reaction":
        if word_count(text) > MAX_REACTION_WORDS:
            raise ValueError(f"English reactions must contain no more than {MAX_REACTION_WORDS} words.")
    elif kind == "prompt":
        if word_count(text) > MAX_PROMPT_WORDS:
            raise ValueError(f"English prompts must contain no more than {MAX_PROMPT_WORDS} words.")
        if not text.endswith("?"):
            raise ValueError("English prompts must end with a question mark.")


def build_english(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    ordinal = 1
    total = len(paragraphs)
    for paragraph in paragraphs:
        source_id = paragraph_id(paragraph)
        parts = split_for_speech(english_spoken_source(paragraph["text"]), MAX_CAPTION_UNIT_CHARS)
        speaker_id = speaker_for_paragraph(int(paragraph["order"]), total)
        for part in parts:
            segments.append({
                "segment_id": f"en-{ordinal:03d}",
                "speaker_id": speaker_id,
                "kind": "verbatim" if len(parts) == 1 else "sentence_split",
                "spoken_text": part,
                "source_paragraph_ids": [source_id],
            })
            ordinal += 1
    return segments


def english_request(article: dict[str, Any], paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    """Create the compact request used for a reviewed conversational English draft."""
    return {
        "source_sha256": article["source_sha256"],
        "language": "en",
        "instructions": ENGLISH_STYLE_INSTRUCTIONS,
        "speaker_balance": {
            "target_word_share": {speaker: TARGET_ENGLISH_WORD_SHARE for speaker in sorted(SPEAKERS)},
            "acceptable_word_share": {
                "minimum": MIN_ENGLISH_WORD_SHARE,
                "maximum": MAX_ENGLISH_WORD_SHARE,
            },
            "max_consecutive_segments": MAX_CONSECUTIVE_ENGLISH_SEGMENTS,
            "interaction_policy": "Both hosts should have substantive factual turns and useful question/response opportunities.",
        },
        "paragraphs": [
            {
                "source_paragraph_id": paragraph_id(item),
                "source_speaker_id": speaker_for_paragraph(int(item["order"]), len(paragraphs)),
                "partner_speaker_id": partner_for_speaker(speaker_for_paragraph(int(item["order"]), len(paragraphs))),
                "max_spoken_segment_chars": MAX_ENGLISH_SEGMENT_CHARS,
                "max_caption_unit_chars": MAX_CAPTION_UNIT_CHARS,
                "source_text": english_spoken_source(item["text"]),
            }
            for item in paragraphs
        ],
    }


def validate_english_candidate_body(
    paragraphs: list[dict[str, Any]], candidate: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Validate a model draft before assigning canonical English segment IDs."""
    if not isinstance(candidate, list) or not candidate:
        raise ValueError("English candidate must be a non-empty JSON array.")
    known = [paragraph_id(item) for item in paragraphs]
    known_set = set(known)
    grouped = {source_id: [] for source_id in known}
    for item in candidate:
        if not isinstance(item, dict) or set(item) != ALLOWED_FIELDS:
            raise ValueError("Every English candidate segment must contain exactly the five contract fields.")
        if item.get("speaker_id") not in SPEAKERS or item.get("kind") not in BODY_KINDS:
            raise ValueError("English candidate must contain source-linked body segments with an approved speaker.")
        if not isinstance(item.get("spoken_text"), str) or not item["spoken_text"].strip():
            raise ValueError("Every English candidate segment needs spoken text.")
        if SPOKEN_BRACKETS.search(item["spoken_text"]):
            raise ValueError("English candidate must not retain parenthetical or bracketed text.")
        if len(item["spoken_text"].strip()) > MAX_ENGLISH_SEGMENT_CHARS:
            raise ValueError("English candidate contains an overlong segment; split it into shorter spoken clauses.")
        ids = item.get("source_paragraph_ids")
        if not isinstance(ids, list) or len(ids) != 1 or ids[0] not in known_set:
            raise ValueError("Each English candidate segment must reference one known source paragraph.")
        grouped[ids[0]].append(item)
    missing = [source_id for source_id in known if not grouped[source_id]]
    if missing:
        raise ValueError(f"English candidate is missing source paragraphs: {', '.join(missing)}.")
    for paragraph in paragraphs:
        source_id = paragraph_id(paragraph)
        factual = [item for item in grouped[source_id] if item["kind"] in FACTUAL_KINDS]
        interactions = [item for item in grouped[source_id] if item["kind"] in INTERACTION_KINDS]
        if not factual:
            raise ValueError(f"English candidate has no factual source coverage for {source_id}.")
        if len(interactions) > max(1, (len(factual) + 1) // 2):
            raise ValueError(f"Source paragraph {source_id} has too many interaction segments.")
        for index, item in enumerate(grouped[source_id]):
            if item["kind"] in INTERACTION_KINDS:
                validate_interaction(item)
            if item["kind"] == "prompt":
                if index + 1 >= len(grouped[source_id]) or grouped[source_id][index + 1]["kind"] not in FACTUAL_KINDS:
                    raise ValueError("An English prompt must be immediately followed by a factual source segment.")
                if grouped[source_id][index + 1]["speaker_id"] == item["speaker_id"]:
                    raise ValueError("An English prompt must be answered by the other speaker.")
    return grouped


def finalize_english(paragraphs: list[dict[str, Any]], candidate: Any) -> list[dict[str, Any]]:
    """Freeze an oral English draft while retaining source links and speaker balance."""
    grouped = validate_english_candidate_body(paragraphs, candidate)
    segments: list[dict[str, Any]] = []
    ordinal = 1
    for paragraph in paragraphs:
        source_id = paragraph_id(paragraph)
        for item in grouped[source_id]:
            segments.append({
                "segment_id": f"en-{ordinal:03d}",
                "speaker_id": item["speaker_id"],
                "kind": item["kind"],
                "spoken_text": item["spoken_text"].strip(),
                "source_paragraph_ids": [source_id],
            })
            ordinal += 1
    validate_structure(segments, "en")
    validate_coverage(paragraphs, segments, speaker_policy="english")
    validate_english(paragraphs, segments)
    return segments


def validate_candidate_body(
    paragraphs: list[dict[str, Any]], candidate: Any, allowed_ids: set[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(candidate, list) or not candidate:
        raise ValueError("Chinese candidate must be a non-empty JSON array.")
    known = [paragraph_id(item) for item in paragraphs]
    known_set = set(known)
    grouped = {source_id: [] for source_id in known}
    for item in candidate:
        if not isinstance(item, dict) or set(item) != ALLOWED_FIELDS:
            raise ValueError("Every Chinese candidate segment must contain exactly the five contract fields.")
        if item.get("speaker_id") not in SPEAKERS or item.get("kind") not in FACTUAL_KINDS:
            raise ValueError("Chinese candidate must contain source-linked body segments with an approved speaker.")
        if not isinstance(item.get("spoken_text"), str) or not item["spoken_text"].strip():
            raise ValueError("Every Chinese candidate segment needs spoken text.")
        ids = item.get("source_paragraph_ids")
        if not isinstance(ids, list) or len(ids) != 1 or ids[0] not in known_set:
            raise ValueError("Each Chinese candidate segment must reference one known source paragraph.")
        source_id = ids[0]
        if allowed_ids is not None and source_id not in allowed_ids:
            raise ValueError("Chinese retry patch contains a paragraph that was not requested.")
        grouped[source_id].append(item)
    expected = allowed_ids if allowed_ids is not None else known_set
    missing = [source_id for source_id in expected if not grouped[source_id]]
    if missing:
        raise ValueError(f"Chinese candidate is missing source paragraphs: {', '.join(sorted(missing))}.")
    if allowed_ids is None and any(not grouped[source_id] for source_id in known):
        raise ValueError("Chinese candidate must cover every source paragraph.")
    total = len(paragraphs)
    for paragraph in paragraphs:
        source_id = paragraph_id(paragraph)
        if not grouped[source_id]:
            continue
        speakers = {item["speaker_id"] for item in grouped[source_id]}
        if len(speakers) != 1:
            raise ValueError("All segments from one source paragraph must use the same speaker.")
        expected_speaker = speaker_for_paragraph(int(paragraph["order"]), total)
        if speakers != {expected_speaker}:
            raise ValueError(f"Source paragraph {source_id} has the wrong deterministic speaker assignment.")
    return grouped


def finalize_zh(paragraphs: list[dict[str, Any]], candidate: Any) -> list[dict[str, Any]]:
    """Make the Chinese contract canonical while preserving paragraph speakers."""
    grouped = validate_candidate_body(paragraphs, candidate)
    segments: list[dict[str, Any]] = []
    ordinal = 1
    for paragraph in paragraphs:
        source_id = paragraph_id(paragraph)
        for candidate_segment in grouped[source_id]:
            segments.append({
                "segment_id": f"zh-CN-{ordinal:03d}",
                "speaker_id": candidate_segment["speaker_id"],
                "kind": "sentence_split",
                "spoken_text": candidate_segment["spoken_text"].strip(),
                "source_paragraph_ids": [source_id],
            })
            ordinal += 1
    return segments


def bracket_error(text: str) -> bool:
    expected: list[str] = []
    closers = set(BRACKET_PAIRS.values())
    for character in text:
        if character in BRACKET_PAIRS:
            expected.append(BRACKET_PAIRS[character])
        elif character in closers and (not expected or expected.pop() != character):
            return True
    return bool(expected)


def chinese_punctuation_issues(segments: list[dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for segment in segments:
        text = segment["spoken_text"]
        reasons: list[str] = []
        if bracket_error(text):
            reasons.append("unpaired brackets")
        if SPOKEN_BRACKETS.search(text):
            reasons.append("parenthetical or bracketed content is not spoken text")
        if REPEATED_CHINESE_PUNCTUATION.search(text):
            reasons.append("repeated Chinese punctuation")
        if COMMA_WRAPPED_LATIN.search(text):
            reasons.append("comma-wrapped Latin abbreviation or name")
        if COMMA_WRAPPED_AMOUNT.search(text):
            reasons.append("comma-wrapped currency conversion")
        if reasons:
            issues.append({"source_paragraph_id": segment["source_paragraph_ids"][0], "reason": "; ".join(reasons)})
    return issues


VARIANTS = {"en", "en-zh", "zh-CN"}
SUBTITLE_DRAFT_FIELDS = {"unit_id", "translation_zh"}
SENTENCE_ENDINGS = ".!?;"
SENTENCE_ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.",
    "e.g.", "i.e.", "u.s.", "u.k.", "no.", "fig.", "inc.", "ltd.", "co.",
}


def variant_configuration(variant: str) -> tuple[list[str], dict[str, str], dict[str, Any]]:
    """Return the only scripts and captions needed for one production run."""
    if variant not in VARIANTS:
        raise ValueError(f"Unsupported production variant: {variant}.")
    if variant == "en":
        return ["en"], {"script_en": "script.en.json"}, {
            "provider": "approved-script", "variants": ["en"],
        }
    if variant == "en-zh":
        return ["en"], {"script_en": "script.en.json", "subtitle_script_en_zh": "subtitle-script.en-zh.json"}, {
            "provider": "approved-bilingual-script",
            "variants": ["en-zh"],
            "source_locale": "en-US",
            "target_locale": "zh-Hans",
            "translation_mode": "reviewed_source_linked",
            "translation_quality": "reviewed_required",
            "publication_status": "blocked_until_reviewed",
        }
    return ["zh-CN"], {"script_zh_cn": "script.zh-CN.json"}, {
        "provider": "approved-script", "variants": ["zh-CN"],
    }


def init_production(
    article_path: Path,
    output_path: Path,
    variant: str = "en",
    region: str | None = None,
    aspect_ratios: list[str] | None = None,
) -> None:
    article, _ = load_article(article_path)
    languages, script_artifacts, captions = variant_configuration(variant)
    package_root = output_path.parent
    try:
        article_relative = str(article_path.resolve().relative_to(package_root.resolve()))
    except ValueError:
        article_relative = str(article_path.resolve())
    production = {
        "state": "queued",
        "variant": variant,
        "article": {"path": article_relative, "source_sha256": article["source_sha256"]},
        "script_generation": {
            "provider": "codex-skill",
            "policy_version": "5.1",
            "policy": "source_bounded_conversational_rewrite",
            "zh_punctuation_retry_limit": 1,
        },
        "languages": languages,
        "speakers": {"primary": "primary", "secondary": "secondary"},
        "target_duration_minutes": {"minimum": 8, "maximum": 12, "policy": "coverage_first"},
        "output": {"caption_formats": ["srt", "vtt"], "aspect_ratios": aspect_ratios or ["16:9"]},
        "speech": {
            "provider": "azure-speech",
            "region": region,
            "tier": "F0",
            "alignment_method": "azure_word_boundary",
            "voices": {
                "en": {
                    "primary": {"name": "en-US-Ava:DragonHDLatestNeural", "parameters": {}},
                    "secondary": {"name": "en-US-Andrew:DragonHDLatestNeural", "parameters": {"temperature": 1.0}},
                },
                "zh-CN": {"primary": "zh-CN-XiaoxiaoNeural", "secondary": "zh-CN-YunxiNeural"},
            },
            "delivery": {
                "en": {
                    "primary": {"structure": "none"},
                    "secondary": {"structure": "none"},
                },
            },
        },
        "captions": captions,
        "artifacts": script_artifacts,
        "progress": {"segments": {}},
        "failures": [],
    }
    write_json(output_path, production)


def translation_request(article: dict[str, Any], paragraphs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_sha256": article["source_sha256"],
        "language": "zh-CN",
        "paragraphs": [
            {
                "source_paragraph_id": paragraph_id(item),
                "speaker_id": speaker_for_paragraph(int(item["order"]), len(paragraphs)),
                "source_text": chinese_translation_source(item["text"]),
            }
            for item in paragraphs
        ],
    }


def is_sentence_end(text: str, position: int) -> bool:
    """Return whether punctuation at position ends an English display sentence."""
    if text[position] not in SENTENCE_ENDINGS:
        return False
    tail = position + 1
    while tail < len(text) and text[tail] in "\"')]}”’":
        tail += 1
    if text[position] == ".":
        if position > 0 and position + 1 < len(text) and text[position - 1].isdigit() and text[position + 1].isdigit():
            return False
        token = re.search(r"[A-Za-z.]+$", text[:position + 1])
        if token and token.group(0).lower() in SENTENCE_ABBREVIATIONS and tail < len(text):
            return False
        if position + 2 < len(text) and text[position + 1].isalpha() and text[position + 2] == ".":
            return False
    return tail == len(text) or text[tail].isspace()


def caption_unit_spans(script: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one complete caption unit per frozen spoken segment.

    Audio segments are already proactively split by the writing stage.  Do not
    join them again: doing so recreates the long caption units that the writing
    budget intentionally removed.
    """
    units: list[dict[str, Any]] = []
    for ordinal, segment in enumerate(script, start=1):
        source_text = str(segment["spoken_text"]).strip()
        if not source_text:
            raise ValueError("Subtitle source text cannot be empty.")
        if len(source_text) > MAX_CAPTION_UNIT_CHARS:
            raise ValueError("English caption unit exceeds the configured subtitle budget.")
        if source_text.endswith((",", ":", ";", "—", "–", "-")):
            raise ValueError("English caption unit cannot end with dangling punctuation.")
        endings = sentence_boundaries(source_text)
        if len(endings) != 1 or endings[0] != len(source_text):
            raise ValueError("Every reviewed bilingual subtitle unit must be a complete English sentence or self-contained clause.")
        units.append({
            "unit_id": f"en-zh-unit-{ordinal:03d}",
            "source_text": source_text,
            "source_spans": [{
                "segment_id": segment["segment_id"], "source_start": 0, "source_end": len(source_text),
            }],
            "source_paragraph_ids": list(segment["source_paragraph_ids"]),
        })
    return units


# Kept as a compatibility alias for callers of the previous helper.
sentence_spans = caption_unit_spans


def subtitle_request(article: dict[str, Any], script: list[dict[str, Any]]) -> dict[str, Any]:
    """Create the compact, source-linked request for reviewed bilingual captions."""
    validate_structure(script, "en")
    units = caption_unit_spans(script)
    return {
        "schema_version": "3.0",
        "source_sha256": article["source_sha256"],
        "script_sha256": sha256_json(script),
        "language": "zh-Hans",
        "instructions": (
            "Return exactly {units:[{unit_id,translation_zh}]}. Translate each supplied final English spoken unit into one complete, natural Chinese subtitle unit. Do not restore article wording that the English rewrite condensed, and do not add unsupported content. "
            "Keep the translation within the supplied 48-character layout budget, do not add line breaks, and use Chinese names where established. Do not insert an English clause into Chinese."
        ),
        "units": units,
    }


def validate_subtitle_draft(article: dict[str, Any], script: list[dict[str, Any]], draft: Any) -> dict[str, Any]:
    request = subtitle_request(article, script)
    if not isinstance(draft, dict) or set(draft) != {"units"} or not isinstance(draft["units"], list):
        raise ValueError("Subtitle draft must contain exactly a units array.")
    requested = request["units"]
    if len(draft["units"]) != len(requested):
        raise ValueError("Subtitle draft must translate every English caption unit exactly once.")
    final_units: list[dict[str, Any]] = []
    for expected, candidate in zip(requested, draft["units"]):
        if not isinstance(candidate, dict) or set(candidate) != SUBTITLE_DRAFT_FIELDS:
            raise ValueError("Every subtitle draft unit must contain unit_id and translation_zh.")
        if candidate["unit_id"] != expected["unit_id"]:
            raise ValueError("Subtitle draft units are out of source order.")
        translation = str(candidate["translation_zh"]).strip()
        if not translation or "\n" in translation or "\r" in translation:
            raise ValueError("Subtitle translations must be non-empty single-paragraph Chinese text.")
        if not re.search(r"[。！？]$", translation):
            raise ValueError("Every reviewed bilingual subtitle unit must be a complete Chinese sentence.")
        if len(translation) > MAX_CHINESE_CAPTION_CHARS:
            raise ValueError("Chinese subtitle unit exceeds the configured layout budget.")
        if re.search(r"[A-Za-z]{4,}\s+[A-Za-z]{4,}", translation):
            raise ValueError("A Chinese subtitle contains an English clause rather than an indivisible proper name.")
        final_units.append({**expected, "translation_zh": translation})
    return {
        "schema_version": "3.0",
        "translation_mode": "reviewed_source_linked",
        "translation_quality": "reviewed",
        "caption_unit_policy": "captionable_clause",
        "source_sha256": article["source_sha256"],
        "script_sha256": sha256_json(script),
        "units": final_units,
    }


def preflight_subtitle_layout(article_path: Path, result: dict[str, Any], production_path: Path) -> None:
    """Use the renderer's real fonts and safe areas before spending Azure TTS quota."""
    production = read_json(production_path)
    ratios = production.get("output", {}).get("aspect_ratios") or ["16:9"]
    if not isinstance(ratios, list) or any(ratio not in {"16:9", "9:16"} for ratio in ratios):
        raise ValueError("Production output needs supported aspect ratios for caption layout preflight.")
    article = read_json(article_path)
    cover_file = article.get("issue_cover", {}).get("file")
    if not isinstance(cover_file, str) or not cover_file:
        raise ValueError("Article package needs an issue cover for caption layout preflight.")
    cover_path = article_path.parent / cover_file
    if not cover_path.is_file():
        raise ValueError("Caption layout preflight could not find the verified issue cover.")

    visual_path = SCRIPT_DIR.parent.parent / "economist-static-slide-video" / "scripts" / "preview_visual_system.py"
    spec = importlib.util.spec_from_file_location("economist_caption_layout_preflight", visual_path)
    if spec is None or spec.loader is None:
        raise ValueError("Caption layout preflight could not load the static-video renderer.")
    visual = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(visual)
    definition = visual.read_definition(visual.DEFAULT_DEFINITION)
    failures: list[dict[str, str]] = []
    dimensions = {
        "16:9": (1080, 1920, "landscape_opening"),
        "9:16": (1920, 1080, "portrait_opening"),
    }
    for unit in result["units"]:
        for ratio in ratios:
            height, width, template = dimensions[ratio]
            content = copy.deepcopy(visual.SAMPLE_CONTENT)
            content["caption"]["current"] = {"en": unit["source_text"], "zh": unit["translation_zh"]}
            try:
                visual.render_template(
                    definition, template, cover_path, content, height, width,
                    diagnostics=[],
                )
            except RuntimeError as error:
                failures.append({
                    "unit_id": unit["unit_id"], "aspect_ratio": ratio, "reason": str(error),
                })
    if failures:
        raise ValueError(
            "Caption layout preflight failed; rewrite only these caption units: "
            + json.dumps(failures, ensure_ascii=False)
        )


def finalize_subtitles(article_path: Path, script_path: Path, draft_path: Path, output_path: Path, production_path: Path | None = None) -> dict[str, Any]:
    article, _ = load_article(article_path)
    script = read_json(script_path)
    validate_structure(script, "en")
    result = validate_subtitle_draft(article, script, read_json(draft_path))
    if production_path is not None:
        preflight_subtitle_layout(article_path, result, production_path)
    write_json(output_path, result)
    if production_path is not None:
        production = read_json(production_path)
        root = production_path.parent.resolve()
        production.setdefault("artifacts", {})["subtitle_script_en_zh"] = relative_path(output_path, root)
        production.setdefault("artifact_hashes", {})["subtitle_script_en_zh"] = sha256_json(result)
        production.setdefault("captions", {}).update({
            "provider": "approved-bilingual-script",
            "translation_mode": "reviewed_source_linked",
            "translation_quality": "reviewed",
            "publication_status": "approved_for_rendering",
        })
        write_json(production_path, production)
    return result


def retry_request(article: dict[str, Any], paragraphs: list[dict[str, Any]], segments: list[dict[str, Any]], attempt: int) -> dict[str, Any]:
    if attempt != 1:
        raise ValueError("Automatic Chinese punctuation retry limit reached.")
    validate_structure(segments, "zh-CN")
    validate_coverage(paragraphs, segments)
    issues = chinese_punctuation_issues(segments)
    if not issues:
        raise ValueError("Chinese script has no punctuation issues to retry.")
    failed_ids: list[str] = []
    for issue in issues:
        if issue["source_paragraph_id"] not in failed_ids:
            failed_ids.append(issue["source_paragraph_id"])
    source_by_id = {paragraph_id(item): item for item in paragraphs}
    return {
        "source_sha256": article["source_sha256"],
        "language": "zh-CN",
        "attempt": 1,
        "instructions": RETRY_INSTRUCTIONS,
        "issues": issues,
        "paragraphs": [
            {"source_paragraph_id": source_id, "source_text": chinese_translation_source(source_by_id[source_id]["text"])}
            for source_id in failed_ids
        ],
    }


def apply_zh_retry(paragraphs: list[dict[str, Any]], script: list[dict[str, Any]], patch: Any) -> list[dict[str, Any]]:
    validate_structure(script, "zh-CN")
    validate_coverage(paragraphs, script)
    issues = chinese_punctuation_issues(script)
    failed_ids = {item["source_paragraph_id"] for item in issues}
    if not failed_ids:
        raise ValueError("Chinese script has no punctuation issues to replace.")
    replacement = validate_candidate_body(paragraphs, patch, allowed_ids=failed_ids)
    original_body = list(script)
    original = validate_candidate_body(paragraphs, original_body)
    combined: list[dict[str, Any]] = []
    for paragraph in paragraphs:
        source_id = paragraph_id(paragraph)
        combined.extend(replacement[source_id] if source_id in failed_ids else original[source_id])
    return finalize_zh(paragraphs, combined)


def validate_structure(segments: Any, language: str) -> None:
    if not isinstance(segments, list) or not segments:
        raise ValueError("Script must be a non-empty JSON array.")
    prefix = "en" if language == "en" else "zh-CN"
    for ordinal, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict) or set(segment) != ALLOWED_FIELDS:
            raise ValueError("Every script segment must contain exactly the five contract fields.")
        if segment["segment_id"] != f"{prefix}-{ordinal:03d}":
            raise ValueError("Segment IDs must be consecutive and language-prefixed.")
        if segment["kind"] not in ALLOWED_KINDS:
            raise ValueError("Script contains an illegal segment kind.")
        if not isinstance(segment["spoken_text"], str) or not segment["spoken_text"].strip():
            raise ValueError("Every segment needs spoken text.")
        if not isinstance(segment["source_paragraph_ids"], list):
            raise ValueError("source_paragraph_ids must be an array.")
        if segment["speaker_id"] not in SPEAKERS:
            raise ValueError("Every body segment must use an approved speaker.")
        if not segment["source_paragraph_ids"] or len(segment["source_paragraph_ids"]) != 1:
            raise ValueError("Every body segment must reference exactly one source paragraph.")
        if language == "zh-CN" and segment["kind"] != "sentence_split":
            raise ValueError("Chinese body segments must use sentence_split.")


def validate_coverage(
    paragraphs: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    speaker_policy: str = "legacy",
) -> None:
    known = [paragraph_id(item) for item in paragraphs]
    index = {value: position for position, value in enumerate(known)}
    flattened: list[str] = []
    completed: list[str] = []
    factual_speakers: set[str] = set()
    for segment in segments:
        ids = segment["source_paragraph_ids"]
        if len(ids) != 1 or ids[0] not in index:
            raise ValueError("Each body segment must reference one known source paragraph.")
        if segment["kind"] in FACTUAL_KINDS:
            factual_speakers.add(segment["speaker_id"])
        flattened.append(ids[0])
        if not completed or completed[-1] != ids[0]:
            completed.append(ids[0])
    if completed != known:
        raise ValueError("Every source paragraph must be covered once, in source order.")
    if any(index[flattened[position]] > index[flattened[position + 1]] for position in range(len(flattened) - 1)):
        raise ValueError("Body segments are out of source order.")
    if len(known) >= 2 and factual_speakers != {"primary", "secondary"}:
        raise ValueError("Articles with at least two paragraphs must use both speakers.")

    if speaker_policy == "english":
        factual_segments = [segment for segment in segments if segment["kind"] in FACTUAL_KINDS]
        if len(factual_segments) >= 2 and factual_speakers != SPEAKERS:
            raise ValueError("English scripts with at least two factual segments must give both hosts substantive turns.")
        for position, segment in enumerate(segments):
            if segment["kind"] != "prompt":
                continue
            if position + 1 >= len(segments) or segments[position + 1]["kind"] not in FACTUAL_KINDS:
                raise ValueError("An English prompt must be immediately followed by a factual source segment.")
            if segments[position + 1]["speaker_id"] == segment["speaker_id"]:
                raise ValueError("An English prompt must be answered by the other speaker.")
        return

    by_source: dict[str, set[str]] = {source_id: set() for source_id in known}
    for segment in segments:
        if segment["kind"] in FACTUAL_KINDS:
            by_source[segment["source_paragraph_ids"][0]].add(segment["speaker_id"])
    for order, source_id in enumerate(known, start=1):
        if by_source[source_id] != {speaker_for_paragraph(order, len(known))}:
            raise ValueError("Factual segments must keep the deterministic source speaker assignment.")
    for segment in segments:
        if segment["kind"] in INTERACTION_KINDS:
            source_id = segment["source_paragraph_ids"][0]
            order = index[source_id] + 1
            if segment["speaker_id"] != partner_for_speaker(speaker_for_paragraph(order, len(known))):
                raise ValueError("Interaction segments must use the deterministic partner speaker.")


def english_speaker_balance(segments: list[dict[str, Any]]) -> dict[str, Any]:
    word_counts = {
        speaker: sum(word_count(segment["spoken_text"]) for segment in segments if segment["speaker_id"] == speaker)
        for speaker in sorted(SPEAKERS)
    }
    total_words = sum(word_counts.values())
    shares = {
        speaker: round((count / total_words) if total_words else 0.0, 4)
        for speaker, count in word_counts.items()
    }
    dominant = max(word_counts, key=word_counts.get) if total_words else None
    repairable_segment_ids = [
        segment["segment_id"]
        for segment in segments
        if dominant and segment["speaker_id"] == dominant and segment["kind"] in FACTUAL_KINDS
    ]
    return {
        "word_counts": word_counts,
        "total_words": total_words,
        "word_shares": shares,
        "target_word_share": TARGET_ENGLISH_WORD_SHARE,
        "acceptable_word_share": {
            "minimum": MIN_ENGLISH_WORD_SHARE,
            "maximum": MAX_ENGLISH_WORD_SHARE,
        },
        "repairable_segment_ids": repairable_segment_ids,
    }


def validate_english_speaker_balance(segments: list[dict[str, Any]]) -> None:
    report = english_speaker_balance(segments)
    if report["total_words"] < MIN_BALANCED_ENGLISH_WORDS:
        return
    shares = report["word_shares"]
    if any(share < MIN_ENGLISH_WORD_SHARE or share > MAX_ENGLISH_WORD_SHARE for share in shares.values()):
        raise ValueError("English speaker balance failed: " + json.dumps(report, ensure_ascii=False))


def validate_english_turn_balance(segments: list[dict[str, Any]]) -> None:
    run: list[dict[str, Any]] = []
    for segment in segments:
        speaker = segment["speaker_id"]
        if run and run[-1]["speaker_id"] != speaker:
            run = [segment]
        else:
            run.append(segment)
        if len(run) > MAX_CONSECUTIVE_ENGLISH_SEGMENTS:
            raise ValueError(
                f"English script has more than {MAX_CONSECUTIVE_ENGLISH_SEGMENTS} consecutive segments from {speaker}: "
                + json.dumps([item["segment_id"] for item in run], ensure_ascii=False)
            )
    factual_count = sum(segment["kind"] in FACTUAL_KINDS for segment in segments)
    interactions = [segment for segment in segments if segment["kind"] in INTERACTION_KINDS]
    if factual_count >= MIN_INTERACTION_FACTUAL_SEGMENTS:
        if len(interactions) < MIN_INTERACTION_SEGMENTS:
            raise ValueError(
                f"English script needs at least {MIN_INTERACTION_SEGMENTS} useful interactions for a long two-host exchange."
            )
        if {segment["speaker_id"] for segment in interactions} != SPEAKERS:
            raise ValueError("English script must give both hosts an interaction opportunity.")


def validate_english(paragraphs: list[dict[str, Any]], segments: list[dict[str, Any]]) -> None:
    for segment in segments:
        if SPOKEN_BRACKETS.search(segment["spoken_text"]):
            raise ValueError("English script must not retain parenthetical or bracketed text.")
        if len(segment["spoken_text"].strip()) > MAX_ENGLISH_SEGMENT_CHARS:
            raise ValueError("English script contains an overlong segment; split it into shorter spoken clauses.")
        if len(segment["spoken_text"].strip()) > MAX_CAPTION_UNIT_CHARS:
            raise ValueError("English script contains an overlong caption unit; split it before synthesis.")
        if segment["spoken_text"].strip().endswith((",", ":", ";", "—", "–", "-")):
            raise ValueError("English script contains a segment with dangling terminal punctuation.")
        endings = sentence_boundaries(segment["spoken_text"].strip())
        if len(endings) != 1 or endings[0] != len(segment["spoken_text"].strip()):
            raise ValueError("English script segments must be complete captionable sentences or self-contained clauses.")
        if segment["kind"] in INTERACTION_KINDS:
            validate_interaction(segment)
    validate_english_speaker_balance(segments)
    validate_english_turn_balance(segments)


def validate_script(article_path: Path, script_path: Path, language: str) -> dict[str, Any]:
    _, paragraphs = load_article(article_path)
    segments = read_json(script_path)
    validate_structure(segments, language)
    validate_coverage(paragraphs, segments, speaker_policy="english" if language == "en" else "legacy")
    if language == "en":
        validate_english(paragraphs, segments)
    else:
        issues = chinese_punctuation_issues(segments)
        if issues:
            affected = ", ".join(item["source_paragraph_id"] for item in issues)
            raise ValueError(f"Chinese punctuation lint failed for: {affected}.")
    body = segments
    characters = sum(len(item["spoken_text"]) for item in body)
    estimate = round((characters / (260 if language == "zh-CN" else 900)) * 60, 1)
    return {"status": "valid", "language": language, "segments": len(segments), "body_segments": len(body), "characters": characters, "estimated_seconds": estimate}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init_parser = commands.add_parser("init-production")
    init_parser.add_argument("article")
    init_parser.add_argument("production")
    init_parser.add_argument("--variant", choices=tuple(sorted(VARIANTS)), required=True)
    init_parser.add_argument("--region", required=True)
    init_parser.add_argument("--aspect-ratio", choices=("16:9", "9:16"), action="append", dest="aspect_ratios")
    en_parser = commands.add_parser("english")
    en_parser.add_argument("article")
    en_parser.add_argument("output")
    english_request_parser = commands.add_parser("english-request", help="Print the source-linked request for a conversational English draft.")
    english_request_parser.add_argument("article")
    english_finalize_parser = commands.add_parser("finalize-english", help="Validate and freeze a conversational English draft.")
    english_finalize_parser.add_argument("article")
    english_finalize_parser.add_argument("candidate")
    english_finalize_parser.add_argument("output")
    request_parser = commands.add_parser("translation-request")
    request_parser.add_argument("article")
    subtitle_request_parser = commands.add_parser("subtitle-request", help="Print the source-linked request for reviewed en-zh captions.")
    subtitle_request_parser.add_argument("article")
    subtitle_request_parser.add_argument("script")
    subtitle_finalize_parser = commands.add_parser("finalize-subtitles", help="Validate and write reviewed en-zh subtitle units.")
    subtitle_finalize_parser.add_argument("article")
    subtitle_finalize_parser.add_argument("script")
    subtitle_finalize_parser.add_argument("draft")
    subtitle_finalize_parser.add_argument("output")
    subtitle_finalize_parser.add_argument("--production")
    subtitle_validate_parser = commands.add_parser("validate-subtitles", help="Validate reviewed en-zh subtitle units without writing output.")
    subtitle_validate_parser.add_argument("article")
    subtitle_validate_parser.add_argument("script")
    subtitle_validate_parser.add_argument("draft")
    finalize_parser = commands.add_parser("finalize-zh")
    finalize_parser.add_argument("article")
    finalize_parser.add_argument("candidate")
    finalize_parser.add_argument("output")
    retry_parser = commands.add_parser("retry-request")
    retry_parser.add_argument("article")
    retry_parser.add_argument("script")
    retry_parser.add_argument("--attempt", type=int, required=True)
    apply_retry_parser = commands.add_parser("apply-zh-retry")
    apply_retry_parser.add_argument("article")
    apply_retry_parser.add_argument("script")
    apply_retry_parser.add_argument("patch")
    apply_retry_parser.add_argument("output")
    validate_parser = commands.add_parser("validate")
    validate_parser.add_argument("article")
    validate_parser.add_argument("script")
    validate_parser.add_argument("--language", choices=("en", "zh-CN"), required=True)
    editorial_request_parser = commands.add_parser("editorial-request", help="Print the source-linked request for guide questions and publishing assets.")
    editorial_request_parser.add_argument("article")
    editorial_finalize_parser = commands.add_parser("finalize-editorial", help="Validate an editorial draft and materialise publishing assets.")
    editorial_finalize_parser.add_argument("article")
    editorial_finalize_parser.add_argument("draft")
    editorial_finalize_parser.add_argument("assets")
    editorial_finalize_parser.add_argument("--production")
    editorial_validate_parser = commands.add_parser("validate-editorial", help="Validate publishing copy without writing artifacts.")
    editorial_validate_parser.add_argument("article")
    editorial_validate_parser.add_argument("draft")
    args = parser.parse_args()
    try:
        if args.command == "init-production":
            init_production(
                Path(args.article), Path(args.production), args.variant, args.region, args.aspect_ratios,
            )
            print(json.dumps({"status": "created", "production": str(Path(args.production).resolve())}, ensure_ascii=False))
        elif args.command == "english":
            _, paragraphs = load_article(Path(args.article))
            segments = build_english(paragraphs)
            write_json(Path(args.output), segments)
            print(json.dumps({"status": "created", "script": str(Path(args.output).resolve()), "segments": len(segments)}, ensure_ascii=False))
        elif args.command == "english-request":
            article, paragraphs = load_article(Path(args.article))
            print(json.dumps(english_request(article, paragraphs), ensure_ascii=False, indent=2))
        elif args.command == "finalize-english":
            _, paragraphs = load_article(Path(args.article))
            segments = finalize_english(paragraphs, read_json(Path(args.candidate)))
            write_json(Path(args.output), segments)
            print(json.dumps({"status": "created", "script": str(Path(args.output).resolve()), "segments": len(segments)}, ensure_ascii=False))
        elif args.command == "translation-request":
            article, paragraphs = load_article(Path(args.article))
            print(json.dumps(translation_request(article, paragraphs), ensure_ascii=False, indent=2))
        elif args.command == "subtitle-request":
            article, _ = load_article(Path(args.article))
            print(json.dumps(subtitle_request(article, read_json(Path(args.script))), ensure_ascii=False, indent=2))
        elif args.command == "finalize-subtitles":
            result = finalize_subtitles(
                Path(args.article), Path(args.script), Path(args.draft), Path(args.output),
                Path(args.production) if args.production else None,
            )
            print(json.dumps({"status": "created", "subtitle_script": str(Path(args.output).resolve()), "units": len(result["units"])}, ensure_ascii=False))
        elif args.command == "validate-subtitles":
            article, _ = load_article(Path(args.article))
            result = validate_subtitle_draft(article, read_json(Path(args.script)), read_json(Path(args.draft)))
            print(json.dumps({"status": "valid", "units": len(result["units"])}, ensure_ascii=False))
        elif args.command == "finalize-zh":
            _, paragraphs = load_article(Path(args.article))
            segments = finalize_zh(paragraphs, read_json(Path(args.candidate)))
            write_json(Path(args.output), segments)
            print(json.dumps({"status": "created", "script": str(Path(args.output).resolve()), "segments": len(segments)}, ensure_ascii=False))
        elif args.command == "retry-request":
            article, paragraphs = load_article(Path(args.article))
            payload = retry_request(article, paragraphs, read_json(Path(args.script)), args.attempt)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "apply-zh-retry":
            _, paragraphs = load_article(Path(args.article))
            segments = apply_zh_retry(paragraphs, read_json(Path(args.script)), read_json(Path(args.patch)))
            write_json(Path(args.output), segments)
            print(json.dumps({"status": "created", "script": str(Path(args.output).resolve()), "segments": len(segments)}, ensure_ascii=False))
        elif args.command == "editorial-request":
            print(json.dumps(editorial_request(Path(args.article)), ensure_ascii=False, indent=2))
        elif args.command == "finalize-editorial":
            assets = finalise_editorial_assets(
                Path(args.article), Path(args.draft), Path(args.assets), Path(args.production) if args.production else None,
            )
            print(json.dumps({"status": "created", "editorial_assets": str(Path(args.assets).resolve()), "cover_outputs": assets["cover_art"]["outputs"]}, ensure_ascii=False))
        elif args.command == "validate-editorial":
            editorial_article, editorial_paragraphs = load_editorial_article(Path(args.article))
            validate_editorial_draft(editorial_article, editorial_paragraphs, read_editorial_json(Path(args.draft)))
            print(json.dumps({"status": "valid"}, ensure_ascii=False))
        else:
            result = validate_script(Path(args.article), Path(args.script), args.language)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
