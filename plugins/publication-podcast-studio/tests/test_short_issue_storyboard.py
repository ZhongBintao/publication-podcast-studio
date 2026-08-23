import importlib.util
import json
import tempfile
import unittest
import wave
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "skills" / "publication-static-slide-video" / "scripts" / "static_slide_storyboard.py"
SPEC = importlib.util.spec_from_file_location("short_issue_storyboard", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ShortIssueStoryboardTests(unittest.TestCase):
    def make_package(self, root: Path) -> tuple[Path, Path]:
        (root / "assets").mkdir()
        (root / "audio" / "en").mkdir(parents=True)
        Image.new("RGB", (600, 800), "#9d1c22").save(root / "assets" / "front-page.png")
        Image.new("RGB", (800, 500), "#356b74").save(root / "assets" / "lead.png")
        with wave.open(str(root / "audio" / "en" / "final.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(48000)
            wav.writeframes(b"\0\0" * 48000 * 12)
        (root / "captions.en.srt").write_text(
            "1\n00:00:02,000 --> 00:00:07,000\nLead item.\n\n"
            "2\n00:00:07,000 --> 00:00:12,000\nSecond item.\n",
            encoding="utf-8",
        )
        source = {
            "schema_version": "2.0.0",
            "review_status": "verified",
            "source_sha256": "short-source",
            "content_mode": "short_issue",
            "source_language": "en",
            "publication": {"name": "City Ledger", "display_name": "城市纪事", "kind": "newspaper", "issue_date": "2026-08-23", "issue_number": "42"},
            "front_page": {"file": "assets/front-page.png", "source_page": 1},
            "content_units": [
                {"content_unit_id": "lead", "source_order": 2, "editorial_priority": 1, "episode_order": 1, "is_lead_story": True, "kind": "article", "metadata": {"section": "City", "kicker": "LEAD", "headline": "The lead story", "subtitle": "What changed", "byline": None, "dateline": None}, "page_numbers": [2], "paragraph_ids": ["p001"], "asset_ids": ["lead-photo"], "boundary_evidence": {}},
                {"content_unit_id": "brief", "source_order": 1, "editorial_priority": 2, "episode_order": 2, "is_lead_story": False, "kind": "brief", "metadata": {"section": "Briefing", "kicker": "BRIEF", "headline": "The second item", "subtitle": None, "byline": None, "dateline": None}, "page_numbers": [1], "paragraph_ids": ["p002"], "asset_ids": [], "boundary_evidence": {}},
            ],
            "paragraphs": [
                {"id": "p001", "order": 1, "content_unit_id": "lead", "text": "The lead item changed the city."},
                {"id": "p002", "order": 2, "content_unit_id": "brief", "text": "The second item explains the response."},
            ],
            "assets": [{"id": "lead-photo", "order": 1, "role": "article_image", "file": "assets/lead.png", "content_unit_id": "lead", "source_paragraph_ids": ["p001"]}],
        }
        (root / "article.json").write_text(json.dumps(source), encoding="utf-8")
        (root / "alignment.en.json").write_text(json.dumps({"segments": [
            {"segment_id": "opening", "start_seconds": 0, "end_seconds": 2, "source_paragraph_ids": []},
            {"segment_id": "lead", "start_seconds": 2, "end_seconds": 7, "source_paragraph_ids": ["p001"]},
            {"segment_id": "brief", "start_seconds": 7, "end_seconds": 11, "source_paragraph_ids": ["p002"]},
            {"segment_id": "closing", "start_seconds": 11, "end_seconds": 12, "source_paragraph_ids": []},
        ]}), encoding="utf-8")
        production = {
            "state": "complete", "variant": "en", "content_mode": "short_issue",
            "article": {"path": "article.json", "source_sha256": "short-source"},
            "video_timing": {"opening_seconds": 2.0, "asset_dwell_target_seconds": 3.0},
            "output": {"aspect_ratios": ["9:16"]},
            "artifacts": {"audio_en": "audio/en/final.wav", "captions_en_srt": "captions.en.srt", "alignment_en": "alignment.en.json"},
        }
        production_path = root / "production.json"
        production_path.write_text(json.dumps(production), encoding="utf-8")
        editorial = {
            "format": "publication-editorial-assets", "article_source_sha256": "short-source",
            "display": {"headline_zh": "本期城市简报", "subtitle_zh": "两则值得关注的变化"},
            "content_unit_display": [
                {"content_unit_id": "lead", "headline_zh": "城市迎来转折", "subtitle_zh": "变化从这里开始"},
                {"content_unit_id": "brief", "headline_zh": "随后如何应对", "subtitle_zh": ""},
            ],
            "guide_questions": [
                {"question": "What changed in the lead story for the city?", "translation_zh": "这座城市发生了什么转折？", "source_paragraph_ids": ["p001"]},
                {"question": "How did the response develop after that change?", "translation_zh": "随后各方如何应对？", "source_paragraph_ids": ["p002"]},
            ],
        }
        editorial_path = root / "editorial-assets.json"
        editorial_path.write_text(json.dumps(editorial), encoding="utf-8")
        return production_path, editorial_path

    def test_alignment_creates_unit_chapters_and_never_borrows_another_units_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production, editorial = self.make_package(root)
            result = MODULE.build_storyboard(production, editorial, root / "storyboard.json")
            self.assertEqual(result["content_mode"], "short_issue")
            content = result["slides"][1:]
            self.assertTrue(all(item["template_role"] == "issue_item" for item in content))
            lead = [item for item in content if item["content_unit_id"] == "lead"]
            brief = [item for item in content if item["content_unit_id"] == "brief"]
            self.assertEqual((lead[0]["start_seconds"], lead[-1]["end_seconds"]), (2.0, 7.0))
            self.assertEqual((brief[0]["start_seconds"], brief[-1]["end_seconds"]), (7.0, 12.0))
            self.assertTrue(all(item["asset"]["file"] == "assets/lead.png" for item in lead))
            self.assertTrue(all(item["asset"]["file"] == "assets/front-page.png" for item in brief))
            source = MODULE.resolve_article(json.loads(production.read_text()), root)[1]
            brief_content = MODULE.display_content(source, result, "Second item.", "第二则。", brief[0])
            self.assertEqual(brief_content["article"]["headline_zh"], "随后如何应对")
            self.assertIn("城市纪事", brief_content["article"]["byline_dateline_issue"])

    def test_short_issue_requires_alignment_and_frozen_timing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production, editorial = self.make_package(root)
            payload = json.loads(production.read_text())
            payload["artifacts"].pop("alignment_en")
            production.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.StoryboardError, "alignment artifact"):
                MODULE.build_storyboard(production, editorial, root / "storyboard.json")
            payload["artifacts"]["alignment_en"] = "alignment.en.json"
            production.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.StoryboardError, "differs from the frozen"):
                MODULE.build_storyboard(production, editorial, root / "storyboard.json", opening_duration=3.0)


if __name__ == "__main__":
    unittest.main()
