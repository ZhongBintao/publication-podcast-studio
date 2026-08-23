import importlib.util
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "skills" / "publication-azure-speech-media" / "scripts" / "voice_ab.py"
SPEC = importlib.util.spec_from_file_location("voice_ab", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(24000)
        file.writeframes(b"\0\0" * 24000)
    return output.getvalue()


class FakeProvider:
    def list_voices(self, locale):
        self.locale = locale
        return [
            {"short_name": "en-US-JennyNeural", "styles": ["newscast"]},
            {"short_name": "en-US-GuyNeural", "styles": ["newscast"]},
            {"short_name": "en-US-AriaNeural", "styles": ["narration-professional"]},
        ]

    def synthesize(self, language, voice, text, delivery=None, voice_parameters=None):
        self.delivery = getattr(self, "delivery", [])
        self.delivery.append(delivery)
        return {"audio": wav_bytes(), "word_boundaries": [{"text": "sample"}]}


class VoiceAbTests(unittest.TestCase):
    def test_voice_ab_filters_runtime_voice_list_and_writes_comparable_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "script.en.json"
            script.write_text(json.dumps([{"segment_id": "en-001", "spoken_text": "A controlled voice comparison sample."}]), encoding="utf-8")
            report = MODULE.run_voice_ab("southeastasia", script, root / ".work" / "voice-ab", FakeProvider())
            self.assertEqual([item["voice"] for item in report["results"]], ["en-US-JennyNeural", "en-US-GuyNeural", "en-US-AriaNeural"])
            self.assertEqual(report["sample"]["segment_id"], "en-001")
            self.assertTrue((root / ".work" / "voice-ab" / "voice-ab.json").is_file())
            self.assertTrue(all((root / ".work" / "voice-ab" / item["audio"]).is_file() for item in report["results"]))

    def test_aria_ab_uses_four_delivery_profiles_with_live_style_filter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "script.en.json"
            script.write_text(json.dumps([{"segment_id": "en-001", "spoken_text": "A controlled voice comparison sample."}]), encoding="utf-8")
            provider = FakeProvider()
            provider.list_voices = lambda locale: [{
                "short_name": "en-US-AriaNeural",
                "styles": ["narration-professional", "newscast-casual"],
            }]
            report = MODULE.run_aria_ab("southeastasia", script, root / ".work" / "aria-ab", provider)
            self.assertEqual([item["id"] for item in report["results"]], [
                "aria-neutral", "aria-narration-professional", "aria-newscast-casual", "aria-balanced-prosody",
            ])
            self.assertEqual(len(provider.delivery), 4)
            self.assertEqual(provider.delivery[1]["style"], "narration-professional")
            self.assertEqual(provider.delivery[2]["style"], "newscast-casual")
            self.assertEqual(provider.delivery[3]["rate"], "-3%")
            self.assertTrue((root / ".work" / "aria-ab" / "aria-ab.json").is_file())
