import importlib.util
import json
import subprocess
import tempfile
import wave
from pathlib import Path
import unittest

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "skills" / "economist-static-slide-video" / "scripts" / "static_slide_storyboard.py"
SPEC = importlib.util.spec_from_file_location("static_slide_storyboard", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StaticSlideStoryboardTests(unittest.TestCase):
    def make_package(self, root: Path) -> tuple[Path, Path]:
        assets = root / "assets"
        audio_dir = root / "audio" / "en"
        assets.mkdir()
        audio_dir.mkdir(parents=True)
        Image.new("RGB", (600, 800), "#9d1c22").save(assets / "issue-cover.png")
        with wave.open(str(audio_dir / "final.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            wav.writeframes(b"\0\0" * 48000 * 2)
        (root / "captions.en-zh.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nLong-term capital is needed.\n需要长期资本。\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nCan markets adapt?\n市场能适应吗？\n",
            encoding="utf-8",
        )
        article = {
            "review_status": "verified",
            "source_sha256": "source-hash",
            "article": {"kicker": "KICKER", "headline": "The future", "subtitle": "Long-term capital is needed.", "byline": None, "dateline": "SHANGHAI"},
            "issue_cover": {"file": "assets/issue-cover.png", "source_page": 1},
        }
        (root / "article.json").write_text(json.dumps(article), encoding="utf-8")
        production = {
            "state": "complete",
            "variant": "en-zh",
            "article": {"path": "article.json", "source_sha256": "source-hash"},
            "output": {"aspect_ratios": ["16:9", "9:16"]},
            "artifacts": {"audio_en": "audio/en/final.wav", "captions_en_zh_srt": "captions.en-zh.srt"},
        }
        production_path = root / "production.json"
        production_path.write_text(json.dumps(production), encoding="utf-8")
        questions = {
            "display": {"headline_zh": "未来如何融资", "subtitle_zh": "需要长期资本。"},
            "guide_questions": [
                {"question": "Who funds the future?", "translation_zh": "谁为未来融资？", "source_paragraph_ids": ["p001"]},
                {"question": "Can markets adapt?", "translation_zh": "市场能适应吗？", "source_paragraph_ids": ["p002"]},
            ],
        }
        questions_path = root / "guide-questions.json"
        questions_path.write_text(json.dumps(questions), encoding="utf-8")
        return production_path, questions_path

    def test_build_and_render_a_bilingual_9x16_video(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production, questions = self.make_package(root)
            storyboard_path = root / "storyboard.json"
            storyboard = MODULE.build_storyboard(production, questions, storyboard_path, 1.0)
            self.assertEqual([slide["template_role"] for slide in storyboard["slides"]], ["opening", "guide_questions"])
            self.assertEqual(storyboard["slides"][1]["source_paragraph_ids"], ["p001", "p002"])

            output, reused = MODULE.render_storyboard(production, storyboard_path, "9:16")
            self.assertFalse(reused)
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 1000)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json", str(output)],
                check=True, capture_output=True, text=True,
            )
            metadata = json.loads(probe.stdout)
            video = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
            self.assertEqual((video["width"], video["height"]), (1080, 1920))
            self.assertAlmostEqual(float(metadata["format"]["duration"]), 2.0, delta=0.15)
            self.assertTrue(MODULE.render_storyboard(production, storyboard_path, "9:16")[1])
            persisted = json.loads(production.read_text(encoding="utf-8"))
            self.assertEqual(persisted["video"]["outputs"]["en-zh/default/9:16"]["path"], "video/en-zh/default/9x16/final.mp4")
            report = root / persisted["video"]["outputs"]["en-zh/default/9:16"]["render_report"]
            self.assertTrue(report.is_file())
            self.assertTrue(json.loads(report.read_text(encoding="utf-8"))["frames"])

    def test_missing_slide_asset_blocks_rendering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production, questions = self.make_package(root)
            storyboard_path = root / "storyboard.json"
            storyboard = MODULE.build_storyboard(production, questions, storyboard_path, 1.0)
            storyboard["slides"][1]["asset"]["file"] = "assets/missing.png"
            storyboard_path.write_text(json.dumps(storyboard), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.StoryboardError, "asset for guide-questions is missing"):
                MODULE.render_storyboard(production, storyboard_path, "16:9")

    def test_editorial_assets_are_accepted_in_place_of_legacy_question_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production, questions = self.make_package(root)
            payload = json.loads(questions.read_text(encoding="utf-8"))
            payload.update({"format": "economist-editorial-assets", "schema_version": "1.0.0", "article_source_sha256": "source-hash"})
            editorial_assets = root / "editorial-assets.json"
            editorial_assets.write_text(json.dumps(payload), encoding="utf-8")
            storyboard = MODULE.build_storyboard(production, editorial_assets, root / "storyboard.json", 1.0)
            self.assertEqual(storyboard["guide_questions"][0]["question"], "Who funds the future?")
            payload["article_source_sha256"] = "wrong-source"
            editorial_assets.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.StoryboardError, "does not belong"):
                MODULE.build_storyboard(production, editorial_assets, root / "other-storyboard.json", 1.0)

    def test_legacy_srt_is_consumed_without_repartitioning_text_or_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.srt"
            path.write_text(
                "1\n00:00:00,000 --> 00:00:08,000\nA complete legacy English sentence.\n一条完整的历史中文字幕。\n",
                encoding="utf-8",
            )
            cues = MODULE.legacy_caption_cues(path, "en-zh")
            self.assertEqual(cues, [{
                "start": 0.0, "end": 8.0, "en_text": "A complete legacy English sentence.", "zh_text": "一条完整的历史中文字幕。",
            }])

    def test_structured_bilingual_cues_keep_language_fields_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "caption-cues.en-zh.json"
            path.write_text(json.dumps({"schema_version": "1.0", "variant": "en-zh", "cues": [{
                "start_seconds": 0, "end_seconds": 2, "en_text": "English sentence.", "zh_text": "完整中文句子。",
            }]}), encoding="utf-8")
            cues = MODULE.structured_caption_cues(path, "en-zh")
            self.assertEqual(MODULE.caption_fields(cues[0], "en-zh"), ("English sentence.", "完整中文句子。"))
