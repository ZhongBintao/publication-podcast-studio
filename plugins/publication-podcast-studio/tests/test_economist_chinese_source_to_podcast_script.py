import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "skills" / "publication-chinese-source-to-podcast-script" / "scripts" / "chinese_source_to_podcast_script.py"
SPEC = importlib.util.spec_from_file_location("chinese_source_to_podcast_script", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ChineseSourceToPodcastScriptTests(unittest.TestCase):
    def setUp(self):
        self.article = {
            "review_status": "verified",
            "source_sha256": "chinese-source-hash",
            "article": {"headline": "A source article"},
            "paragraphs": [
                {"order": 1, "text": "OpenAI launched a model in 2025 and created 120 jobs."},
                {"order": 2, "text": "Anthropic reported a 20-50% change after a $100,000 test."},
                {"order": 3, "text": "The company said the result was uncertain."},
            ],
        }
        self.paragraphs = self.article["paragraphs"]

    def candidate(self):
        return [
            {
                "segment_id": "draft-1",
                "speaker_id": "primary",
                "kind": "prompt",
                "spoken_text": "那这件事为什么重要？",
                "source_paragraph_ids": ["p001"],
            },
            {
                "segment_id": "draft-2",
                "speaker_id": "secondary",
                "kind": "sentence_split",
                "spoken_text": "因为 OpenAI 在2025年推出了这个模型，并创造了120个岗位。",
                "source_paragraph_ids": ["p001"],
            },
            {
                "segment_id": "draft-3",
                "speaker_id": "primary",
                "kind": "sentence_split",
                "spoken_text": "Anthropic 报告说，一项测试之后，结果变化了20%到50%，而这项测试的金额是100000美元。",
                "source_paragraph_ids": ["p002"],
            },
            {
                "segment_id": "draft-4",
                "speaker_id": "secondary",
                "kind": "reaction",
                "spoken_text": "这说明变化并不稳定。",
                "source_paragraph_ids": ["p003"],
            },
            {
                "segment_id": "draft-5",
                "speaker_id": "primary",
                "kind": "sentence_split",
                "spoken_text": "公司说，结果仍然不确定。",
                "source_paragraph_ids": ["p003"],
            },
        ]

    def framed_candidate(self):
        return {
            "opening": [
                {
                    "segment_id": "opening-hook",
                    "speaker_id": "primary",
                    "kind": "opening",
                    "spoken_text": "一个新模型带来了岗位，也留下了一个更值得追问的问题。",
                    "source_paragraph_ids": ["p001"],
                },
                {
                    "segment_id": "opening-handoff",
                    "speaker_id": "primary",
                    "kind": "opening",
                    "spoken_text": "我们从这些变化背后的数字说起。",
                    "source_paragraph_ids": [],
                },
            ],
            "body": self.candidate(),
            "closing": [
                {
                    "segment_id": "closing-payoff",
                    "speaker_id": "secondary",
                    "kind": "closing",
                    "spoken_text": "回到开头，新模型带来的变化仍然值得继续观察。",
                    "source_paragraph_ids": ["p001"],
                },
                {
                    "segment_id": "closing-signoff",
                    "speaker_id": "secondary",
                    "kind": "closing",
                    "spoken_text": "我们先聊到这里，感谢你的收听。",
                    "source_paragraph_ids": [],
                },
            ],
        }

    def test_request_contains_oral_and_mixed_language_contract(self):
        payload = MODULE.request_payload(self.article, self.paragraphs)
        self.assertEqual(payload["language"], "zh-CN")
        self.assertIn("Translate and orally adapt", payload["instructions"])
        self.assertIn("OpenAI", payload["mixed_language_policy"]["preserve_examples"])
        self.assertEqual(payload["numeric_localization_policy"]["examples"][0], {"source": "200bn", "spoken_zh": "2000亿"})
        self.assertIn("Localise English quantity abbreviations", payload["instructions"])
        self.assertEqual(payload["paragraphs"][0]["max_caption_unit_chars"], 48)
        self.assertNotIn("spoken_text", payload["paragraphs"][0])
        self.assertEqual(payload["framing"]["opening"]["kind"], "opening")
        self.assertEqual(payload["framing"]["opening"]["min_segments"], 2)
        self.assertEqual(payload["framing"]["anchor_source_paragraph_id"], "p001")
        self.assertEqual(payload["framing"]["closing"]["speaker_id"], "secondary")

    def test_finalize_allows_source_linked_prompt_and_reaction(self):
        result = MODULE.finalize_chinese(self.paragraphs, self.candidate())
        self.assertEqual([item["segment_id"] for item in result], ["zh-CN-001", "zh-CN-002", "zh-CN-003", "zh-CN-004", "zh-CN-005"])
        self.assertEqual(result[0]["kind"], "prompt")
        self.assertEqual(result[1]["speaker_id"], "secondary")
        self.assertEqual(result[3]["kind"], "reaction")

    def test_finalize_rejects_prompt_without_other_host_answer(self):
        candidate = self.candidate()
        candidate[1]["speaker_id"] = "primary"
        with self.assertRaisesRegex(ValueError, "other speaker"):
            MODULE.finalize_chinese(self.paragraphs, candidate)

    def test_finalize_rejects_missing_source_number(self):
        candidate = self.candidate()
        candidate[2]["spoken_text"] = "Anthropic 报告说，测试之后发生了变化。"
        with self.assertRaisesRegex(ValueError, "missing source number"):
            MODULE.finalize_chinese(self.paragraphs, candidate)

    def test_finalize_accepts_exact_chinese_magnitude_localisation(self):
        paragraphs = [{
            "order": 1,
            "text": "Investment reached $200bn, serving 100 million people and using 1.25bn components.",
        }]
        candidate = [{
            "segment_id": "draft-1",
            "speaker_id": "primary",
            "kind": "verbatim",
            "spoken_text": "投资额达到2000亿美元，覆盖1亿人，并使用12.5亿个零部件。",
            "source_paragraph_ids": ["p001"],
        }]
        result = MODULE.finalize_chinese(paragraphs, candidate)
        self.assertEqual(result[0]["spoken_text"], candidate[0]["spoken_text"])

    def test_finalize_rejects_english_magnitude_or_changed_precision(self):
        paragraphs = [{"order": 1, "text": "Investment reached $1.25bn."}]
        copied = [{
            "segment_id": "draft-1",
            "speaker_id": "primary",
            "kind": "verbatim",
            "spoken_text": "投资额达到1.25bn美元。",
            "source_paragraph_ids": ["p001"],
        }]
        with self.assertRaisesRegex(ValueError, "English magnitude values must use Chinese units"):
            MODULE.finalize_chinese(paragraphs, copied)

        rounded = [dict(copied[0], spoken_text="投资额达到13亿美元。")]
        with self.assertRaisesRegex(ValueError, "missing source number"):
            MODULE.finalize_chinese(paragraphs, rounded)

    def test_legacy_package_remains_valid_before_numeric_localization_policy(self):
        article = {
            "review_status": "verified",
            "source_sha256": "legacy-numeric-source-hash",
            "article": {"headline": "Legacy numeric article"},
            "paragraphs": [{"order": 1, "text": "Investment reached $200bn."}],
        }
        candidate = [{
            "segment_id": "draft-1",
            "speaker_id": "primary",
            "kind": "verbatim",
            "spoken_text": "投资额达到200bn美元。",
            "source_paragraph_ids": ["p001"],
        }]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article_path = root / "article.json"
            script_path = root / "script.zh-CN.json"
            production_path = root / "production.json"
            article_path.write_text(json.dumps(article, ensure_ascii=False), encoding="utf-8")
            script_path.write_text(json.dumps(
                MODULE.finalize_chinese(article["paragraphs"], candidate, enforce_numeric_localization=False),
                ensure_ascii=False,
            ), encoding="utf-8")
            production_path.write_text(json.dumps({"script_generation": {"policy_version": "5.3"}}), encoding="utf-8")
            result = MODULE.validate_final_script(article_path, script_path, production_path)
            self.assertEqual(result["status"], "valid")

    def test_new_chinese_production_freezes_numeric_localization_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article_path = root / "article.json"
            production_path = root / "production.json"
            article_path.write_text(json.dumps(self.article, ensure_ascii=False), encoding="utf-8")
            MODULE.init_production(article_path, production_path, "region", ["9:16"])
            production = json.loads(production_path.read_text(encoding="utf-8"))
            self.assertEqual(
                production["script_generation"]["numeric_localization_policy_version"],
                MODULE.NUMERIC_LOCALIZATION_POLICY_VERSION,
            )

    def test_finalize_places_opening_and_closing_around_body(self):
        result = MODULE.finalize_chinese(self.paragraphs, self.framed_candidate())
        self.assertEqual(result[0]["kind"], "opening")
        self.assertEqual(result[-1]["kind"], "closing")
        self.assertEqual(result[0]["source_paragraph_ids"], ["p001"])
        self.assertEqual(result[-1]["source_paragraph_ids"], [])
        self.assertEqual([item["segment_id"] for item in result], [f"zh-CN-{index:03d}" for index in range(1, 10)])
        self.assertEqual([item["kind"] for item in result[2:-2]], [item["kind"] for item in self.candidate()])

    def test_unlinked_wrapper_cannot_introduce_numeric_fact(self):
        candidate = self.framed_candidate()
        candidate["opening"][0]["spoken_text"] = "欢迎收听，这是 2025 年的一场讨论。"
        candidate["opening"][0]["source_paragraph_ids"] = []
        with self.assertRaisesRegex(ValueError, "unlinked opening/closing"):
            MODULE.finalize_chinese(self.paragraphs, candidate)

    def test_unlinked_wrapper_cannot_introduce_source_specific_name(self):
        candidate = self.framed_candidate()
        candidate["opening"][0]["spoken_text"] = "今天我们来聊聊 OpenAI。"
        candidate["opening"][0]["source_paragraph_ids"] = []
        with self.assertRaisesRegex(ValueError, "source-specific names"):
            MODULE.finalize_chinese(self.paragraphs, candidate)

    def test_source_linked_wrapper_may_contain_article_number(self):
        candidate = self.framed_candidate()
        candidate["opening"][0]["spoken_text"] = "2025 年，OpenAI 推出了这个模型。"
        candidate["opening"][0]["source_paragraph_ids"] = ["p001"]
        result = MODULE.finalize_chinese(self.paragraphs, candidate)
        self.assertEqual(result[0]["source_paragraph_ids"], ["p001"])

    def test_wrapper_retry_only_replaces_failed_opening(self):
        valid = MODULE.finalize_chinese(self.paragraphs, self.framed_candidate())
        invalid = [dict(item) for item in valid]
        invalid[0]["spoken_text"] = "欢迎收听，"
        payload = MODULE.retry_payload(self.article, self.paragraphs, invalid, 1)
        self.assertEqual(payload["repair"]["opening"], True)
        self.assertEqual(payload["repair"]["body_source_paragraph_ids"], [])
        repaired = MODULE.apply_retry(
            self.paragraphs,
            invalid,
            {"opening": self.framed_candidate()["opening"]},
        )
        self.assertEqual(repaired[0]["spoken_text"], self.framed_candidate()["opening"][0]["spoken_text"])
        self.assertEqual(repaired[-1]["spoken_text"], valid[-1]["spoken_text"])

    def test_wrapper_arc_retry_repairs_only_short_closing(self):
        candidate = self.framed_candidate()
        candidate["closing"] = candidate["closing"][-1:]
        payload = MODULE.retry_payload(self.article, self.paragraphs, candidate, 1)
        self.assertEqual(payload["repair"]["opening"], False)
        self.assertEqual(payload["repair"]["closing"], True)
        repaired = MODULE.apply_retry(
            self.paragraphs,
            candidate,
            {"closing": self.framed_candidate()["closing"]},
        )
        self.assertEqual(repaired[0]["spoken_text"], candidate["opening"][0]["spoken_text"])
        self.assertEqual(repaired[-2]["source_paragraph_ids"], ["p001"])

    def test_retry_only_requests_affected_paragraph(self):
        candidate = self.candidate()
        candidate[2]["spoken_text"] = "Anthropic 报告说，测试之后发生了变化。"
        script = []
        grouped = MODULE.grouped_candidate(self.paragraphs, candidate)
        for paragraph in self.paragraphs:
            script.extend(grouped[MODULE.paragraph_id(paragraph)])
        payload = MODULE.retry_payload(self.article, self.paragraphs, script, 1)
        self.assertEqual([item["source_paragraph_id"] for item in payload["paragraphs"]], ["p002"])

    def test_final_script_cli_validation_is_canonical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article_path = root / "article.json"
            script_path = root / "script.zh-CN.json"
            article_path.write_text(json.dumps(self.article, ensure_ascii=False), encoding="utf-8")
            script_path.write_text(json.dumps(MODULE.finalize_chinese(self.paragraphs, self.candidate()), ensure_ascii=False), encoding="utf-8")
            result = MODULE.validate_final_script(article_path, script_path)
            self.assertEqual(result["status"], "valid")
            self.assertEqual(result["language"], "zh-CN")

    def test_policy_52_single_segment_wrappers_remain_valid(self):
        legacy = self.framed_candidate()
        legacy["opening"] = [{
            "segment_id": "opening-legacy", "speaker_id": "primary", "kind": "opening",
            "spoken_text": "先从这项变化说起。", "source_paragraph_ids": ["p001"],
        }]
        legacy["closing"] = [{
            "segment_id": "closing-legacy", "speaker_id": "secondary", "kind": "closing",
            "spoken_text": "感谢收听。", "source_paragraph_ids": [],
        }]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            article_path = root / "article.json"
            script_path = root / "script.zh-CN.json"
            production_path = root / "production.json"
            article_path.write_text(json.dumps(self.article, ensure_ascii=False), encoding="utf-8")
            script_path.write_text(json.dumps(
                MODULE.finalize_chinese(self.paragraphs, legacy, enforce_wrapper_arc=False),
                ensure_ascii=False,
            ), encoding="utf-8")
            production_path.write_text(json.dumps({
                "duration": {"mode": "coverage_unbounded", "target_minutes": 10, "max_minutes": None},
                "script_generation": {"policy_version": "5.2"},
            }), encoding="utf-8")
            result = MODULE.validate_final_script(article_path, script_path, production_path)
            self.assertEqual(result["status"], "valid")


if __name__ == "__main__":
    unittest.main()
