import unittest
from src.heyaa.edl.legacy import edl_mode, should_render_edl

class LegacyTests(unittest.TestCase):
    def test_default_off(self):
        self.assertEqual(edl_mode({}),"off"); self.assertFalse(should_render_edl({}))
    def test_modes(self):
        self.assertEqual(edl_mode({"edl_mode":"shadow"}),"shadow")
        self.assertTrue(should_render_edl({"edl_mode":"on"}))
    def test_invalid_fail_closed(self):
        for value in ("ON","yes",None,1): self.assertEqual(edl_mode({"edl_mode":value}),"off")

if __name__ == "__main__": unittest.main()
