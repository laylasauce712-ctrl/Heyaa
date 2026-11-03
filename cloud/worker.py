"""Durable PostgreSQL queue consumer for isolated Heyaa renders.

Run one worker process per container. Each job gets a private workspace, so
project-relative input/output paths in the existing renderer cannot collide.
"""
from __future__ import annotations

import json
import os
import selectors
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

import boto3
import psycopg
from psycopg.rows import dict_row

from src.heyaa.gpu import inspect_vulkan_hardware

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLL_SECONDS = float(os.environ.get("HEYAA_WORKER_POLL_SECONDS", "3"))
LEASE_SECONDS = 900
HEARTBEAT_SECONDS = 20
MAX_EVENTS = 250
MAX_LOG_CHARS = 24000


def db_connection():
    dsn = os.environ.get("HEYAA_DATABASE_URL")
    if not dsn:
        raise RuntimeError("HEYAA_DATABASE_URL is required by the render worker.")
    return psycopg.connect(dsn, row_factory=dict_row)


def s3_client():
    required = ("HEYAA_STORAGE_BUCKET", "HEYAA_STORAGE_ACCESS_KEY", "HEYAA_STORAGE_SECRET_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing object-storage configuration: " + ", ".join(missing))
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("HEYAA_STORAGE_ENDPOINT_URL") or None,
        region_name=os.environ.get("HEYAA_STORAGE_REGION", "auto"),
        aws_access_key_id=os.environ["HEYAA_STORAGE_ACCESS_KEY"],
        aws_secret_access_key=os.environ["HEYAA_STORAGE_SECRET_KEY"],
    )


def event(stage: str, state: str, summary: str) -> dict[str, str]:
    from datetime import datetime, timezone
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "status": state,
        "summary": summary[:1000],
    }


def record_event(job_id: UUID, stage: str, state: str, summary: str) -> None:
    item = event(stage, state, summary)
    with db_connection() as conn:
        row = conn.execute(
            "SELECT progress FROM heyaa_cloud_jobs WHERE job_id = %s",
            (job_id,),
        ).fetchone()
        if not row:
            return
        events = list(row.get("progress") or [])
        events.append(item)
        conn.execute(
            "UPDATE heyaa_cloud_jobs SET progress = %s::jsonb, updated_at = NOW() WHERE job_id = %s",
            (json.dumps(events[-MAX_EVENTS:]), job_id),
        )


def record_log(job_id: UUID, line: str) -> None:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT log_tail FROM heyaa_cloud_jobs WHERE job_id = %s",
            (job_id,),
        ).fetchone()
        if not row:
            return
        tail = (row.get("log_tail") or "") + line
        conn.execute(
            "UPDATE heyaa_cloud_jobs SET log_tail = %s, updated_at = NOW() WHERE job_id = %s",
            (tail[-MAX_LOG_CHARS:], job_id),
        )


def heartbeat(job_id: UUID, worker_id: str) -> None:
    with db_connection() as conn:
        conn.execute(
            """
            UPDATE heyaa_cloud_jobs
            SET lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                updated_at = NOW()
            WHERE job_id = %s AND worker_id = %s AND status IN ('running', 'cancel_requested')
            """,
            (LEASE_SECONDS, job_id, worker_id),
        )


def cancellation_requested(job_id: UUID) -> bool:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT cancel_requested FROM heyaa_cloud_jobs WHERE job_id = %s",
            (job_id,),
        ).fetchone()
    return bool(row and row["cancel_requested"])


def claim_next_job(worker_id: str) -> dict[str, Any] | None:
    with db_connection() as conn:
        row = conn.execute(
            """
            SELECT job_id, owner_key, request
            FROM heyaa_cloud_jobs
            WHERE status = 'queued'
               OR (status = 'running' AND lease_expires_at < NOW())
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        ).fetchone()
        if not row:
            return None
        conn.execute(
            """
            UPDATE heyaa_cloud_jobs
            SET status = 'running', worker_id = %s,
                lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                cancel_requested = FALSE, error = NULL, updated_at = NOW(),
                progress = progress || %s::jsonb
            WHERE job_id = %s
            """,
            (
                worker_id,
                LEASE_SECONDS,
                json.dumps([event("worker", "running", f"Render worker {worker_id} claimed the job.")]),
                row["job_id"],
            ),
        )
        return dict(row)


def finish_job(job_id: UUID, state: str, *, error: str | None = None,
               output_key: str | None = None, report_key: str | None = None,
               report: dict[str, Any] | None = None) -> None:
    with db_connection() as conn:
        conn.execute(
            """
            UPDATE heyaa_cloud_jobs
            SET status = %s, error = %s, output_key = %s, report_key = %s,
                report = %s::jsonb, lease_expires_at = NULL, updated_at = NOW(),
                progress = progress || %s::jsonb
            WHERE job_id = %s
            """,
            (
                state,
                error[:2000] if error else None,
                output_key,
                report_key,
                json.dumps(report) if report is not None else None,
                json.dumps([event("worker", state, error or {
                    "ready_for_review": "Render passed required technical gates and is ready for human review.",
                    "failed": "Render worker failed; see the job log for details.",
                    "cancelled": "Render was cancelled.",
                }.get(state, state))]),
                job_id,
            ),
        )


def _safe_workspace_file(workspace: Path, slot: str, object_key: str) -> Path:
    suffix = PurePosixPath(object_key).suffix.lower()
    allowed = {
        "video": {".mp4", ".mov", ".mkv", ".webm", ".m4v"},
        "reference": {".mp4", ".mov", ".mkv", ".webm", ".m4v"},
        "music": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"},
    }[slot]
    if suffix not in allowed:
        raise RuntimeError(f"Uploaded {slot} object has an unsupported extension.")
    return workspace / "input" / f"cloud_{slot}{suffix}"


def prepare_workspace(workspace: Path, payload: dict[str, Any], owner_key: str,
                      storage: Any) -> tuple[list[str], dict[str, Any]]:
    shutil.copytree(PROJECT_ROOT / "src", workspace / "src")
    shutil.copy2(PROJECT_ROOT / "params.json", workspace / "params.json")
    (workspace / "input").mkdir(parents=True, exist_ok=True)
    (workspace / "output").mkdir(parents=True, exist_ok=True)
    (workspace / "tools").mkdir(exist_ok=True)
    source_tools = PROJECT_ROOT / "tools" / "realesrgan"
    if source_tools.exists():
        os.symlink(source_tools, workspace / "tools" / "realesrgan", target_is_directory=True)

    config = json.loads((workspace / "params.json").read_text(encoding="utf-8"))
    config["edit_settings"]["layout_mode"] = payload.get("layout_mode", "fill")
    config["video_settings"]["ai_upscale_enabled"] = bool(payload.get("ai_upscale_enabled"))
    if config["video_settings"]["ai_upscale_enabled"]:
        if os.environ.get("HEYAA_ENABLE_AI_UPSCALE") != "1":
            raise RuntimeError("This worker is not configured to accept AI-upscaled jobs.")
        gpu = inspect_vulkan_hardware()
        if gpu.get("status") != "hardware_available":
            raise RuntimeError(
                "AI-upscaled job requires a hardware-backed Vulkan device on this worker; "
                + str(gpu.get("reason") or gpu.get("status"))
            )
        config["video_settings"]["ai_upscale_binary"] = os.environ.get(
            "HEYAA_REAL_ESRGAN_BINARY", "tools/realesrgan/realesrgan-ncnn-vulkan"
        )
        config["video_settings"]["ai_upscale_model_dir"] = os.environ.get(
            "HEYAA_REAL_ESRGAN_MODEL_DIR", "tools/realesrgan/models"
        )
    settings_path = workspace / "params.cloud.json"
    settings_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    media = payload["media"]
    paths = {
        "video": "input/cloud_video.mp4",
        "music": "input/cloud_music.mp3",
        "reference": "input/cloud_reference.mp4",
    }
    command = [sys.executable, "src/agent_director.py", "--edits", "1"]
    path_flags = {
        "video": "--video-path",
        "music": "--music-path",
        "reference": "--reference-path",
    }
    url_flags = {
        "video": "--video-url",
        "music": "--music-url",
        "reference": "--reference-url",
    }
    for slot in ("video", "music", "reference"):
        source = media.get(slot)
        if not source:
            if slot == "reference":
                command.extend([path_flags[slot], ""])
            continue
        if source["kind"] == "url":
            # The path argument is the worker-local download destination.
            command.extend([path_flags[slot], paths[slot], url_flags[slot], source["url"]])
        elif source["kind"] == "upload":
            destination = _safe_workspace_file(workspace, slot, source["object_key"])
            storage.download_file(
                os.environ["HEYAA_STORAGE_BUCKET"],
                source["object_key"],
                str(destination),
            )
            command.extend([path_flags[slot], str(destination.relative_to(workspace))])
        else:
            raise RuntimeError(f"Unsupported {slot} source type.")
    if media.get("reference"):
        command.append("--require-reference")
    return command, config


def _progress_from_line(job_id: UUID, line: str) -> None:
    """Convert the renderer's text progress line into a durable cloud event."""
    text = line.strip()
    if not text.startswith("[progress:"):
        return
    stage, separator, remainder = text[len("[progress:"):].partition("]")
    if not separator:
        return
    state, separator, summary = remainder.strip().partition(":")
    if not separator or not stage.strip() or not state.strip():
        return
    record_event(job_id, stage.strip(), state.strip(), summary.strip())


def run_renderer(job: dict[str, Any], worker_id: str, storage: Any) -> None:
    job_id = job["job_id"]
    owner_key = job["owner_key"]
    workspace_parent = Path(os.environ.get("HEYAA_WORK_ROOT", "/tmp/heyaa-cloud-jobs"))
    workspace_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{job_id}-", dir=workspace_parent) as temp:
        workspace = Path(temp)
        try:
            command, _config = prepare_workspace(workspace, job["request"], owner_key, storage)
            record_event(job_id, "worker_prepare", "completed", "Private job workspace and selected source files are ready.")
            env = os.environ.copy()
            env["HEYAA_PARAMS_PATH"] = str(workspace / "params.cloud.json")
            env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
            selector = selectors.DefaultSelector()
            assert process.stdout is not None
            selector.register(process.stdout, selectors.EVENT_READ)
            last_heartbeat = time.monotonic()
            terminating_for_cancel = False
            while selector.get_map() or process.poll() is None:
                for key, _mask in selector.select(timeout=5):
                    line = key.fileobj.readline()
                    if line:
                        record_log(job_id, line)
                        _progress_from_line(job_id, line)
                    else:
                        selector.unregister(key.fileobj)
                now = time.monotonic()
                if now - last_heartbeat >= HEARTBEAT_SECONDS:
                    heartbeat(job_id, worker_id)
                    last_heartbeat = now
                if not terminating_for_cancel and cancellation_requested(job_id):
                    terminating_for_cancel = True
                    record_event(job_id, "worker_cancel", "running", "Cancellation requested; stopping the render process tree.")
                    try:
                        os.killpg(process.pid, signal.SIGINT)
                    except ProcessLookupError:
                        pass
            return_code = process.wait()
            if terminating_for_cancel:
                finish_job(job_id, "cancelled", error="Cancelled by user.")
                return
            if return_code != 0:
                raise RuntimeError(f"Renderer exited with code {return_code}.")
            outputs = sorted(
                (workspace / "output" / "runs").rglob("final_phonk_20s.mp4"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not outputs:
                raise RuntimeError("Renderer exited successfully but no final_phonk_20s.mp4 was created.")
            video_path = outputs[0]
            report_path = video_path.parent / "agent_report.json"
            if not report_path.is_file():
                raise RuntimeError("Final render has no Agent Report; it cannot be marked ready for review.")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report.get("status") != "ready_for_human_review":
                raise RuntimeError(
                    "The render did not pass the required Director gates: "
                    + str(report.get("status") or "unknown report status")
                )
            output_key = f"outputs/{owner_key}/{job_id}/final_phonk_20s.mp4"
            report_key = f"outputs/{owner_key}/{job_id}/agent_report.json"
            bucket = os.environ["HEYAA_STORAGE_BUCKET"]
            storage.upload_file(str(video_path), bucket, output_key, ExtraArgs={"ContentType": "video/mp4"})
            storage.upload_file(str(report_path), bucket, report_key, ExtraArgs={"ContentType": "application/json"})
            finish_job(
                job_id,
                "ready_for_review",
                output_key=output_key,
                report_key=report_key,
                report=report,
            )
        except Exception as exc:
            finish_job(job_id, "failed", error=str(exc))
            record_log(job_id, f"\\n[worker error] {exc}\\n")


def main() -> int:
    worker_id = os.environ.get("HEYAA_WORKER_ID") or f"{socket.gethostname()}-{os.getpid()}"
    print(f"[cloud-worker] {worker_id} online; polling for jobs", flush=True)
    while True:
        job = claim_next_job(worker_id)
        if not job:
            time.sleep(POLL_SECONDS)
            continue
        job_id = job["job_id"]
        print(f"[cloud-worker] claimed job {job_id}", flush=True)
        try:
            run_renderer(job, worker_id, s3_client())
        except Exception as exc:
            finish_job(job_id, "failed", error=str(exc))
            print(f"[cloud-worker] job {job_id} failed: {exc}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
