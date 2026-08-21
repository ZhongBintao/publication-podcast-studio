import importlib.util
import io
import json
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "skills" / "economist-azure-speech-media" / "scripts" / "background_music.py"
SPEC = importlib.util.spec_from_file_location("background_music", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def audio(frame_count, value, sample_rate=10):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(struct.pack("<h", value) * frame_count)
    return MODULE.read_wav_bytes(output.getvalue())


def samples(track):
    return [value[0] for value in struct.iter_unpack("<h", track.frames)]


class BackgroundMusicTests(unittest.TestCase):
    def test_mix_keeps_voice_and_attenuates_background(self):
        mixed = MODULE.mix_audio_tracks(audio(3, 1000), audio(3, 1000), -20.0)

        self.assertEqual(mixed.frame_count, 3)
        self.assertTrue(all(1000 < value <= 1100 for value in samples(mixed)))

    def test_timeline_uses_exact_frame_offsets_and_middle_loops(self):
        voice, background, timeline = MODULE.build_background_timeline(
            audio(200, 10),
            audio(80, 1),
            audio(4, 2),
            audio(60, 3),
        )

        self.assertEqual(voice.frame_count, 290)
        self.assertEqual(background.frame_count, 290)
        self.assertEqual(timeline["voice"]["start_frame"], 60)
        self.assertEqual(timeline["voice"]["end_frame"], 260)
        self.assertEqual(timeline["placements"]["opening"]["end_frame"], 60)
        self.assertEqual(timeline["placements"]["middle"]["start_frame"], 110)
        self.assertEqual(timeline["placements"]["middle"]["end_frame"], 230)
        self.assertEqual(timeline["placements"]["middle"]["loop_count"], 30)
        self.assertEqual(timeline["placements"]["ending"]["start_frame"], 230)
        self.assertEqual(timeline["placements"]["ending"]["end_frame"], 290)
        self.assertEqual(samples(voice)[59:62], [0, 10, 10])
        self.assertEqual(samples(voice)[259:262], [10, 0, 0])
        self.assertEqual(samples(background)[0], 1)
        self.assertEqual(samples(background)[59:61], [1, 0])
        self.assertEqual(samples(background)[109:112], [0, 2, 2])
        self.assertEqual(samples(background)[229:232], [2, 3, 3])

    def test_section_gains_raise_middle_above_opening_and_ending(self):
        _, background, timeline = MODULE.build_background_timeline(
            audio(200, 10), audio(80, 1000), audio(4, 1000), audio(60, 1000),
            MODULE.DEFAULT_SECTION_GAINS_DB,
        )
        values = samples(background)
        self.assertEqual(timeline["gains_db"], {"opening": 8.0, "middle": 10.0, "ending": 8.0})
        self.assertGreater(abs(values[110]), abs(values[0]))
        self.assertGreater(abs(values[110]), abs(values[230]))

    def test_peak_protection_only_reduces_background(self):
        voice = audio(2, 32000)
        mixed, report = MODULE.mix_audio_tracks(voice, audio(2, 32000), return_report=True)
        self.assertTrue(report["peak_protection_applied"])
        self.assertLess(report["background_scale"], 1.0)
        self.assertEqual(samples(mixed), [32767, 32767])

    def test_add_background_music_writes_two_tracks_and_production_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio_dir = root / "audio" / "en"
            audio_dir.mkdir(parents=True)
            MODULE.write_wav(audio_dir / "final.wav", audio(200, 10))
            opening = root / "opening.wav"
            middle = root / "middle.wav"
            ending = root / "ending.wav"
            MODULE.write_wav(opening, audio(80, 1))
            MODULE.write_wav(middle, audio(4, 2))
            MODULE.write_wav(ending, audio(60, 3))
            production = root / "production.json"
            production.write_text(json.dumps({
                "variant": "en",
                "state": "complete",
                "artifacts": {"audio_en": "audio/en/final.wav"},
            }), encoding="utf-8")

            result = MODULE.add_background_music(production, opening, middle, ending)

            self.assertEqual(result["status"], "complete")
            self.assertTrue((audio_dir / "voice-track.wav").is_file())
            self.assertTrue((audio_dir / "background-music.wav").is_file())
            self.assertTrue((audio_dir / "mixed-with-background-music.wav").is_file())
            self.assertTrue((root / "background-music.en.json").is_file())
            persisted = json.loads(production.read_text(encoding="utf-8"))
            self.assertEqual(persisted["artifacts"]["voice_track_en"], "audio/en/voice-track.wav")
            self.assertEqual(persisted["artifacts"]["background_music_en"], "audio/en/background-music.wav")
            self.assertEqual(persisted["artifacts"]["mixed_audio_en"], "audio/en/mixed-with-background-music.wav")
            self.assertEqual(persisted["background_music"]["en"]["state"], "complete")
            self.assertEqual(persisted["background_music"]["en"]["gains_db"], {"opening": 8.0, "middle": 10.0, "ending": 8.0})
            self.assertIn("peak_protection", persisted["background_music"]["en"])

    def test_legacy_uniform_gain_remains_available(self):
        production = {"background_music": {"en": {"gain_db": -18}}}
        self.assertEqual(
            MODULE.resolved_section_gains(production, "en", None, None),
            {"opening": -18.0, "middle": -18.0, "ending": -18.0},
        )
