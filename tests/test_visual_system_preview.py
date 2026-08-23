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
    def test_image_border_wraps_the_contained_image_not_the_letterbox_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "square.png"
            Image.new("RGB", (100, 100), "#A61919").save(source)
            canvas = Image.new("RGB", (300, 120), "#000000")
            MODULE.draw_image(canvas, {
                "bbox": [0, 0, 300, 120],
                "fit": "contain",
                "style": {"stroke": "solid", "border_color": "#FFFFFF", "border_width_output_px": 3},
            }, source, 1.0)
            self.assertEqual(canvas.getpixel((89, 0)), (38, 38, 38))
            self.assertEqual(canvas.getpixel((90, 0)), (255, 255, 255))
            self.assertEqual(canvas.getpixel((94, 4)), (166, 25, 25))

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
                    "en": "An English subtitle wraps naturally into two centered lines.",
                    "zh": "完整中文字幕自然换成两行。",
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
                    self.assertEqual(item["font_weight"], "medium")
                    self.assertTrue(all(not line.startswith(tuple("，。！？；：、）》】〉〕〗」』")) for line in item["lines"]))
                else:
                    self.assertEqual(item["font"], "Arial Bold/bold")
                    self.assertEqual(item["font_weight"], "bold")

    def test_english_only_mode_hides_chinese_caption_layer_in_all_template_states(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "cover.png"
            Image.new("RGB", (600, 800), "#A61919").save(cover)
            definition = MODULE.read_definition(MODULE.DEFAULT_DEFINITION)
            content = {**MODULE.SAMPLE_CONTENT, "caption": {"current": {
                "en": "A complete English subtitle sentence.",
                "zh": "一条完整的中文字幕句子。",
            }}}
            for template, height, width in (
                ("landscape_opening", 1080, 1920),
                ("landscape_guide_questions", 1080, 1920),
                ("portrait_opening", 1920, 1080),
                ("portrait_guide_questions", 1920, 1080),
            ):
                diagnostics = []
                MODULE.render_template(definition, template, cover, content, height, width, diagnostics, "en-only")
                caption_diagnostics = [item for item in diagnostics if item["layer"].startswith("caption_")]
                self.assertEqual([item["layer"] for item in caption_diagnostics], ["caption_en"])
                english = caption_diagnostics[0]
                x, _, safe_width, _ = english["safe_bbox"]
                for line_x, _, line_width, _ in english["line_bboxes"]:
                    self.assertAlmostEqual(line_x + line_width / 2, x + safe_width / 2, delta=2)
                self.assertEqual(english["font"], "Arial Bold/bold")

                layers = MODULE.caption_layers_for_frame(
                    __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(Image.new("RGB", (width, height))),
                    definition["templates"][template],
                    MODULE.layer_map(definition, template),
                    content,
                    height / definition["templates"][template]["canvas"]["height"],
                    "en-only",
                )
                self.assertFalse(layers["caption_zh"]["visible"])
                self.assertEqual(layers["caption_zh"]["bbox"][3], 0)

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

    def test_portrait_caption_blocks_overlong_cues_instead_of_truncating(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "cover.png"
            Image.new("RGB", (600, 800), "#A61919").save(cover)
            definition = MODULE.read_definition(MODULE.DEFAULT_DEFINITION)
            diagnostics = []
            with self.assertRaisesRegex(RuntimeError, "without truncation"):
                MODULE.render_template(
                    definition, "portrait_guide_questions", cover,
                    {**MODULE.SAMPLE_CONTENT, "caption": {"current": {
                        "en": "This complete English sentence is deliberately too long for the narrow portrait rail and must be split before rendering as a timed cue. " * 3,
                        "zh": "这是一条过长的中文字幕，必须在进入竖屏渲染前拆成完整的计时单元。" * 3,
                    }}},
                    1920, 1080, diagnostics,
                )

    def test_legacy_leading_punctuation_examples_are_never_produced_by_cjk_wrapping(self):
        fixture = Path(__file__).parent / "fixtures" / "legacy-leading-punctuation.json"
        examples = json.loads(fixture.read_text(encoding="utf-8"))["leading_lines"]
        self.assertEqual(len(examples), 19)
        self.assertTrue(all(line.startswith(tuple("，。！？；：、）》】")) for line in examples))
        self.assertEqual(MODULE.cjk_wrap_tokens("油气，贸易。"), ["油", "气，", "贸", "易。"])

    def test_mixed_cjk_caption_with_latin_name_wraps_inside_portrait_safe_box(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cover = root / "cover.png"
            Image.new("RGB", (600, 800), "#A61919").save(cover)
            definition = MODULE.read_definition(MODULE.DEFAULT_DEFINITION)
            diagnostics = []
            MODULE.render_template(
                definition, "portrait_opening", cover,
                {**MODULE.SAMPLE_CONTENT, "caption": {"current": {
                    "en": "",
                    "zh": "Anthropic 的研究人员用他们开发的一种数学工具，成功看进了这些层。",
                }}},
                1920, 1080, diagnostics,
            )
            caption = next(item for item in diagnostics if item["layer"] == "caption_zh")
            _, _, width, _ = caption["safe_bbox"]
            self.assertTrue(all(line[2] <= width for line in caption["line_bboxes"]))
            self.assertFalse(any(line.startswith(tuple("，。！？；：、）》】〉〕〗」』")) for line in caption["lines"]))

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

    def test_portrait_opening_metadata_flows_without_overlapping_the_caption_card(self):
        definition = MODULE.read_definition(MODULE.DEFAULT_DEFINITION)
        template = definition["templates"]["portrait_opening"]
        canvas = Image.new("RGB", (1080, 1920), "#262626")
        content = {
            **MODULE.SAMPLE_CONTENT,
            "article": {
                **MODULE.SAMPLE_CONTENT["article"],
                "headline": "A deliberately long portrait headline that wraps cleanly",
                "headline_zh": "一个足够长的中文标题也必须完整显示并保持清晰间距",
                "subtitle": "A supporting deck with enough words to exercise the portrait opening flow and its adaptive typography.",
                "subtitle_zh": "一条较长的副标题用于验证竖屏首屏的动态排版。",
            },
            "caption": {"current": {"en": "A short cue.", "zh": "一条短字幕。"}},
        }
        layers = MODULE.prepare_portrait_opening_layers(
            __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(canvas),
            template,
            MODULE.layer_map(definition, "portrait_opening"),
            content,
            1920 / 720,
        )
        metadata_ids = ("headline", "headline_zh", "subtitle", "subtitle_zh", "byline_dateline")
        for previous, current in zip(metadata_ids, metadata_ids[1:]):
            previous_box = layers[previous]["bbox"]
            current_box = layers[current]["bbox"]
            self.assertLessEqual(previous_box[1] + previous_box[3], current_box[1])
        metadata_bottom = max(layers[name]["bbox"][1] + layers[name]["bbox"][3] for name in metadata_ids)
        rail = next(item for item in template["layers"] if item["id"] == "subtitle_rail")
        self.assertLessEqual(metadata_bottom + 8, rail["bbox"][1])
