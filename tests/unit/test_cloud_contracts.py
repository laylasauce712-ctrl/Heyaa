import unittest

from cloud.contracts import (
    CloudInputError,
    MAX_MUSIC_BYTES,
    MAX_VIDEO_BYTES,
    object_key_belongs_to_owner,
    validate_platform_url,
    validate_upload_metadata,
)


class CloudContractsTests(unittest.TestCase):
    def test_upload_metadata_accepts_video_music_and_reference(self):
        self.assertEqual(
            validate_upload_metadata("video", "phone.mp4", "video/mp4", 100),
            (".mp4", MAX_VIDEO_BYTES),
        )
        self.assertEqual(
            validate_upload_metadata("reference", "reference.mov", "video/quicktime", 100),
            (".mov", MAX_VIDEO_BYTES),
        )
        self.assertEqual(
            validate_upload_metadata("music", "track.mp3", "audio/mpeg", 100),
            (".mp3", MAX_MUSIC_BYTES),
        )

    def test_upload_metadata_rejects_paths_wrong_mime_and_oversize(self):
        cases = [
            ("video", "../escape.mp4", "video/mp4", 10),
            ("video", "clip.mp4", "application/octet-stream", 10),
            ("music", "track.mp3", "audio/mpeg", MAX_MUSIC_BYTES + 1),
            ("other", "clip.mp4", "video/mp4", 10),
            ("video", "clip.mp4", "video/mp4", True),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(CloudInputError):
                validate_upload_metadata(*args)

    def test_upload_object_key_is_owner_scoped_and_path_safe(self):
        self.assertTrue(object_key_belongs_to_owner("uploads/owner123/a.mp4", "owner123"))
        self.assertFalse(object_key_belongs_to_owner("uploads/other/a.mp4", "owner123"))
        self.assertFalse(object_key_belongs_to_owner("uploads/owner123/../secret.mp4", "owner123"))
        self.assertFalse(object_key_belongs_to_owner("outputs/owner123/a.mp4", "owner123"))

    def test_platform_urls_only_allow_validated_youtube_or_tiktok(self):
        self.assertEqual(
            validate_platform_url("https://www.tiktok.com/@creator/video/1234567890123456789", "video"),
            "https://www.tiktok.com/@creator/video/1234567890123456789",
        )
        with self.assertRaises(CloudInputError):
            validate_platform_url("http://www.youtube.com/watch?v=abc123", "music")
        with self.assertRaises(CloudInputError):
            validate_platform_url("https://127.0.0.1:8080/admin", "video")
        with self.assertRaises(CloudInputError):
            validate_platform_url("https://www.tiktok.com/@creator", "video")


if __name__ == "__main__":
    unittest.main()
