#!/usr/bin/env python3
"""Produce one selected Azure Speech podcast audio and caption variant.

The module keeps Azure SDK imports inside the live provider so unit tests can
exercise the complete package contract without credentials or the SDK.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from background_music import BackgroundMusicError, add_background_music, default_background_music_paths


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ENV_FILE = WORKSPACE_ROOT / ".env"
SCRIPT_FIELDS = {"segment_id", "speaker_id", "kind", "spoken_text", "source_paragraph_ids"}
VARIANTS = {"en", "en-zh", "zh-CN"}
TICKS_PER_SECOND = 10_000_000
MIN_CUE_SECONDS = 1.5
MAX_CUE_SECONDS = 7.0
MAX_ENGLISH_CHARS = 84
MAX_CHINESE_CHARS = 32


class MediaError(RuntimeError):
    """A safe, non-secret media-production failure."""


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def relative_path(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def duration_seconds(wav_bytes: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            if wav_file.getframerate() <= 0:
                raise MediaError("WAV sample rate must be positive.")
            return wav_file.getnframes() / wav_file.getframerate()
    except wave.Error as error:
        raise MediaError("Azure synthesis did not return a valid WAV file.") from error


def concatenate_wavs(items: list[bytes]) -> bytes:
    if not items:
        raise MediaError("No synthesized WAV segments were produced.")
    output = io.BytesIO()
    expected: tuple[int, int, int, str, str, int] | None = None
    with wave.open(output, "wb") as combined:
        for data in items:
            try:
                with wave.open(io.BytesIO(data), "rb") as item:
                    parameters = item.getparams()
                    signature = (
                        parameters.nchannels, parameters.sampwidth, parameters.framerate,
                        parameters.comptype, parameters.compname, parameters.nframes,
                    )
                    comparable = signature[:5]
                    if expected is None:
                        expected = comparable
                        combined.setparams(parameters)
                    elif comparable != expected:
                        raise MediaError("Synthesized WAV segments use incompatible audio formats.")
                    combined.writeframes(item.readframes(item.getnframes()))
            except wave.Error as error:
                raise MediaError("A cached segment is not a valid WAV file.") from error
    return output.getvalue()


def shift_alignment(aligned_segments: list[dict[str, Any]], offset_seconds: float) -> list[dict[str, Any]]:
    """Move the speech timeline onto the mixed track's absolute clock."""
    shifted: list[dict[str, Any]] = []
    for segment in aligned_segments:
        shifted.append({
            **segment,
            "start_seconds": round(segment["start_seconds"] + offset_seconds, 7),
            "end_seconds": round(segment["end_seconds"] + offset_seconds, 7),
            "words": [
                {
                    **word,
                    "start_seconds": round(word["start_seconds"] + offset_seconds, 7),
                    "end_seconds": round(word["end_seconds"] + offset_seconds, 7),
                }
                for word in segment["words"]
            ],
        })
    return shifted


def ticks(value: Any) -> int:
    if hasattr(value, "total_seconds"):
        return round(float(value.total_seconds()) * TICKS_PER_SECOND)
    return int(value)


def normal_boundary_type(value: Any) -> str:
    return str(value).rsplit(".", 1)[-1].lower()


def is_caption_boundary(value: Any) -> bool:
    name = normal_boundary_type(value)
    # DragonHD can emit zero-duration punctuation callbacks slightly out of
    # temporal order. Approved script text supplies punctuation for captions;
    # only word callbacks are reliable alignment events.
    return name == "word"


def escape_ssml_text(text: str) -> tuple[str, list[int]]:
    """Escape text and map SSML-content character positions back to script positions."""
    pieces: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(text):
        escaped = html.escape(character)
        pieces.append(escaped)
        offsets.extend([index] * len(escaped))
    offsets.append(len(text))
    return "".join(pieces), offsets


_STYLE_RE = re.compile(r"[A-Za-z][A-Za-z-]*")
_RATE_RE = re.compile(r"(?:[+-]?\d+(?:\.\d+)?%|(?:0\.[5-9]\d*|1(?:\.\d+)?|2(?:\.0+)?)|x-slow|slow|medium|fast|x-fast)")
_PITCH_RE = re.compile(r"(?:[+-]?\d+(?:\.\d+)?(?:Hz|st|%)|\d+(?:\.\d+)?Hz|x-low|low|medium|high|x-high)")
_VOLUME_RE = re.compile(r"(?:[+-]?\d+(?:\.\d+)?(?:%|)|silent|x-soft|soft|medium|loud|x-loud)")
_CONTOUR_RE = re.compile(r"\(\d+(?:\.\d+)?%,[+-]?\d+(?:\.\d+)?(?:Hz|st|%)\)(?:\s+\(\d+(?:\.\d+)?%,[+-]?\d+(?:\.\d+)?(?:Hz|st|%)\))*")
DRAGON_HD_SUFFIX = ":dragonhdlatestneural"
DRAGON_HD_PARAMETER_NAMES = {"temperature"}


def is_dragon_hd_voice(voice: str) -> bool:
    return voice.casefold().endswith(DRAGON_HD_SUFFIX)


def format_ssml_parameter(value: float) -> str:
    return format(value, "g")


def normalise_voice_parameters(voice: str, parameters: Any) -> dict[str, float]:
    if parameters is None:
        return {}
    if not isinstance(parameters, dict):
        raise MediaError("Voice parameters must be an object.")
    if not parameters:
        return {}
    if not is_dragon_hd_voice(voice):
        raise MediaError("Voice parameters are supported only for DragonHD voices.")
    if set(parameters) - DRAGON_HD_PARAMETER_NAMES:
        raise MediaError("DragonHD voice parameters contain an unsupported key.")
    temperature = parameters.get("temperature")
    if not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or not 0 <= float(temperature) <= 1:
        raise MediaError("DragonHD temperature must be a number from 0 to 1.")
    return {"temperature": float(temperature)}


def normalise_voice_configuration(value: Any) -> dict[str, Any]:
    """Accept legacy voice strings and the structured DragonHD voice contract."""
    if isinstance(value, str) and value.strip():
        return {"name": value.strip(), "parameters": {}}
    if not isinstance(value, dict) or set(value) - {"name", "parameters"}:
        raise MediaError("Voice configuration must be a voice name or an object with name and parameters.")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MediaError("Voice configuration needs a non-empty name.")
    name = name.strip()
    return {"name": name, "parameters": normalise_voice_parameters(name, value.get("parameters", {}))}


def validate_delivery(delivery: Any, voice: str | None = None) -> dict[str, Any]:
    """Validate the supported SSML delivery controls before sending them to Azure."""
    if delivery is None:
        return {}
    if not isinstance(delivery, dict):
        raise MediaError("Speech delivery configuration must be an object.")
    result = dict(delivery)
    style = result.get("style")
    if style is not None and (not isinstance(style, str) or not _STYLE_RE.fullmatch(style)):
        raise MediaError("Speech delivery style is invalid.")
    role = result.get("role")
    if role is not None and (not isinstance(role, str) or not _STYLE_RE.fullmatch(role)):
        raise MediaError("Speech delivery role is invalid.")
    style_degree = result.get("style_degree")
    if style_degree is not None and (
        not isinstance(style_degree, (int, float)) or isinstance(style_degree, bool) or not 0.01 <= float(style_degree) <= 2.0
    ):
        raise MediaError("Speech style_degree must be between 0.01 and 2.0.")
    for key, pattern in (("rate", _RATE_RE), ("pitch", _PITCH_RE), ("range", _PITCH_RE), ("volume", _VOLUME_RE)):
        value = result.get(key)
        if value is not None and (not isinstance(value, str) or not pattern.fullmatch(value)):
            raise MediaError(f"Speech delivery {key} is invalid.")
        if key == "rate" and isinstance(value, str) and value.endswith("%"):
            try:
                percentage = float(value[:-1])
            except ValueError as error:
                raise MediaError("Speech delivery rate is invalid.") from error
            if percentage < -50 or percentage > 100:
                raise MediaError("Speech delivery rate is outside Azure's 0.5x to 2x range.")
    contour = result.get("contour")
    if contour is not None and (not isinstance(contour, str) or not _CONTOUR_RE.fullmatch(contour.strip())):
        raise MediaError("Speech delivery contour is invalid.")
    structure = result.get("structure", "paragraph")
    if structure not in {"none", "paragraph", "sentence"}:
        raise MediaError("Speech delivery structure must be none, paragraph, or sentence.")
    for key in ("pre_break_ms", "post_break_ms"):
        value = result.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10000):
            raise MediaError(f"Speech delivery {key} must be an integer from 0 to 10000.")
    if voice is not None and is_dragon_hd_voice(voice):
        unsupported = {"style", "role", "style_degree", "rate", "pitch", "range", "volume", "contour"}.intersection(result)
        if unsupported:
            raise MediaError("DragonHD voices do not support express-as or prosody delivery controls.")
    return result


def source_span_from_ssml(
    raw_offset: int, raw_length: int, content_start: int, offsets: list[int], text_length: int,
) -> tuple[int, int]:
    start = raw_offset - content_start
    end = start + raw_length
    if start < 0 or end < start or start >= len(offsets) or end >= len(offsets):
        raise MediaError("Azure WordBoundary text span is outside the generated SSML content.")
    source_start = offsets[start]
    source_end = offsets[end]
    if source_end <= source_start or source_end > text_length:
        raise MediaError("Azure WordBoundary could not be mapped to the approved script.")
    return source_start, source_end


def validate_script(value: Any, language: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise MediaError("Selected script must be a non-empty JSON array.")
    prefix = "en" if language == "en" else "zh-CN"
    for position, segment in enumerate(value, start=1):
        if not isinstance(segment, dict) or set(segment) != SCRIPT_FIELDS:
            raise MediaError("Selected script violates the five-field segment contract.")
        if segment["segment_id"] != f"{prefix}-{position:03d}":
            raise MediaError("Selected script has non-consecutive segment IDs.")
        if not isinstance(segment["spoken_text"], str) or not segment["spoken_text"].strip():
            raise MediaError("Selected script has an empty spoken segment.")
    return value


def env_file_value(path: Path, name: str) -> str | None:
    """Read one simple local dotenv value without evaluating shell syntax."""
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise MediaError("Azure Speech credentials are unavailable.") from error
    assignment = re.compile(rf"^(?:export\s+)?{re.escape(name)}\s*=\s*(.*)$")
    for line in lines:
        match = assignment.match(line.strip())
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def load_credentials(env_file: Path | None = None) -> str:
    """Prefer process credentials, with a local workspace dotenv fallback."""
    key = os.environ.get("AZURE_SPEECH_KEY") or env_file_value(env_file or WORKSPACE_ENV_FILE, "AZURE_SPEECH_KEY")
    if not key:
        raise MediaError("Azure Speech credentials are unavailable.")
    return key


def build_ssml(
    language: str,
    voice: str,
    text: str,
    delivery: Any = None,
    voice_parameters: Any = None,
) -> tuple[str, int, list[int]]:
    """Build a safe in-memory SSML document and its text-offset mapping."""
    delivery_config = validate_delivery(delivery, voice)
    parameter_config = normalise_voice_parameters(voice, voice_parameters)
    locale = "zh-CN" if language == "zh-CN" else "en-US"
    style = delivery_config.get("style")
    role = delivery_config.get("role")
    namespace = ' xmlns:mstts="https://www.w3.org/2001/mstts"' if style or role else ""
    parameter_attribute = ""
    if parameter_config:
        serialized = ";".join(f"{name}={format_ssml_parameter(value)}" for name, value in sorted(parameter_config.items()))
        parameter_attribute = f' parameters="{html.escape(serialized, quote=True)}"'
    opening = (
        f'<speak version="1.0" xml:lang="{locale}" xmlns="http://www.w3.org/2001/10/synthesis"{namespace}>'
        f'<voice name="{html.escape(voice, quote=True)}"{parameter_attribute}>'
    )
    escaped_text, ssml_offsets = escape_ssml_text(text)
    structure = delivery_config.get("structure", "paragraph")
    content_opening = ""
    content_closing = ""
    pre_break_ms = delivery_config.get("pre_break_ms")
    post_break_ms = delivery_config.get("post_break_ms")
    if pre_break_ms:
        content_opening += f'<break time="{pre_break_ms}ms"/>'
    if structure == "paragraph":
        content_opening += "<p>"
        content_closing = "</p>" + content_closing
    elif structure == "sentence":
        content_opening += "<s>"
        content_closing = "</s>" + content_closing
    if style or role:
        style_degree = delivery_config.get("style_degree")
        degree = f' styledegree="{float(style_degree):.1f}"' if isinstance(style_degree, (int, float)) else ""
        attributes = ""
        if style:
            attributes += f' style="{html.escape(style, quote=True)}"'
        if role:
            attributes += f' role="{html.escape(role, quote=True)}"'
        content_opening += f'<mstts:express-as{attributes}{degree}>'
        content_closing = "</mstts:express-as>" + content_closing
    prosody_fields = ("rate", "pitch", "range", "contour", "volume")
    prosody_attributes = "".join(
        f' {name}="{html.escape(str(delivery_config[name]), quote=True)}"'
        for name in prosody_fields if delivery_config.get(name) is not None
    )
    if prosody_attributes:
        content_opening += f"<prosody{prosody_attributes}>"
        content_closing = "</prosody>" + content_closing
    if post_break_ms:
        content_closing += f'<break time="{post_break_ms}ms"/>'
    return f"{opening}{content_opening}{escaped_text}{content_closing}</voice></speak>", len(opening) + len(content_opening), ssml_offsets


class AzureSpeechProvider:
    """Thin live adapter; all secrets remain inside this process."""

    def __init__(self, region: str):
        if not region:
            raise MediaError("production.json needs an Azure Speech region.")
        self.region = region
        self.key = load_credentials()
        try:
            import azure.cognitiveservices.speech as speechsdk
            from azure.cognitiveservices.speech.translation import SpeechTranslationConfig, TranslationRecognizer
        except ImportError as error:
            raise MediaError("Azure Speech SDK is not installed. Install azure-cognitiveservices-speech.") from error
        self.sdk = speechsdk
        self.SpeechTranslationConfig = SpeechTranslationConfig
        self.TranslationRecognizer = TranslationRecognizer

    def list_voices(self, locale: str) -> list[dict[str, Any]]:
        config = self.sdk.SpeechConfig(subscription=self.key, region=self.region)
        synthesizer = self.sdk.SpeechSynthesizer(speech_config=config, audio_config=None)
        result = synthesizer.get_voices_async(locale).get()
        voices = getattr(result, "voices", None)
        if voices is None:
            raise MediaError("Azure voice-list request failed.")
        return [
            {
                "short_name": str(getattr(voice, "short_name", "")),
                "styles": list(getattr(voice, "style_list", None) or []),
            }
            for voice in voices
            if str(getattr(voice, "short_name", ""))
        ]

    def synthesize(
        self,
        language: str,
        voice: str,
        text: str,
        delivery: dict[str, Any] | None = None,
        voice_parameters: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        sdk = self.sdk
        config = sdk.SpeechConfig(subscription=self.key, region=self.region)
        config.speech_synthesis_voice_name = voice
        config.set_property(sdk.PropertyId.SpeechServiceResponse_RequestWordBoundary, "true")
        config.set_speech_synthesis_output_format(sdk.SpeechSynthesisOutputFormat.Riff24Khz16BitMonoPcm)
        boundaries: list[dict[str, Any]] = []
        ssml, content_start, ssml_offsets = build_ssml(language, voice, text, delivery, voice_parameters)
        synthesizer = sdk.SpeechSynthesizer(speech_config=config, audio_config=None)

        def received(event: Any) -> None:
            if not is_caption_boundary(event.boundary_type):
                return
            text_offset, text_end = source_span_from_ssml(
                int(event.text_offset), int(event.word_length), content_start, ssml_offsets, len(text),
            )
            boundaries.append({
                "boundary_type": normal_boundary_type(event.boundary_type),
                "audio_offset_ticks": ticks(event.audio_offset),
                "duration_ticks": ticks(event.duration),
                "text_offset": text_offset,
                "word_length": text_end - text_offset,
            })

        synthesizer.synthesis_word_boundary.connect(received)
        result = synthesizer.speak_ssml_async(ssml).get()
        if result.reason != sdk.ResultReason.SynthesizingAudioCompleted:
            raise MediaError("Azure synthesis request failed.")
        return {"audio": bytes(result.audio_data), "word_boundaries": boundaries}

    def translate(self, audio_path: Path, source_locale: str, target_locale: str) -> list[dict[str, Any]]:
        config = self.SpeechTranslationConfig(subscription=self.key, region=self.region)
        config.speech_recognition_language = source_locale
        config.add_target_language(target_locale)
        recognizer = self.TranslationRecognizer(
            translation_config=config, audio_config=self.sdk.audio.AudioConfig(filename=str(audio_path)),
        )
        completed = threading.Event()
        failures: list[str] = []
        results: list[dict[str, Any]] = []

        def recognized(event: Any) -> None:
            result = event.result
            if result.reason == self.sdk.ResultReason.TranslatedSpeech:
                results.append({
                    "offset_ticks": ticks(result.offset),
                    "duration_ticks": ticks(result.duration),
                    "source_text": result.text or "",
                    "translated_text": result.translations.get(target_locale, "") or "",
                })

        def canceled(event: Any) -> None:
            details = event.result.cancellation_details
            if "Error" in str(details.reason):
                failures.append("Azure speech translation request failed.")
            completed.set()

        recognizer.recognized.connect(recognized)
        recognizer.canceled.connect(canceled)
        recognizer.session_stopped.connect(lambda _: completed.set())
        recognizer.start_continuous_recognition_async().get()
        if not completed.wait(timeout=15 * 60):
            recognizer.stop_continuous_recognition_async().get()
            raise MediaError("Azure speech translation request timed out.")
        recognizer.stop_continuous_recognition_async().get()
        if failures:
            raise MediaError(failures[0])
        return results


def validate_boundaries(text: str, boundaries: Any) -> list[dict[str, Any]]:
    if not isinstance(boundaries, list):
        raise MediaError("Azure synthesis did not return WordBoundary events.")
    result: list[dict[str, Any]] = []
    previous = -1
    for boundary in boundaries:
        if not isinstance(boundary, dict) or not is_caption_boundary(boundary.get("boundary_type", "word")):
            continue
        offset = int(boundary["audio_offset_ticks"])
        duration = int(boundary["duration_ticks"])
        text_offset = int(boundary["text_offset"])
        word_length = int(boundary["word_length"])
        if offset < previous or duration < 0 or text_offset < 0 or word_length <= 0:
            raise MediaError("Azure WordBoundary offsets are invalid or non-monotonic.")
        end = text_offset + word_length
        if end > len(text):
            raise MediaError("Azure WordBoundary text span exceeds the approved script.")
        source_text = text[text_offset:end]
        if not source_text:
            raise MediaError("Azure WordBoundary selected an empty script span.")
        result.append({
            "start_seconds": offset / TICKS_PER_SECOND,
            "end_seconds": (offset + duration) / TICKS_PER_SECOND,
            "text_offset": text_offset,
            "word_length": word_length,
            "text": source_text,
        })
        previous = offset
    if not result:
        raise MediaError("Azure synthesis returned no usable WordBoundary events.")
    return result


def cue_text(text: str, start: int, end: int) -> str:
    return re.sub(r"\s+", " ", text[start:end]).strip()


def script_cues(alignment: dict[str, Any], language: str) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for segment in alignment["segments"]:
        text = segment["spoken_text"]
        current: list[dict[str, Any]] = []

        def flush() -> None:
            if not current:
                return
            start_offset = current[0]["text_offset"]
            end_offset = current[-1]["text_offset"] + current[-1]["word_length"]
            start = current[0]["start_seconds"]
            end = current[-1]["end_seconds"]
            groups.append({"start_seconds": start, "end_seconds": end, "text": cue_text(text, start_offset, end_offset)})
            current.clear()

        for word in segment["words"]:
            current.append(word)
            if word["text"].endswith((".", "!", "?", "。", "！", "？")):
                flush()
        flush()
    return normalize_cues(groups)


def bilingual_display_cues(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Legacy phrase display only; never slice text or manufacture cue timings.

    Azure Translation phrases are retained for older packages, but they are not
    sentence-aligned and therefore cannot satisfy the current publication
    contract.  The renderer may still read them unchanged for compatibility.
    """
    return normalize_cues([
        {"start_seconds": phrase["start_seconds"], "end_seconds": phrase["end_seconds"],
         "text": f"{phrase['source_text']}\n{phrase['translated_text']}"}
        for phrase in phrases
    ])


def readable_characters(value: str) -> int:
    return len(re.sub(r"[\s\W_]", "", value, flags=re.UNICODE))


def reviewed_bilingual_cues_legacy(alignment: dict[str, Any], subtitle_script: dict[str, Any]) -> list[dict[str, Any]]:
    """Read the pre-5.0 reviewed contract without changing old production packages."""
    if not isinstance(subtitle_script, dict) or subtitle_script.get("translation_quality") != "reviewed":
        raise MediaError("en-zh publication captions require a reviewed subtitle script.")
    units = subtitle_script.get("units")
    if not isinstance(units, list) or not units:
        raise MediaError("Reviewed subtitle script has no units.")
    segments = {item["segment_id"]: item for item in alignment.get("segments", [])}
    if not segments:
        raise MediaError("English WordBoundary alignment is unavailable for reviewed captions.")
    previous_by_segment: dict[str, int] = {}
    result: list[dict[str, Any]] = []
    previous_end = -1.0
    for unit in units:
        required = {"unit_id", "segment_id", "source_start", "source_end", "source_text", "source_paragraph_ids", "translation_zh"}
        if not isinstance(unit, dict) or not required.issubset(unit):
            raise MediaError("Reviewed subtitle unit has an invalid contract.")
        segment_id = str(unit["segment_id"])
        segment = segments.get(segment_id)
        if segment is None:
            raise MediaError("Reviewed subtitle unit refers to an unknown English segment.")
        start = int(unit["source_start"])
        end = int(unit["source_end"])
        source_text = str(unit["source_text"])
        chinese = str(unit["translation_zh"]).strip()
        spoken = str(segment["spoken_text"])
        if start < 0 or end <= start or end > len(spoken) or spoken[start:end] != source_text:
            raise MediaError("Reviewed subtitle source span does not match the frozen English script.")
        prior = previous_by_segment.get(segment_id, 0)
        if spoken[prior:start].strip():
            raise MediaError("Reviewed subtitle units do not cover the English script in order.")
        previous_by_segment[segment_id] = end
        if unit["source_paragraph_ids"] != segment["source_paragraph_ids"]:
            raise MediaError("Reviewed subtitle source links do not match the frozen English segment.")
        if not chinese or "\n" in chinese or "\r" in chinese:
            raise MediaError("Reviewed Chinese subtitle text must be one non-empty logical line.")
        if len(source_text) > MAX_ENGLISH_CHARS or len(chinese) > MAX_CHINESE_CHARS:
            raise MediaError("Reviewed subtitle unit exceeds the two-line display limit.")
        if re.search(r"[A-Za-z]{4,}\s+[A-Za-z]{4,}", chinese):
            raise MediaError("Reviewed Chinese subtitle contains an English clause.")
        words = [word for word in segment.get("words", []) if word["text_offset"] + word["word_length"] > start and word["text_offset"] < end]
        if not words:
            raise MediaError("Reviewed subtitle unit cannot be mapped to English WordBoundary events.")
        cue_start = float(words[0]["start_seconds"])
        cue_end = float(words[-1]["end_seconds"])
        duration = cue_end - cue_start
        if duration < MIN_CUE_SECONDS or duration > MAX_CUE_SECONDS:
            raise MediaError("Reviewed subtitle cue duration is outside the readable 1.5–7 second range.")
        if readable_characters(source_text) / duration > 20 or readable_characters(chinese) / duration > 9:
            raise MediaError("Reviewed subtitle cue exceeds the readable character-per-second limit.")
        if cue_start < previous_end - 0.0001:
            raise MediaError("Reviewed subtitle cue timing overlaps.")
        result.append({
            "cue_id": str(unit["unit_id"]), "start_seconds": round(cue_start, 7), "end_seconds": round(cue_end, 7),
            "en_text": source_text, "zh_text": chinese, "segment_id": segment_id,
            "source_paragraph_ids": unit["source_paragraph_ids"],
        })
        previous_end = cue_end
    for segment_id, segment in segments.items():
        if str(segment["spoken_text"])[previous_by_segment.get(segment_id, 0):].strip():
            raise MediaError("Reviewed subtitle units do not completely cover the English script.")
    return result


def reviewed_bilingual_cues(alignment: dict[str, Any], subtitle_script: Any) -> list[dict[str, Any]]:
    """Project reviewed complete-sentence units onto the English WordBoundary clock."""
    if not isinstance(subtitle_script, dict) or subtitle_script.get("translation_quality") != "reviewed":
        raise MediaError("en-zh publication captions require a reviewed subtitle script.")
    if str(subtitle_script.get("schema_version")) == "1.0":
        return reviewed_bilingual_cues_legacy(alignment, subtitle_script)
    if str(subtitle_script.get("schema_version")) != "2.0" or subtitle_script.get("caption_unit_policy") != "full_sentence":
        raise MediaError("en-zh publication captions require the 2.0 full-sentence subtitle contract.")
    units = subtitle_script.get("units")
    if not isinstance(units, list) or not units:
        raise MediaError("Reviewed subtitle script has no units.")
    ordered_segments = alignment.get("segments", [])
    segments = {item["segment_id"]: item for item in ordered_segments}
    if not segments:
        raise MediaError("English WordBoundary alignment is unavailable for reviewed captions.")
    order = [str(item["segment_id"]) for item in ordered_segments]
    segment_index, cursor, previous_end = 0, 0, -1.0
    result: list[dict[str, Any]] = []
    for unit in units:
        required = {"unit_id", "source_text", "source_spans", "source_paragraph_ids", "translation_zh"}
        if not isinstance(unit, dict) or not required.issubset(unit) or not isinstance(unit["source_spans"], list) or not unit["source_spans"]:
            raise MediaError("Reviewed sentence subtitle unit has an invalid contract.")
        chinese = str(unit["translation_zh"]).strip()
        if not chinese or "\n" in chinese or "\r" in chinese:
            raise MediaError("Reviewed Chinese subtitle text must be one non-empty logical line.")
        if not re.search(r"[。！？]$", chinese):
            raise MediaError("Reviewed subtitle unit must be a complete Chinese sentence.")
        selected_parts: list[str] = []
        words: list[dict[str, Any]] = []
        paragraph_ids: list[str] = []
        segment_ids: list[str] = []
        for span in unit["source_spans"]:
            if not isinstance(span, dict) or set(span) != {"segment_id", "source_start", "source_end"}:
                raise MediaError("Reviewed sentence subtitle source spans are invalid.")
            segment_id = str(span["segment_id"])
            if segment_index >= len(order) or segment_id != order[segment_index]:
                raise MediaError("Reviewed sentence subtitle units are out of source order.")
            segment = segments[segment_id]
            spoken = str(segment["spoken_text"])
            start, end = span["source_start"], span["source_end"]
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start or end > len(spoken):
                raise MediaError("Reviewed sentence subtitle source span does not match the frozen English script.")
            if spoken[cursor:start].strip():
                raise MediaError("Reviewed sentence subtitle units do not completely cover the English script.")
            selected = spoken[start:end]
            if not selected.strip():
                raise MediaError("Reviewed sentence subtitle source span is empty.")
            selected_parts.append(selected.strip())
            words.extend(word for word in segment.get("words", []) if word["text_offset"] + word["word_length"] > start and word["text_offset"] < end)
            segment_ids.append(segment_id)
            for paragraph_id in segment["source_paragraph_ids"]:
                if paragraph_id not in paragraph_ids:
                    paragraph_ids.append(paragraph_id)
            cursor = end
            if not spoken[cursor:].strip():
                segment_index += 1
                cursor = 0
        source_text = " ".join(selected_parts)
        if re.sub(r"\s+", " ", str(unit["source_text"])).strip() != source_text:
            raise MediaError("Reviewed sentence subtitle text does not match its frozen source spans.")
        if unit["source_paragraph_ids"] != paragraph_ids:
            raise MediaError("Reviewed sentence subtitle source links do not match the frozen English segments.")
        if not re.search(r"[.!?][\"')\]}”’]*$", source_text):
            raise MediaError("Reviewed subtitle unit must be a complete English sentence.")
        if re.search(r"[A-Za-z]{4,}\s+[A-Za-z]{4,}", chinese):
            raise MediaError("Reviewed Chinese subtitle contains an English clause.")
        if not words:
            raise MediaError("Reviewed subtitle unit cannot be mapped to English WordBoundary events.")
        cue_start, cue_end = float(words[0]["start_seconds"]), float(words[-1]["end_seconds"])
        if cue_start < previous_end - 0.0001 or cue_end <= cue_start:
            raise MediaError("Reviewed subtitle cue timing overlaps or is invalid.")
        result.append({
            "cue_id": str(unit["unit_id"]), "start_seconds": round(cue_start, 7), "end_seconds": round(cue_end, 7),
            "en_text": source_text, "zh_text": chinese, "segment_id": segment_ids[0], "segment_ids": segment_ids,
            "source_paragraph_ids": paragraph_ids,
        })
        previous_end = cue_end
    if segment_index != len(order):
        raise MediaError("Reviewed sentence subtitle units do not completely cover the English script.")
    return result


def write_caption_cues(root: Path, base: str, cues: list[dict[str, Any]]) -> Path:
    path = root / f"caption-cues.{base}.json"
    write_json(path, {"schema_version": "1.0", "variant": base, "cues": cues})
    return path


def export_bilingual_cues(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"start_seconds": cue["start_seconds"], "end_seconds": cue["end_seconds"], "text": f"{cue['en_text']}\n{cue['zh_text']}"}
        for cue in cues
    ]


def normalize_cues(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not cues:
        raise MediaError("No caption cues were generated.")
    normalized: list[dict[str, Any]] = []
    previous_end = 0.0
    for position, cue in enumerate(cues):
        start = float(cue["start_seconds"])
        end = float(cue["end_seconds"])
        if position + 1 < len(cues):
            end = min(end, float(cues[position + 1]["start_seconds"]))
        if start < previous_end - 0.0001:
            raise MediaError("Caption cues overlap.")
        if end <= start:
            raise MediaError("Caption cue has non-positive duration.")
        text = str(cue["text"]).strip()
        if not text:
            raise MediaError("Caption cue is empty.")
        normalized.append({"start_seconds": start, "end_seconds": end, "text": text})
        previous_end = end
    return normalized


def format_timestamp(seconds: float, srt: bool) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{',' if srt else '.'}{milliseconds:03d}"


def render_srt(cues: list[dict[str, Any]]) -> str:
    blocks = []
    for number, cue in enumerate(cues, start=1):
        blocks.append(
            f"{number}\n{format_timestamp(cue['start_seconds'], True)} --> {format_timestamp(cue['end_seconds'], True)}\n{cue['text']}"
        )
    return "\n\n".join(blocks) + "\n"


def render_vtt(cues: list[dict[str, Any]]) -> str:
    blocks = []
    for cue in cues:
        blocks.append(
            f"{format_timestamp(cue['start_seconds'], False)} --> {format_timestamp(cue['end_seconds'], False)}\n{cue['text']}"
        )
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def write_captions(root: Path, base: str, cues: list[dict[str, Any]]) -> dict[str, str]:
    srt_path = root / f"{base}.srt"
    vtt_path = root / f"{base}.vtt"
    srt_path.write_text(render_srt(cues), encoding="utf-8")
    vtt_path.write_text(render_vtt(cues), encoding="utf-8")
    return {"srt": str(srt_path), "vtt": str(vtt_path)}


def validate_translation(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise MediaError("Azure speech translation returned no caption phrases.")
    result: list[dict[str, Any]] = []
    previous = -1
    for item in value:
        offset = int(item["offset_ticks"])
        duration = int(item["duration_ticks"])
        source = str(item["source_text"]).strip()
        translated = str(item["translated_text"]).strip()
        if offset < previous or duration <= 0 or not source or not translated:
            raise MediaError("Azure speech translation returned invalid caption phrases.")
        result.append({
            "start_seconds": offset / TICKS_PER_SECOND,
            "end_seconds": (offset + duration) / TICKS_PER_SECOND,
            "source_text": source,
            "translated_text": translated,
        })
        previous = offset
    return result


def failure(production_path: Path, production: dict[str, Any], error: Exception) -> None:
    production["state"] = "failed"
    reason = str(error) if isinstance(error, (MediaError, ValueError)) else "Unexpected media-processing failure."
    production.setdefault("failures", []).append({"stage": "azure-speech-media", "reason": reason})
    write_json(production_path, production)


def selected_language(variant: str) -> str:
    return "zh-CN" if variant == "zh-CN" else "en"


def selected_script_path(root: Path, production: dict[str, Any], language: str) -> Path:
    name = "script_zh_cn" if language == "zh-CN" else "script_en"
    try:
        return root / production["artifacts"][name]
    except KeyError as error:
        raise MediaError("production.json has no script for the selected variant.") from error


def reviewed_subtitle_path(root: Path, production: dict[str, Any]) -> Path | None:
    reference = production.get("artifacts", {}).get("subtitle_script_en_zh")
    if not isinstance(reference, str):
        return None
    path = root / reference
    return path if path.is_file() else None


def materialize_reviewed_bilingual_captions(root: Path, production: dict[str, Any], alignment: dict[str, Any]) -> dict[str, str]:
    subtitle_path = reviewed_subtitle_path(root, production)
    if subtitle_path is None:
        raise MediaError("en-zh needs subtitle-script.en-zh.json before publication captions can be built.")
    cues = reviewed_bilingual_cues(alignment, read_json(subtitle_path))
    cue_path = write_caption_cues(root, "en-zh", cues)
    caption_paths = write_captions(root, "captions.en-zh", export_bilingual_cues(cues))
    artifacts = production.setdefault("artifacts", {})
    artifacts.update({
        "caption_cues_en_zh": relative_path(cue_path, root),
        "captions_en_zh_srt": relative_path(Path(caption_paths["srt"]), root),
        "captions_en_zh_vtt": relative_path(Path(caption_paths["vtt"]), root),
    })
    production.setdefault("captions", {}).update({
        "provider": "approved-bilingual-script",
        "translation_mode": "reviewed_source_linked",
        "translation_quality": "reviewed",
        "publication_status": "approved_for_rendering",
    })
    return artifacts


def rebuild_captions(production_path: Path) -> dict[str, Any]:
    """Rebuild reviewed en-zh captions from local script and WordBoundary artifacts only."""
    production = read_json(production_path)
    if production.get("variant") != "en-zh":
        raise MediaError("Local caption rebuild is only required for the en-zh variant.")
    root = production_path.parent.resolve()
    alignment_reference = production.get("artifacts", {}).get("alignment_en")
    if not isinstance(alignment_reference, str):
        raise MediaError("production.json has no English WordBoundary alignment.")
    alignment_path = root / alignment_reference
    if not alignment_path.is_file():
        raise MediaError("English WordBoundary alignment is missing.")
    materialize_reviewed_bilingual_captions(root, production, read_json(alignment_path))
    production["state"] = "complete"
    production["failures"] = []
    write_json(production_path, production)
    return {"status": "complete", "variant": "en-zh", "artifacts": production["artifacts"]}


def load_cached_segment(cache_audio: Path, cache_meta: Path, fingerprint: str) -> dict[str, Any] | None:
    if not cache_audio.exists() or not cache_meta.exists():
        return None
    meta = read_json(cache_meta)
    if meta.get("input_sha256") != fingerprint:
        return None
    return {"audio": cache_audio.read_bytes(), "word_boundaries": meta.get("word_boundaries")}


def run_media(production_path: Path, provider: Any | None = None) -> dict[str, Any]:
    production = read_json(production_path)
    root = production_path.parent.resolve()
    variant = production.get("variant")
    if variant not in VARIANTS:
        raise MediaError("production.json needs one supported variant.")
    language = selected_language(variant)
    try:
        script = validate_script(read_json(selected_script_path(root, production, language)), language)
        policy_version = float(production.get("script_generation", {}).get("policy_version", "0"))
        if variant == "en-zh" and policy_version >= 5.0 and reviewed_subtitle_path(root, production) is None:
            raise MediaError("en-zh policy 5.0 requires a reviewed 2.0 full-sentence subtitle script before synthesis.")
        speech = production["speech"]
        voice = speech["voices"][language]
        if provider is None:
            provider = AzureSpeechProvider(speech.get("region"))
        work = root / ".work" / "azure-speech-media" / variant / "segments"
        work.mkdir(parents=True, exist_ok=True)
        production["failures"] = []
        production["state"] = "running"
        progress = production.setdefault("progress", {}).setdefault("segments", {}).setdefault(language, {})
        write_json(production_path, production)

        audio_segments: list[bytes] = []
        aligned_segments: list[dict[str, Any]] = []
        cumulative = 0.0
        for segment in script:
            selected_voice = normalise_voice_configuration(voice[segment["speaker_id"]])
            delivery = speech.get("delivery", {}).get(language, {}).get(segment["speaker_id"])
            if delivery is not None and not isinstance(delivery, dict):
                raise MediaError("Speech delivery configuration must be an object.")
            delivery = validate_delivery(delivery, selected_voice["name"])
            fingerprint = sha256_json({
                "text": segment["spoken_text"],
                "voice": selected_voice["name"],
                "voice_parameters": selected_voice["parameters"],
                "language": language,
                "delivery": delivery,
            })
            cache_audio = work / f"{segment['segment_id']}.wav"
            cache_meta = work / f"{segment['segment_id']}.json"
            raw = load_cached_segment(cache_audio, cache_meta, fingerprint)
            if raw is None:
                raw = provider.synthesize(
                    language,
                    selected_voice["name"],
                    segment["spoken_text"],
                    delivery,
                    selected_voice["parameters"],
                )
                if not isinstance(raw, dict) or not isinstance(raw.get("audio"), bytes):
                    raise MediaError("Azure provider returned an invalid synthesis result.")
                cache_audio.write_bytes(raw["audio"])
                write_json(cache_meta, {"input_sha256": fingerprint, "word_boundaries": raw.get("word_boundaries")})
            local_words = validate_boundaries(segment["spoken_text"], raw["word_boundaries"])
            segment_duration = duration_seconds(raw["audio"])
            words = [
                {**word, "start_seconds": round(cumulative + word["start_seconds"], 7), "end_seconds": round(cumulative + word["end_seconds"], 7)}
                for word in local_words
            ]
            aligned_segments.append({
                "segment_id": segment["segment_id"],
                "speaker_id": segment["speaker_id"],
                "source_paragraph_ids": segment["source_paragraph_ids"],
                "spoken_text": segment["spoken_text"],
                "start_seconds": round(cumulative, 7),
                "end_seconds": round(cumulative + segment_duration, 7),
                "words": words,
            })
            audio_segments.append(raw["audio"])
            cumulative += segment_duration
            progress[segment["segment_id"]] = {
                "status": "complete", "input_sha256": fingerprint,
                "cache_audio": relative_path(cache_audio, root), "cache_alignment": relative_path(cache_meta, root),
            }
            write_json(production_path, production)

        voice_only_audio = concatenate_wavs(audio_segments)
        audio_path = root / "audio" / language / "final.wav"
        voice_only_path = audio_path.parent / "voice-only.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        voice_only_path.write_bytes(voice_only_audio)
        suffix = "zh_cn" if language == "zh-CN" else "en"
        artifacts = production.setdefault("artifacts", {})
        artifacts[f"voice_only_{suffix}"] = relative_path(voice_only_path, root)
        # The background-music helper reads the completed voice artifact as its input.
        artifacts[f"audio_{suffix}"] = relative_path(voice_only_path, root)
        write_json(production_path, production)

        defaults = default_background_music_paths()
        background_result = add_background_music(
            production_path,
            defaults["opening"],
            defaults["middle"],
            defaults["ending"],
            language,
            mixed_output_path=audio_path,
        )
        # The helper persists its stem/timeline metadata; refresh our state
        # before the media stage writes its final alignment and captions.
        production = read_json(production_path)
        artifacts = production.setdefault("artifacts", {})
        final_audio = audio_path.read_bytes()
        voice_offset = float(background_result["timeline"]["voice"]["caption_offset_seconds"])
        aligned_segments = shift_alignment(aligned_segments, voice_offset)
        alignment_path = root / f"alignment.{language}.json"
        alignment = {
            "schema_version": "1.0", "language": language, "provider": "azure-speech",
            "method": "azure_word_boundary", "script_sha256": sha256_json(script),
            "audio": {"path": relative_path(audio_path, root), "sha256": sha256_bytes(final_audio), "duration_seconds": round(duration_seconds(final_audio), 7)},
            "segments": aligned_segments,
        }
        write_json(alignment_path, alignment)
        artifacts[f"audio_{suffix}"] = relative_path(audio_path, root)
        artifacts[f"alignment_{suffix}"] = relative_path(alignment_path, root)

        if variant == "en-zh":
            if reviewed_subtitle_path(root, production) is not None:
                materialize_reviewed_bilingual_captions(root, production, alignment)
            else:
                # Legacy packages retain the former Azure Translation route, but are explicitly non-publishable.
                translation_cache = root / ".work" / "azure-speech-media" / variant / "translation.json"
                audio_hash = sha256_bytes(final_audio)
                if translation_cache.exists() and read_json(translation_cache).get("audio_sha256") == audio_hash:
                    translated = read_json(translation_cache)["phrases"]
                else:
                    translated = provider.translate(audio_path, "en-US", "zh-Hans")
                    write_json(translation_cache, {"audio_sha256": audio_hash, "phrases": translated})
                phrases = validate_translation(translated)
                translation_path = root / "translation.en-zh.json"
                translation = {
                    "schema_version": "1.1", "provider": "azure-speech-translation", "source_locale": "en-US", "target_locale": "zh-Hans",
                    "translation_mode": "azure_speech_translation", "translation_quality": "machine_unreviewed",
                    "audio": {"path": relative_path(audio_path, root), "sha256": audio_hash}, "phrases": phrases,
                }
                write_json(translation_path, translation)
                production.setdefault("captions", {}).update({
                    "translation_mode": "azure_speech_translation",
                    "translation_quality": "machine_unreviewed",
                    "publication_status": "review_required",
                })
                caption_paths = write_captions(root, "captions.en-zh", bilingual_display_cues(phrases))
                artifacts.update({"translation_en_zh": relative_path(translation_path, root), "captions_en_zh_srt": relative_path(Path(caption_paths["srt"]), root), "captions_en_zh_vtt": relative_path(Path(caption_paths["vtt"]), root)})
        else:
            cues = script_cues(alignment, language)
            base = "captions.zh-CN" if language == "zh-CN" else "captions.en"
            caption_paths = write_captions(root, base, cues)
            artifacts.update({f"captions_{suffix}_srt": relative_path(Path(caption_paths["srt"]), root), f"captions_{suffix}_vtt": relative_path(Path(caption_paths["vtt"]), root)})

        production["state"] = "complete"
        write_json(production_path, production)
        return {"status": "complete", "variant": variant, "artifacts": artifacts}
    except Exception as error:
        failure(production_path, production, error)
        if isinstance(error, MediaError):
            raise
        raise MediaError("Media production failed.") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("production", type=Path)
    parser.add_argument("--rebuild-captions", action="store_true", help="Use only local reviewed subtitle and WordBoundary artifacts; do not synthesize audio.")
    parser.add_argument("--add-background-music", action="store_true", help="Create timeline-aligned voice and background-music tracks from three local audio files.")
    parser.add_argument("--opening", type=Path, help="Opening background-music file, required with --add-background-music.")
    parser.add_argument("--middle", type=Path, help="Middle background-music file, required with --add-background-music.")
    parser.add_argument("--ending", type=Path, help="Ending background-music file, required with --add-background-music.")
    parser.add_argument("--language", choices=("en", "zh-CN"), help="Language track to align; defaults from production.variant.")
    arguments = parser.parse_args()
    try:
        if arguments.add_background_music and arguments.rebuild_captions:
            raise MediaError("--add-background-music and --rebuild-captions cannot be used together.")
        if arguments.add_background_music:
            if not all((arguments.opening, arguments.middle, arguments.ending)):
                raise MediaError("--add-background-music requires --opening, --middle, and --ending.")
            result = add_background_music(
                arguments.production,
                arguments.opening,
                arguments.middle,
                arguments.ending,
                arguments.language,
            )
        elif arguments.rebuild_captions:
            result = rebuild_captions(arguments.production)
        else:
            result = run_media(arguments.production)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (MediaError, BackgroundMusicError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
