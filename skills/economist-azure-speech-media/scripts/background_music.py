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


def _repeat_to_length(frames: bytes, frame_width: int, frame_count: int) -> bytes:
    if not frames or len(frames) % frame_width:
        raise BackgroundMusicError("The middle background music must contain complete PCM frames.")
    if frame_count <= 0:
        return b""
    source_frames = len(frames) // frame_width
    repeats = math.ceil(frame_count / source_frames)
    return (frames * repeats)[: frame_count * frame_width]


def mix_audio_tracks(voice: AudioBuffer, background: AudioBuffer, gain_db: float = -18.0) -> AudioBuffer:
    """Mix aligned tracks while keeping the voice at full level."""
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
    mixed = bytearray()
    for (voice_sample,), (background_sample,) in zip(
        struct.iter_unpack("<h", voice.frames), struct.iter_unpack("<h", background.frames)
    ):
        value = round(voice_sample + background_sample * gain)
        mixed.extend(struct.pack("<h", max(-32768, min(32767, value))))
    return AudioBuffer(voice.format, bytes(mixed))


def build_background_timeline(
    voice: AudioBuffer,
    opening: AudioBuffer,
    middle: AudioBuffer,
    ending: AudioBuffer,
) -> tuple[AudioBuffer, AudioBuffer, dict[str, Any]]:
    """Return a timeline-aligned voice track, background track and audit data.

    The voice track starts with six seconds of silence so both exported tracks
    share one absolute clock. The canonical Azure voice WAV remains unchanged;
    this padded copy is the track to use with the generated background track.
    """
    audio_format = voice.format
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
    _place(background_frames, audio_format, 0, opening.frames[: opening_frames * audio_format.frame_width])

    middle_frames = middle_end - middle_start
    middle_loop_count = 0
    if middle_frames > 0:
        middle_loop_count = math.ceil(middle_frames / middle.frame_count)
        _place(
            background_frames,
            audio_format,
            middle_start,
            _repeat_to_length(middle.frames, audio_format.frame_width, middle_frames),
        )
    _place(background_frames, audio_format, ending_start, ending.frames)

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


def add_background_music(
    production_path: Path,
    opening_path: Path,
    middle_path: Path,
    ending_path: Path,
    language: str | None = None,
    gain_db: float = -18.0,
    mixed_output_path: Path | None = None,
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
    voice_track, background_track, timeline = build_background_timeline(voice, opening, middle, ending)

    output_dir = root / "audio" / selected_language
    voice_track_path = output_dir / "voice-track.wav"
    background_path = output_dir / "background-music.wav"
    mixed_path = mixed_output_path.resolve() if mixed_output_path is not None else output_dir / "mixed-with-background-music.wav"
    timeline_path = root / f"background-music.{selected_language}.json"
    mixed_track = mix_audio_tracks(voice_track, background_track, gain_db)
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
            "mixed_audio": {"path": relative_path(mixed_path, root), "sha256": sha256_file(mixed_path), "duration_seconds": round(mixed_track.duration_seconds, 7), "background_gain_db": gain_db},
        },
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
        "gain_db": gain_db,
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
    parser.add_argument("--gain-db", type=float, default=-18.0, help="Background level relative to voice, default -18 dB.")
    arguments = parser.parse_args()
    try:
        result = add_background_music(
            arguments.production,
            arguments.opening,
            arguments.middle,
            arguments.ending,
            arguments.language,
            arguments.gain_db,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, BackgroundMusicError) as error:
        print(json.dumps({"status": "failed", "reason": str(error)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
