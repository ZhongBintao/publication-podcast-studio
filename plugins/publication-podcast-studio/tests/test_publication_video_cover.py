import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).parents[1] / "skills" / "publication-video-cover" / "scripts" / "publication_video_cover.py"
SPEC = importlib.util.spec_from_file_location("publication_video_cover", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
RELEASE_SCRIPT = Path(__file__).parents[1] / "skills" / "publication-podcast-studio-workflow" / "scripts" / "release_package.py"
RELEASE_SPEC = importlib.util.spec_from_file_location("release_package", RELEASE_SCRIPT)
RELEASE = importlib.util.module_from_spec(RELEASE_SPEC)
RELEASE_SPEC.loader.exec_module(RELEASE)


class PublicationVideoCoverTests(unittest.TestCase):
    def make_video(self, root: Path, name: str, size: tuple[int, int], colour: str, second_colour: str | None = None) -> Path:
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is required for the finished-video-frame cover test")
        source = root / f"{name}.png"
        Image.new("RGB", size, colour).save(source)
        video = root / f"{name}.mkv"
        if second_colour is not None:
            source.rename(root / f"{name}-0.png")
            Image.new("RGB", size, second_colour).save(root / f"{name}-1.png")
            input_args = ["-framerate", "1", "-i", str(root / f"{name}-%d.png"), "-frames:v", "2"]
        else:
            input_args = ["-loop", "1", "-i", str(source), "-t", "1"]
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *input_args,
                "-r", "1", "-c:v", "ffv1", "-pix_fmt", "yuv444p", str(video),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.skipTest(f"ffmpeg cannot create the fixture video: {result.stderr}")
        return video

    def make_package(self, root: Path) -> tuple[dict, list[dict]]:
        editorial = {
            "format": "publication-editorial-assets",
            "cover_art": {
                "text_lines": [
                    {"position": "top", "text": "情感消费陷阱", "source_paragraph_ids": ["p001"]},
                    {"position": "middle", "text": "你不是在自愈", "source_paragraph_ids": ["p001"]},
                    {"position": "bottom", "text": "而是在购买片刻安宁", "source_paragraph_ids": ["p002"]},
                ],
                "outputs": {
                    "9:16": {"state": "pending_video_frame", "source_kind": "pending_video_frame"},
                },
            },
        }
        editorial_path = root / "editorial-assets.json"
        editorial_path.write_text(json.dumps(editorial, ensure_ascii=False), encoding="utf-8")
        production = {
            "state": "complete",
            "artifacts": {"editorial_assets": "editorial-assets.json"},
            "artifact_hashes": {},
        }
        (root / "production.json").write_text(json.dumps(production), encoding="utf-8")
        video = self.make_video(root, "en-zh", (1080, 1920), "#315f82", "#b64636")
        other = self.make_video(root, "en", (1080, 1920), "#7e4b2d")
        rendered = [
            {"product": "en", "aspect_ratio": "9:16", "path": str(other.relative_to(root))},
            {"product": "en-zh", "aspect_ratio": "9:16", "path": str(video.relative_to(root))},
        ]
        return production, rendered

    def test_cover_uses_priority_video_frame_and_reference_palette(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production, rendered = self.make_package(root)
            report = MODULE.materialize_video_covers(root, production, rendered, ["9:16"])
            record = report["9:16"]
            self.assertEqual(record["source_kind"], "finished_video_frame")
            self.assertEqual(record["source_video"], "en-zh.mkv")
            self.assertEqual(record["frame_time_seconds"], 0.0)
            self.assertEqual(record["dimensions"], {"width": 1080, "height": 1920})
            self.assertEqual(record["overlay"]["palette"]["line_1"], "#FFE500")
            self.assertEqual(record["overlay"]["palette"]["line_2"], "#12D9FF")
            self.assertEqual(record["overlay"]["palette"]["line_3"], "#12D9FF")
            self.assertTrue(record["overlay"]["enabled"])
            self.assertTrue(all(item["stroke_width_px"] > 0 for item in record["overlay"]["lines"]))
            cover_path = root / record["path"]
            with Image.open(cover_path) as cover:
                self.assertEqual(cover.size, (1080, 1920))
                # Bottom-right is outside the top text safe area and remains
                # the selected video frame's background colour.
                pixel = cover.convert("RGB").getpixel((1079, 1919))
                self.assertLessEqual(max(abs(actual - expected) for actual, expected in zip(pixel, (49, 95, 130))), 2)
            assets = json.loads((root / "editorial-assets.json").read_text(encoding="utf-8"))
            self.assertEqual(assets["cover_art"]["state"], "complete")
            self.assertEqual(assets["cover_art"]["background_source"]["mode"], "finished_video_frame")
            self.assertEqual(assets["cover_art"]["background_source"]["videos"]["9:16"]["path"], "en-zh.mkv")
            self.assertEqual(assets["cover_art"]["style"]["line_1_fill"], "#FFE500")
            self.assertEqual(production["artifacts"]["cover_9x16"], "release/covers/cover-9x16.png")
            self.assertEqual(len(production["artifact_hashes"]["cover_9x16"]), 64)

    def test_second_run_reuses_identical_cover(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production, rendered = self.make_package(root)
            first = MODULE.materialize_video_covers(root, production, rendered, ["9:16"])
            first_bytes = (root / first["9:16"]["path"]).read_bytes()
            second = MODULE.materialize_video_covers(root, production, rendered, ["9:16"])
            self.assertTrue(second["9:16"]["reused"])
            self.assertEqual(first_bytes, (root / second["9:16"]["path"]).read_bytes())

    def test_wrong_video_dimensions_are_rejected_without_scaling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            production, _ = self.make_package(root)
            wrong = self.make_video(root, "wrong", (640, 360), "#315f82")
            rendered = [{"product": "en-zh", "aspect_ratio": "9:16", "path": str(wrong.relative_to(root))}]
            with self.assertRaisesRegex(MODULE.VideoCoverError, "without scaling"):
                MODULE.materialize_video_covers(root, production, rendered, ["9:16"])

    def test_release_package_rejects_pending_or_legacy_cover_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "editorial-assets.json").write_text(json.dumps({
                "cover_art": {"outputs": {"9:16": {"state": "pending_video_frame", "source_kind": "pending_video_frame", "path": "release/covers/cover-9x16.png"}}},
            }), encoding="utf-8")
            with self.assertRaisesRegex(RELEASE.ReleasePackageError, "publication-video-cover"):
                RELEASE._cover_sources(root, {"artifacts": {"editorial_assets": "editorial-assets.json"}}, ["9:16"])


if __name__ == "__main__":
    unittest.main()
