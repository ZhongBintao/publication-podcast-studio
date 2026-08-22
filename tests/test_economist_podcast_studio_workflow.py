import importlib.util
import json
import tempfile
import wave
from pathlib import Path
import unittest

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "skills" / "economist-podcast-studio-workflow" / "scripts" / "economist_podcast_studio_workflow.py"
SPEC = importlib.util.spec_from_file_location("economist_podcast_studio_workflow", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EconomistPodcastStudioWorkflowTests(unittest.TestCase):
    def make_package(self, root: Path, *, with_media: bool = True) -> None:
        assets = root / "assets"
        audio_dir = root / "audio" / "en"
        assets.mkdir()
        audio_dir.mkdir(parents=True)
        Image.new("RGB", (600, 800), "#9d1c22").save(assets / "issue-cover.png")
        (root / "article.json").write_text(json.dumps({
            "review_status": "verified",
            "source_sha256": "source-hash",
            "article": {"kicker": "KICKER", "headline": "The future", "subtitle": "A short subtitle.", "byline": None, "dateline": "SHANGHAI"},
            "issue_cover": {"file": "assets/issue-cover.png", "source_page": 1},
        }), encoding="utf-8")
        (root / "editorial-assets.json").write_text(json.dumps({
            "format": "economist-editorial-assets",
            "article_source_sha256": "source-hash",
            "display": {"headline_zh": "未来", "subtitle_zh": "简短副标题。"},
            "guide_questions": [
                {"question": "Who funds the future when markets and technology change?", "translation_zh": "当市场和技术变化时，谁在为未来融资？", "source_paragraph_ids": ["p001"]},
                {"question": "Can markets adapt to a world shaped by new technology?", "translation_zh": "市场能适应新技术塑造的世界吗？", "source_paragraph_ids": ["p001"]},
            ],
        }), encoding="utf-8")
        artifacts = {
            "script_en": "script.en.json",
            "subtitle_script_en_zh": "subtitle-script.en-zh.json",
            "editorial_assets": "editorial-assets.json",
            "caption_cues_en_zh": "caption-cues.en-zh.json",
            "captions_en_zh_srt": "captions.en-zh.srt",
            "audio_en": "audio/en/final.wav",
        }
        (root / "script.en.json").write_text("[]", encoding="utf-8")
        (root / "subtitle-script.en-zh.json").write_text("{}", encoding="utf-8")
        if with_media:
            with wave.open(str(audio_dir / "final.wav"), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(b"\0\0" * 48000 * 2)
            (root / "captions.en-zh.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nA complete sentence.\n完整的句子。\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nAnother complete sentence.\n另一条完整的句子。\n",
                encoding="utf-8",
            )
            (root / "caption-cues.en-zh.json").write_text(json.dumps({
                "variant": "en-zh",
                "cues": [
                    {"start_seconds": 0, "end_seconds": 1, "en_text": "A complete sentence.", "zh_text": "完整的句子。"},
                    {"start_seconds": 1, "end_seconds": 2, "en_text": "Another complete sentence.", "zh_text": "另一条完整的句子。"},
                ],
            }), encoding="utf-8")
        (root / "production.json").write_text(json.dumps({
            "state": "complete",
            "variant": "en-zh",
            "article": {"path": "article.json", "source_sha256": "source-hash"},
            "output": {"aspect_ratios": ["16:9"]},
            "artifacts": artifacts,
        }), encoding="utf-8")

    def test_local_only_reuses_media_and_renders_vertical_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root)
            report = MODULE.run_workflow(root, "en-zh", ["9:16"], "default", True, 1.0)
            self.assertEqual(report["state"], "complete")
            self.assertEqual(report["external_api_calls"], [])
            output = root / "video" / "en-zh" / "default" / "9x16" / "final.mp4"
            self.assertTrue(output.is_file())
            self.assertEqual(json.loads((root / "production.json").read_text())["output"]["aspect_ratios"], ["16:9", "9:16"])
            self.assertEqual(json.loads((root / "workflow-report.json").read_text())["execution_mode"], "local_only")

    def test_local_only_reports_missing_speech_boundary_without_calling_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root, with_media=False)
            with self.assertRaisesRegex(MODULE.WorkflowBlocked, "Azure Speech"):
                MODULE.run_workflow(root, "en-zh", ["9:16"], "default", True, 1.0)

    def test_local_only_freezes_english_only_mode_and_uses_separate_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root)
            report = MODULE.run_workflow(root, "en-zh", ["9:16"], "default", True, 1.0, "en-only")
            self.assertEqual(report["subtitle_mode"], "en-only")
            self.assertTrue((root / "video" / "en-zh" / "default" / "en-only" / "9x16" / "final.mp4").is_file())
            production = json.loads((root / "production.json").read_text())
            self.assertEqual(production["output"]["subtitle_mode"], "en-only")
            self.assertEqual(production["workflow"]["request"]["subtitle_mode"], "en-only")


if __name__ == "__main__":
    unittest.main()
