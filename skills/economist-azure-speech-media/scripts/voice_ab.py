#!/usr/bin/env python3
"""Create a controlled Azure Neural Voice comparison without changing a production package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from azure_speech_media import AzureSpeechProvider, MediaError, duration_seconds, sha256_bytes, write_json


CANDIDATE_VOICES = (
    "en-US-JennyNeural",
    "en-US-GuyNeural",
    "en-US-AriaNeural",
    "en-US-DavisNeural",
    "en-US-SaraNeural",
)


ARIA_AB_VARIANTS = (
    {
        "id": "aria-neutral",
        "label": "Aria neutral with paragraph structure",
        "delivery": {"structure": "paragraph"},
    },
    {
        "id": "aria-narration-professional",
        "label": "Aria narration-professional",
        "delivery": {"style": "narration-professional", "style_degree": 1.1, "structure": "paragraph"},
    },
    {
        "id": "aria-newscast-casual",
        "label": "Aria newscast-casual",
        "delivery": {"style": "newscast-casual", "style_degree": 1.0, "structure": "paragraph"},
    },
    {
        "id": "aria-balanced-prosody",
        "label": "Aria narration-professional with balanced prosody",
        "delivery": {
            "style": "narration-professional",
            "style_degree": 1.1,
            "rate": "-3%",
            "pitch": "-1st",
            "structure": "paragraph",
            "pre_break_ms": 80,
            "post_break_ms": 140,
        },
    },
)


def select_candidates(available: list[dict[str, Any]], candidates: tuple[str, ...] = CANDIDATE_VOICES) -> list[dict[str, Any]]:
    by_name = {str(item.get("short_name", "")): item for item in available}
    return [by_name[name] for name in candidates if name in by_name]


def sample_segment(script_path: Path, segment_id: str = "en-001") -> dict[str, Any]:
    payload = json.loads(script_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise MediaError("Voice comparison needs a frozen English script array.")
    segment = next((item for item in payload if isinstance(item, dict) and item.get("segment_id") == segment_id), None)
    if not isinstance(segment, dict) or not isinstance(segment.get("spoken_text"), str) or not segment["spoken_text"].strip():
        raise MediaError(f"Voice comparison sample {segment_id} is unavailable.")
    return segment


def run_voice_ab(region: str, script_path: Path, output_dir: Path, provider: Any | None = None) -> dict[str, Any]:
    if provider is None:
        provider = AzureSpeechProvider(region)
    available = provider.list_voices("en-US")
    candidates = select_candidates(available)
    if len(candidates) < 3:
        raise MediaError("The configured Azure region has fewer than three approved Neural Voice candidates.")
    sample = sample_segment(script_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for voice in candidates:
        raw = provider.synthesize("en", voice["short_name"], sample["spoken_text"])
        if not isinstance(raw, dict) or not isinstance(raw.get("audio"), bytes):
            raise MediaError(f"Voice comparison synthesis failed for {voice['short_name']}.")
        audio_path = output_dir / f"{voice['short_name']}.wav"
        audio_path.write_bytes(raw["audio"])
        results.append({
            "voice": voice["short_name"],
            "styles": voice.get("styles", []),
            "audio": audio_path.name,
            "audio_sha256": sha256_bytes(raw["audio"]),
            "duration_seconds": round(duration_seconds(raw["audio"]), 3),
            "word_boundary_count": len(raw.get("word_boundaries") or []),
            "assessment": {
                "naturalness": None,
                "prosody": None,
                "pronunciation": None,
                "long_sentence_continuity": None,
                "listener_fatigue": None,
            },
        })
    report = {
        "format": "economist-azure-voice-ab",
        "schema_version": "1.0",
        "region": region,
        "sample": {"script": str(script_path.resolve()), "segment_id": sample["segment_id"], "character_count": len(sample["spoken_text"])},
        "candidate_source": "azure_voice_list_api_via_speech_sdk",
        "results": results,
    }
    write_json(output_dir / "voice-ab.json", report)
    return report


def run_aria_ab(region: str, script_path: Path, output_dir: Path, provider: Any | None = None) -> dict[str, Any]:
    """Compare four SSML deliveries using the same live Aria voice."""
    if provider is None:
        provider = AzureSpeechProvider(region)
    available = provider.list_voices("en-US")
    by_name = {str(item.get("short_name", "")): item for item in available}
    aria = by_name.get("en-US-AriaNeural")
    if aria is None:
        raise MediaError("The configured Azure region does not expose en-US-AriaNeural.")
    available_styles = set(aria.get("styles") or [])
    required_styles = {variant["delivery"]["style"] for variant in ARIA_AB_VARIANTS if variant["delivery"].get("style")}
    missing_styles = sorted(required_styles - available_styles)
    if missing_styles:
        raise MediaError(f"Aria styles are unavailable in the configured region: {', '.join(missing_styles)}")
    sample = sample_segment(script_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for variant in ARIA_AB_VARIANTS:
        delivery = variant["delivery"]
        raw = provider.synthesize("en", "en-US-AriaNeural", sample["spoken_text"], delivery)
        if not isinstance(raw, dict) or not isinstance(raw.get("audio"), bytes):
            raise MediaError(f"Aria synthesis failed for {variant['id']}.")
        audio_path = output_dir / f"{variant['id']}.wav"
        audio_path.write_bytes(raw["audio"])
        results.append({
            "id": variant["id"],
            "label": variant["label"],
            "voice": "en-US-AriaNeural",
            "styles": aria.get("styles", []),
            "delivery": delivery,
            "audio": audio_path.name,
            "audio_sha256": sha256_bytes(raw["audio"]),
            "duration_seconds": round(duration_seconds(raw["audio"]), 3),
            "word_boundary_count": len(raw.get("word_boundaries") or []),
            "assessment": {
                "naturalness": None,
                "prosody": None,
                "pronunciation": None,
                "long_sentence_continuity": None,
                "listener_fatigue": None,
            },
        })
    report = {
        "format": "economist-azure-aria-ssml-ab",
        "schema_version": "1.0",
        "region": region,
        "voice": "en-US-AriaNeural",
        "sample": {"script": str(script_path.resolve()), "segment_id": sample["segment_id"], "character_count": len(sample["spoken_text"])},
        "candidate_source": "azure_voice_list_api_via_speech_sdk",
        "results": results,
    }
    write_json(output_dir / "aria-ab.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("voices", "aria"), default="voices")
    args = parser.parse_args()
    try:
        if args.mode == "aria":
            report = run_aria_ab(args.region, args.script.resolve(), args.out_dir.resolve())
            summary = {"status": "complete", "report": str((args.out_dir / "aria-ab.json").resolve()), "voice": report["voice"], "variants": [item["id"] for item in report["results"]]}
        else:
            report = run_voice_ab(args.region, args.script.resolve(), args.out_dir.resolve())
            summary = {"status": "complete", "report": str((args.out_dir / "voice-ab.json").resolve()), "voices": [item["voice"] for item in report["results"]]}
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except MediaError as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
