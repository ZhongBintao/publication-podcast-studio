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
    def make_package(self, root: Path, *, with_media: bool = True, all_products: bool = False) -> None:
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
        if all_products:
            zh_audio_dir = root / "audio" / "zh-CN"
            zh_audio_dir.mkdir(parents=True)
            artifacts.update({
                "script_zh_cn": "script.zh-CN.json",
                "audio_zh_cn": "audio/zh-CN/final.wav",
                "captions_zh_cn_srt": "captions.zh-CN.srt",
                "captions_zh_cn_vtt": "captions.zh-CN.vtt",
                "captions_en_srt": "captions.en.srt",
                "captions_en_vtt": "captions.en.vtt",
            })
            (root / "script.zh-CN.json").write_text("[]", encoding="utf-8")
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
            if all_products:
                with wave.open(str(root / "audio" / "zh-CN" / "final.wav"), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(48000)
                    wav.writeframes(b"\0\0" * 48000 * 2)
                (root / "captions.en.srt").write_text(
                    "1\n00:00:00,000 --> 00:00:01,000\nAn English sentence.\n\n", encoding="utf-8"
                )
                (root / "captions.en.vtt").write_text(
                    "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nAn English sentence.\n", encoding="utf-8"
                )
                (root / "captions.zh-CN.srt").write_text(
                    "1\n00:00:00,000 --> 00:00:01,000\n一条中文句子。\n\n", encoding="utf-8"
                )
                (root / "captions.zh-CN.vtt").write_text(
                    "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n一条中文句子。\n", encoding="utf-8"
                )
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
            self.assertEqual(report["quality"]["background_music"]["en-zh"]["status"], "legacy_not_enforced")
            self.assertIn("media_rotation", report["quality"])
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

    def test_confirmed_product_matrix_renders_each_product_and_ratio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root, all_products=True)
            report = MODULE.run_workflow(
                root, None, ["9:16", "16:9"], "default", True, 1.0,
                products=["en-zh", "en", "zh-CN"], confirmed=True,
            )
            self.assertEqual(report["products"], ["en-zh", "en", "zh-CN"])
            self.assertEqual(len(report["outputs"]), 6)
            for product in report["products"]:
                for ratio in ("9x16", "16x9"):
                    self.assertTrue((root / "video" / product / "default" / ratio / "final.mp4").is_file())
            production = json.loads((root / "production.json").read_text())
            self.assertEqual(production["workflow"]["request"]["products"], ["en-zh", "en", "zh-CN"])
            self.assertEqual(set(production["workflow"]["storyboards"]), {"en-zh", "en", "zh-CN"})

    def test_unconfirmed_product_matrix_has_no_side_effect(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root)
            before = (root / "production.json").read_text()
            with self.assertRaisesRegex(MODULE.WorkflowBlocked, "confirmed production request"):
                MODULE.run_workflow(root, None, ["9:16"], "default", True, 1.0, products=["en-zh"])
            self.assertEqual((root / "production.json").read_text(), before)

    def test_confirmed_product_interface_does_not_expose_internal_subtitle_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root)
            with self.assertRaisesRegex(MODULE.WorkflowError, "internal compatibility option"):
                MODULE.run_workflow(
                    root, None, ["9:16"], "default", True, 1.0,
                    subtitle_mode="en-only", products=["en-zh"], confirmed=True,
                )


if __name__ == "__main__":
    unittest.main()
