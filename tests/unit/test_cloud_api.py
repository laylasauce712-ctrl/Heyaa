import hashlib
import os
import unittest
from unittest.mock import MagicMock, patch
from contextlib import nullcontext
from uuid import uuid4

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from cloud.api import (
    UploadRequest,
    _validate_media,
    _validate_upload,
    authenticate,
)


class CloudApiTests(unittest.TestCase):
    def test_authentication_requires_configured_long_bearer_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                authenticate(None)
        self.assertEqual(caught.exception.status_code, 503)

    def test_authentication_hashes_the_shared_private_beta_token(self):
        token = "a" * 64
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with patch.dict(os.environ, {"HEYAA_CLOUD_API_TOKEN": token}, clear=True):
            owner = authenticate(credentials)
        self.assertEqual(owner, hashlib.sha256(token.encode()).hexdigest()[:32])

    def test_authentication_rejects_invalid_token(self):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
        with patch.dict(os.environ, {"HEYAA_CLOUD_API_TOKEN": "b" * 64}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                authenticate(credentials)
        self.assertEqual(caught.exception.status_code, 401)

    def test_upload_validation_reuses_shared_slot_contract(self):
        request = UploadRequest(
            slot="video", filename="source.mp4",
            content_type="video/mp4", size_bytes=1024,
        )
        suffix, limit = _validate_upload(request)
        self.assertEqual(suffix, ".mp4")
        self.assertEqual(limit, 2 * 1024 * 1024 * 1024)

    def test_upload_validation_maps_wrong_mime_to_415(self):
        request = UploadRequest(
            slot="music", filename="track.mp3",
            content_type="video/mp4", size_bytes=1024,
        )
        with self.assertRaises(HTTPException) as caught:
            _validate_upload(request)
        self.assertEqual(caught.exception.status_code, 415)

    def test_ai_upscale_request_is_rejected_when_deployment_flag_is_off(self):
        from cloud.api import JobCreate, MediaInput, create_job

        request = JobCreate(
            video=MediaInput(url="https://www.tiktok.com/@creator/video/1234567890123456789"),
            music=MediaInput(url="https://www.youtube.com/watch?v=abcdefghijk"),
            ai_upscale_enabled=True,
        )
        with patch.dict(os.environ, {"HEYAA_AI_UPSCALE_REQUESTS_ENABLED": "0"}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                create_job(request, "owner-key")
        self.assertEqual(caught.exception.status_code, 409)

    def test_preview_url_is_inline_and_uses_public_storage_endpoint(self):
        from cloud.api import preview_job

        connection = MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchone.return_value = {
            "status": "ready_for_review",
            "output_key": "outputs/owner/job/final_phonk_20s.mp4",
        }
        signer = MagicMock()
        signer.generate_presigned_url.return_value = "https://storage.example/preview"
        with patch.dict(os.environ, {"HEYAA_STORAGE_BUCKET": "heyaa-test"}), patch(
            "cloud.api.database_connection", return_value=connection
        ), patch("cloud.api.public_storage_client", return_value=signer):
            result = preview_job(uuid4(), "owner")
        self.assertEqual(result["url"], "https://storage.example/preview")
        params = signer.generate_presigned_url.call_args.kwargs["Params"]
        self.assertIn("inline", params["ResponseContentDisposition"])

    def test_download_url_requires_approval_and_uses_public_storage_attachment(self):
        from cloud.api import download_job

        connection = MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchone.return_value = {
            "status": "approved",
            "output_key": "outputs/owner/job/final_phonk_20s.mp4",
        }
        signer = MagicMock()
        signer.generate_presigned_url.return_value = "https://storage.example/final"
        with patch.dict(os.environ, {"HEYAA_STORAGE_BUCKET": "heyaa-test"}), patch(
            "cloud.api.database_connection", return_value=connection
        ), patch("cloud.api.public_storage_client", return_value=signer):
            result = download_job(uuid4(), "owner")
        self.assertEqual(result["url"], "https://storage.example/final")
        params = signer.generate_presigned_url.call_args.kwargs["Params"]
        self.assertIn("attachment", params["ResponseContentDisposition"])

    def test_job_cannot_reference_another_owners_object_key(self):
        class NeverCalledStorage:
            def head_object(self, **_kwargs):
                raise AssertionError("cross-owner object must be rejected before storage access")

        with self.assertRaises(HTTPException) as caught:
            _validate_media(
                type("Media", (), {"url": None, "object_key": "uploads/other/file.mp4"})(),
                "video",
                "my-owner",
                NeverCalledStorage(),
            )
        self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
