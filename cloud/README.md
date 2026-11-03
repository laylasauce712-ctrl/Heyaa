# Heyaa Cloud stack (development foundation)

This is a local Docker Compose development stack for the first cloud control-plane/worker implementation. It is **not a public deployment** and does not yet provide end-user sign-in or a hosted phone UI.

## Architecture in this slice

- FastAPI control plane: authenticated job creation, private presigned uploads, status/events, cancellation, preview, explicit approval and approved-download URLs.
- PostgreSQL: durable job state, event summaries, worker lease and render report.
- MinIO: private S3-compatible local object storage for uploaded source media and final outputs.
- Worker: runs as an unprivileged user in a read-only container with a bounded writable scratch mount; each job gets its own isolated render workspace, reusing the existing Heyaa renderer. It claims jobs with `FOR UPDATE SKIP LOCKED`, streams actual renderer progress into job events, heartbeats its lease, supports cancellation and promotes only reports with status `ready_for_human_review`.
- AI restoration defaults off. A worker accepts AI restoration only when explicitly enabled and its default Vulkan device is hardware-backed.

## Local setup

From the repository root:

```bash
cp cloud/.env.example cloud/.env
# Edit cloud/.env: set a unique random HEYAA_CLOUD_API_TOKEN and local-only passwords.
docker compose --env-file cloud/.env -f cloud/compose.yaml up --build
```

API: http://localhost:8080
Health: http://localhost:8080/healthz
OpenAPI: http://localhost:8080/docs
MinIO S3 endpoint: http://localhost:9000
MinIO console: http://localhost:9001

The API and MinIO ports bind to `127.0.0.1` by default. For deliberate LAN testing,
set `HEYAA_API_BIND_ADDRESS=0.0.0.0` and
`HEYAA_STORAGE_BIND_ADDRESS=0.0.0.0`, then set
`HEYAA_STORAGE_PUBLIC_ENDPOINT_URL` to the laptop's reachable LAN address
(for example `http://192.168.1.20:9000`). Allow only the phone-facing web
origin in both `HEYAA_ALLOWED_ORIGINS` and `cloud/minio-cors.xml`, and use the
Windows firewall to restrict access. The current web UI is not deployed yet;
these settings prepare the storage endpoint for the future browser client.

The responsive Studio is served at the API root. It asks for the bearer token each session and keeps it in page memory only (not localStorage or a cookie). The API uses one shared bearer token in this first private-beta slice. This is a single-tenant/developer credential, not a complete user-account system. Compose injects this token into the API only; it is not passed to the render worker. Do not distribute it to other users or expose this stack to the internet; production requires real account authentication/OIDC.

## API flow

1. Call `POST /v1/uploads` with bearer auth and JSON containing `slot`, `filename`, `content_type`, and `size_bytes`.
2. Upload the bytes directly to the returned presigned POST URL using every returned form field. The API does not proxy media bytes.
3. Call `POST /v1/jobs` with the returned `object_key` for video/music and optional reference, or validated YouTube/TikTok URLs.
4. Poll `GET /v1/jobs/{job_id}` for status and recorded Agent Room progress.
5. When status becomes `ready_for_review`, call `GET /v1/jobs/{job_id}/preview` to inspect the finished render.
6. Call `POST /v1/jobs/{job_id}/approve` only after human review.
7. Call `GET /v1/jobs/{job_id}/download` for a short-lived private download URL after approval.

All job and upload object keys are scoped to the same bearer-token owner. The first release supports one job per worker process and one edit per job. Limits, retention and authentication need further hardening before a multi-user/public launch.

## GPU worker configuration

The default local Compose stack sets `HEYAA_ENABLE_AI_UPSCALE=0`. Do not enable it on CPU-only Vulkan (llvmpipe/lavapipe). A real cloud GPU worker must have its host driver/device exposed to the container, the Real-ESRGAN model files, and a successful `vulkaninfo --summary` preflight. The ncnn-vulkan binary is installed in the worker image, but its presence alone does not mean hardware acceleration is available.

## Current limitations

- The API token is a single-tenant bootstrap credential; add real user authentication/OIDC before sharing with others.
- No public hosting, domain, TLS, database service, or cloud object bucket is provisioned by this repository.
- The first responsive phone UI is served by the cloud API and supports upload/link submission, job status, Agent Room events, preview, explicit approval and approved downloads. It is still a private-beta client using a manually entered shared token; production sign-in/OIDC and multi-user identity are not implemented.
- URL inputs are restricted to validated YouTube/TikTok posts. Arbitrary direct URLs are not accepted by the cloud API; any later direct URL feature must enforce a robust SSRF policy.
- The API never auto-approves or publishes a render.
