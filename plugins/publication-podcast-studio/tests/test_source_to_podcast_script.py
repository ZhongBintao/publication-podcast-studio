import importlib.util
from pathlib import Path
import json
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).parents[1] / "skills" / "publication-source-to-podcast-script" / "scripts" / "source_to_podcast_script.py"
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

    def framed_english_candidate(self, body=None):
        return {
            "opening": [
                {
                    "segment_id": "opening-hook", "speaker_id": "primary", "kind": "opening",
                    "spoken_text": "The first fact creates the tension at the centre of this story.",
                    "source_paragraph_ids": ["p001"],
                },
                {
                    "segment_id": "opening-handoff", "speaker_id": "primary", "kind": "opening",
                    "spoken_text": "The details show why that tension is worth following.",
                    "source_paragraph_ids": [],
                },
            ],
            "body": body if body is not None else self.build_body_candidate(),
            "closing": [
                {
                    "segment_id": "closing-payoff", "speaker_id": "secondary", "kind": "closing",
                    "spoken_text": "That first tension is still the point to remember.",
                    "source_paragraph_ids": ["p001"],
                },
                {
                    "segment_id": "closing-signoff", "speaker_id": "secondary", "kind": "closing",
                    "spoken_text": "For now, thanks for listening.",
                    "source_paragraph_ids": [],
                },
            ],
        }

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

    def test_english_allows_source_bounded_paraphrase(self):
        segments = MODULE.build_english(self.paragraphs)
        segments[0]["spoken_text"] = "A different fact."
        MODULE.validate_english(self.paragraphs, segments)

    def test_english_request_carries_conversational_style_without_full_source_duplication(self):
        request = MODULE.english_request(self.article, self.paragraphs)
        self.assertIn("short turns", request["instructions"])
        self.assertIn("well, so, right", request["instructions"])
        self.assertIn("source-bounded", request["instructions"])
        self.assertNotIn("SOURCE FIDELITY IS THE NON-NEGOTIABLE RULE", request["instructions"])
        self.assertEqual(request["speaker_balance"]["target_word_share"]["primary"], 0.5)
        self.assertEqual(request["speaker_balance"]["acceptable_word_share"]["minimum"], 0.4)
        self.assertEqual(set(request["paragraphs"][0]), {
            "source_paragraph_id", "source_speaker_id", "partner_speaker_id",
            "max_spoken_segment_chars", "max_caption_unit_chars", "source_text",
            "content_unit_id", "content_unit_headline", "begins_content_unit",
        })
        self.assertEqual(request["paragraphs"][0]["max_caption_unit_chars"], MODULE.MAX_CAPTION_UNIT_CHARS)
        self.assertNotIn("spoken_text", request["paragraphs"][0])

    def test_duration_is_a_target_with_a_hard_cap_not_a_minimum(self):
        short_source = {"content_mode": "short_issue"}
        policy = MODULE.normalise_duration_policy(short_source)
        self.assertEqual((policy["target_minutes"], policy["max_minutes"]), (20.0, 25.0))
        self.assertFalse(policy["target_is_minimum"])
        short_script = [{"spoken_text": "A concise complete script."}]
        self.assertLess(MODULE.validate_duration(short_script, "en", policy)["estimated_minutes"], 20)
        long_script = [{"spoken_text": " ".join(["word"] * 4000)}]
        with self.assertRaisesRegex(ValueError, "hard duration cap"):
            MODULE.validate_duration(long_script, "en", policy)
        unbounded = MODULE.normalise_duration_policy(short_source, {"mode": "coverage_unbounded", "target_minutes": 20, "max_minutes": None})
        self.assertIsNone(unbounded["max_minutes"])
        MODULE.validate_duration(long_script, "en", unbounded)
        with self.assertRaisesRegex(ValueError, "retry limit"):
            MODULE.duration_retry_request({}, [], [], "en", policy, attempt=2)

    def test_english_request_freezes_creative_frame_and_seeded_schedule(self):
        request = MODULE.english_request(self.article, self.paragraphs)
        self.assertEqual(request["creative_frame"]["enabled"], True)
        self.assertEqual(request["creative_frame"]["source_policy"], "source_bounded_delivery_only")
        self.assertEqual(request["creative_frame"]["media_mode"], "audio_and_bilingual_captions")
        self.assertEqual(request["creative_frame"]["arc_policy"], MODULE.CREATIVE_FRAME_ARC_POLICY)
        self.assertEqual(request["creative_frame"]["anchor_source_paragraph_id"], "p001")
        self.assertEqual(request["creative_frame"]["opening"]["min_segments"], 2)
        self.assertEqual(request["creative_frame"]["opening"]["max_segments"], 4)
        self.assertEqual(request["creative_frame"]["closing"]["target_words"], 40)
        self.assertEqual(request["speaker_schedule"]["mode"], "seeded_constrained_random")
        self.assertEqual(request["speaker_schedule"]["seed"], MODULE.speaker_seed("source-hash"))
        self.assertTrue(request["speaker_schedule"]["avoid_mechanical_alternation"])

    def test_finalize_english_places_creative_opening_and_closing_around_body(self):
        candidate = self.framed_english_candidate()
        result = MODULE.finalize_english(self.paragraphs, candidate)
        self.assertEqual(result[0]["kind"], "opening")
        self.assertEqual(result[-1]["kind"], "closing")
        self.assertEqual(result[0]["source_paragraph_ids"], ["p001"])
        self.assertEqual(result[-1]["source_paragraph_ids"], [])
        MODULE.validate_coverage(self.paragraphs, result, speaker_policy="english")

    def test_english_framing_retry_repairs_only_failed_wrappers(self):
        candidate = self.framed_english_candidate()
        candidate["opening"] = candidate["opening"][1:]
        payload = MODULE.english_framing_retry_payload(self.article, self.paragraphs, candidate, 1)
        self.assertEqual(payload["repair"], {"opening": True, "closing": False})
        repaired = MODULE.apply_english_framing_retry(
            self.paragraphs,
            candidate,
            {"opening": self.framed_english_candidate()["opening"]},
        )
        self.assertEqual(repaired[0]["source_paragraph_ids"], ["p001"])
        self.assertEqual(repaired[-2]["spoken_text"], candidate["closing"][0]["spoken_text"])
        with self.assertRaisesRegex(ValueError, "retry limit"):
            MODULE.english_framing_retry_payload(self.article, self.paragraphs, candidate, 2)

    def test_short_issue_framing_anchors_to_lead_without_linking_other_items(self):
        source = {
            "review_status": "verified", "source_sha256": "short-source", "content_mode": "short_issue",
            "source_language": "en",
            "publication": {"name": "City Ledger", "display_name": "城市纪事", "kind": "newspaper"},
            "front_page": {"file": "assets/front.png"},
            "content_units": [
                {"content_unit_id": "lead", "source_order": 2, "editorial_priority": 1, "episode_order": 1, "is_lead_story": True, "kind": "article", "metadata": {"headline": "Lead"}, "paragraph_ids": ["p001"]},
                {"content_unit_id": "brief", "source_order": 1, "editorial_priority": 2, "episode_order": 2, "is_lead_story": False, "kind": "brief", "metadata": {"headline": "Brief"}, "paragraph_ids": ["p002"]},
            ],
            "paragraphs": [
                {"id": "p001", "order": 1, "content_unit_id": "lead", "text": "The lead item changed the city."},
                {"id": "p002", "order": 2, "content_unit_id": "brief", "text": "A separate brief records another event."},
            ],
            "assets": [],
        }
        article = MODULE.source_context(source, source["paragraphs"])
        paragraphs = article["paragraphs"]
        request = MODULE.english_request(article, paragraphs)
        self.assertEqual(request["content_mode"], "short_issue")
        self.assertEqual(request["creative_frame"]["anchor_source_paragraph_id"], "p001")
        opening = self.framed_english_candidate()["opening"]
        closing = self.framed_english_candidate()["closing"]
        self.assertEqual(MODULE.wrapper_arc_issues(opening, closing, paragraphs), [])
        self.assertNotIn("p002", {source_id for item in opening + closing for source_id in item["source_paragraph_ids"]})

    def test_unlinked_english_wrapper_cannot_introduce_source_fact(self):
        candidate = {
            "opening": [
                {
                    "segment_id": "opening-draft", "speaker_id": "primary", "kind": "opening",
                    "spoken_text": "In 2025, the market changed.", "source_paragraph_ids": [],
                },
                self.framed_english_candidate()["opening"][1],
            ],
            "body": self.build_body_candidate(),
            "closing": self.framed_english_candidate()["closing"],
        }
        with self.assertRaisesRegex(ValueError, "Unlinked opening/closing"):
            MODULE.finalize_english(self.paragraphs, candidate)

    def build_body_candidate(self):
        return [
            {
                "segment_id": f"draft-{paragraph['order']}", "speaker_id": MODULE.speaker_for_paragraph(paragraph["order"], len(self.paragraphs)),
                "kind": "sentence_split", "spoken_text": f"Paragraph {paragraph['order']} is in the story.",
                "source_paragraph_ids": [f"p{paragraph['order']:03d}"],
            }
            for paragraph in self.paragraphs
        ]

    def test_english_allows_a_discourse_marker_outside_the_old_closed_list(self):
        candidate = self.build_body_candidate()
        candidate[0]["spoken_text"] = "Frankly, paragraph 1 is in the story."
        result = MODULE.finalize_english(self.paragraphs, candidate)
        self.assertEqual(result[0]["spoken_text"], "Frankly, paragraph 1 is in the story.")

    def test_repeated_discourse_markers_are_reported_as_warnings_not_rejected(self):
        segments = self.build_body_candidate()
        for index in (0, 2, 4):
            segments[index]["spoken_text"] = f"Well, paragraph {index + 1} is in the story."
        warnings = MODULE.english_delivery_warnings(segments)
        self.assertTrue(any("well" in warning for warning in warnings))

    def test_marker_only_interaction_segment_is_rejected(self):
        segments = self.build_body_candidate()
        segments.insert(1, {
            "segment_id": "marker-reaction", "speaker_id": "secondary", "kind": "reaction",
            "spoken_text": "Well.", "source_paragraph_ids": ["p001"],
        })
        with self.assertRaisesRegex(ValueError, "standalone"):
            MODULE.finalize_english(self.paragraphs, segments)

    def test_seeded_speaker_schedule_is_reproducible_but_not_fixed_alternation(self):
        segments = [
            {"segment_id": f"draft-{index}", "speaker_id": "primary", "kind": "sentence_split", "spoken_text": f"A factual point number {index}.", "source_paragraph_ids": ["p001"]}
            for index in range(1, 9)
        ]
        segments[1]["kind"] = "reaction"
        segments[1]["spoken_text"] = "That sets the scene."
        segments[5]["kind"] = "reaction"
        segments[5]["spoken_text"] = "That changes the picture."
        first = MODULE.assign_speaker_schedule(segments, 1)
        repeat = MODULE.assign_speaker_schedule(segments, 1)
        other = MODULE.assign_speaker_schedule(segments, 2)
        self.assertEqual([item["speaker_id"] for item in first], [item["speaker_id"] for item in repeat])
        self.assertNotEqual([item["speaker_id"] for item in first], [item["speaker_id"] for item in other])
        self.assertLessEqual(max(len(list(group)) for _, group in __import__("itertools").groupby(item["speaker_id"] for item in first)), 4)
        self.assertFalse(MODULE._mechanically_alternates([item["speaker_id"] for item in first]))

    def test_speaker_seed_uses_policy_version_and_init_can_freeze_explicit_seed(self):
        expected = int(__import__("hashlib").sha256(b"source-hash:5.3").hexdigest()[:16], 16)
        self.assertEqual(MODULE.speaker_seed("source-hash"), expected)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article_path = root / "article.json"
            production_path = root / "production.json"
            article_path.write_text(json.dumps(self.article), encoding="utf-8")
            MODULE.init_production(article_path, production_path, "en", "region", ["16:9"], 123456789)
            production = json.loads(production_path.read_text(encoding="utf-8"))
            self.assertEqual(production["speaker_schedule"], {
                "mode": "seeded_constrained_random",
                "seed": 123456789,
                "max_consecutive_segments": 4,
                "avoid_mechanical_alternation": True,
            })

    def test_request_and_validation_use_the_production_frozen_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article_path = root / "article.json"
            production_path = root / "production.json"
            article_path.write_text(json.dumps(self.article), encoding="utf-8")
            MODULE.init_production(article_path, production_path, "en", "region", ["16:9"], 2468)
            article, paragraphs = MODULE.load_article(article_path)
            schedule = MODULE.production_speaker_schedule(article, production_path)
            request = MODULE.english_request(article, paragraphs, schedule)
            self.assertEqual(request["speaker_schedule"]["seed"], 2468)
            final = MODULE.finalize_english(paragraphs, self.build_body_candidate(), 2468)
            MODULE.validate_frozen_speaker_schedule(article, paragraphs, final, production_path)
            final[0]["speaker_id"] = MODULE.partner_for_speaker(final[0]["speaker_id"])
            with self.assertRaisesRegex(ValueError, "frozen production seed"):
                MODULE.validate_frozen_speaker_schedule(article, paragraphs, final, production_path)

    def test_frozen_seed_validation_keeps_framed_wrappers_outside_body_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article_path = root / "article.json"
            production_path = root / "production.json"
            article_path.write_text(json.dumps(self.article), encoding="utf-8")
            MODULE.init_production(article_path, production_path, "en", "region", ["16:9"], 2468)
            article, paragraphs = MODULE.load_article(article_path)
            candidate = self.framed_english_candidate()
            final = MODULE.finalize_english(paragraphs, candidate, 2468)
            MODULE.validate_frozen_speaker_schedule(article, paragraphs, final, production_path)
            self.assertEqual(final[0]["speaker_id"], "primary")
            self.assertEqual(final[-1]["speaker_id"], "secondary")

    def test_finalizer_ignores_draft_speaker_ids_and_fixed_wrappers(self):
        candidate = self.framed_english_candidate(body=[
            {
                "segment_id": f"draft-{paragraph['order']}", "speaker_id": "secondary",
                "kind": "sentence_split", "spoken_text": f"Paragraph {paragraph['order']} is in the story.",
                "source_paragraph_ids": [f"p{paragraph['order']:03d}"],
            }
            for paragraph in self.paragraphs
        ])
        first = MODULE.finalize_english(self.paragraphs, candidate, 123)
        candidate["body"] = [dict(item, speaker_id="primary") for item in candidate["body"]]
        second = MODULE.finalize_english(self.paragraphs, candidate, 123)
        self.assertEqual([item["speaker_id"] for item in first], [item["speaker_id"] for item in second])
        self.assertEqual(first[0]["speaker_id"], "primary")
        self.assertEqual(first[-1]["speaker_id"], "secondary")

    def test_schedule_enforces_factual_share_and_sliding_alternation_rule(self):
        segments = [
            {
                "segment_id": f"draft-{index}", "speaker_id": "primary", "kind": "sentence_split",
                "spoken_text": "The source gives this detailed factual point.", "source_paragraph_ids": ["p001"],
            }
            for index in range(1, 7)
        ]
        scheduled = MODULE.assign_speaker_schedule(segments, 77)
        report = MODULE.english_speaker_balance(scheduled)
        self.assertGreaterEqual(report["word_shares"]["primary"], 0.4)
        self.assertLessEqual(report["word_shares"]["primary"], 0.6)
        self.assertTrue(MODULE._mechanically_alternates([
            "primary", "secondary", "primary", "secondary", "primary", "secondary", "primary",
        ]))

    def test_long_script_without_two_shared_interactions_is_blocked(self):
        paragraphs = [{"order": index, "text": f"Source fact {index}."} for index in range(1, 9)]
        candidate = [
            {
                "segment_id": f"draft-{index}", "speaker_id": "primary", "kind": "sentence_split",
                "spoken_text": f"Source fact {index}.", "source_paragraph_ids": [f"p{index:03d}"],
            }
            for index in range(1, 9)
        ]
        with self.assertRaisesRegex(ValueError, "interactions"):
            MODULE.finalize_english(paragraphs, candidate, 1)

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
                    "spoken_text": f"{label.capitalize()}.",
                    "source_paragraph_ids": [f"p{index:03d}"],
                }
                for index, label in ((3, "third fact"), (4, "fourth fact"), (5, "fifth fact"))
            ],
        ]
        result = MODULE.finalize_english(self.paragraphs, candidate)
        self.assertEqual(result[0]["segment_id"], "en-001")
        self.assertEqual(result[0]["spoken_text"], "Well, first fact, IPO, still essential.")
        MODULE.validate_coverage(self.paragraphs, result)

    def test_english_candidate_keeps_source_links_when_rewritten(self):
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
        result = MODULE.finalize_english(self.paragraphs, candidate)
        self.assertEqual(len(result), 5)

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
                self.assertEqual(production["script_generation"]["policy_version"], "5.3")
                self.assertEqual(production["script_generation"]["framing_retry_limit"], 1)
                self.assertEqual(production["script_generation"]["policy"], "source_bounded_conversational_rewrite")
                self.assertNotIn("key", json.dumps(production).lower())
            bilingual = json.loads((root / "en-zh.production.json").read_text(encoding="utf-8"))
            self.assertEqual(bilingual["captions"]["provider"], "approved-bilingual-script")
            self.assertEqual(bilingual["captions"]["target_locale"], "zh-Hans")
            chinese = json.loads((root / "zh-CN.production.json").read_text(encoding="utf-8"))
            self.assertEqual(
                chinese["speech"]["voices"]["zh-CN"],
                {
                    "primary": {
                        "id": "7ea726c9-9cde-49eb-ad47-e3ab8a49f4b6",
                        "name": "zh-CN-Xiaochen:DragonHDLatestNeural",
                        "parameters": {"temperature": 1.0},
                    },
                    "secondary": {
                        "id": "d4182cbc-7818-4a96-9a95-d5c2bdf05bae",
                        "name": "zh-CN-Yunxiao:DragonHDFlashLatestNeural",
                        "parameters": {"temperature": 1.0},
                    },
                },
            )

    def test_reviewed_subtitle_draft_preserves_complete_sentence_spans_and_source_links(self):
        script = MODULE.build_english(self.paragraphs)
        request = MODULE.subtitle_request(self.article, script)
        draft = {"units": [{"unit_id": item["unit_id"], "translation_zh": f"第{index}条字幕。"} for index, item in enumerate(request["units"], start=1)]}
        result = MODULE.validate_subtitle_draft(self.article, script, draft)
        self.assertEqual(result["translation_quality"], "reviewed")
        self.assertEqual(result["caption_unit_policy"], "captionable_clause")
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

    def test_caption_units_do_not_rejoin_audio_segments(self):
        script = [
            {"segment_id": "en-001", "speaker_id": "primary", "kind": "sentence_split", "spoken_text": "A complete caption unit ends here.", "source_paragraph_ids": ["p001"]},
            {"segment_id": "en-002", "speaker_id": "primary", "kind": "sentence_split", "spoken_text": "Another caption unit follows.", "source_paragraph_ids": ["p001"]},
        ]
        request = MODULE.subtitle_request(self.article, script)
        self.assertEqual([item["source_text"] for item in request["units"]], ["A complete caption unit ends here.", "Another caption unit follows."])
        self.assertEqual([item["segment_id"] for item in request["units"][0]["source_spans"]], ["en-001"])

    def test_caption_units_reject_a_long_or_multi_sentence_audio_segment(self):
        script = [{"segment_id": "en-001", "speaker_id": "primary", "kind": "verbatim", "spoken_text": "The U.S. market changed. It then recovered.", "source_paragraph_ids": ["p001"]}]
        with self.assertRaisesRegex(ValueError, "complete English"):
            MODULE.subtitle_request(self.article, script)
        script[0]["spoken_text"] = "This single captionable clause is deliberately made far too long to fit within the maximum display unit character budget cleanly."
        with self.assertRaisesRegex(ValueError, "subtitle budget"):
            MODULE.subtitle_request(self.article, script)

    def test_english_interaction_uses_partner_and_does_not_bypass_facts(self):
        paragraphs = [{"order": 1, "text": "The market changed. It then recovered."}]
        candidate = [
            {"segment_id": "draft-1", "speaker_id": "secondary", "kind": "prompt", "spoken_text": "What does that mean?", "source_paragraph_ids": ["p001"]},
            {"segment_id": "draft-2", "speaker_id": "primary", "kind": "sentence_split", "spoken_text": "The market changed.", "source_paragraph_ids": ["p001"]},
            {"segment_id": "draft-3", "speaker_id": "secondary", "kind": "sentence_split", "spoken_text": "It then recovered.", "source_paragraph_ids": ["p001"]},
        ]
        result = MODULE.finalize_english(paragraphs, candidate)
        self.assertEqual(result[0]["speaker_id"], "secondary")
        self.assertEqual(result[0]["kind"], "prompt")
        self.assertEqual(result[1]["speaker_id"], "primary")

    def test_english_interaction_allows_natural_response_and_rejects_same_speaker_answer(self):
        paragraphs = [{"order": 1, "text": "A source fact. Another source fact."}]
        candidate = [
            {"segment_id": "draft-1", "speaker_id": "secondary", "kind": "reaction", "spoken_text": "That is a serious concern.", "source_paragraph_ids": ["p001"]},
            {"segment_id": "draft-2", "speaker_id": "primary", "kind": "sentence_split", "spoken_text": "A source fact.", "source_paragraph_ids": ["p001"]},
            {"segment_id": "draft-3", "speaker_id": "secondary", "kind": "sentence_split", "spoken_text": "Another source fact.", "source_paragraph_ids": ["p001"]},
        ]
        result = MODULE.finalize_english(paragraphs, candidate)
        self.assertEqual(result[0]["spoken_text"], "That is a serious concern.")
        candidate[0] = {"segment_id": "draft-1", "speaker_id": "secondary", "kind": "prompt", "spoken_text": "What does that mean?", "source_paragraph_ids": ["p001"]}
        candidate[1]["speaker_id"] = "secondary"
        with self.assertRaisesRegex(ValueError, "other speaker"):
            MODULE.finalize_english(paragraphs, candidate)

    def test_english_rejects_dangling_terminal_punctuation(self):
        paragraphs = [{"order": 1, "text": "A source fact."}]
        candidate = [{
            "segment_id": "draft-1", "speaker_id": "primary", "kind": "sentence_split",
            "spoken_text": "A source fact;", "source_paragraph_ids": ["p001"],
        }]
        with self.assertRaisesRegex(ValueError, "dangling"):
            MODULE.finalize_english(paragraphs, candidate)

    def test_english_allows_two_speakers_inside_one_source_paragraph(self):
        paragraphs = [
            {"order": 1, "text": "First source fact."},
            {"order": 2, "text": "Second source fact."},
        ]
        candidate = [
            {"segment_id": "draft-1", "speaker_id": "primary", "kind": "sentence_split", "spoken_text": "First source fact.", "source_paragraph_ids": ["p001"]},
            {"segment_id": "draft-2", "speaker_id": "secondary", "kind": "sentence_split", "spoken_text": "That point matters.", "source_paragraph_ids": ["p001"]},
            {"segment_id": "draft-3", "speaker_id": "secondary", "kind": "sentence_split", "spoken_text": "Second source fact.", "source_paragraph_ids": ["p002"]},
        ]
        result = MODULE.finalize_english(paragraphs, candidate)
        self.assertEqual([item["speaker_id"] for item in result], ["primary", "secondary", "secondary"])

    def test_english_balance_reports_word_counts_and_repairable_segments(self):
        paragraphs = [{"order": 1, "text": "First source fact."}, {"order": 2, "text": "Second source fact."}]
        long_text = "The report describes a major change in the market and its effects today."
        short_text = "A brief point."
        candidate = [
            {"segment_id": "reaction-1", "speaker_id": "secondary", "kind": "reaction", "spoken_text": "That changes the picture.", "source_paragraph_ids": ["p001"]},
            {"segment_id": "reaction-2", "speaker_id": "primary", "kind": "reaction", "spoken_text": "It is an important shift.", "source_paragraph_ids": ["p001"]},
        ]
        for index in range(12):
            candidate.append({
                "segment_id": f"draft-{index}", "speaker_id": "primary" if index % 4 else "secondary",
                "kind": "sentence_split", "spoken_text": long_text if index % 4 else short_text,
                "source_paragraph_ids": ["p001"],
            })
        candidate.append({
            "segment_id": "draft-last", "speaker_id": "secondary", "kind": "sentence_split",
            "spoken_text": "Second source fact.", "source_paragraph_ids": ["p002"],
        })
        with self.assertRaisesRegex(ValueError, "speaker balance failed"):
            MODULE.finalize_english(paragraphs, candidate)

    def test_split_for_speech_refuses_to_create_a_semicolon_fragment(self):
        with self.assertRaisesRegex(ValueError, "dangling clause"):
            MODULE.split_for_speech(
                "This is a long sentence, with many words that cannot be split naturally without rewriting.",
                40,
            )

    def test_subtitle_layout_preflight_blocks_output_before_tts_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article_path = root / "article.json"
            script_path = root / "script.en.json"
            draft_path = root / "draft.json"
            output_path = root / "subtitle-script.en-zh.json"
            production_path = root / "production.json"
            article = {"review_status": "verified", "source_sha256": "source-hash", "paragraphs": [{"order": 1, "text": "A source fact."}]}
            script = [{"segment_id": "en-001", "speaker_id": "primary", "kind": "verbatim", "spoken_text": "A source fact.", "source_paragraph_ids": ["p001"]}]
            article_path.write_text(json.dumps(article), encoding="utf-8")
            script_path.write_text(json.dumps(script), encoding="utf-8")
            draft_path.write_text(json.dumps({"units": [{"unit_id": "en-zh-unit-001", "translation_zh": "一条字幕。"}]}), encoding="utf-8")
            production_path.write_text(json.dumps({"output": {"aspect_ratios": ["16:9"]}}), encoding="utf-8")
            with mock.patch.object(MODULE, "preflight_subtitle_layout", side_effect=ValueError("Caption layout preflight failed; rewrite only these caption units")):
                with self.assertRaisesRegex(ValueError, "layout preflight"):
                    MODULE.finalize_subtitles(article_path, script_path, draft_path, output_path, production_path)
            self.assertFalse(output_path.exists())
