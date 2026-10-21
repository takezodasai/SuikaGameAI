"""Check actual Scene wiring and world-space composition invariants."""
import re
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
class GameLayoutTests(unittest.TestCase):
    def test_world_canvases_share_camera_coordinate_system(self):
        scene = (ROOT / "Unity/Assets/Scenes/gameDisplay.unity").read_text()
        blocks = re.split(r"(?=--- !u!)", scene)
        def block(header): return next(b for b in blocks if b.startswith(header))
        for canvas in (28667875, 1029358306):
            self.assertIn("m_RenderMode: 2", block(f"--- !u!223 &{canvas}"))
        bg = block("--- !u!224 &28667876")
        scale = float(re.search(r"m_LocalScale: .*?x: ([0-9.]+)", bg)[1])
        self.assertAlmostEqual(scale * 436.9686, 10, places=6)
        cam = block("--- !u!20 &1501276639")
        self.assertIn("orthographic size: 5", cam)
        self.assertIn("referenceSize: {x: 800, y: 436.9686}", scene)
    def test_existing_score_boxes_fit_inside_reference_frame(self):
        scene = (ROOT / "Unity/Assets/Scenes/gameDisplay.unity").read_text()
        blocks = re.split(r"(?=--- !u!)", scene)
        parent = next(b for b in blocks if b.startswith("--- !u!224 &1029358307"))
        scale = float(re.search(r"m_LocalScale: .*?x: ([0-9.]+)", parent)[1])
        world_half_width = 5 * 800 / 436.9686
        for ident in (447515206, 521351013):
            b = next(b for b in blocks if b.startswith(f"--- !u!224 &{ident}"))
            x = float(re.search(r"m_AnchoredPosition: .*?x: ([-0-9.]+)", b)[1])
            width = float(re.search(r"m_SizeDelta: .*?x: ([0-9.]+)", b)[1])
            self.assertLessEqual((abs(x) + width / 2) * scale, world_half_width)
