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
            "opening": [{
                "segment_id": "opening-draft",
                "speaker_id": "primary",
                "kind": "opening",
                "spoken_text": "欢迎收听今天的外刊播客。我们先从一个看似简单的问题聊起。",
                "source_paragraph_ids": [],
            }],
            "body": self.candidate(),
            "closing": [{
                "segment_id": "closing-draft",
                "speaker_id": "secondary",
                "kind": "closing",
                "spoken_text": "今天的内容就聊到这里，感谢你的收听。",
                "source_paragraph_ids": [],
            }],
        }

    def test_request_contains_oral_and_mixed_language_contract(self):
        payload = MODULE.request_payload(self.article, self.paragraphs)
        self.assertEqual(payload["language"], "zh-CN")
        self.assertIn("Translate and orally adapt", payload["instructions"])
        self.assertIn("OpenAI", payload["mixed_language_policy"]["preserve_examples"])
        self.assertEqual(payload["paragraphs"][0]["max_caption_unit_chars"], 48)
        self.assertNotIn("spoken_text", payload["paragraphs"][0])
        self.assertEqual(payload["framing"]["opening"]["kind"], "opening")
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

    def test_finalize_places_opening_and_closing_around_body(self):
        result = MODULE.finalize_chinese(self.paragraphs, self.framed_candidate())
        self.assertEqual(result[0]["kind"], "opening")
        self.assertEqual(result[-1]["kind"], "closing")
        self.assertEqual(result[0]["source_paragraph_ids"], [])
        self.assertEqual(result[-1]["source_paragraph_ids"], [])
        self.assertEqual([item["segment_id"] for item in result], [f"zh-CN-{index:03d}" for index in range(1, 8)])
        self.assertEqual([item["kind"] for item in result[1:-1]], [item["kind"] for item in self.candidate()])

    def test_unlinked_wrapper_cannot_introduce_numeric_fact(self):
        candidate = self.framed_candidate()
        candidate["opening"][0]["spoken_text"] = "欢迎收听，这是 2025 年的一场讨论。"
        with self.assertRaisesRegex(ValueError, "unlinked opening/closing"):
            MODULE.finalize_chinese(self.paragraphs, candidate)

    def test_unlinked_wrapper_cannot_introduce_source_specific_name(self):
        candidate = self.framed_candidate()
        candidate["opening"][0]["spoken_text"] = "今天我们来聊聊 OpenAI。"
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
            {"opening": [{
                "segment_id": "opening-retry",
                "speaker_id": "primary",
                "kind": "opening",
                "spoken_text": "欢迎收听今天的外刊播客。",
                "source_paragraph_ids": [],
            }]},
        )
        self.assertEqual(repaired[0]["spoken_text"], "欢迎收听今天的外刊播客。")
        self.assertEqual(repaired[-1]["spoken_text"], valid[-1]["spoken_text"])

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
