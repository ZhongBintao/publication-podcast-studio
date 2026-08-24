import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
import wave
from unittest import mock

from PIL import Image


ROOT = Path(__file__).parents[1]
MEDIA_PATH = ROOT / "skills" / "publication-azure-speech-media" / "scripts" / "azure_speech_media.py"
SOURCE_PATH = ROOT / "skills" / "publication-source-to-podcast-script" / "scripts" / "source_to_podcast_script.py"
CHINESE_PATH = ROOT / "skills" / "publication-chinese-source-to-podcast-script" / "scripts" / "chinese_source_to_podcast_script.py"

MEDIA_SPEC = importlib.util.spec_from_file_location("azure_speech_media", MEDIA_PATH)
MEDIA = importlib.util.module_from_spec(MEDIA_SPEC)
MEDIA_SPEC.loader.exec_module(MEDIA)
SOURCE_SPEC = importlib.util.spec_from_file_location("source_to_podcast_script_for_media", SOURCE_PATH)
SOURCE = importlib.util.module_from_spec(SOURCE_SPEC)
SOURCE_SPEC.loader.exec_module(SOURCE)
CHINESE_SPEC = importlib.util.spec_from_file_location("chinese_source_to_podcast_script_for_media", CHINESE_PATH)
CHINESE = importlib.util.module_from_spec(CHINESE_SPEC)
CHINESE_SPEC.loader.exec_module(CHINESE)


def wav_bytes(duration_seconds):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\0\0" * round(24000 * duration_seconds))
    return output.getvalue()


class FakeAzureProvider:
    def __init__(self, missing_boundaries=False, non_monotonic_translation=False):
        self.synthesis_calls = []
        self.translation_calls = []
        self.missing_boundaries = missing_boundaries
        self.non_monotonic_translation = non_monotonic_translation

    def synthesize(self, language, voice, text, delivery=None, voice_parameters=None):
        self.synthesis_calls.append((language, voice, text, delivery, voice_parameters))
        boundaries = []
        for index, match in enumerate(re.finditer(r"\S+", text)):
            boundaries.append({
                "boundary_type": "word",
                "audio_offset_ticks": index * 20_000_000,
                "duration_ticks": 15_000_000,
                "text_offset": match.start(),
                "word_length": len(match.group()),
            })
        return {"audio": wav_bytes(max(1.0, len(boundaries) * 2.0 + 0.5)), "word_boundaries": [] if self.missing_boundaries else boundaries}

    def translate(self, audio_path, source_locale, target_locale):
        self.translation_calls.append((audio_path, source_locale, target_locale))
        phrases = [
            {"offset_ticks": 0, "duration_ticks": 10_000_000, "source_text": "English first line.", "translated_text": "中文第一行。"},
            {"offset_ticks": 11_000_000, "duration_ticks": 8_000_000, "source_text": "English second line.", "translated_text": "中文第二行。"},
        ]
        if self.non_monotonic_translation:
            phrases[1]["offset_ticks"] = -1
        return phrases


class AzureSpeechMediaTests(unittest.TestCase):
    def test_workspace_dotenv_path_is_the_project_root(self):
        self.assertEqual(MEDIA.WORKSPACE_ROOT, ROOT)
        self.assertEqual(MEDIA.WORKSPACE_ENV_FILE, ROOT / ".env")

    def test_credentials_prefer_process_environment_over_workspace_dotenv(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_text("AZURE_SPEECH_KEY=file-key\n", encoding="utf-8")
            with mock.patch.dict(MEDIA.os.environ, {"AZURE_SPEECH_KEY": "process-key"}, clear=True):
                self.assertEqual(MEDIA.load_credentials(env_file), "process-key")

    def test_credentials_fall_back_to_workspace_dotenv_without_exposing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            env_file = Path(temporary) / ".env"
            env_file.write_text("# local runtime secret\nexport AZURE_SPEECH_KEY='file-key'\n", encoding="utf-8")
            with mock.patch.dict(MEDIA.os.environ, {}, clear=True):
                self.assertEqual(MEDIA.load_credentials(env_file), "file-key")

    def test_missing_credentials_remain_a_non_secret_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(MEDIA.os.environ, {}, clear=True):
                with self.assertRaisesRegex(MEDIA.MediaError, "credentials are unavailable"):
                    MEDIA.load_credentials(Path(temporary) / ".env")

    def test_zero_duration_punctuation_is_excluded_from_dragonhd_word_alignment(self):
        boundaries = [
            {"boundary_type": "word", "audio_offset_ticks": 100, "duration_ticks": 20, "text_offset": 0, "word_length": 5},
            {"boundary_type": "punctuation", "audio_offset_ticks": 120, "duration_ticks": 0, "text_offset": 5, "word_length": 1},
            {"boundary_type": "punctuation", "audio_offset_ticks": 110, "duration_ticks": 0, "text_offset": 6, "word_length": 1},
            {"boundary_type": "word", "audio_offset_ticks": 130, "duration_ticks": 20, "text_offset": 8, "word_length": 4},
        ]
        words = MEDIA.validate_boundaries("Hello., next", boundaries)
        self.assertEqual([item["text"] for item in words], ["Hello", "next"])

    def make_package(self, variant):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        cover_path = root / "cover.png"
        Image.new("RGB", (1920, 1080), "#202020").save(cover_path)
        article = {"review_status": "verified", "source_sha256": "source-hash", "issue_cover": {"file": "cover.png"}, "paragraphs": [{"order": 1, "text": "First source paragraph."}, {"order": 2, "text": "Second source paragraph."}]}
        article_path = root / "article.json"
        article_path.write_text(json.dumps(article), encoding="utf-8")
        production_path = root / "production.json"
        SOURCE.init_production(article_path, production_path, variant, "southeastasia", ["16:9"])
        if variant in {"en", "en-zh"}:
            (root / "script.en.json").write_text(json.dumps(SOURCE.build_english(article["paragraphs"])), encoding="utf-8")
        else:
            candidate = [
                {"segment_id": "draft-1", "speaker_id": "primary", "kind": "sentence_split", "spoken_text": "第一段。", "source_paragraph_ids": ["p001"]},
                {"segment_id": "draft-2", "speaker_id": "secondary", "kind": "sentence_split", "spoken_text": "第二段。", "source_paragraph_ids": ["p002"]},
            ]
            (root / "script.zh-CN.json").write_text(json.dumps(SOURCE.finalize_zh(article["paragraphs"], candidate)), encoding="utf-8")
        return temp, root, production_path

    def test_english_variant_writes_only_english_artifacts_and_skips_translation(self):
        temp, root, production_path = self.make_package("en")
        with temp:
            provider = FakeAzureProvider()
            result = MEDIA.run_media(production_path, provider)
            self.assertEqual(result["variant"], "en")
            self.assertEqual(len(provider.translation_calls), 0)
            self.assertTrue((root / "audio/en/final.wav").exists())
            self.assertTrue((root / "audio/en/voice-only.wav").exists())
            self.assertTrue((root / "audio/en/voice-track.wav").exists())
            self.assertTrue((root / "audio/en/background-music.wav").exists())
            self.assertTrue((root / "alignment.en.json").exists())
            self.assertTrue((root / "captions.en.srt").exists())
            self.assertFalse((root / "captions.en-zh.srt").exists())
            self.assertFalse((root / "audio/zh-CN/final.wav").exists())
            persisted = json.loads(production_path.read_text())
            self.assertEqual(persisted["state"], "complete")
            self.assertEqual(persisted["background_music"]["en"]["state"], "complete")
            alignment = json.loads((root / "alignment.en.json").read_text())
            self.assertEqual(alignment["segments"][0]["start_seconds"], 6.0)

    def test_default_english_hosts_use_selected_dragonhd_voices_and_parameters(self):
        temp, root, production_path = self.make_package("en")
        with temp:
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            self.assertEqual(provider.synthesis_calls[0][1], "en-US-Ava:DragonHDLatestNeural")
            self.assertEqual(provider.synthesis_calls[0][4], {})
            self.assertEqual(provider.synthesis_calls[1][1], "en-US-Andrew:DragonHDLatestNeural")
            self.assertEqual(provider.synthesis_calls[1][4], {"temperature": 1.0})

    def test_default_chinese_hosts_use_selected_dragonhd_voices_and_parameters(self):
        temp, root, production_path = self.make_package("zh-CN")
        with temp:
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            self.assertEqual(
                [(call[1], call[4]) for call in provider.synthesis_calls],
                [
                    ("zh-CN-Xiaochen:DragonHDLatestNeural", {"temperature": 1.0}),
                    ("zh-CN-Yunxiao:DragonHDFlashLatestNeural", {"temperature": 1.0}),
                ],
            )
            self.assertTrue((root / "alignment.zh-CN.json").exists())
            self.assertTrue((root / "captions.zh-CN.srt").exists())

    def test_chinese_temperature_change_invalidates_only_the_affected_host_segment(self):
        temp, root, production_path = self.make_package("zh-CN")
        with temp:
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            initial_calls = len(provider.synthesis_calls)
            production = json.loads(production_path.read_text(encoding="utf-8"))
            production["speech"]["voices"]["zh-CN"]["secondary"]["parameters"]["temperature"] = 0.8
            production_path.write_text(json.dumps(production), encoding="utf-8")
            MEDIA.run_media(production_path, provider)
            self.assertEqual(len(provider.synthesis_calls), initial_calls + 1)
            self.assertEqual(provider.synthesis_calls[-1][1], "zh-CN-Yunxiao:DragonHDFlashLatestNeural")
            self.assertEqual(provider.synthesis_calls[-1][4], {"temperature": 0.8})

    def test_english_opening_and_closing_share_tts_alignment_and_captions(self):
        temp, root, production_path = self.make_package("en")
        with temp:
            article = json.loads((root / "article.json").read_text(encoding="utf-8"))
            candidate = {
                "opening": [
                    {"segment_id": "opening-hook", "speaker_id": "primary", "kind": "opening", "spoken_text": "The first point sets up this story.", "source_paragraph_ids": ["p001"]},
                    {"segment_id": "opening-handoff", "speaker_id": "primary", "kind": "opening", "spoken_text": "Here is why it matters.", "source_paragraph_ids": []},
                ],
                "body": SOURCE.build_english(article["paragraphs"]),
                "closing": [
                    {"segment_id": "closing-payoff", "speaker_id": "secondary", "kind": "closing", "spoken_text": "That first point still frames the result.", "source_paragraph_ids": ["p001"]},
                    {"segment_id": "closing-signoff", "speaker_id": "secondary", "kind": "closing", "spoken_text": "For now, thanks for listening.", "source_paragraph_ids": []},
                ],
            }
            script = SOURCE.finalize_english(article["paragraphs"], candidate)
            (root / "script.en.json").write_text(json.dumps(script), encoding="utf-8")
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            self.assertEqual([call[2] for call in provider.synthesis_calls], [
                "The first point sets up this story.", "Here is why it matters.", "First source paragraph.", "Second source paragraph.",
                "That first point still frames the result.", "For now, thanks for listening.",
            ])
            alignment = json.loads((root / "alignment.en.json").read_text(encoding="utf-8"))
            self.assertEqual(alignment["segments"][0]["kind"], "opening")
            self.assertEqual(alignment["segments"][-1]["kind"], "closing")
            captions = (root / "captions.en.srt").read_text(encoding="utf-8")
            self.assertIn("The first point sets up this story.", captions)
            self.assertIn("For now, thanks for listening.", captions)

    def test_bilingual_variant_uses_one_translation_session_and_two_line_cues(self):
        temp, root, production_path = self.make_package("en-zh")
        with temp:
            production = json.loads(production_path.read_text(encoding="utf-8"))
            production["script_generation"]["policy_version"] = "4.0"
            production_path.write_text(json.dumps(production), encoding="utf-8")
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            self.assertEqual(len(provider.translation_calls), 1)
            self.assertEqual(provider.translation_calls[0][1:], ("en-US", "zh-Hans"))
            srt = (root / "captions.en-zh.srt").read_text(encoding="utf-8")
            self.assertIn("English first line.\n中文第一行。", srt)
            translation = json.loads((root / "translation.en-zh.json").read_text(encoding="utf-8"))
            self.assertEqual(translation["translation_mode"], "azure_speech_translation")
            self.assertEqual(translation["translation_quality"], "machine_unreviewed")
            self.assertEqual(json.loads(production_path.read_text())["captions"]["publication_status"], "review_required")
            self.assertFalse((root / "script.zh-CN.json").exists())

    def test_reviewed_bilingual_subtitles_use_wordboundaries_without_translation(self):
        temp, root, production_path = self.make_package("en-zh")
        with temp:
            article = json.loads((root / "article.json").read_text(encoding="utf-8"))
            script = json.loads((root / "script.en.json").read_text(encoding="utf-8"))
            request = SOURCE.subtitle_request(article, script)
            draft = {"units": [{"unit_id": item["unit_id"], "translation_zh": f"第{index}条中文字幕。"} for index, item in enumerate(request["units"], start=1)]}
            (root / "draft.json").write_text(json.dumps(draft), encoding="utf-8")
            SOURCE.finalize_subtitles(root / "article.json", root / "script.en.json", root / "draft.json", root / "subtitle-script.en-zh.json", production_path)
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            self.assertEqual(provider.translation_calls, [])
            cues = json.loads((root / "caption-cues.en-zh.json").read_text(encoding="utf-8"))["cues"]
            self.assertTrue(cues)
            self.assertEqual(set(cues[0]), {"cue_id", "start_seconds", "end_seconds", "en_text", "zh_text", "segment_id", "segment_ids", "source_paragraph_ids"})
            production = json.loads(production_path.read_text(encoding="utf-8"))
            self.assertEqual(production["captions"]["translation_quality"], "reviewed")
            self.assertIn("caption_cues_en_zh", production["artifacts"])

    def test_legacy_bilingual_phrase_is_not_split_or_retimed(self):
        phrases = [{
            "start_seconds": 0.0,
            "end_seconds": 8.0,
            "source_text": "This deliberately long English phrase contains enough words that it must be divided safely for a narrow portrait subtitle rail.",
            "translated_text": "这是一条刻意加长的中文字幕，用于验证在狭窄的竖屏字幕区域内可以安全拆分，同时不丢失任何内容。",
        }]
        cues = MEDIA.bilingual_display_cues(phrases)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["text"], f"{phrases[0]['source_text']}\n{phrases[0]['translated_text']}")
        self.assertAlmostEqual(cues[0]["start_seconds"], 0.0)
        self.assertAlmostEqual(cues[-1]["end_seconds"], 8.0)

    def test_caption_export_preserves_terminal_punctuation_without_adding_a_period(self):
        cues = [
            {"start_seconds": 0.0, "end_seconds": 1.0, "text": "A cue without terminal punctuation"},
            {"start_seconds": 1.0, "end_seconds": 2.0, "text": "A cue that already ends."},
        ]
        rendered = MEDIA.render_srt(cues)
        self.assertIn("A cue without terminal punctuation\n", rendered)
        self.assertNotIn("punctuation.\n", rendered)
        self.assertIn("A cue that already ends.\n", rendered)

    def test_script_cues_use_approved_chinese_punctuation_when_word_events_omit_it(self):
        text = "第一句。第二句；第三句。"
        alignment = {"segments": [{
            "spoken_text": text,
            "words": [
                {"text": "第一句", "text_offset": 0, "word_length": 3, "start_seconds": 0.0, "end_seconds": 1.0},
                {"text": "第二句", "text_offset": 4, "word_length": 3, "start_seconds": 1.1, "end_seconds": 2.0},
                {"text": "第三句", "text_offset": 8, "word_length": 3, "start_seconds": 2.1, "end_seconds": 3.0},
            ],
        }]}
        cues = MEDIA.script_cues(alignment, "zh-CN")
        self.assertEqual([cue["text"] for cue in cues], ["第一句。", "第二句；", "第三句。"])

    def test_script_cues_split_a_long_approved_chinese_sentence_without_adding_punctuation(self):
        text = "这是第一段完整字幕文本，用于测试长句如何在不添加标点的情况下安全拆分。第二段完整字幕文本也必须保持原样。"
        alignment = {"segments": [{
            "spoken_text": text,
            "words": [
                {"text": "这是第一段完整字幕文本", "text_offset": 0, "word_length": 11, "start_seconds": 0.0, "end_seconds": 1.0},
                {"text": "用于测试长句如何在不添加标点的情况下安全拆分", "text_offset": 12, "word_length": 22, "start_seconds": 1.1, "end_seconds": 2.0},
                {"text": "第二段完整字幕文本也必须保持原样", "text_offset": 35, "word_length": 16, "start_seconds": 2.1, "end_seconds": 3.0},
            ],
        }]}

        cues = MEDIA.script_cues(alignment, "zh-CN")

        self.assertTrue(all(len(cue["text"]) <= MEDIA.MAX_CHINESE_CHARS for cue in cues))
        self.assertEqual("".join(cue["text"] for cue in cues), text)

    def test_local_caption_rebuild_supports_chinese_without_synthesis(self):
        temp, root, production_path = self.make_package("zh-CN")
        with temp:
            MEDIA.run_media(production_path, FakeAzureProvider())
            (root / "captions.zh-CN.srt").unlink()
            result = MEDIA.rebuild_captions(production_path)
            self.assertEqual(result["variant"], "zh-CN")
            self.assertTrue((root / "captions.zh-CN.srt").is_file())

    def test_current_bilingual_policy_refuses_machine_phrase_captions_before_provider_use(self):
        temp, _, production_path = self.make_package("en-zh")
        with temp:
            provider = FakeAzureProvider()
            with self.assertRaisesRegex(MEDIA.MediaError, "full-sentence subtitle script"):
                MEDIA.run_media(production_path, provider)
            self.assertEqual(provider.synthesis_calls, [])
            self.assertEqual(provider.translation_calls, [])

    def test_complete_sentence_cue_is_not_limited_by_old_character_or_duration_caps(self):
        source = "This intentionally long complete English sentence remains one timed cue even though its visual layout will require several lines in a narrow portrait video frame."
        alignment = {"segments": [{
            "segment_id": "en-001", "spoken_text": source, "source_paragraph_ids": ["p001"],
            "words": [{"text_offset": 0, "word_length": len(source), "start_seconds": 0.0, "end_seconds": 12.0}],
        }]}
        subtitle = {"schema_version": "2.0", "translation_quality": "reviewed", "caption_unit_policy": "full_sentence", "units": [{
            "unit_id": "en-zh-sentence-001", "source_text": source,
            "source_spans": [{"segment_id": "en-001", "source_start": 0, "source_end": len(source)}],
            "source_paragraph_ids": ["p001"],
            "translation_zh": "这是一条刻意加长的完整中文字幕，它仍然必须作为一个时间单元显示，并由视频画面自行决定自然换成多少行。",
        }]}
        cues = MEDIA.reviewed_bilingual_cues(alignment, subtitle)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["en_text"], source)
        self.assertEqual(cues[0]["end_seconds"], 12.0)

    def test_chinese_variant_never_synthesizes_english_or_translates(self):
        temp, root, production_path = self.make_package("zh-CN")
        with temp:
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            self.assertTrue(all(call[0] == "zh-CN" for call in provider.synthesis_calls))
            self.assertEqual(provider.translation_calls, [])
            self.assertTrue((root / "captions.zh-CN.vtt").exists())
            self.assertFalse((root / "audio/en/final.wav").exists())

    def test_chinese_opening_and_closing_share_tts_alignment_and_captions(self):
        temp, root, production_path = self.make_package("zh-CN")
        with temp:
            article = json.loads((root / "article.json").read_text(encoding="utf-8"))
            candidate = {
                "opening": [
                    {"segment_id": "opening-hook", "speaker_id": "primary", "kind": "opening", "spoken_text": "第一段信息提出了今天的核心问题。", "source_paragraph_ids": ["p001"]},
                    {"segment_id": "opening-handoff", "speaker_id": "primary", "kind": "opening", "spoken_text": "我们从这里说起。", "source_paragraph_ids": []},
                ],
                "body": [
                    {"segment_id": "body-1", "speaker_id": "primary", "kind": "sentence_split", "spoken_text": "第一段。", "source_paragraph_ids": ["p001"]},
                    {"segment_id": "body-2", "speaker_id": "secondary", "kind": "sentence_split", "spoken_text": "第二段。", "source_paragraph_ids": ["p002"]},
                ],
                "closing": [
                    {"segment_id": "closing-payoff", "speaker_id": "secondary", "kind": "closing", "spoken_text": "回到开头，第一段信息仍是理解结果的关键。", "source_paragraph_ids": ["p001"]},
                    {"segment_id": "closing-signoff", "speaker_id": "secondary", "kind": "closing", "spoken_text": "我们先停在这里，感谢收听。", "source_paragraph_ids": []},
                ],
            }
            (root / "script.zh-CN.json").write_text(json.dumps(CHINESE.finalize_chinese(article["paragraphs"], candidate), ensure_ascii=False), encoding="utf-8")
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            self.assertEqual([call[2] for call in provider.synthesis_calls], [
                "第一段信息提出了今天的核心问题。", "我们从这里说起。", "第一段。", "第二段。",
                "回到开头，第一段信息仍是理解结果的关键。", "我们先停在这里，感谢收听。",
            ])
            alignment = json.loads((root / "alignment.zh-CN.json").read_text(encoding="utf-8"))
            self.assertEqual(alignment["segments"][0]["kind"], "opening")
            self.assertEqual(alignment["segments"][-1]["kind"], "closing")
            self.assertLess(alignment["segments"][0]["end_seconds"], alignment["segments"][-1]["start_seconds"])
            self.assertIn("第一段信息提出了今天的核心问题。", (root / "captions.zh-CN.srt").read_text(encoding="utf-8"))
            self.assertIn("我们先停在这里，感谢收听。", (root / "captions.zh-CN.srt").read_text(encoding="utf-8"))

    def test_missing_word_boundaries_fails_without_translation(self):
        temp, root, production_path = self.make_package("en")
        with temp:
            provider = FakeAzureProvider(missing_boundaries=True)
            with self.assertRaisesRegex(MEDIA.MediaError, "WordBoundary"):
                MEDIA.run_media(production_path, provider)
            production = json.loads(production_path.read_text(encoding="utf-8"))
            self.assertEqual(production["state"], "failed")
            self.assertEqual(provider.translation_calls, [])

    def test_rerun_reuses_verified_segment_cache_without_new_tts_requests(self):
        temp, root, production_path = self.make_package("en")
        with temp:
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            initial_calls = len(provider.synthesis_calls)
            MEDIA.run_media(production_path, provider)
            self.assertEqual(len(provider.synthesis_calls), initial_calls)
            production = json.loads(production_path.read_text(encoding="utf-8"))
            self.assertEqual(production["state"], "complete")
            self.assertEqual(len(production["progress"]["segments"]["en"]), initial_calls)

    def test_voice_change_invalidates_cached_audio_segments(self):
        temp, root, production_path = self.make_package("en")
        with temp:
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            initial_calls = len(provider.synthesis_calls)
            production = json.loads(production_path.read_text(encoding="utf-8"))
            production["speech"]["voices"]["en"]["primary"] = "en-US-GuyNeural"
            production_path.write_text(json.dumps(production), encoding="utf-8")
            MEDIA.run_media(production_path, provider)
            self.assertGreater(len(provider.synthesis_calls), initial_calls)
            self.assertEqual(provider.translation_calls, [])

    def test_temperature_change_invalidates_only_the_affected_host_segment(self):
        temp, root, production_path = self.make_package("en")
        with temp:
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            initial_calls = len(provider.synthesis_calls)
            production = json.loads(production_path.read_text(encoding="utf-8"))
            production["speech"]["voices"]["en"]["secondary"]["parameters"]["temperature"] = 0.8
            production_path.write_text(json.dumps(production), encoding="utf-8")
            MEDIA.run_media(production_path, provider)
            self.assertEqual(len(provider.synthesis_calls), initial_calls + 1)
            self.assertEqual(provider.synthesis_calls[-1][4], {"temperature": 0.8})

    def test_legacy_string_voice_configuration_remains_supported(self):
        temp, root, production_path = self.make_package("en")
        with temp:
            production = json.loads(production_path.read_text(encoding="utf-8"))
            production["speech"]["voices"]["en"] = {
                "primary": "en-US-AriaNeural",
                "secondary": "en-US-GuyNeural",
            }
            production_path.write_text(json.dumps(production), encoding="utf-8")
            provider = FakeAzureProvider()
            MEDIA.run_media(production_path, provider)
            self.assertEqual([call[1] for call in provider.synthesis_calls], ["en-US-AriaNeural", "en-US-GuyNeural"])

    def test_delivery_controls_are_validated_against_supported_ssml_shapes(self):
        self.assertEqual(MEDIA.validate_delivery({"style": "narration-professional", "style_degree": 1.1, "rate": "-3%", "pitch": "-1st", "volume": "medium", "structure": "paragraph", "pre_break_ms": 80, "post_break_ms": 140})["style"], "narration-professional")
        with self.assertRaisesRegex(MEDIA.MediaError, "style_degree"):
            MEDIA.validate_delivery({"style": "narration-professional", "style_degree": 2.1})
        with self.assertRaisesRegex(MEDIA.MediaError, "rate"):
            MEDIA.validate_delivery({"rate": "-70%"})
        with self.assertRaisesRegex(MEDIA.MediaError, "DragonHD"):
            MEDIA.validate_delivery({"style": "friendly", "pre_break_ms": 100}, "en-US-Andrew:DragonHDLatestNeural")

    def test_dragonhd_ssml_uses_only_the_selected_voice_parameters(self):
        ava_ssml, _, _ = MEDIA.build_ssml(
            "en", "en-US-Ava:DragonHDLatestNeural", "A < B", {"structure": "none"}, {},
        )
        self.assertIn('<voice name="en-US-Ava:DragonHDLatestNeural">A &lt; B</voice>', ava_ssml)
        self.assertNotIn("parameters=", ava_ssml)
        self.assertNotIn("mstts:", ava_ssml)
        self.assertNotIn("<!--", ava_ssml)
        andrew_ssml, _, _ = MEDIA.build_ssml(
            "en", "en-US-Andrew:DragonHDLatestNeural", "Test", {"structure": "none"}, {"temperature": 1.0},
        )
        self.assertIn('parameters="temperature=1"', andrew_ssml)
        self.assertNotIn("<prosody", andrew_ssml)
        yunxiao_ssml, _, _ = MEDIA.build_ssml(
            "zh-CN",
            "zh-CN-Yunxiao:DragonHDFlashLatestNeural",
            "你好，欢迎收听。",
            {"structure": "none"},
            {"temperature": 1.0},
        )
        self.assertIn('xml:lang="zh-CN"', yunxiao_ssml)
        self.assertIn('parameters="temperature=1"', yunxiao_ssml)
        self.assertNotIn("mstts:", yunxiao_ssml)
        self.assertNotIn("<prosody", yunxiao_ssml)

    def test_dragonhd_flash_configuration_accepts_audit_id(self):
        self.assertTrue(MEDIA.is_dragon_hd_voice("zh-CN-Xiaochen:DragonHDLatestNeural"))
        self.assertTrue(MEDIA.is_dragon_hd_voice("zh-CN-Yunxiao:DragonHDFlashLatestNeural"))
        self.assertEqual(
            MEDIA.normalise_voice_configuration(
                {
                    "id": "d4182cbc-7818-4a96-9a95-d5c2bdf05bae",
                    "name": "zh-CN-Yunxiao:DragonHDFlashLatestNeural",
                    "parameters": {"temperature": 1},
                }
            ),
            {
                "id": "d4182cbc-7818-4a96-9a95-d5c2bdf05bae",
                "name": "zh-CN-Yunxiao:DragonHDFlashLatestNeural",
                "parameters": {"temperature": 1.0},
            },
        )

    def test_non_monotonic_translation_fails_and_records_no_secret(self):
        temp, root, production_path = self.make_package("en-zh")
        with temp:
            production = json.loads(production_path.read_text(encoding="utf-8"))
            production["script_generation"]["policy_version"] = "4.0"
            production_path.write_text(json.dumps(production), encoding="utf-8")
            provider = FakeAzureProvider(non_monotonic_translation=True)
            with self.assertRaisesRegex(MEDIA.MediaError, "translation"):
                MEDIA.run_media(production_path, provider)
            production = json.loads(production_path.read_text(encoding="utf-8"))
            self.assertEqual(production["state"], "failed")
            self.assertNotIn("azure_speech_studio", json.dumps(production))
