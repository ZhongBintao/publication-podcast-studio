import importlib.util
import json
import tempfile
import wave
from pathlib import Path
import unittest

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "skills" / "publication-podcast-studio-workflow" / "scripts" / "publication_podcast_studio_workflow.py"
SPEC = importlib.util.spec_from_file_location("publication_podcast_studio_workflow", SCRIPT)
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
            "paragraphs": [{"order": 1, "text": "Markets and technology are changing."}],
            "assets": [],
        }), encoding="utf-8")
        (root / "editorial-assets.json").write_text(json.dumps({
            "format": "economist-editorial-assets",
            "article_source_sha256": "source-hash",
            "display": {"headline_zh": "未来", "subtitle_zh": "简短副标题。"},
            "guide_questions": [
                {"question": "Who funds the future when markets and technology change?", "translation_zh": "当市场和技术变化时，谁在为未来融资？", "source_paragraph_ids": ["p001"]},
                {"question": "Can markets adapt to a world shaped by new technology?", "translation_zh": "市场能适应新技术塑造的世界吗？", "source_paragraph_ids": ["p001"]},
            ],
            "cover_art": {
                "text_lines": [
                    {"position": "top", "text": "未来谁买单"},
                    {"position": "middle", "text": "资本正在改写规则"},
                    {"position": "bottom", "text": "市场能否跟上"},
                ],
            },
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
        cover_dir = root / "release" / "covers"
        cover_dir.mkdir(parents=True)
        for ratio in ("16x9", "9x16"):
            Image.new("RGB", (64, 64), "#ffd400").save(cover_dir / f"cover-{ratio}.png")
        (root / "publish-copy.md").write_text(
            "# 发布素材\n\n竖屏：release/covers/cover-9x16.png\n横屏：release/covers/cover-16x9.png\n",
            encoding="utf-8",
        )

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
            package = root / "release" / "video-publish-package"
            self.assertTrue((package / "publish-copy.md").is_file())
            self.assertEqual(
                sorted(path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file()),
                [
                    "covers/cover-16x9.png", "covers/cover-9x16.png", "package.json", "publish-copy.md",
                    "videos/en-zh/default/16x9.mp4", "videos/en-zh/default/9x16.mp4",
                    "videos/en/default/16x9.mp4", "videos/en/default/9x16.mp4",
                    "videos/zh-CN/default/16x9.mp4", "videos/zh-CN/default/9x16.mp4",
                ],
            )
            self.assertNotIn("release/covers/", (package / "publish-copy.md").read_text(encoding="utf-8"))
            self.assertEqual(report["cleanup"]["policy"], "safe")
            self.assertIn("[打开视频发布包]", report["chat_link"])
            cover_generation = report["release_package"]["cover_generation"]
            self.assertEqual(cover_generation["9:16"]["source_kind"], "finished_video_frame")
            self.assertEqual(cover_generation["9:16"]["frame_time_seconds"], 0.0)
            self.assertEqual(cover_generation["9:16"]["source_video"], "video/en-zh/default/9x16/final.mp4")
            self.assertEqual(len(cover_generation["9:16"]["source_video_sha256"]), 64)
            self.assertTrue(cover_generation["9:16"]["overlay"]["enabled"])
            with Image.open(root / "release" / "covers" / "cover-9x16.png") as cover:
                self.assertNotEqual(cover.getpixel((0, 0)), (255, 212, 0))

    def test_confirmed_release_cleanup_removes_only_selected_media_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root)
            selected = root / ".work" / "azure-speech-media" / "en-zh"
            unrelated = root / ".work" / "voice-ab"
            selected.mkdir(parents=True)
            unrelated.mkdir(parents=True)
            (selected / "segments.wav").write_bytes(b"cache")
            (unrelated / "keep.txt").write_text("keep", encoding="utf-8")
            report = MODULE.run_workflow(
                root, None, ["9:16"], "default", True, 1.0,
                products=["en-zh"], confirmed=True,
            )
            self.assertFalse(selected.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(report["cleanup"]["removed_count"], 1)
            publish_copy = (root / "release" / "video-publish-package" / "publish-copy.md").read_text(encoding="utf-8")
            self.assertIn("cover-9x16.png", publish_copy)
            self.assertNotIn("cover-16x9.png", publish_copy)

    def test_legacy_variant_does_not_create_release_package_or_clean_cache(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root)
            cache = root / ".work" / "azure-speech-media" / "en-zh"
            cache.mkdir(parents=True)
            (cache / "keep.txt").write_text("keep", encoding="utf-8")
            MODULE.run_workflow(root, "en-zh", ["9:16"], "default", True, 1.0)
            self.assertFalse((root / "release" / "video-publish-package").exists())
            self.assertTrue(cache.exists())

    def test_finalize_command_contract_can_retry_package_without_rerendering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_package(root)
            first = MODULE.run_workflow(root, "en-zh", ["9:16"], "default", True, 1.0)
            self.assertEqual(first["release_package"]["state"], "skipped")
            report = MODULE.finalize_existing_workflow(root, "none")
            self.assertTrue((root / "release" / "video-publish-package" / "videos" / "en-zh" / "default" / "9x16.mp4").is_file())
            self.assertEqual(report["cleanup"]["policy"], "none")
            self.assertIn("[打开视频发布包]", report["chat_link"])

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
