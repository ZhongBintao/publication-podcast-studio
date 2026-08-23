import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "skills" / "economist-chinese-source-to-podcast-script" / "scripts" / "chinese_source_to_podcast_script.py"
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
                    "spoken_text": "一个模型创造了岗位，却也留下了难以判断的变化。",
                    "source_paragraph_ids": ["p001"],
                },
                {
                    "segment_id": "opening-question",
                    "speaker_id": "secondary",
                    "kind": "opening",
                    "spoken_text": "这些变化究竟说明了什么？",
                    "source_paragraph_ids": ["p001", "p002"],
                },
                {
                    "segment_id": "opening-bridge",
                    "speaker_id": "primary",
                    "kind": "opening",
                    "spoken_text": "我们沿着报道给出的线索往下看。",
                    "source_paragraph_ids": [],
                },
            ],
            "body": self.candidate(),
            "closing": [
                {
                    "segment_id": "closing-summary",
                    "speaker_id": "primary",
                    "kind": "closing",
                    "spoken_text": "变化已经出现，但公司也承认，结果仍不确定。",
                    "source_paragraph_ids": ["p003"],
                },
                {
                    "segment_id": "closing-signoff",
                    "speaker_id": "secondary",
                    "kind": "closing",
                    "spoken_text": "这次就聊到这里，我们下期再见。",
                    "source_paragraph_ids": [],
                },
            ],
        }

    def test_request_contains_oral_and_mixed_language_contract(self):
        payload = MODULE.request_payload(self.article, self.paragraphs)
        self.assertEqual(payload["language"], "zh-CN")
        self.assertIn("Translate and orally adapt", payload["instructions"])
        self.assertIn("OpenAI", payload["mixed_language_policy"]["preserve_examples"])
        self.assertEqual(payload["paragraphs"][0]["max_caption_unit_chars"], 48)
        self.assertNotIn("spoken_text", payload["paragraphs"][0])
        self.assertEqual(payload["framing"]["opening"]["kind"], "opening")
        self.assertEqual(payload["framing"]["opening"]["speaker_order"], ["primary", "secondary", "primary"])
        self.assertEqual(payload["framing"]["closing"]["speaker_order"], ["primary", "secondary"])
        self.assertEqual(payload["script_policy_version"], "5.3")

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

    def test_finalize_places_opening_and_closing_around_body(self):
        result = MODULE.finalize_chinese(self.paragraphs, self.framed_candidate())
        self.assertEqual(result[0]["kind"], "opening")
        self.assertEqual(result[-1]["kind"], "closing")
        self.assertEqual(result[0]["source_paragraph_ids"], ["p001"])
        self.assertEqual(result[-1]["source_paragraph_ids"], [])
        self.assertEqual([item["segment_id"] for item in result], [f"zh-CN-{index:03d}" for index in range(1, 11)])
        self.assertEqual([item["kind"] for item in result[3:-2]], [item["kind"] for item in self.candidate()])

    def test_unlinked_wrapper_cannot_introduce_numeric_fact(self):
        candidate = self.framed_candidate()
        candidate["opening"][0]["spoken_text"] = "欢迎收听，这是 2025 年的一场讨论。"
        candidate["opening"][0]["source_paragraph_ids"] = []
        with self.assertRaisesRegex(ValueError, "unlinked opening/closing"):
            MODULE.finalize_chinese(self.paragraphs, candidate)

    def test_unlinked_wrapper_cannot_introduce_source_specific_name(self):
        candidate = self.framed_candidate()
        candidate["opening"][2]["spoken_text"] = "接下来我们看看 OpenAI。"
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

    def test_template_opening_and_fact_plus_signoff_single_turn_are_rejected(self):
        candidate = self.framed_candidate()
        candidate["opening"][0]["spoken_text"] = "欢迎收听，我们从报道里的模型说起。"
        with self.assertRaisesRegex(ValueError, "prohibited programme boilerplate"):
            MODULE.finalize_chinese(self.paragraphs, candidate)
        candidate = self.framed_candidate()
        candidate["closing"] = [candidate["closing"][0]]
        with self.assertRaisesRegex(ValueError, "exactly 2"):
            MODULE.finalize_chinese(self.paragraphs, candidate)

    def test_long_article_requires_prompt_answer_pair_in_each_quarter(self):
        paragraphs = [
            {"order": index, "text": f"Source paragraph {index} reports one result."}
            for index in range(1, 21)
        ]
        body = []
        anchors = {1, 6, 11, 16}
        for index in range(1, 21):
            speaker = "primary" if index % 2 else "secondary"
            source_id = f"p{index:03d}"
            if index in anchors:
                body.append({
                    "segment_id": f"prompt-{index}",
                    "speaker_id": "secondary" if speaker == "primary" else "primary",
                    "kind": "prompt",
                    "spoken_text": "这一段的关键是什么？",
                    "source_paragraph_ids": [source_id],
                })
            body.append({
                "segment_id": f"fact-{index}",
                "speaker_id": speaker,
                "kind": "sentence_split",
                "spoken_text": f"来源第{index}段报告了一项结果。",
                "source_paragraph_ids": [source_id],
            })
        result = MODULE.finalize_chinese(paragraphs, body)
        self.assertEqual(sum(item["kind"] == "prompt" for item in result), 4)
        body = [item for item in body if item["segment_id"] != "prompt-16"]
        with self.assertRaisesRegex(ValueError, "one in each source-paragraph quarter"):
            MODULE.finalize_chinese(paragraphs, body)

    def test_framing_polish_payload_is_compact_and_preserves_body(self):
        payload = MODULE.framing_polish_payload(self.article, self.paragraphs, self.framed_candidate())
        self.assertEqual(set(payload["current"]), {"opening", "closing"})
        self.assertEqual(payload["body_context"]["first_segment"], self.candidate()[0])
        self.assertNotIn("paragraphs", payload)
        polished = MODULE.apply_framing_polish(
            self.paragraphs,
            self.framed_candidate(),
            {"opening": self.framed_candidate()["opening"], "closing": self.framed_candidate()["closing"]},
        )
        self.assertEqual([item["kind"] for item in polished[3:-2]], [item["kind"] for item in self.candidate()])

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


if __name__ == "__main__":
    unittest.main()
