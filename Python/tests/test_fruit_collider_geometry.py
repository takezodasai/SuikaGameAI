"""Current user-authored Circle/Capsule configuration and runtime compatibility."""
import re
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
class FruitColliderGeometryTests(unittest.TestCase):
    def test_each_fruit_has_one_enabled_circle_or_capsule(self):
        count = 0
        for path in (ROOT / "Unity/Assets/Scenes/Prefab").glob("*.prefab"):
            blocks = re.split(r"(?=--- !u!)", path.read_text(encoding="utf-8-sig"))
            shapes = [b for b in blocks if b.startswith(("--- !u!58 ", "--- !u!60 ", "--- !u!70 "))]
            if not shapes: continue
            count += 1
            active = [b for b in shapes if "  m_Enabled: 1" in b]
            with self.subTest(fruit=path.name):
                self.assertEqual(len(active), 1)
                self.assertTrue(active[0].startswith(("--- !u!58 ", "--- !u!70 ")))
        self.assertEqual(count, 11)
    def test_runtime_never_reenables_or_adds_legacy_polygon(self):
        for p in (ROOT / "Unity/Assets/Scenes/Script").glob("*.cs"):
            with self.subTest(file=p.name):
                self.assertNotIn("GetComponent<PolygonCollider2D>", p.read_text(encoding="utf-8-sig"))
                self.assertNotIn("AddComponent<PolygonCollider2D>", p.read_text(encoding="utf-8-sig"))
