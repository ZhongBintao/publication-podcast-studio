#!/usr/bin/env python3
"""Build a precisely timed, two-track podcast voice/background-music package."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any, NamedTuple


VOICE_START_SECONDS = 6.0
MIDDLE_DELAY_AFTER_VOICE_SECONDS = 5.0
ENDING_LEAD_SECONDS = 3.0
DEFAULT_SECTION_GAINS_DB = {"opening": 8.0, "middle": 10.0, "ending": 8.0}
DEFAULT_BACKGROUND_MUSIC_DIR = Path(__file__).resolve().parents[1] / "assets" / "background-music"
DEFAULT_BACKGROUND_MUSIC_FILES = {
    "opening": DEFAULT_BACKGROUND_MUSIC_DIR / "opening.mp3",
    "middle": DEFAULT_BACKGROUND_MUSIC_DIR / "middle-loop.mp3",
    "ending": DEFAULT_BACKGROUND_MUSIC_DIR / "ending.mp3",
}


class BackgroundMusicError(RuntimeError):
    """A safe, user-actionable background-music failure."""


class AudioFormat(NamedTuple):
    channels: int
    sample_width: int
    sample_rate: int

    @property
    def frame_width(self) -> int:
        return self.channels * self.sample_width


class AudioBuffer(NamedTuple):
    format: AudioFormat
    frames: bytes

    @property
    def frame_count(self) -> int:
        width = self.format.frame_width
        if width <= 0 or len(self.frames) % width:
            raise BackgroundMusicError("Audio data is not aligned to complete PCM frames.")
        return len(self.frames) // width

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.format.sample_rate


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def relative_path(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def input_path_reference(path: Path, root: Path) -> str:
    """Keep package-local inputs relative while preserving external source paths."""
    try:
        return relative_path(path, root)
    except ValueError:
        return str(path.resolve())


def default_background_music_paths() -> dict[str, Path]:
    missing = [str(path) for path in DEFAULT_BACKGROUND_MUSIC_FILES.values() if not path.is_file()]
    if missing:
        raise BackgroundMusicError(
            "The skill's default background-music assets are missing: " + ", ".join(missing)
        )
    return dict(DEFAULT_BACKGROUND_MUSIC_FILES)


def read_wav_bytes(data: bytes, label: str = "audio") -> AudioBuffer:
    try:
        with wave.open(io.BytesIO(data), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                raise BackgroundMusicError(f"{label} must contain uncompressed PCM audio.")
            audio_format = AudioFormat(
                channels=wav_file.getnchannels(),
                sample_width=wav_file.getsampwidth(),
                sample_rate=wav_file.getframerate(),
            )
            if audio_format.channels <= 0 or audio_format.sample_width <= 0 or audio_format.sample_rate <= 0:
                raise BackgroundMusicError(f"{label} has invalid WAV format parameters.")
            frames = wav_file.readframes(wav_file.getnframes())
    except wave.Error as error:
        raise BackgroundMusicError(f"{label} is not a readable PCM WAV file.") from error
    return AudioBuffer(audio_format, frames)


def write_wav(path: Path, audio: AudioBuffer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with wave.open(str(temporary), "wb") as wav_file:
        wav_file.setnchannels(audio.format.channels)
        wav_file.setsampwidth(audio.format.sample_width)
        wav_file.setframerate(audio.format.sample_rate)
        wav_file.writeframes(audio.frames)
    temporary.replace(path)


def ffmpeg_decode(path: Path, target: AudioFormat | None = None) -> AudioBuffer:
    if shutil.which("ffmpeg") is None:
        raise BackgroundMusicError(
            f"{path.name} is not a PCM WAV and ffmpeg is unavailable for audio conversion."
        )
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-vn"]
    if target is not None:
        if target.sample_width != 2:
            raise BackgroundMusicError("ffmpeg conversion currently requires 16-bit PCM output.")
        command.extend(["-ac", str(target.channels), "-ar", str(target.sample_rate), "-sample_fmt", "s16"])
    command.extend(["-f", "wav", "pipe:1"])
    try:
        result = subprocess.run(command, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        raise BackgroundMusicError(f"ffmpeg could not decode {path.name}: {detail}") from error
    return read_wav_bytes(result.stdout, path.name)


def load_audio(path: Path, target: AudioFormat | None = None) -> AudioBuffer:
    if not path.is_file():
        raise BackgroundMusicError(f"Audio input is missing: {path}")
    if path.suffix.casefold() == ".wav":
        try:
            audio = read_wav_bytes(path.read_bytes(), path.name)
            if target is None or audio.format == target:
                return audio
        except BackgroundMusicError:
            if target is None:
                raise
    return ffmpeg_decode(path, target)


def silence(format: AudioFormat, frame_count: int) -> bytes:
    if frame_count < 0:
        raise BackgroundMusicError("Audio frame count cannot be negative.")
    return b"\0" * (frame_count * format.frame_width)


def _place(buffer: bytearray, format: AudioFormat, start_frame: int, frames: bytes) -> None:
    if start_frame < 0:
        raise BackgroundMusicError("Audio placement cannot start before the timeline origin.")
    start = start_frame * format.frame_width
    end = start + len(frames)
    if end > len(buffer):
        raise BackgroundMusicError("An audio placement exceeds the computed timeline.")
    buffer[start:end] = frames


def scale_pcm_16bit(frames: bytes, gain_db: float) -> bytes:
    """Apply a finite gain to one 16-bit PCM stem without wrapping samples."""
    try:
        gain = 10 ** (float(gain_db) / 20.0)
    except (TypeError, ValueError) as error:
        raise BackgroundMusicError("Background music gain must be a finite number of decibels.") from error
    if not math.isfinite(gain) or gain < 0 or len(frames) % 2:
        raise BackgroundMusicError("Background music gain must be a finite level for 16-bit PCM audio.")
    scaled = bytearray()
    for (sample,) in struct.iter_unpack("<h", frames):
        scaled.extend(struct.pack("<h", max(-32768, min(32767, round(sample * gain)))))
    return bytes(scaled)


def _repeat_to_length(frames: bytes, frame_width: int, frame_count: int) -> bytes:
    if not frames or len(frames) % frame_width:
        raise BackgroundMusicError("The middle background music must contain complete PCM frames.")
    if frame_count <= 0:
        return b""
    source_frames = len(frames) // frame_width
    repeats = math.ceil(frame_count / source_frames)
    return (frames * repeats)[: frame_count * frame_width]


def mix_audio_tracks(
    voice: AudioBuffer, background: AudioBuffer, gain_db: float = 0.0, return_report: bool = False,
) -> AudioBuffer | tuple[AudioBuffer, dict[str, Any]]:
    """Mix aligned tracks while reducing only background if clipping would occur."""
    if voice.format != background.format or voice.frame_count != background.frame_count:
        raise BackgroundMusicError("Voice and background tracks must have identical PCM formats and lengths.")
    if voice.format.sample_width != 2:
        raise BackgroundMusicError("Automatic voice/background mixing currently requires 16-bit PCM audio.")
    try:
        gain = 10 ** (float(gain_db) / 20.0)
    except (TypeError, ValueError) as error:
        raise BackgroundMusicError("Background music gain must be a finite number of decibels.") from error
    if not math.isfinite(gain) or gain < 0:
        raise BackgroundMusicError("Background music gain must be a finite non-negative level.")
    voice_samples = [sample[0] for sample in struct.iter_unpack("<h", voice.frames)]
    background_samples = [round(sample[0] * gain) for sample in struct.iter_unpack("<h", background.frames)]
    background_scale = 1.0
    for voice_sample, background_sample in zip(voice_samples, background_samples):
        if not background_sample:
            continue
        # Calculate the available headroom in the direction the background is
        # moving. The voice remains unmodified; only this global background
        # scale is reduced when an actual sum would clip.
        limit = ((32767 - voice_sample) / background_sample if background_sample > 0
                 else (-32768 - voice_sample) / background_sample)
        background_scale = min(background_scale, max(0.0, limit))
    mixed = bytearray()
    peak = 0
    for voice_sample, background_sample in zip(voice_samples, background_samples):
        value = round(voice_sample + background_sample * background_scale)
        value = max(-32768, min(32767, value))
        peak = max(peak, abs(value))
        mixed.extend(struct.pack("<h", value))
    result = AudioBuffer(voice.format, bytes(mixed))
    report = {
        "peak_protection_applied": background_scale < 0.999999,
        "background_scale": round(background_scale, 9),
        "background_attenuation_db": round(20 * math.log10(background_scale), 7) if background_scale else None,
        "mixed_peak_sample": peak,
    }
    return (result, report) if return_report else result


def build_background_timeline(
    voice: AudioBuffer,
    opening: AudioBuffer,
    middle: AudioBuffer,
    ending: AudioBuffer,
    gains_db: dict[str, float] | None = None,
) -> tuple[AudioBuffer, AudioBuffer, dict[str, Any]]:
    """Return a timeline-aligned voice track, background track and audit data.

    The voice track starts with six seconds of silence so both exported tracks
    share one absolute clock. The canonical Azure voice WAV remains unchanged;
    this padded copy is the track to use with the generated background track.
    """
    audio_format = voice.format
    selected_gains = gains_db or {label: 0.0 for label in DEFAULT_SECTION_GAINS_DB}
    if set(selected_gains) != set(DEFAULT_SECTION_GAINS_DB):
        raise BackgroundMusicError("Background music gains must define opening, middle and ending.")
    if audio_format.sample_width != 2:
        raise BackgroundMusicError("Background music section gains currently require 16-bit PCM audio.")
    for label, audio in (("opening", opening), ("middle", middle), ("ending", ending)):
        if audio.format != audio_format:
            raise BackgroundMusicError(
                f"{label} background music format does not match the voice format."
            )
        if audio.frame_count <= 0:
            raise BackgroundMusicError(f"{label} background music is empty.")

    voice_start = round(VOICE_START_SECONDS * audio_format.sample_rate)
    voice_end = voice_start + voice.frame_count
    middle_start = voice_start + round(MIDDLE_DELAY_AFTER_VOICE_SECONDS * audio_format.sample_rate)
    ending_start = max(voice_start, voice_end - round(ENDING_LEAD_SECONDS * audio_format.sample_rate))
    middle_end = max(middle_start, ending_start)
    ending_end = ending_start + ending.frame_count
    total_frames = max(voice_end, ending_end, middle_end)

    background_frames = bytearray(silence(audio_format, total_frames))
    opening_frames = min(opening.frame_count, voice_start)
    _place(
        background_frames, audio_format, 0,
        scale_pcm_16bit(opening.frames[: opening_frames * audio_format.frame_width], selected_gains["opening"]),
    )

    middle_frames = middle_end - middle_start
    middle_loop_count = 0
    if middle_frames > 0:
        middle_loop_count = math.ceil(middle_frames / middle.frame_count)
        _place(
            background_frames,
            audio_format,
            middle_start,
            scale_pcm_16bit(_repeat_to_length(middle.frames, audio_format.frame_width, middle_frames), selected_gains["middle"]),
        )
    _place(background_frames, audio_format, ending_start, scale_pcm_16bit(ending.frames, selected_gains["ending"]))

    voice_track_frames = bytearray(silence(audio_format, total_frames))
    _place(voice_track_frames, audio_format, voice_start, voice.frames)

    timeline = {
        "schema_version": "1.0",
        "clock": {
            "sample_rate": audio_format.sample_rate,
            "channels": audio_format.channels,
            "sample_width_bytes": audio_format.sample_width,
            "total_frames": total_frames,
            "total_seconds": round(total_frames / audio_format.sample_rate, 7),
        },
        "voice": {
            "start_frame": voice_start,
            "start_seconds": round(voice_start / audio_format.sample_rate, 7),
            "end_frame": voice_end,
            "end_seconds": round(voice_end / audio_format.sample_rate, 7),
            "duration_seconds": round(voice.duration_seconds, 7),
            "caption_offset_seconds": VOICE_START_SECONDS,
        },
        "rules": {
            "voice_lead_in_seconds": VOICE_START_SECONDS,
            "middle_delay_after_voice_seconds": MIDDLE_DELAY_AFTER_VOICE_SECONDS,
            "ending_lead_before_voice_end_seconds": ENDING_LEAD_SECONDS,
        },
        "gains_db": {label: float(selected_gains[label]) for label in DEFAULT_SECTION_GAINS_DB},
        "placements": {
            "opening": {
                "start_frame": 0,
                "start_seconds": 0.0,
                "end_frame": opening_frames,
                "end_seconds": round(opening_frames / audio_format.sample_rate, 7),
                "truncated_to_voice_start": opening.frame_count > voice_start,
            },
            "middle": {
                "start_frame": middle_start,
                "start_seconds": round(middle_start / audio_format.sample_rate, 7),
                "end_frame": middle_end,
                "end_seconds": round(middle_end / audio_format.sample_rate, 7),
                "loop_count": middle_loop_count,
                "played_frames": middle_frames,
            },
            "ending": {
                "start_frame": ending_start,
                "start_seconds": round(ending_start / audio_format.sample_rate, 7),
                "end_frame": ending_end,
                "end_seconds": round(ending_end / audio_format.sample_rate, 7),
            },
        },
    }
    return AudioBuffer(audio_format, bytes(voice_track_frames)), AudioBuffer(audio_format, bytes(background_frames)), timeline


def _variant_language(production: dict[str, Any], requested: str | None) -> str:
    language = requested or ("zh-CN" if production.get("variant") == "zh-CN" else "en")
    if language not in {"en", "zh-CN"}:
        raise BackgroundMusicError("Background music language must be en or zh-CN.")
    return language


def _audio_artifact_key(language: str) -> str:
    return "audio_zh_cn" if language == "zh-CN" else "audio_en"


def resolved_section_gains(
    production: dict[str, Any], language: str, explicit_gains: dict[str, float] | None, legacy_gain: float | None,
) -> dict[str, float]:
    """Resolve new per-section settings while accepting old single-gain packages."""
    configured = production.get("background_music", {}).get(language, {})
    candidate = explicit_gains if explicit_gains is not None else configured.get("gains_db")
    if candidate is not None:
        if not isinstance(candidate, dict) or set(candidate) != set(DEFAULT_SECTION_GAINS_DB):
            raise BackgroundMusicError("Background music gains must define opening, middle and ending.")
        try:
            gains = {label: float(candidate[label]) for label in DEFAULT_SECTION_GAINS_DB}
        except (TypeError, ValueError) as error:
            raise BackgroundMusicError("Background music gains must be finite decibel values.") from error
    else:
        fallback = legacy_gain if legacy_gain is not None else configured.get("gain_db")
        gains = ({label: float(fallback) for label in DEFAULT_SECTION_GAINS_DB}
                 if fallback is not None else dict(DEFAULT_SECTION_GAINS_DB))
    if any(not math.isfinite(value) for value in gains.values()):
        raise BackgroundMusicError("Background music gains must be finite decibel values.")
    return gains


def add_background_music(
    production_path: Path,
    opening_path: Path,
    middle_path: Path,
    ending_path: Path,
    language: str | None = None,
    gain_db: float | None = None,
    mixed_output_path: Path | None = None,
    gains_db: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Create aligned voice, background, and mixed WAV tracks."""
    production = read_json(production_path)
    root = production_path.parent.resolve()
    selected_language = _variant_language(production, language)
    artifact_key = _audio_artifact_key(selected_language)
    suffix = "zh_cn" if selected_language == "zh-CN" else "en"
    artifacts = production.get("artifacts", {})
    # Prefer the unpadded, voice-only stem so a rebuild never mixes music into
    # a previous mixed output a second time. Older packages only have audio_*.
    voice_reference = artifacts.get(f"voice_only_{suffix}") or artifacts.get(artifact_key)
    if not isinstance(voice_reference, str):
        raise BackgroundMusicError(f"production.json has no completed {selected_language} voice artifact.")
    voice_path = (root / voice_reference).resolve()
    voice = load_audio(voice_path)
    opening = load_audio(opening_path.resolve(), voice.format)
    middle = load_audio(middle_path.resolve(), voice.format)
    ending = load_audio(ending_path.resolve(), voice.format)
    section_gains = resolved_section_gains(production, selected_language, gains_db, gain_db)
    voice_track, background_track, timeline = build_background_timeline(
        voice, opening, middle, ending, section_gains,
    )

    output_dir = root / "audio" / selected_language
    voice_track_path = output_dir / "voice-track.wav"
    background_path = output_dir / "background-music.wav"
    mixed_path = mixed_output_path.resolve() if mixed_output_path is not None else output_dir / "mixed-with-background-music.wav"
    timeline_path = root / f"background-music.{selected_language}.json"
    mixed_track, peak_protection = mix_audio_tracks(voice_track, background_track, return_report=True)
    applied_gains = {
        label: (round(gain + peak_protection["background_attenuation_db"], 7)
                if peak_protection["background_attenuation_db"] is not None else None)
        for label, gain in section_gains.items()
    }
    write_wav(voice_track_path, voice_track)
    write_wav(background_path, background_track)
    write_wav(mixed_path, mixed_track)
    timeline.update({
        "inputs": {
            "voice": {"path": relative_path(voice_path, root), "sha256": sha256_file(voice_path)},
            "opening": {"path": input_path_reference(opening_path, root), "sha256": sha256_file(opening_path)},
            "middle": {"path": input_path_reference(middle_path, root), "sha256": sha256_file(middle_path)},
            "ending": {"path": input_path_reference(ending_path, root), "sha256": sha256_file(ending_path)},
        },
        "outputs": {
            "voice_track": {"path": relative_path(voice_track_path, root), "sha256": sha256_file(voice_track_path), "duration_seconds": round(voice_track.duration_seconds, 7)},
            "background_music": {"path": relative_path(background_path, root), "sha256": sha256_file(background_path), "duration_seconds": round(background_track.duration_seconds, 7)},
            "mixed_audio": {
                "path": relative_path(mixed_path, root), "sha256": sha256_file(mixed_path),
                "duration_seconds": round(mixed_track.duration_seconds, 7),
                "background_gains_db": section_gains, "peak_protection": peak_protection,
            },
        },
        "peak_protection": peak_protection,
        "applied_gains_db": applied_gains,
    })
    write_json(timeline_path, timeline)

    artifacts = production.setdefault("artifacts", {})
    artifacts.update({
        f"voice_track_{suffix}": relative_path(voice_track_path, root),
        f"background_music_{suffix}": relative_path(background_path, root),
        f"mixed_audio_{suffix}": relative_path(mixed_path, root),
        f"background_music_timeline_{suffix}": relative_path(timeline_path, root),
    })
    background_config = production.setdefault("background_music", {}).setdefault(selected_language, {})
    background_config.update({
        "state": "complete",
        "provider": "local_pcm_timeline",
        "timeline": relative_path(timeline_path, root),
        "rules": timeline["rules"],
        "gains_db": section_gains,
        "applied_gains_db": applied_gains,
        "peak_protection": peak_protection,
    })
    write_json(production_path, production)
    return {
        "status": "complete",
        "language": selected_language,
        "artifacts": {
            "voice_track": relative_path(voice_track_path, root),
            "background_music": relative_path(background_path, root),
            "mixed_audio": relative_path(mixed_path, root),
            "timeline": relative_path(timeline_path, root),
        },
        "timeline": timeline,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("production", type=Path)
    parser.add_argument("--opening", required=True, type=Path)
    parser.add_argument("--middle", required=True, type=Path)
    parser.add_argument("--ending", required=True, type=Path)
    parser.add_argument("--language", choices=("en", "zh-CN"))
    parser.add_argument("--gain-db", type=float, help="Legacy uniform background level for all sections.")
    parser.add_argument("--opening-gain-db", type=float, help="Opening background gain in dB.")
    parser.add_argument("--middle-gain-db", type=float, help="Middle background gain in dB.")
    parser.add_argument("--ending-gain-db", type=float, help="Ending background gain in dB.")
    arguments = parser.parse_args()
    try:
        section_arguments = [arguments.opening_gain_db, arguments.middle_gain_db, arguments.ending_gain_db]
        if arguments.gain_db is not None and any(value is not None for value in section_arguments):
            raise BackgroundMusicError("Use --gain-db or all three section gain options, not both.")
        if any(value is not None for value in section_arguments) and not all(value is not None for value in section_arguments):
            raise BackgroundMusicError("Opening, middle and ending gain options must be supplied together.")
        gains = (dict(zip(DEFAULT_SECTION_GAINS_DB, section_arguments))
                 if all(value is not None for value in section_arguments) else None)
        result = add_background_music(
            arguments.production,
            arguments.opening,
            arguments.middle,
            arguments.ending,
            arguments.language,
            arguments.gain_db,
            gains_db=gains,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, BackgroundMusicError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
