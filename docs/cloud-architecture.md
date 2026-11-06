# Heyaa cloud architecture and deployment plan

Status: first cloud foundation implemented on `feat/cloud-studio-foundation`; local Compose stack and responsive private-beta client are in place. No public hosting, managed database, cloud bucket or GPU worker fleet has been provisioned.

## Current verified architecture

- GitHub stores the source code and runs GitHub Actions for automated tests.
- The current Studio is a local Python HTTP server. It binds to 127.0.0.1:8765, reads local input/ files, starts the existing FFmpeg renderer, and writes to local output/.
- GitHub Actions is not a persistent render server and does not keep a GPU worker available for user jobs.
- The original developer Studio remains local-only. A separate cloud API now serves a responsive phone-first Studio from the API origin; it is still a local/private-beta Compose stack, not a public deployment.
- Real-ESRGAN asset checks previously proved only that the executable and model files existed. They did not prove a hardware-backed Vulkan device was available. AI preflight now distinguishes hardware Vulkan from CPU software drivers and blocks the known llvmpipe failure by default. It also refuses a mixed device list when llvmpipe is the first/default device and a hardware GPU appears only later, because the current renderer does not explicitly select a Vulkan device index.

## Target phone-first architecture

1. **Web client:** responsive Studio UI served over HTTPS. A phone uploads/selects media, configures an edit and watches job progress. No renderer or model runs on the phone.
2. **Control-plane API:** authenticated job creation, upload authorization, job status/events, cancellation, review and approved-download endpoints. It never performs video encoding inside an HTTP request.
3. **Durable job database/queue:** PostgreSQL stores job ownership, state, lease, settings, event summaries and output references. Workers claim jobs transactionally so two workers cannot take the same queued job.
4. **Private object storage:** S3-compatible storage (Cloudflare R2 or another compatible provider) stores user uploads and render outputs. The API issues short-lived, scoped upload/download URLs; media bytes do not pass through the API process.
5. **Render workers:** isolated containers run the existing Heyaa renderer, FFmpeg, yt-dlp and optional Real-ESRGAN. One render job per worker process/container initially, because the current renderer uses project-relative input/output workspaces.
6. **GPU worker pool:** GPU-backed workers are a separate capability. AI restoration is enabled only when the worker proves a hardware-backed Vulkan device is visible. CPU-only workers can run the non-AI path; they must not claim AI restoration succeeded.
7. **GitHub Actions:** tests, container builds and controlled deployment automation only. It is not the runtime queue, database or media store.

## Security and reliability requirements

- Require authenticated API access. The current private-beta page asks the operator to enter a shared bearer token and holds it only in page memory; this is a development bootstrap, not production user authentication. Production must replace it with per-user OIDC/session auth and must not embed a service token in browser assets.
- Scope every job and object key to an authenticated owner. A job ID alone is not authorization.
- Use short-lived presigned object URLs and enforce slot-specific file extensions, content types and size limits before job submission.
- Accept platform URLs only through the existing YouTube/TikTok validation path. Do not let the cloud worker fetch arbitrary private-network URLs; direct URL downloads need an explicit public-host/SSRF policy.
- Keep uploads, temporary source downloads, scratch frames and exports private. Apply lifecycle cleanup to abandoned uploads and completed job scratch data.
- Persist progress events and worker leases. A crashed worker must not leave a job permanently marked running.
- Never automatically publish a render. Technical QA makes an output ready for human review; approval remains explicit.
- Redact credentials and signed URLs from logs.
- Apply per-user concurrency, duration, file-size and retention limits before enabling public access.

## Delivery phases

### Phase 0 — safety and architecture
- Confirm the local-vs-cloud boundary.
- Detect hardware-backed Vulkan before AI processing, preventing the observed 600-second llvmpipe timeout.
- Keep the local Studio and renderer working while the cloud path is developed independently.

### Phase 1 — cloud control plane (implemented foundation)
- FastAPI container, health check, shared private-beta bearer auth, strict upload/URL validation and durable job contract.
- PostgreSQL-backed job claiming/status/events and S3-compatible presigned upload/download support.
- API tests cover authentication, owner-scoped object keys, upload metadata and URL constraints.
- Remaining before public beta: real user identity/OIDC, rate limits, per-user quota/concurrency and retention policies.

### Phase 2 — isolated render worker (implemented foundation)
- Package the existing renderer, FFmpeg and yt-dlp in a worker image.
- Pull only selected job assets into a temporary isolated workspace.
- Report renderer progress events and a bounded log tail to the job record; maintain a worker lease and support cancellation.
- Upload a technically approved render and Agent Report to private storage; expose it as ready for human review, not automatically approved.
- AI is off by default and requires a hardware-backed Vulkan worker. Container build/runtime GPU passthrough still needs host-specific verification.

### Phase 3 — phone-first UI (first slice implemented)
- Responsive client is served by the cloud API and uses the same-origin API.
- It supports private file uploads, YouTube/TikTok links, job list/status, Agent Room events, render-log inspection, preview, explicit approval and approved download.
- The client clears its shared development token on refresh; production per-user sign-in/session auth and multi-user isolation remain future work.
- Preserve local mode as a developer/testing option.

### Phase 4 — hosting and release
- Select a control-plane host, PostgreSQL service, private S3-compatible bucket and GPU-capable worker host.
- Configure secrets, CORS/origin allowlist, TLS, resource limits, cost alerts and retention.
- Deploy from a protected non-main branch, then verify a real phone upload and a real cloud render before calling the product cloud-ready.

## Deployment boundary

A cloud service cannot be activated by pushing code to GitHub alone. It requires a selected hosting account, object-storage credentials, database provisioning and deployment secrets. Keep the implementation provider-neutral until those resources are selected; do not commit credentials or use a public demo bucket.
