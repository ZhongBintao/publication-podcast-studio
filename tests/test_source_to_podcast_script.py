import importlib.util
from pathlib import Path
import json
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "skills" / "economist-source-to-podcast-script" / "scripts" / "source_to_podcast_script.py"
SPEC = importlib.util.spec_from_file_location("source_to_podcast_script", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SourceToPodcastScriptTests(unittest.TestCase):
    def setUp(self):
        self.article = {
            "review_status": "verified",
            "source_sha256": "source-hash",
            "paragraphs": [
                {"order": 1, "text": "First fact (IPO)—still essential (see chart)."},
                {"order": 2, "text": "Second fact."},
                {"order": 3, "text": "Third fact."},
                {"order": 4, "text": "Fourth fact."},
                {"order": 5, "text": "Fifth fact."},
            ],
        }
        self.paragraphs = self.article["paragraphs"]

    def zh_candidate(self, overrides=None):
        overrides = overrides or {}
        return [
            {
                "segment_id": f"draft-{paragraph['order']}",
                "speaker_id": MODULE.speaker_for_paragraph(paragraph["order"], len(self.paragraphs)),
                "kind": "sentence_split",
                "spoken_text": overrides.get(paragraph["order"], f"第{paragraph['order']}段。"),
                "source_paragraph_ids": [f"p{paragraph['order']:03d}"],
            }
            for paragraph in self.paragraphs
        ]

    def test_english_source_keeps_factual_parenthetical_content(self):
        self.assertEqual(
            MODULE.english_spoken_source("A fact (ie, detail)—continues."),
            "A fact, i.e., detail, continues.",
        )

    def test_chinese_source_preserves_parentheses_and_dash(self):
        self.assertEqual(
            MODULE.chinese_translation_source("A fact (IPO)—continues (see chart)."),
            "A fact (IPO)—continues.",
        )

    def test_spoken_source_does_not_damage_numbers(self):
        self.assertEqual(MODULE.english_spoken_source("A $4.3bn deal and 9,500 funds."), "A $4.3bn deal and 9,500 funds.")

    def test_translation_request_is_compact_and_uses_chinese_source(self):
        payload = MODULE.translation_request(self.article, self.paragraphs)
        self.assertEqual(set(payload), {"source_sha256", "language", "paragraphs"})
        self.assertEqual(payload["paragraphs"][0]["source_text"], "First fact (IPO)—still essential.")
        self.assertNotIn("spoken_source", payload["paragraphs"][0])

    def test_english_removes_only_visual_reference_and_assigns_two_hosts(self):
        segments = MODULE.build_english(self.paragraphs)
        self.assertEqual(segments[0]["spoken_text"], "First fact, IPO, still essential.")
        self.assertFalse(any(MODULE.SPOKEN_BRACKETS.search(item["spoken_text"]) for item in segments))
        self.assertEqual([item["speaker_id"] for item in segments], ["primary", "primary", "secondary", "primary", "primary"])
        self.assertTrue(all(item["kind"] in {"verbatim", "sentence_split"} for item in segments))
        MODULE.validate_structure(segments, "en")
        MODULE.validate_coverage(self.paragraphs, segments)
        MODULE.validate_english(self.paragraphs, segments)

    def test_finalize_zh_reindexes_and_preserves_paragraph_speakers(self):
        segments = MODULE.finalize_zh(self.paragraphs, self.zh_candidate())
        self.assertEqual([segment["segment_id"] for segment in segments], ["zh-CN-001", "zh-CN-002", "zh-CN-003", "zh-CN-004", "zh-CN-005"])
        self.assertEqual(segments[2]["speaker_id"], "secondary")
        self.assertTrue(all(segment["source_paragraph_ids"] for segment in segments))
        MODULE.validate_structure(segments, "zh-CN")
        MODULE.validate_coverage(self.paragraphs, segments)

    def test_short_article_does_not_add_a_second_host_without_content(self):
        paragraphs = [{"order": 1, "text": "Only source paragraph."}]
        segments = MODULE.build_english(paragraphs)
        self.assertEqual([item["speaker_id"] for item in segments], ["primary"])
        MODULE.validate_structure(segments, "en")
        MODULE.validate_coverage(paragraphs, segments)

    def test_split_segments_keep_one_paragraph_speaker(self):
        paragraphs = [
            {"order": 1, "text": "First source paragraph."},
            {"order": 2, "text": "Second source paragraph." + " More detail." * 160},
        ]
        segments = MODULE.build_english(paragraphs)
        second_speakers = {item["speaker_id"] for item in segments if item["source_paragraph_ids"] == ["p002"]}
        self.assertEqual(second_speakers, {"secondary"})
        MODULE.validate_coverage(paragraphs, segments)

    def test_chinese_lint_allows_bare_proper_name(self):
        segments = MODULE.finalize_zh(self.paragraphs, self.zh_candidate({1: "宇树科技获得批准，估值为420亿元，也就是60亿美元。"}))
        self.assertEqual(MODULE.chinese_punctuation_issues(segments), [])

    def test_chinese_lint_rejects_all_parenthetical_content(self):
        segments = MODULE.finalize_zh(self.paragraphs, self.zh_candidate({1: "宇树科技（Unitree）获得批准。"}))
        reason = MODULE.chinese_punctuation_issues(segments)[0]["reason"]
        self.assertIn("parenthetical", reason)

    def test_chinese_lint_reports_comma_wrapped_items(self):
        segments = MODULE.finalize_zh(self.paragraphs, self.zh_candidate({1: "首次公开募股，IPO，获得批准，估值为420亿元，60亿美元，。"}))
        issues = MODULE.chinese_punctuation_issues(segments)
        self.assertEqual(issues[0]["source_paragraph_id"], "p001")
        self.assertIn("Latin", issues[0]["reason"])
        self.assertIn("currency", issues[0]["reason"])

    def test_chinese_lint_reports_unpaired_brackets_and_repeated_punctuation(self):
        segments = MODULE.finalize_zh(self.paragraphs, self.zh_candidate({1: "首次公开募股（IPO，，获得批准。"}))
        reason = MODULE.chinese_punctuation_issues(segments)[0]["reason"]
        self.assertIn("unpaired", reason)
        self.assertIn("repeated", reason)

    def test_retry_request_and_apply_patch_only_replace_bad_paragraphs(self):
        bad = MODULE.finalize_zh(self.paragraphs, self.zh_candidate({1: "公司，Unitree，估值为420亿元，60亿美元，。"}))
        payload = MODULE.retry_request(self.article, self.paragraphs, bad, attempt=1)
        self.assertEqual([item["source_paragraph_id"] for item in payload["paragraphs"]], ["p001"])
        self.assertEqual(payload["paragraphs"][0]["source_text"], "First fact (IPO)—still essential.")
        patch = [self.zh_candidate({1: "公司 Unitree 的估值为420亿元，也就是60亿美元。"})[0]]
        repaired = MODULE.apply_zh_retry(self.paragraphs, bad, patch)
        self.assertEqual(repaired[0]["spoken_text"], "公司 Unitree 的估值为420亿元，也就是60亿美元。")
        self.assertEqual(repaired[4]["spoken_text"], "第5段。")
        self.assertEqual(MODULE.chinese_punctuation_issues(repaired), [])
        MODULE.validate_structure(repaired, "zh-CN")
        MODULE.validate_coverage(self.paragraphs, repaired)

    def test_retry_limit_is_one(self):
        bad = MODULE.finalize_zh(self.paragraphs, self.zh_candidate({1: "公司，IPO，。"}))
        with self.assertRaisesRegex(ValueError, "limit"):
            MODULE.retry_request(self.article, self.paragraphs, bad, attempt=2)

    def test_english_rejects_paraphrase(self):
        segments = MODULE.build_english(self.paragraphs)
        segments[0]["spoken_text"] = "A different fact."
        with self.assertRaisesRegex(ValueError, "lexical"):
            MODULE.validate_english(self.paragraphs, segments)

    def test_english_request_carries_conversational_style_without_full_source_duplication(self):
        request = MODULE.english_request(self.article, self.paragraphs)
        self.assertIn("short, direct clauses", request["instructions"])
        self.assertIn("well, so, right", request["instructions"])
        self.assertEqual(set(request["paragraphs"][0]), {"source_paragraph_id", "speaker_id", "source_text"})
        self.assertNotIn("spoken_text", request["paragraphs"][0])

    def test_finalize_english_allows_controlled_fillers_and_contractions(self):
        candidate = [
            {
                "segment_id": "draft-1",
                "speaker_id": "primary",
                "kind": "sentence_split",
                "spoken_text": "Well, first fact, IPO, still essential.",
                "source_paragraph_ids": ["p001"],
            },
            {
                "segment_id": "draft-2",
                "speaker_id": "primary",
                "kind": "sentence_split",
                "spoken_text": "Right, second fact.",
                "source_paragraph_ids": ["p002"],
            },
            *[
                {
                    "segment_id": f"draft-{index}",
                    "speaker_id": MODULE.speaker_for_paragraph(index, len(self.paragraphs)),
                    "kind": "sentence_split",
                    "spoken_text": f"And, {label}.",
                    "source_paragraph_ids": [f"p{index:03d}"],
                }
                for index, label in ((3, "third fact"), (4, "fourth fact"), (5, "fifth fact"))
            ],
        ]
        result = MODULE.finalize_english(self.paragraphs, candidate)
        self.assertEqual(result[0]["segment_id"], "en-001")
        self.assertEqual(result[0]["spoken_text"], "Well, first fact, IPO, still essential.")
        MODULE.validate_coverage(self.paragraphs, result)

    def test_english_rejects_unapproved_added_claim(self):
        candidate = [
            {
                "segment_id": "draft-1",
                "speaker_id": "primary",
                "kind": "sentence_split",
                "spoken_text": "Well, this is surprising: first fact, IPO, still essential.",
                "source_paragraph_ids": ["p001"],
            },
            *[
                {
                    "segment_id": f"draft-{index}",
                    "speaker_id": MODULE.speaker_for_paragraph(index, len(self.paragraphs)),
                    "kind": "sentence_split",
                    "spoken_text": f"{label}.",
                    "source_paragraph_ids": [f"p{index:03d}"],
                }
                for index, label in ((2, "second fact"), (3, "third fact"), (4, "fourth fact"), (5, "fifth fact"))
            ],
        ]
        with self.assertRaisesRegex(ValueError, "lexical"):
            MODULE.finalize_english(self.paragraphs, candidate)

    def test_english_lexical_check_expands_contractions(self):
        paragraphs = [{"order": 1, "text": "The system does not work."}]
        segments = [{
            "segment_id": "en-001",
            "speaker_id": "primary",
            "kind": "sentence_split",
            "spoken_text": "Well, the system doesn't work.",
            "source_paragraph_ids": ["p001"],
        }]
        MODULE.validate_structure(segments, "en")
        MODULE.validate_coverage(paragraphs, segments)
        MODULE.validate_english(paragraphs, segments)

    def test_english_rejects_retained_parentheses(self):
        segments = MODULE.build_english(self.paragraphs)
        segments[0]["spoken_text"] = "First fact (IPO), still essential."
        with self.assertRaisesRegex(ValueError, "bracketed"):
            MODULE.validate_english(self.paragraphs, segments)

    def test_transition_segments_are_rejected(self):
        segments = MODULE.build_english(self.paragraphs)
        segments.append({
            "segment_id": f"en-{len(segments) + 1:03d}",
            "speaker_id": "secondary",
            "kind": "transition",
            "spoken_text": "Let’s continue.",
            "source_paragraph_ids": [],
        })
        with self.assertRaisesRegex(ValueError, "illegal segment kind"):
            MODULE.validate_structure(segments, "en")

    def test_one_paragraph_cannot_mix_speakers(self):
        candidate = self.zh_candidate()
        candidate[2]["speaker_id"] = "primary"
        with self.assertRaisesRegex(ValueError, "wrong deterministic speaker"):
            MODULE.finalize_zh(self.paragraphs, candidate)

    def test_segments_from_one_paragraph_cannot_mix_speakers(self):
        candidate = self.zh_candidate()
        candidate[2]["speaker_id"] = "secondary"
        candidate.insert(3, {
            "segment_id": "draft-3b",
            "speaker_id": "primary",
            "kind": "sentence_split",
            "spoken_text": "同一段的另一句。",
            "source_paragraph_ids": ["p003"],
        })
        with self.assertRaisesRegex(ValueError, "same speaker"):
            MODULE.finalize_zh(self.paragraphs, candidate)

    def test_coverage_rejects_missing_paragraph(self):
        segments = MODULE.build_english(self.paragraphs)
        segments = [item for item in segments if item["source_paragraph_ids"] != ["p003"]]
        segments = [item for item in segments if item["kind"] != "transition"]
        with self.assertRaisesRegex(ValueError, "covered"):
            MODULE.validate_coverage(self.paragraphs, segments)

    def test_init_production_only_declares_selected_variant_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article_path = root / "article.json"
            article_path.write_text(json.dumps(self.article), encoding="utf-8")
            for variant, expected_languages, expected_artifacts in (
                ("en", ["en"], {"script_en"}),
                ("en-zh", ["en"], {"script_en", "subtitle_script_en_zh"}),
                ("zh-CN", ["zh-CN"], {"script_zh_cn"}),
            ):
                production_path = root / f"{variant}.production.json"
                MODULE.init_production(article_path, production_path, variant, "southeastasia", ["16:9"])
                production = json.loads(production_path.read_text(encoding="utf-8"))
                self.assertEqual(production["variant"], variant)
                self.assertEqual(production["languages"], expected_languages)
                self.assertEqual(set(production["artifacts"]), expected_artifacts)
                self.assertNotIn("key", json.dumps(production).lower())
            bilingual = json.loads((root / "en-zh.production.json").read_text(encoding="utf-8"))
            self.assertEqual(bilingual["captions"]["provider"], "approved-bilingual-script")
            self.assertEqual(bilingual["captions"]["target_locale"], "zh-Hans")

    def test_reviewed_subtitle_draft_preserves_complete_sentence_spans_and_source_links(self):
        script = MODULE.build_english(self.paragraphs)
        request = MODULE.subtitle_request(self.article, script)
        draft = {"units": [{"unit_id": item["unit_id"], "translation_zh": f"第{index}条字幕。"} for index, item in enumerate(request["units"], start=1)]}
        result = MODULE.validate_subtitle_draft(self.article, script, draft)
        self.assertEqual(result["translation_quality"], "reviewed")
        self.assertEqual(result["caption_unit_policy"], "full_sentence")
        self.assertTrue(result["units"][0]["source_text"].endswith("."))
        self.assertTrue(result["units"][0]["source_spans"])

    def test_reviewed_subtitle_draft_rejects_english_clause_and_out_of_order_unit(self):
        script = MODULE.build_english(self.paragraphs)
        request = MODULE.subtitle_request(self.article, script)
        draft = {"units": [{"unit_id": item["unit_id"], "translation_zh": "Englishword Chineseword。"} for item in request["units"]]}
        with self.assertRaisesRegex(ValueError, "English clause"):
            MODULE.validate_subtitle_draft(self.article, script, draft)
        draft = {"units": [{"unit_id": item["unit_id"], "translation_zh": "中文。"} for item in reversed(request["units"])]}
        with self.assertRaisesRegex(ValueError, "source order"):
            MODULE.validate_subtitle_draft(self.article, script, draft)

    def test_sentence_units_can_cross_audio_segments_without_splitting_the_sentence(self):
        script = [
            {"segment_id": "en-001", "speaker_id": "primary", "kind": "sentence_split", "spoken_text": "A complete sentence begins", "source_paragraph_ids": ["p001"]},
            {"segment_id": "en-002", "speaker_id": "primary", "kind": "sentence_split", "spoken_text": "and ends here. Another sentence follows.", "source_paragraph_ids": ["p001"]},
        ]
        request = MODULE.subtitle_request(self.article, script)
        self.assertEqual([item["source_text"] for item in request["units"]], ["A complete sentence begins and ends here.", "Another sentence follows."])
        self.assertEqual([item["segment_id"] for item in request["units"][0]["source_spans"]], ["en-001", "en-002"])

    def test_sentence_units_do_not_split_inside_an_english_abbreviation(self):
        script = [{"segment_id": "en-001", "speaker_id": "primary", "kind": "verbatim", "spoken_text": "The U.S. market changed. It then recovered.", "source_paragraph_ids": ["p001"]}]
        request = MODULE.subtitle_request(self.article, script)
        self.assertEqual([item["source_text"] for item in request["units"]], ["The U.S. market changed.", "It then recovered."])
