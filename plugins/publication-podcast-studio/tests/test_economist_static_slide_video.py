import importlib.util
import json
import tempfile
from pathlib import Path
import unittest

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "skills" / "publication-static-slide-video" / "scripts" / "render_static_slide_template.py"
SPEC = importlib.util.spec_from_file_location("publication_static_slide_video", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EconomistStaticSlideVideoTests(unittest.TestCase):
    def make_article(self, root: Path) -> Path:
        assets = root / "assets"
        assets.mkdir()
        Image.new("RGB", (800, 1100), "#9d1c22").save(assets / "issue-cover.png")
        package = {
            "article": {
                "section": "Finance & economics",
                "kicker": "Technology finance",
                "headline": "How to fund the future",
                "subtitle": "China’s capital markets take on Xi Jinping’s tech ambitions",
                "byline": None,
                "dateline": "SHANGHAI",
            },
            "issue_cover": {"file": "assets/issue-cover.png", "source_page": 1},
        }
        path = root / "article.json"
        path.write_text(json.dumps(package), encoding="utf-8")
        return path

    def test_issue_cover_frame_renders_both_aspect_ratios(self):
        with tempfile.TemporaryDirectory() as temporary:
            article = self.make_article(Path(temporary))
            landscape = MODULE.render_editorial_frame(article, "16:9", "English caption.", "中文字幕。")
            portrait = MODULE.render_editorial_frame(article, "9:16", "English caption.", "中文字幕。")
            self.assertEqual(landscape.size, (1920, 1080))
            self.assertEqual(portrait.size, (1080, 1920))
            self.assertEqual(landscape.getpixel((10, 900)), (244, 241, 236))
            self.assertEqual(portrait.getpixel((10, 1700)), (244, 241, 236))

    def test_english_only_frame_renders_both_aspect_ratios_without_chinese_caption(self):
        with tempfile.TemporaryDirectory() as temporary:
            article = self.make_article(Path(temporary))
            for aspect_ratio in ("16:9", "9:16"):
                frame = MODULE.render_editorial_frame(
                    article, aspect_ratio, "English caption.", "中文字幕。", subtitle_mode="en-only"
                )
                self.assertEqual(frame.size, MODULE.CANVASES[aspect_ratio])

    def test_historical_article_requires_explicit_cover_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            article = self.make_article(root)
            package = json.loads(article.read_text(encoding="utf-8"))
            package.pop("issue_cover")
            article.write_text(json.dumps(package), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.TemplateError, "no front_page"):
                MODULE.render_editorial_frame(article, "16:9", "", "")
            image = root / "assets" / "issue-cover.png"
            frame = MODULE.render_editorial_frame(article, "16:9", "", "", str(image))
            self.assertEqual(frame.size, (1920, 1080))

    def test_article_asset_uses_the_same_media_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            article = self.make_article(root)
            wide_asset = root / "assets" / "wide.png"
            Image.new("RGB", (1200, 600), "#29616c").save(wide_asset)
            frame = MODULE.render_editorial_frame(article, "16:9", "English caption.", "中文字幕。", str(wide_asset), "article_asset")
            self.assertEqual(frame.getpixel((1400, 440)), (41, 97, 108))

    def test_bilingual_srt_preserves_two_caption_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "captions.srt"
            path.write_text("1\n00:00:00,000 --> 00:00:01,250\nEnglish line.\n中文行。\n", encoding="utf-8")
            cue = MODULE.parse_srt(path)[0]
            self.assertEqual(MODULE.cue_text(cue, "en-zh"), ("English line.", "中文行。"))
            self.assertEqual(MODULE.caption_segments([cue], 2.0), [(0.0, 1.25, cue), (1.25, 2.0, None)])

    def test_legacy_landscape_caption_fonts_and_dash_normalization(self):
        english = MODULE.font(MODULE.ARIAL_BOLD_FONTS, 48, weight="bold", text="AI-supported ‘film’")
        chinese = MODULE.font(MODULE.NOTO_SANS_SC_FONTS, 48, weight="medium", text="人工智能，电影。")
        self.assertEqual(english.getname(), ("Arial", "Bold"))
        self.assertEqual(chinese.getname(), ("Noto Sans SC", "Medium"))
        self.assertEqual(MODULE.normalize_caption_text("AI\u2011supported"), "AI-supported")

    def test_legacy_long_landscape_caption_is_wrapped_without_truncation(self):
        with tempfile.TemporaryDirectory() as temporary:
            article = self.make_article(Path(temporary))
            value = "Though the much-publicised arrival last year of Tilly Norwood, an AI-generated actor, did cause a fleeting panic, and the story continues to affect how studios think about their future."
            frame = MODULE.render_editorial_frame(article, "16:9", value, "一条很长的中文字幕也必须完整显示，并且自然换成两行而不是截断。")
            self.assertEqual(frame.size, (1920, 1080))
