"""Authenticated control-plane API for the phone-first Heyaa cloud service.

The API manages small job records and presigned object-storage URLs. It never
streams large media through the API or performs rendering inside a request.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID, uuid4

import boto3
import psycopg
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg.rows import dict_row

from src.heyaa.media_sources import (
    TIKTOK_HOSTS,
    YOUTUBE_HOSTS,
    validate_tiktok_url,
    validate_youtube_url,
)

API_VERSION = "v1"
UPLOAD_TTL_SECONDS = 900
DOWNLOAD_TTL_SECONDS = 600
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
MAX_MUSIC_BYTES = 512 * 1024 * 1024
MAX_EVENTS = 250
bearer = HTTPBearer(auto_error=False)

SLOT_EXTENSIONS = {
    "video": {".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska", ".webm": "video/webm", ".m4v": "video/x-m4v"},
    "reference": {".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska", ".webm": "video/webm", ".m4v": "video/x-m4v"},
    "music": {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/opus"},
}


def database_connection():
    dsn = os.environ.get("HEYAA_DATABASE_URL")
    if not dsn:
        raise RuntimeError("HEYAA_DATABASE_URL is required")
    return psycopg.connect(dsn, row_factory=dict_row)


def storage_client():
    required = ("HEYAA_STORAGE_BUCKET", "HEYAA_STORAGE_ACCESS_KEY", "HEYAA_STORAGE_SECRET_KEY")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Missing object-storage configuration: " + ", ".join(missing))
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("HEYAA_STORAGE_ENDPOINT_URL") or None,
        region_name=os.environ.get("HEYAA_STORAGE_REGION", "auto"),
        aws_access_key_id=os.environ["HEYAA_STORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["HEYAA_STORAGE_SECRET_KEY"],
    )


def ensure_schema() -> None:
    with database_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS heyaa_cloud_jobs (
                job_id UUID PRIMARY KEY,
                owner_key TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN (
                    'queued', 'running', 'cancel_requested', 'cancelled',
                    'ready_for_review', 'approved', 'failed'
                )),
                request JSONB NOT NULL,
                progress JSONB NOT NULL DEFAULT '[]'::jsonb,
                log_tail TEXT NOT NULL DEFAULT '',
                output_key TEXT,
                report_key TEXT,
                report JSONB,
                error TEXT,
                worker_id TEXT,
                lease_expires_at TIMESTAMPTZ,
                cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS heyaa_cloud_jobs_owner_created "
            "ON heyaa_cloud_jobs (owner_key, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS heyaa_cloud_jobs_queue "
            "ON heyaa_cloud_jobs (status, created_at)"
        )


def _owner_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def authenticate(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    expected = os.environ.get("HEYAA_CLOUD_API_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloud API authentication is not configured.",
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer authentication is required.")
    if not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="Invalid API token.")
    return _owner_key(expected)


class UploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: Literal["video", "music", "reference"]
    filename: str = Field(min_length=1, max_length=180)
    content_type: str = Field(min_length=3, max_length=100)
    size_bytes: int = Field(gt=0)


class MediaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_key: str | None = Field(default=None, max_length=512)
    url: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def require_exactly_one_source(self):
        if bool(self.object_key) == bool(self.url):
            raise ValueError("Provide exactly one of object_key or url.")
        return self


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    video: MediaInput
    music: MediaInput
    reference: MediaInput | None = None
    ai_upscale_enabled: bool = False
    layout_mode: Literal["fill", "blur_fit"] = "fill"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    yield


app = FastAPI(
    title="Heyaa Cloud API",
    version="1.0.0",
    description="Authenticated media uploads, durable render jobs and private exports.",
    lifespan=lifespan,
)
origins = [value.strip() for value in os.environ.get("HEYAA_ALLOWED_ORIGINS", "").split(",") if value.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )


def _validate_upload(request: UploadRequest) -> tuple[str, int]:
    original = request.filename.replace("\\", "/")
    filename = PurePosixPath(original).name
    if filename != original or filename in {"", ".", ".."}:
        raise HTTPException(status_code=422, detail="Filename must not contain a path.")
    suffix = PurePosixPath(filename).suffix.lower()
    expected_type = SLOT_EXTENSIONS[request.slot].get(suffix)
    if not expected_type:
        raise HTTPException(status_code=415, detail=f"Unsupported {request.slot} file extension.")
    if request.content_type.split(";", 1)[0].strip().lower() != expected_type:
        raise HTTPException(status_code=415, detail="Content-Type does not match the selected file extension.")
    limit = MAX_MUSIC_BYTES if request.slot == "music" else MAX_VIDEO_BYTES
    if request.size_bytes > limit:
        raise HTTPException(status_code=413, detail=f"File exceeds the {limit // (1024 * 1024)} MiB {request.slot} limit.")
    return suffix, limit


def _validate_platform_url(url: str, slot: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail=f"{slot} URL must be a public HTTPS YouTube or TikTok link.")
    host = (parsed.hostname or "").lower()
    try:
        if host in YOUTUBE_HOSTS:
            return validate_youtube_url(url, slot)
        if host in TIKTOK_HOSTS:
            return validate_tiktok_url(url, slot)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(
        status_code=422,
        detail=f"{slot} URL host is not allowed. Upload a file or use a supported YouTube/TikTok post URL.",
    )


def _validate_media(
    media: MediaInput,
    slot: str,
    owner_key: str,
    s3: Any,
) -> dict[str, str]:
    if media.url:
        return {"kind": "url", "url": _validate_platform_url(media.url, slot)}
    key = media.object_key or ""
    expected_prefix = f"uploads/{owner_key}/"
    if not key.startswith(expected_prefix) or ".." in PurePosixPath(key).parts:
        raise HTTPException(status_code=403, detail=f"{slot} upload does not belong to this account.")
    try:
        info = s3.head_object(Bucket=os.environ["HEYAA_STORAGE_BUCKET"], Key=key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Uploaded {slot} file was not found or is not accessible.") from exc
    limit = MAX_MUSIC_BYTES if slot == "music" else MAX_VIDEO_BYTES
    if int(info.get("ContentLength") or 0) <= 0 or int(info.get("ContentLength") or 0) > limit:
        raise HTTPException(status_code=413, detail=f"Uploaded {slot} file is empty or exceeds its size limit.")
    return {"kind": "upload", "object_key": key}


def _event(stage: str, state: str, summary: str) -> dict[str, str]:
    from datetime import datetime, timezone
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "status": state,
        "summary": summary[:1000],
    }


def _public_job(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": str(row["job_id"]),
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "progress": row.get("progress") or [],
        "error": row.get("error"),
        "report": row.get("report"),
        "has_output": bool(row.get("output_key")),
    }


@app.get("/healthz")
def healthz():
    try:
        with database_connection() as conn:
            conn.execute("SELECT 1")
        required = ("HEYAA_CLOUD_API_TOKEN", "HEYAA_STORAGE_BUCKET", "HEYAA_STORAGE_ACCESS_KEY", "HEYAA_STORAGE_SECRET_KEY")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError("Missing configuration: " + ", ".join(missing))
        return {"status": "ok", "component": "heyaa-cloud-api"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cloud API is not ready: {exc}") from exc


@app.post("/v1/uploads")
def create_upload(request: UploadRequest, owner_key: str = Depends(authenticate)):
    suffix, max_bytes = _validate_upload(request)
    key = f"uploads/{owner_key}/{uuid4().hex}{suffix}"
    try:
        s3 = storage_client()
        post = s3.generate_presigned_post(
            Bucket=os.environ["HEYAA_STORAGE_BUCKET"],
            Key=key,
            Fields={"Content-Type": request.content_type.split(";", 1)[0].strip().lower()},
            Conditions=[
                {"Content-Type": request.content_type.split(";", 1)[0].strip().lower()},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=UPLOAD_TTL_SECONDS,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not create private upload authorization: {exc}") from exc
    return {
        "object_key": key,
        "method": "POST",
        "url": post["url"],
        "fields": post["fields"],
        "expires_in_seconds": UPLOAD_TTL_SECONDS,
        "max_bytes": max_bytes,
    }


@app.post("/v1/jobs", status_code=202)
def create_job(request: JobCreate, owner_key: str = Depends(authenticate)):
    try:
        s3 = storage_client()
        media = {
            "video": _validate_media(request.video, "video", owner_key, s3),
            "music": _validate_media(request.music, "music", owner_key, s3),
            "reference": _validate_media(request.reference, "reference", owner_key, s3)
            if request.reference else None,
        }
        job_id = uuid4()
        payload = {
            "media": media,
            "ai_upscale_enabled": request.ai_upscale_enabled,
            "layout_mode": request.layout_mode,
            "require_reference": request.reference is not None,
        }
        with database_connection() as conn:
            conn.execute(
                """
                INSERT INTO heyaa_cloud_jobs (job_id, owner_key, status, request, progress)
                VALUES (%s, %s, 'queued', %s::jsonb, %s::jsonb)
                """,
                (
                    job_id,
                    owner_key,
                    json.dumps(payload),
                    json.dumps([_event("job", "queued", "Job accepted and waiting for a render worker.")]),
                ),
            )
        return {"job_id": str(job_id), "status": "queued"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not queue render job: {exc}") from exc


@app.get("/v1/jobs")
def list_jobs(owner_key: str = Depends(authenticate)):
    with database_connection() as conn:
        rows = conn.execute(
            """
            SELECT job_id, status, progress, error, report, output_key, created_at, updated_at
            FROM heyaa_cloud_jobs
            WHERE owner_key = %s
            ORDER BY created_at DESC
            LIMIT 30
            """,
            (owner_key,),
        ).fetchall()
    return {"jobs": [_public_job(row) for row in rows]}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: UUID, owner_key: str = Depends(authenticate)):
    with database_connection() as conn:
        row = conn.execute(
            """
            SELECT job_id, status, progress, error, report, output_key, created_at, updated_at
            FROM heyaa_cloud_jobs WHERE job_id = %s AND owner_key = %s
            """,
            (job_id, owner_key),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _public_job(row)


@app.post("/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, owner_key: str = Depends(authenticate)):
    with database_connection() as conn:
        row = conn.execute(
            """
            UPDATE heyaa_cloud_jobs
            SET status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE 'cancel_requested' END,
                cancel_requested = TRUE,
                updated_at = NOW()
            WHERE job_id = %s AND owner_key = %s AND status IN ('queued', 'running')
            RETURNING job_id, status
            """,
            (job_id, owner_key),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Job was not found or is no longer cancellable.")
    return {"job_id": str(row["job_id"]), "status": row["status"]}


@app.post("/v1/jobs/{job_id}/approve")
def approve_job(job_id: UUID, owner_key: str = Depends(authenticate)):
    with database_connection() as conn:
        row = conn.execute(
            """
            UPDATE heyaa_cloud_jobs
            SET status = 'approved', updated_at = NOW(),
                progress = progress || %s::jsonb
            WHERE job_id = %s AND owner_key = %s AND status = 'ready_for_review'
            RETURNING job_id, status
            """,
            (json.dumps([_event("human_review", "approved", "User approved this render for download.")]), job_id, owner_key),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Only a render ready for human review can be approved.")
    return {"job_id": str(row["job_id"]), "status": row["status"]}


@app.get("/v1/jobs/{job_id}/download")
def download_job(job_id: UUID, owner_key: str = Depends(authenticate)):
    with database_connection() as conn:
        row = conn.execute(
            """
            SELECT status, output_key FROM heyaa_cloud_jobs
            WHERE job_id = %s AND owner_key = %s
            """,
            (job_id, owner_key),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found.")
    if row["status"] not in {"ready_for_review", "approved"} or not row.get("output_key"):
        raise HTTPException(status_code=409, detail="The render is not ready for review or download.")
    try:
        url = storage_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": os.environ["HEYAA_STORAGE_BUCKET"], "Key": row["output_key"]},
            ExpiresIn=DOWNLOAD_TTL_SECONDS,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not authorize private download: {exc}") from exc
    return {"url": url, "expires_in_seconds": DOWNLOAD_TTL_SECONDS}
