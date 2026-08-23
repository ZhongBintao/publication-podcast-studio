import importlib.util
import os
from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "skills" / "publication-azure-speech-media" / "scripts" / "azure_speech_media.py"
SPEC = importlib.util.spec_from_file_location("azure_speech_media_live", SCRIPT)
MEDIA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MEDIA)


LIVE_ENABLED = (
    os.environ.get("RUN_AZURE_SPEECH_LIVE") == "1"
    and bool(os.environ.get("AZURE_SPEECH_KEY"))
    and bool(os.environ.get("AZURE_SPEECH_REGION"))
)


@unittest.skipUnless(LIVE_ENABLED, "Set RUN_AZURE_SPEECH_LIVE=1 with Azure Speech credentials to run live DragonHD smoke tests.")
class DragonHdLiveSmokeTests(unittest.TestCase):
    def test_selected_english_voices_synthesize_with_word_boundaries(self):
        provider = MEDIA.AzureSpeechProvider(os.environ["AZURE_SPEECH_REGION"])
        samples = (
            ("en-US-Ava:DragonHDLatestNeural", {}),
            ("en-US-Andrew:DragonHDLatestNeural", {"temperature": 1.0}),
        )
        for voice, parameters in samples:
            result = provider.synthesize("en", voice, "A short DragonHD smoke test.", {"structure": "none"}, parameters)
            self.assertGreater(MEDIA.duration_seconds(result["audio"]), 0)
            self.assertTrue(MEDIA.validate_boundaries("A short DragonHD smoke test.", result["word_boundaries"]))

    def test_selected_chinese_voices_synthesize_with_word_boundaries(self):
        provider = MEDIA.AzureSpeechProvider(os.environ["AZURE_SPEECH_REGION"])
        samples = (
            ("zh-CN-Xiaochen:DragonHDLatestNeural", "小陈主持人测试。"),
            ("zh-CN-Yunxiao:DragonHDFlashLatestNeural", "云霄主持人测试。"),
        )
        for voice, text in samples:
            result = provider.synthesize("zh-CN", voice, text, {"structure": "none"}, {"temperature": 1.0})
            self.assertGreater(MEDIA.duration_seconds(result["audio"]), 0)
            self.assertTrue(MEDIA.validate_boundaries(text, result["word_boundaries"]))
