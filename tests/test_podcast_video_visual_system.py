import json
import importlib.util
from pathlib import Path
import unittest

from PIL import Image, ImageDraw


DEFINITION = Path(__file__).parents[1] / "skills" / "economist-static-slide-video" / "templates" / "podcast-video-visual-system.v1.json"
PREVIEW_SCRIPT = Path(__file__).parents[1] / "skills" / "economist-static-slide-video" / "scripts" / "preview_visual_system.py"
SPEC = importlib.util.spec_from_file_location("preview_visual_system", PREVIEW_SCRIPT)
PREVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREVIEW)


class PodcastVideoVisualSystemTests(unittest.TestCase):
    def setUp(self):
        self.definition = json.loads(DEFINITION.read_text(encoding="utf-8"))

    def test_source_and_template_matrix_are_complete(self):
        self.assertEqual(self.definition["source"]["slide_count"], 4)
        self.assertEqual(set(self.definition["templates"]), {
            "landscape_opening",
            "landscape_guide_questions",
            "portrait_opening",
            "portrait_guide_questions",
        })

    def test_every_explicit_element_has_a_valid_source_bbox(self):
        for template in self.definition["templates"].values():
            width, height = template["canvas"]["width"], template["canvas"]["height"]
            for layer in template["layers"]:
                self.assertIn("source_object_id", layer)
                x, y, element_width, element_height = layer["bbox"]
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertGreater(element_width, 0)
                self.assertGreater(element_height, 0)
                self.assertLessEqual(x + element_width, width + 1)
                self.assertLessEqual(y + element_height, height + 1)

    def test_caption_and_question_contracts_match_the_source_deck(self):
        tokens = self.definition["design_tokens"]["colors"]
        self.assertEqual(tokens["page_background"], "#262626")
        self.assertEqual(tokens["portrait_page_panel"], "#262626")
        self.assertEqual(tokens["ink"], "#FFFFFF")
        self.assertEqual(tokens["subtitle_rail"], "#262626")
        self.assertEqual(tokens["caption_underlay"], "#262626")
        self.assertEqual(tokens["subtitle_english"], "#FFFFFF")
        self.assertEqual(tokens["subtitle_chinese"], "#FFFFFF")
        for name in ("landscape_guide_questions", "portrait_guide_questions"):
            question_ids = [layer["id"] for layer in self.definition["templates"][name]["layers"] if layer["id"] in {"guide_question_1", "guide_question_2"}]
            self.assertEqual(question_ids, ["guide_question_1", "guide_question_2"])
        for name in ("landscape_guide_questions", "portrait_guide_questions"):
            number_layers = [layer for layer in self.definition["templates"][name]["layers"] if layer["id"].endswith("_number")]
            self.assertEqual([layer["text"] for layer in number_layers], ["01", "02"])
            self.assertTrue(all(layer["style"]["color"] == "#D71920" for layer in number_layers))
        landscape_layers = {layer["id"]: layer for layer in self.definition["templates"]["landscape_opening"]["layers"]}
        self.assertEqual(landscape_layers["subtitle_rail"]["fill"], tokens["page_background"])
        for layer_id in ("caption_en", "caption_zh"):
            style = landscape_layers[layer_id]["style"]
            self.assertEqual(style["font"]["latin"], "Arial")
            self.assertEqual(style["font"]["east_asian"], "Noto Sans SC")
            self.assertEqual(style["color"], "#FFFFFF")
            self.assertEqual(style["max_lines"], 2)
            self.assertEqual(style["letter_spacing"], 0)
            self.assertEqual(style["line_spacing_percent"], 105)
            self.assertEqual(style["alignment"], "center")
            self.assertEqual(style["stroke_color"], "#FFFFFF")
            self.assertEqual(style["stroke_width_px"], 0)
            self.assertEqual(style["background_color"], "#262626")
            self.assertAlmostEqual(style["background_opacity"], 1.0)

    def test_portrait_adaptations_use_compact_free_flow_and_native_cjk_stops(self):
        tokens = self.definition["design_tokens"]
        self.assertEqual(tokens["colors"]["page_background"], "#262626")
        self.assertEqual(tokens["colors"]["portrait_page_panel"], "#262626")
        self.assertNotIn("chinese_full_stop", tokens)
        for template in ("landscape_opening", "portrait_opening"):
            layers = {item["id"]: item for item in self.definition["templates"][template]["layers"]}
            self.assertEqual(layers["caption_en"]["style"]["alignment"], "center")
            self.assertEqual(layers["caption_zh"]["style"]["alignment"], "center")
        layers = {layer["id"]: layer for layer in self.definition["templates"]["portrait_opening"]["layers"]}
        self.assertEqual(layers["headline_zh"]["style"]["font_size_pt"], 15)
        self.assertEqual(layers["subtitle_zh"]["style"]["font_size_pt"], 10)
        self.assertGreater(layers["headline_zh"]["bbox"][1], layers["headline"]["bbox"][1])
        self.assertGreater(layers["subtitle_zh"]["bbox"][1], layers["subtitle"]["bbox"][1])
        self.assertEqual(layers["headline_zh"]["bbox"][1], 344)
        self.assertEqual(layers["subtitle"]["bbox"][1], 379)
        self.assertEqual(layers["subtitle_zh"]["bbox"][1], 430)
        self.assertEqual(layers["subtitle_rail"]["bbox"], [32.43, 525.6, 340.47, 108])
        self.assertEqual(layers["subtitle_rail"]["stroke"], "none")
        self.assertNotIn("article_page", layers)
        self.assertNotIn("caption_label", layers)
        self.assertNotIn("caption_cue", layers)
        self.assertNotIn("caption_number", layers)
        self.assertEqual(layers["issue_cover"]["bbox"], [52.67, 40.32, 300, 180])
        self.assertEqual(layers["issue_cover"]["fit"], "contain")
        landscape = self.definition["templates"]["landscape_opening"]
        self.assertEqual(next(layer for layer in landscape["layers"] if layer["id"] == "headline")["bbox"], [80, 82.48, 466.67, 160])

    def test_landscape_caption_rail_uses_one_compact_bilingual_flow(self):
        template = self.definition["templates"]["landscape_opening"]
        canvas = Image.new("RGB", (1920, 1080))
        draw = ImageDraw.Draw(canvas)

        def caption_layers(english: str, chinese: str):
            content = {"caption": {"current": {"en": english, "zh": chinese}}}
            return PREVIEW.caption_layers_for_frame(
                draw, template, PREVIEW.layer_map(self.definition, "landscape_opening"), content, 1.5,
            )

        short = caption_layers("Short sentence.", "简短句子。")
        long = caption_layers(
            "Long-term capital is needed to help markets adapt to a new technology race and to finance ambitious projects around the world today.",
            "长期资本需要帮助市场适应新的技术竞赛，并为未来的科技雄心提供支持，同时为世界各地的雄心项目提供资金。",
        )

        self.assertEqual(short["subtitle_rail"]["bbox"], long["subtitle_rail"]["bbox"])
        for layer_id in ("caption_en", "caption_zh"):
            self.assertEqual(short[layer_id]["style"]["font_size_pt"], 20)
            self.assertEqual(long[layer_id]["style"]["font_size_pt"], 20)
            self.assertEqual(short[layer_id]["style"]["min_font_size_pt"], 16)
            self.assertEqual(long[layer_id]["style"]["min_font_size_pt"], 16)
            self.assertEqual(short[layer_id]["style"]["text_insets_px"], [6, 0, 6, 0])
            self.assertEqual(short[layer_id]["style"]["letter_spacing"], 0)
        short_gap = short["caption_zh"]["bbox"][1] - (short["caption_en"]["bbox"][1] + short["caption_en"]["bbox"][3])
        long_gap = long["caption_zh"]["bbox"][1] - (long["caption_en"]["bbox"][1] + long["caption_en"]["bbox"][3])
        self.assertAlmostEqual(short_gap, 6, delta=0.01)
        self.assertAlmostEqual(long_gap, 6, delta=0.01)
        self.assertNotEqual(short["caption_en"]["bbox"], long["caption_en"]["bbox"])

        self.assertLessEqual(short["issue_cover"]["bbox"][1] + short["issue_cover"]["bbox"][3], short["subtitle_rail"]["bbox"][1])
        guide_template = self.definition["templates"]["landscape_guide_questions"]
        question_1 = next(layer for layer in guide_template["layers"] if layer["id"] == "guide_question_1")["bbox"]
        question_2 = next(layer for layer in guide_template["layers"] if layer["id"] == "guide_question_2")["bbox"]
        self.assertLess(question_2[1] - (question_1[1] + question_1[3]), 80)

    def test_landscape_caption_render_uses_page_background_and_local_underlay(self):
        template = self.definition["templates"]["landscape_opening"]
        cover = Path(__file__).parents[1] / "output" / "template-preview" / "issue-cover.png"
        diagnostics = []
        frame = PREVIEW.render_template(
            self.definition,
            "landscape_opening",
            cover,
            {"caption": {"current": {"en": "A complete English subtitle sentence.", "zh": "一条完整的中文字幕句子。"}}},
            1080,
            1920,
            diagnostics,
        )
        self.assertEqual(frame.getpixel((10, 1000)), (38, 38, 38))
        self.assertEqual(frame.getpixel((1161, 53)), (38, 38, 38))
        caption = next(item for item in diagnostics if item["layer"] == "caption_en")
        self.assertEqual(caption["font"], "Arial Bold/bold")
        self.assertEqual(caption["font_weight"], "bold")
        self.assertEqual(caption["letter_spacing"], 0)
        self.assertEqual(caption["text_justification"], "none")
        self.assertEqual(caption["stroke_width_px"], 0)
        self.assertEqual(caption["background_color"], "#262626")
        line_x, line_y, _, _ = caption["line_bboxes"][0]
        self.assertEqual(frame.getpixel((max(0, line_x - 5), line_y + 5)), (38, 38, 38))

    def test_long_landscape_caption_balances_two_lines_and_keeps_descenders_inside_insets(self):
        cover = Path(__file__).parents[1] / "output" / "template-preview" / "issue-cover.png"
        diagnostics = []
        value = "Though the much-publicised arrival last year of Tilly Norwood, an AI-generated actor, did cause a fleeting panic, and the story continues to affect how studios think about their future."
        PREVIEW.render_template(
            self.definition,
            "landscape_opening",
            cover,
            {"caption": {"current": {"en": value, "zh": "一条很长的中文字幕也必须完整显示，并且自然换成两行而不是截断。"}}},
            1080,
            1920,
            diagnostics,
        )
        english = next(item for item in diagnostics if item["layer"] == "caption_en")
        self.assertEqual(english["line_count"], 2)
        first_width, second_width = english["line_bboxes"][0][2], english["line_bboxes"][1][2]
        self.assertGreater(min(first_width, second_width) / max(first_width, second_width), 0.45)
        self.assertEqual(english["text_insets_px"], [6, 0, 6, 0])

    def test_caption_text_does_not_gain_terminal_punctuation(self):
        cover = Path(__file__).parents[1] / "output" / "template-preview" / "issue-cover.png"
        diagnostics = []
        PREVIEW.render_template(
            self.definition,
            "landscape_opening",
            cover,
            {"caption": {"current": {"en": "A cue without terminal punctuation", "zh": "没有句号的字幕"}}},
            1080,
            1920,
            diagnostics,
        )
        self.assertEqual(next(item for item in diagnostics if item["layer"] == "caption_en")["lines"], ["A cue without terminal punctuation"])
        self.assertEqual(next(item for item in diagnostics if item["layer"] == "caption_zh")["lines"], ["没有句号的字幕"])
