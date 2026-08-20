import importlib.util
from pathlib import Path
from unittest import mock
import unittest


SCRIPT = Path(__file__).parents[1] / "skills" / "economist-article-subtract" / "scripts" / "economist_article_subtract.py"
SPEC = importlib.util.spec_from_file_location("economist_article_subtract", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EconomistArticleSubtractTests(unittest.TestCase):
    def setUp(self):
        self.index = {
            "source_sha256": "source-hash",
            "pages": [
                {"number": 3, "text": "Contents 19 Strength in numbers", "words": [], "width": 100, "height": 100},
                {"number": 19, "text": "American power Strength in numbers", "words": [], "width": 100, "height": 100},
            ],
        }
        self.manifest = {"source_sha256": "source-hash"}
        self.scope = {
            "source_sha256": "source-hash", "review_status": "verified", "article": {"headline": "Strength in numbers"},
            "article_pages": [19], "text_regions": [{"id": "p19-left", "page": 19, "order": 1, "bbox": [0, 0, 50, 100]}],
            "excluded_regions": [], "assets": [], "uncertain_spans": [],
            "boundary_evidence": {"start_reason": "heading", "end_reason": "next article"},
        }

    def test_contents_page_loses_to_body_page(self):
        candidates = MODULE.locate_candidates(self.index, "Strength in numbers", None)
        self.assertEqual(candidates[0]["page"], 19)

    def test_repeated_article_signature_is_one_candidate(self):
        index = {"pages": [{"number": number, "text": "The Wrecking-ball Revolution", "words": []} for number in (13, 14, 15)]}
        candidates = MODULE.locate_candidates(index, "The Wrecking-ball Revolution", None)
        self.assertEqual(candidates[0]["matched_pages"], [13, 14, 15])

    def test_review_includes_all_matched_pages_and_boundaries(self):
        pages = MODULE.review_page_numbers([{"matched_pages": [13, 14, 15, 16, 17, 18]}], 60)
        self.assertEqual(pages, [12, 13, 14, 15, 16, 17, 18, 19])

    def test_small_region_uses_context_plus_high_resolution_crop(self):
        visual_index = {"pages": [{"number": number, "width": 100, "height": 100} for number in range(1, 20)]}
        plan = MODULE.page_visual_plan(visual_index, self.scope)
        self.assertEqual(plan[0]["mode"], "split_regions")
        self.assertLess(plan[0]["planned_reading_pixels"], plan[0]["baseline_reading_pixels"])
        self.assertEqual(plan[0]["regions"][0]["bbox"], [0, 0, 62, 100])

    def test_large_region_uses_existing_high_resolution_full_page(self):
        self.scope["text_regions"][0]["bbox"] = [0, 0, 100, 100]
        visual_index = {"pages": [{"number": number, "width": 100, "height": 100} for number in range(1, 20)]}
        plan = MODULE.page_visual_plan(visual_index, self.scope)
        self.assertEqual(plan[0]["mode"], "full_page")
        self.assertEqual(plan[0]["planned_reading_pixels"], plan[0]["baseline_reading_pixels"])

    def test_scope_requires_no_uncertainty(self):
        self.scope["uncertain_spans"] = [{"text": "?"}]
        with self.assertRaisesRegex(ValueError, "no uncertain spans"):
            MODULE.validate_scope(self.scope, self.manifest, self.index)

    def test_model_rejects_terminal_square_and_excluded_panel(self):
        request = {"source_sha256": "source-hash", "article": {"headline": "Strength in numbers"}, "text_regions": self.scope["text_regions"]}
        model = {
            "source_sha256": "source-hash", "review_status": "verified", "article": {"headline": "Strength in numbers"},
            "paragraphs": [{"order": 1, "text": "A paragraph ■", "source_region_ids": ["p19-left"]}],
            "corrections": [], "uncertain_spans": [],
        }
        with self.assertRaisesRegex(ValueError, "excluded marker"):
            MODULE.validate_model(model, request)

    def test_model_accepts_visual_correction_with_provenance(self):
        request = {"source_sha256": "source-hash", "article": {"headline": "Hope v reality"}, "text_regions": [{"id": "p47-middle", "page": 47, "order": 1, "bbox": [0, 0, 50, 100]}]}
        model = {
            "source_sha256": "source-hash", "review_status": "verified", "article": {"headline": "Hope v reality"},
            "paragraphs": [{"order": 1, "text": "TWO PARALLEL Middle Easts exist.", "source_region_ids": ["p47-middle"]}],
            "corrections": [{"type": "drop_cap", "before": "WO", "after": "TWO", "source_region_ids": ["p47-middle"]}], "uncertain_spans": [],
        }
        MODULE.validate_model(model, request)

    def test_escalation_requires_known_split_page_and_reason(self):
        request = {
            "source_sha256": "source-hash",
            "context_pages": [{"page": 47}],
            "page_visuals": [{"page": 47, "mode": "split_regions"}],
        }
        escalation = {
            "source_sha256": "source-hash", "status": "needs_high_res_context", "pages": [47],
            "reasons": [{"page": 47, "reason": "Cross-column continuation is unclear."}],
        }
        self.assertEqual(MODULE.validate_escalation(escalation, request), [47])

    def test_issue_cover_is_a_separate_issue_level_asset(self):
        with self.subTest("relative asset path"):
            from tempfile import TemporaryDirectory
            with TemporaryDirectory() as temporary:
                output = Path(temporary)
                rendered = output / "assets" / "issue-cover.png"
                rendered.parent.mkdir()
                rendered.touch()
                with mock.patch.object(MODULE, "render_page", return_value=rendered):
                    cover = MODULE.materialise_issue_cover(Path("issue.pdf"), output)
                self.assertEqual(cover["file"], "assets/issue-cover.png")
                self.assertEqual(cover["source_page"], 1)
