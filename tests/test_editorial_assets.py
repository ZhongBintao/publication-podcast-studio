import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "skills" / "economist-source-to-podcast-script" / "scripts" / "editorial_assets.py"
SPEC = importlib.util.spec_from_file_location("editorial_assets", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EditorialAssetsTests(unittest.TestCase):
    def make_package(self, root: Path) -> tuple[Path, Path, Path]:
        assets = root / "assets"
        assets.mkdir()
        Image.new("RGB", (600, 800), "#9d1c22").save(assets / "issue-cover.png")
        article = {
            "review_status": "verified",
            "source_sha256": "source-hash",
            "article": {"section": "Business", "kicker": "Capital", "headline": "The future", "subtitle": "Long-term capital meets technology.", "byline": None, "dateline": "SHANGHAI"},
            "issue_cover": {"file": "assets/issue-cover.png", "source_page": 1},
            "paragraphs": [
                {"order": 1, "text": "Long-term capital backs technology."},
                {"order": 2, "text": "Markets must adapt."},
            ],
        }
        article_path = root / "article.json"
        article_path.write_text(json.dumps(article), encoding="utf-8")
        production_path = root / "production.json"
        production_path.write_text(json.dumps({"state": "queued", "artifacts": {}}), encoding="utf-8")
        draft = {
            "source_sha256": "source-hash",
            "display": {"headline_zh": "谁为未来买单", "subtitle_zh": "长期资本与科技雄心相遇。", "source_paragraph_ids": ["p001", "p002"]},
            "guide_questions": [
                {"question": "Which investors will fund the technology needed for the future?", "translation_zh": "谁会为未来所需的科技投入资金？", "source_paragraph_ids": ["p001"]},
                {"question": "Can markets adapt before long-term capital reshapes the technology race?", "translation_zh": "长期资本改写科技竞赛前，市场来得及适应吗？", "source_paragraph_ids": ["p002"]},
            ],
            "publication": {"title_zh": "《经济学人》：谁在为未来的科技雄心买单 | 外刊播客 | 中英字幕", "description_zh": "长期资本正在决定科技雄心能否落地，市场也必须重新适应。", "source_paragraph_ids": ["p001", "p002"]},
            "cover_text": [
                {"position": "top", "text": "未来谁买单", "source_paragraph_ids": ["p001"]},
                {"position": "middle", "text": "资本正在改写规则", "source_paragraph_ids": ["p001", "p002"]},
                {"position": "bottom", "text": "市场能否跟上", "source_paragraph_ids": ["p002"]},
            ],
        }
        draft_path = root / "editorial-draft.json"
        draft_path.write_text(json.dumps(draft), encoding="utf-8")
        return article_path, draft_path, production_path

    def test_finalise_writes_one_authoritative_package_and_both_covers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            article, draft, production = self.make_package(root)
            result = MODULE.finalise(article, draft, root / "editorial-assets.json", production)
            self.assertEqual(result["format"], MODULE.EDITORIAL_FORMAT)
            self.assertEqual(len(result["guide_questions"]), 2)
            self.assertEqual(result["cover_issue_info"]["status"], "unavailable")
            self.assertTrue((root / "publish-copy.md").is_file())
            self.assertIn(result["publication"]["title_zh"], (root / "publish-copy.md").read_text(encoding="utf-8"))
            for ratio, dimensions in (("16:9", (1920, 1080)), ("9:16", (1080, 1920))):
                output = result["cover_art"]["outputs"][ratio]
                path = root / output["path"]
                self.assertTrue(path.is_file())
                self.assertEqual((output["dimensions"]["width"], output["dimensions"]["height"]), dimensions)
                with Image.open(path) as rendered:
                    self.assertEqual(rendered.getpixel((0, 0)), (38, 38, 38))
                    cover_x, cover_y, _, _ = output["issue_cover_bbox"]
                    self.assertEqual(rendered.getpixel((cover_x, cover_y)), (255, 255, 255))
                self.assertEqual([line["fill"] for line in output["line_layout"]], ["#FFD400", "#E60012", "#FFD400"])
                self.assertTrue(all(line["stroke_width_px"] > 0 for line in output["line_layout"]))
            persisted = json.loads(production.read_text(encoding="utf-8"))
            self.assertEqual(persisted["artifacts"]["editorial_assets"], "editorial-assets.json")
            self.assertIn("editorial_assets", persisted["artifact_hashes"])

    def test_validator_requires_fixed_title_and_exact_three_ordered_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            article_path, draft_path, _ = self.make_package(Path(temporary))
            article, paragraphs = MODULE.load_article(article_path)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["publication"]["title_zh"] = "一个不合格标题"
            with self.assertRaisesRegex(MODULE.EditorialAssetsError, "fixed Economist"):
                MODULE.validate_draft(article, paragraphs, draft)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["cover_text"][1]["position"] = "top"
            with self.assertRaisesRegex(MODULE.EditorialAssetsError, "top, middle, bottom"):
                MODULE.validate_draft(article, paragraphs, draft)

    def test_editorial_request_asks_only_for_a_distilled_title_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            article_path, _, _ = self.make_package(Path(temporary))
            request = MODULE.editorial_request(article_path)
            self.assertIn("title_body_zh", request["draft_schema"]["publication"])
            self.assertNotIn("title_zh", request["draft_schema"]["publication"])
            self.assertIn("must not merely translate", request["instructions"])

    def test_validator_assembles_wrapper_and_rejects_direct_headline_translation(self):
        with tempfile.TemporaryDirectory() as temporary:
            article_path, draft_path, _ = self.make_package(Path(temporary))
            article, paragraphs = MODULE.load_article(article_path)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["publication"] = {
                "title_body_zh": "长期资本如何改写未来科技竞赛",
                "description_zh": draft["publication"]["description_zh"],
                "source_paragraph_ids": ["p001", "p002"],
            }
            result = MODULE.validate_draft(article, paragraphs, draft)
            self.assertEqual(result["publication"]["title_body_zh"], "长期资本如何改写未来科技竞赛")
            self.assertEqual(result["publication"]["title_zh"], "《经济学人》：长期资本如何改写未来科技竞赛 | 外刊播客 | 中英字幕")

            draft["display"]["headline_zh"] = "北京，不是普林斯顿"
            draft["publication"]["title_body_zh"] = "北京，不是普林斯顿"
            with self.assertRaisesRegex(MODULE.EditorialAssetsError, "not repeat or directly translate"):
                MODULE.validate_draft(article, paragraphs, draft)

    def test_zh_cn_variant_uses_chinese_only_publication_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            article_path, draft_path, production = self.make_package(Path(temporary))
            article, paragraphs = MODULE.load_article(article_path)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["publication"]["title_zh"] = "《经济学人》：谁在为未来的科技雄心买单 | 外刊播客 | 中文字幕"
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            result = MODULE.validate_draft(article, paragraphs, draft, "zh-CN")
            self.assertTrue(result["publication"]["title_zh"].endswith("| 中文字幕"))
            assets = MODULE.finalise(article_path, draft_path, Path(temporary) / "zh-editorial-assets.json", production, "zh-CN")
            self.assertEqual(assets["publication_variant"], "zh-CN")
            self.assertTrue(assets["publication"]["title_zh"].endswith("| 中文字幕"))
            invalid = json.loads(draft_path.read_text(encoding="utf-8"))
            invalid["publication"]["title_zh"] = "《经济学人》：谁在为未来的科技雄心买单 | 外刊播客 | 中英字幕"
            with self.assertRaisesRegex(MODULE.EditorialAssetsError, "fixed Economist"):
                MODULE.validate_draft(article, paragraphs, invalid, "zh-CN")

    def test_release_cover_uses_non_overlapping_safe_regions_for_long_titles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            article_path, draft_path, production = self.make_package(root)
            article = json.loads(article_path.read_text(encoding="utf-8"))
            article["article"]["headline"] = "A deliberately long article headline that must reflow without colliding with release artwork"
            article["article"]["subtitle"] = "A deliberately long subtitle also needs to remain readable in its dedicated metadata panel."
            article_path.write_text(json.dumps(article), encoding="utf-8")
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["display"]["headline_zh"] = "这是一个刻意加长的中文标题，用于验证发布封面上的文章信息会自动换行而不会被艺术字遮挡"
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            result = MODULE.finalise(article_path, draft_path, root / "editorial-assets.json", production)
            for output in result["cover_art"]["outputs"].values():
                metadata = [tuple(item["bbox"]) for item in output["metadata_layout"]]
                art = [tuple(item["bbox"]) for item in output["line_layout"]]
                self.assertTrue(all(not MODULE.rect_overlap(left, right) for left in art for right in metadata))
                self.assertTrue(all(not MODULE.rect_overlap(tuple(item["bbox"]), tuple(output["issue_cover_bbox"])) for item in output["line_layout"]))
                self.assertIn("safe_regions", output)

    def test_finalise_can_render_only_confirmed_aspect_ratio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            article_path, draft_path, production = self.make_package(root)
            result = MODULE.finalise(
                article_path, draft_path, root / "editorial-assets.json", production, aspect_ratios=["9:16"]
            )
            self.assertEqual(set(result["cover_art"]["outputs"]), {"9:16"})
            self.assertTrue((root / "release" / "covers" / "cover-9x16.png").is_file())
            self.assertFalse((root / "release" / "covers" / "cover-16x9.png").exists())
            publish_copy = (root / "publish-copy.md").read_text(encoding="utf-8")
            self.assertIn("竖屏：release/covers/cover-9x16.png", publish_copy)
            self.assertNotIn("横屏：", publish_copy)

    def test_validator_rejects_shallow_questions_and_duplicate_cover_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            article_path, draft_path, _ = self.make_package(Path(temporary))
            article, paragraphs = MODULE.load_article(article_path)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["guide_questions"][0]["question"] = "Can wealth be fair?"
            with self.assertRaisesRegex(MODULE.EditorialAssetsError, "8 to 22"):
                MODULE.validate_draft(article, paragraphs, draft)
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["cover_text"][2]["text"] = draft["cover_text"][0]["text"]
            with self.assertRaisesRegex(MODULE.EditorialAssetsError, "distinct"):
                MODULE.validate_draft(article, paragraphs, draft)

    @staticmethod
    def tsv(*rows: tuple[str, str, str]) -> str:
        header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
        result = [header]
        for number, (text, confidence, line) in enumerate(rows, start=1):
            result.append(f"5\t1\t1\t1\t{line}\t{number}\t10\t20\t100\t20\t{confidence}\t{text}")
        return "\n".join(result)

    def test_local_ocr_extracts_date_and_rejects_ambiguous_candidates(self):
        completed = type("Completed", (), {"returncode": 0, "stdout": self.tsv(("JULY 4TH–10TH 2026", "91", "1"))})
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(MODULE.shutil, "which", return_value="tesseract"), mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            cover = Path(temporary) / "cover.png"
            Image.new("RGB", (20, 20)).save(cover)
            output = MODULE.extract_cover_issue_info(cover)
            self.assertEqual(output["status"], "complete")
            self.assertEqual(output["fields"][0]["field_type"], "cover_date")
            self.assertEqual(output["fields"][0]["normalized_value"], "JULY 4TH–10TH 2026")
        ambiguous = type("Completed", (), {"returncode": 0, "stdout": self.tsv(("JULY 4TH–10TH 2026", "91", "1"), ("AUGUST 1ST–7TH 2026", "91", "2"))})
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(MODULE.shutil, "which", return_value="tesseract"), mock.patch.object(MODULE.subprocess, "run", return_value=ambiguous):
            cover = Path(temporary) / "cover.png"
            Image.new("RGB", (20, 20)).save(cover)
            self.assertEqual(MODULE.extract_cover_issue_info(cover)["status"], "unavailable")
        low_confidence = type("Completed", (), {"returncode": 0, "stdout": self.tsv(("JULY 4TH–10TH 2026", "20", "1"))})
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(MODULE.shutil, "which", return_value="tesseract"), mock.patch.object(MODULE.subprocess, "run", return_value=low_confidence):
            cover = Path(temporary) / "cover.png"
            Image.new("RGB", (20, 20)).save(cover)
            self.assertEqual(MODULE.extract_cover_issue_info(cover)["status"], "unavailable")
