import importlib.util
import json
import tempfile
from pathlib import Path
import unittest

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "skills" / "economist-static-slide-video" / "scripts" / "preview_visual_system.py"
SPEC = importlib.util.spec_from_file_location("visual_system_preview", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class VisualSystemPreviewTests(unittest.TestCase):
    def test_extracted_definition_renders_all_four_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "cover.png"
            Image.new("RGB", (600, 800), "#A61919").save(cover)
            outputs = MODULE.render_all(MODULE.DEFAULT_DEFINITION, cover, root / "preview")

            self.assertEqual(set(outputs), {
                "01-landscape-opening",
                "02-landscape-guide-questions",
                "03-portrait-opening",
                "04-portrait-guide-questions",
                "contact_sheet",
            })
            with Image.open(outputs["01-landscape-opening"]) as landscape, Image.open(outputs["03-portrait-opening"]) as portrait:
                self.assertEqual(landscape.size, (1920, 1080))
                self.assertEqual(portrait.size, (1080, 1920))
                self.assertEqual(landscape.getpixel((10, 10)), (38, 38, 38))
                self.assertEqual(portrait.getpixel((10, 10)), (38, 38, 38))

    def test_adaptive_captions_wrap_without_a_two_line_cap_in_landscape_and_portrait(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "cover.png"
            Image.new("RGB", (600, 800), "#A61919").save(cover)
            definition = MODULE.read_definition(MODULE.DEFAULT_DEFINITION)
            content = {
                **MODULE.SAMPLE_CONTENT,
                "caption": {"current": {
                    "en": "Long English captions must remain inside frame.",
                    "zh": "加长中文字幕必须始终位于视频安全区域内。",
                }},
            }
            for template, height, width in (("landscape_opening", 1080, 1920), ("portrait_opening", 1920, 1080)):
                frame = MODULE.render_template(definition, template, cover, content, height, width)
                self.assertEqual(frame.size, (width, height))
                layers = MODULE.layer_map(definition, template)
                draw = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(frame)
                for layer_id, value in (("caption_en", content["caption"]["current"]["en"]), ("caption_zh", content["caption"]["current"]["zh"])):
                    layer = layers[layer_id]
                    x, y, box_width, box_height = MODULE.scaled_box(layer["bbox"], height / definition["templates"][template]["canvas"]["height"])
                    face, lines, line_height = MODULE.fitted_adaptive_lines(draw, value, layer["style"], layer["style"], box_width, box_height, height / definition["templates"][template]["canvas"]["height"])
                    self.assertLessEqual(len(lines) * line_height, box_height)
                    self.assertTrue(all(MODULE.measure(draw, line, face)[0] <= box_width for line in lines))

    def test_bilingual_caption_text_is_centered_and_uses_native_cjk_punctuation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "cover.png"
            Image.new("RGB", (600, 800), "#A61919").save(cover)
            definition = MODULE.read_definition(MODULE.DEFAULT_DEFINITION)
            diagnostics = []
            MODULE.render_template(
                definition, "portrait_opening", cover,
                {**MODULE.SAMPLE_CONTENT, "caption": {"current": {
                    "en": "An English subtitle should wrap naturally into several centered visual lines when the full sentence requires it.",
                    "zh": "带完整中文句号的长字幕，验证原生标点可以自然换行，并且不会把句号或者逗号放到新行的开头。",
                }}},
                1920, 1080, diagnostics,
            )
            self.assertEqual({item["layer"] for item in diagnostics}, {"caption_en", "caption_zh"})
            for item in diagnostics:
                x, _, width, _ = item["safe_bbox"]
                for line_x, _, line_width, _ in item["line_bboxes"]:
                    self.assertAlmostEqual(line_x + line_width / 2, x + width / 2, delta=2)
                if item["layer"] == "caption_zh":
                    self.assertIn("Noto Sans SC", item["font"])
                    self.assertEqual(item["font_weight"], "regular")
                    self.assertTrue(all(not line.startswith(tuple("，。！？；：、）》】〉〕〗」』")) for line in item["lines"]))
                else:
                    self.assertEqual(item["font"], "Arial/regular")
                    self.assertEqual(item["font_weight"], "regular")

    def test_font_selection_covers_special_punctuation_and_mixed_latin_cjk_text(self):
        value = "Mixed ‘quotes’ “smart punctuation” ‑ – and 中文，。"
        path = MODULE.font_path(
            bold=True,
            cjk=True,
            sans=True,
            font_value={"latin": "Arial", "east_asian": "Noto Sans SC"},
            font_weight="medium",
            text=value,
        )
        self.assertIn("NOTOSANSSC-VF.TTF", path)
        self.assertTrue(MODULE.font_supports_text(path, value, weight="medium"))

    def test_sentence_caption_can_use_more_than_two_visual_lines_and_stays_above_guide_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "cover.png"
            Image.new("RGB", (600, 800), "#A61919").save(cover)
            definition = MODULE.read_definition(MODULE.DEFAULT_DEFINITION)
            diagnostics = []
            MODULE.render_template(
                definition, "portrait_guide_questions", cover,
                {**MODULE.SAMPLE_CONTENT, "caption": {"current": {
                    "en": "This complete English sentence wraps over more than two visual lines in the narrow portrait caption rail without becoming several timed cues.",
                    "zh": "这是一条完整的中文字幕，能够在狭窄的竖屏字幕栏中自然换成超过两行，而不被切成多个计时单元。",
                }}},
                1920, 1080, diagnostics,
            )
            captions = [item for item in diagnostics if item["layer"].startswith("caption_")]
            self.assertGreater(sum(item["line_count"] for item in captions), 4)
            self.assertTrue(all(not line.startswith(tuple("，。！？；：、）》】〉〕〗」』")) for line in next(item for item in captions if item["layer"] == "caption_zh")["lines"]))

    def test_legacy_leading_punctuation_examples_are_never_produced_by_cjk_wrapping(self):
        fixture = Path(__file__).parent / "fixtures" / "legacy-leading-punctuation.json"
        examples = json.loads(fixture.read_text(encoding="utf-8"))["leading_lines"]
        self.assertEqual(len(examples), 19)
        self.assertTrue(all(line.startswith(tuple("，。！？；：、）》】")) for line in examples))
        self.assertEqual(MODULE.cjk_wrap_tokens("油气，贸易。"), ["油", "气，", "贸", "易。"])

    def test_caption_fails_instead_of_truncating_when_protected_space_is_exhausted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "cover.png"
            Image.new("RGB", (600, 800), "#A61919").save(cover)
            definition = MODULE.read_definition(MODULE.DEFAULT_DEFINITION)
            content = {**MODULE.SAMPLE_CONTENT, "caption": {"current": {
                "en": "word " * 240,
                "zh": "完整句子，" * 180,
            }}}
            with self.assertRaisesRegex(RuntimeError, "without truncation"):
                MODULE.render_template(definition, "portrait_guide_questions", cover, content, 1920, 1080)

    def test_portrait_guide_questions_stay_inside_their_own_safe_boxes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "cover.png"
            Image.new("RGB", (600, 800), "#A61919").save(cover)
            definition = MODULE.read_definition(MODULE.DEFAULT_DEFINITION)
            diagnostics = []
            MODULE.render_template(
                definition, "portrait_guide_questions", cover,
                {**MODULE.SAMPLE_CONTENT, "guide_questions": [
                    {"question": "Why is trading more profitable for European oil majors?", "translation_zh": "欧洲石油巨头的交易为何更赚钱？"},
                    {"question": "Can European oil majors keep their trading edge?", "translation_zh": "欧洲巨头能保住交易优势吗？"},
                ]},
                1920, 1080, diagnostics,
            )
            guides = [item for item in diagnostics if item["layer"].startswith("guide_question_")]
            self.assertEqual({item["layer"] for item in guides}, {"guide_question_1", "guide_question_2"})
            for item in guides:
                x, y, width, height = item["safe_bbox"]
                for line_x, line_y, line_width, line_height in item["line_bboxes"]:
                    self.assertGreaterEqual(line_x, x)
                    self.assertGreaterEqual(line_y, y)
                    self.assertLessEqual(line_x + line_width, x + width)
                    self.assertLessEqual(line_y + line_height, y + height)
