import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.heyaa.subject_tracking import _find_face_cascade


class FaceCascadeLookupTests(unittest.TestCase):
    def test_finds_opencv_shipped_haar_cascade(self):
        with tempfile.TemporaryDirectory() as folder:
            cascade = Path(folder) / "haarcascade_frontalface_default.xml"
            cascade.write_text("<opencv_storage/>", encoding="utf-8")
            fake_cv2 = SimpleNamespace(
                data=SimpleNamespace(haarcascades=folder + "/"),
                __file__=str(Path(folder) / "cv2.py"),
            )
            self.assertEqual(_find_face_cascade(fake_cv2), cascade)

    def test_missing_packaged_cascade_uses_project_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            fake_cv2 = SimpleNamespace(
                data=SimpleNamespace(haarcascades=folder + "/missing/"),
                __file__=str(Path(folder) / "cv2.py"),
            )
            expected = Path(__file__).resolve().parents[2] / "src" / "heyaa" / "assets" / "haarcascade_frontalface_default.xml"
            self.assertEqual(_find_face_cascade(fake_cv2), expected)

    def test_project_bundles_the_opencv_frontal_face_classifier(self):
        cascade = Path(__file__).resolve().parents[2] / "src" / "heyaa" / "assets" / "haarcascade_frontalface_default.xml"
        self.assertTrue(cascade.is_file())
        self.assertGreater(cascade.stat().st_size, 100_000)
        with cascade.open("r", encoding="utf-8", errors="replace") as handle:
            self.assertIn("Intel License Agreement", handle.read(2500))


if __name__ == "__main__":
    unittest.main()
