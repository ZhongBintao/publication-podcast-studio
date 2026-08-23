import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "lib" / "publication_package.py"
SPEC = importlib.util.spec_from_file_location("publication_package_contract", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublicationPackageTests(unittest.TestCase):
    def test_legacy_article_is_normalised_without_rewriting_it(self):
        source = MODULE.normalise_source_package({
            "review_status": "verified",
            "source_sha256": "legacy",
            "article": {"headline": "Legacy article", "subtitle": None},
            "issue_cover": {"file": "assets/cover.png"},
            "paragraphs": [{"order": 1, "text": "Verified paragraph."}],
            "assets": [],
        }, require_front_page=True)
        self.assertEqual(source["content_mode"], "article")
        self.assertEqual(source["publication"]["name"], "The Economist")
        self.assertEqual(source["front_page"]["file"], "assets/cover.png")
        self.assertEqual(source["paragraphs"][0]["content_unit_id"], "item-001")

    def test_short_issue_requires_one_lead_and_complete_unit_coverage(self):
        payload = {
            "review_status": "verified", "source_sha256": "short", "content_mode": "short_issue", "source_language": "en",
            "publication": {"name": "Daily Paper", "display_name": "每日新闻", "kind": "newspaper"},
            "front_page": {"file": "assets/front.png"},
            "content_units": [
                {"content_unit_id": "a", "source_order": 1, "editorial_priority": 1, "episode_order": 1, "is_lead_story": True, "metadata": {"headline": "Lead"}},
                {"content_unit_id": "b", "source_order": 2, "editorial_priority": 2, "episode_order": 2, "is_lead_story": False, "metadata": {"headline": "Brief"}},
            ],
            "paragraphs": [
                {"id": "p001", "order": 1, "content_unit_id": "a", "text": "Lead text."},
                {"id": "p002", "order": 2, "content_unit_id": "b", "text": "Brief text."},
            ],
            "assets": [],
        }
        source = MODULE.normalise_source_package(payload, require_front_page=True)
        self.assertEqual([item["content_unit_id"] for item in source["content_units"]], ["a", "b"])
        broken = {**payload, "content_units": [{**item, "is_lead_story": False} for item in payload["content_units"]]}
        with self.assertRaisesRegex(MODULE.PublicationPackageError, "exactly one lead"):
            MODULE.normalise_source_package(broken)
        broken = {**payload, "paragraphs": payload["paragraphs"][:1]}
        with self.assertRaisesRegex(MODULE.PublicationPackageError, "has no verified paragraphs"):
            MODULE.normalise_source_package(broken)


if __name__ == "__main__":
    unittest.main()
