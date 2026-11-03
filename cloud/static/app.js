(() => {
  let authToken = "";
  let selectedJob = "";
  let pollHandle = null;
  const $ = (id) => document.getElementById(id);
  const notice = $("notice");
  function showNotice(message, type="error") {
    notice.textContent = message;
    notice.className = "notice " + type;
  }
  function clearNotice() { notice.textContent = ""; notice.className = "notice"; }
  async function api(path, options={}) {
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", "Bearer " + authToken);
    if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
    const response = await fetch(path, {...options, headers});
    const text = await response.text();
    let body = {};
    try { body = text ? JSON.parse(text) : {}; } catch (_) { body = {detail:text}; }
    if (!response.ok) throw new Error(body.detail || ("Request failed: " + response.status));
    return body;
  }
  function setBusy(busy, label) {
    $("createJob").disabled = busy;
    $("createJob").textContent = busy ? (label || "Working…") : "Create edit →";
  }
  function extMime(file, slot) {
    const ext = file.name.split(".").pop().toLowerCase();
    const map = {
      mp4:"video/mp4",mov:"video/quicktime",mkv:"video/x-matroska",webm:"video/webm",m4v:"video/x-m4v",
      mp3:"audio/mpeg",wav:"audio/wav",m4a:"audio/mp4",aac:"audio/aac",flac:"audio/flac",ogg:"audio/ogg",opus:"audio/opus"
    };
    return map[ext] || file.type || (slot === "music" ? "audio/mpeg" : "video/mp4");
  }
  function xhrUpload(url, fields, file, onProgress) {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      Object.entries(fields || {}).forEach(([key,value]) => form.append(key, value));
      form.append("file", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100));
      };
      xhr.onload = () => xhr.status >= 200 && xhr.status < 300
        ? resolve() : reject(new Error("Private storage upload failed (" + xhr.status + ")."));
      xhr.onerror = () => reject(new Error("Network error while uploading to private storage."));
      xhr.send(form);
    });
  }
  async function mediaSource(slot, fileInput, urlInput, label) {
    const file = $(fileInput).files[0];
    const url = $(urlInput).value.trim();
    if (file && url) throw new Error("Choose either a file or a link for " + label + ", not both.");
    if (!file && !url) {
      if (slot === "reference") return null;
      throw new Error("Choose a source video and music track before creating an edit.");
    }
    if (url) return {url};
    $("uploadProgress").textContent = "Preparing secure " + label + " upload…";
    const contentType = extMime(file, slot);
    const sign = await api("/v1/uploads", {
      method:"POST",
      body:JSON.stringify({slot, filename:file.name, content_type:contentType, size_bytes:file.size})
    });
    await xhrUpload(sign.url, sign.fields, file, (pct) => {
      $("uploadProgress").textContent = "Uploading " + label + " · " + pct + "%";
      $("uploadBar").style.width = pct + "%";
    });
    return {object_key:sign.object_key};
  }
  function statusBadge(status) {
    const span = document.createElement("span");
    span.className = "status " + status;
    span.textContent = (status || "unknown").replaceAll("_"," ");
    return span;
  }
  function renderJobs(jobs) {
    const root = $("jobs"); root.replaceChildren();
    if (!jobs.length) { root.textContent = "No jobs yet."; return; }
    jobs.forEach(job => {
      const row = document.createElement("div"); row.className = "jobrow";
      const left = document.createElement("div");
      const id = document.createElement("strong"); id.textContent = job.job_id.slice(0,8);
      const small = document.createElement("small"); small.textContent = job.created_at ? new Date(job.created_at).toLocaleString() : "";
      left.append(id,small);
      const right = statusBadge(job.status);
      const button = document.createElement("button"); button.className = "secondary"; button.textContent = "Open";
      button.addEventListener("click", () => selectJob(job.job_id));
      row.append(left,right,button); root.append(row);
    });
  }
  async function loadJobs() {
    const data = await api("/v1/jobs");
    renderJobs(data.jobs || []);
  }
  function renderEvents(events) {
    const root = $("events"); root.replaceChildren();
    if (!events || !events.length) { root.textContent = "No pipeline events yet."; return; }
    events.slice(-50).reverse().forEach(item => {
      const row = document.createElement("div"); row.className = "event";
      const top = document.createElement("div"); top.className = "eventtop";
      const stage = document.createElement("strong"); stage.textContent = (item.stage || "event") + " · " + (item.status || "");
      const time = document.createElement("span"); time.textContent = item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : "";
      const summary = document.createElement("p"); summary.textContent = item.summary || "";
      top.append(stage,time); row.append(top,summary); root.append(row);
    });
  }
  async function selectJob(jobId) {
    selectedJob = jobId;
    const job = await api("/v1/jobs/" + encodeURIComponent(jobId));
    $("jobSummary").replaceChildren(statusBadge(job.status));
    const description = document.createElement("p"); description.className = "hint";
    description.textContent = "Job " + job.job_id + (job.error ? " · " + job.error : "");
    $("jobSummary").append(description);
    renderEvents(job.progress || []);
    $("logTail").textContent = job.log_tail || "No render log yet.";
    $("previewArea").replaceChildren(); $("jobActions").replaceChildren();
    if (job.status === "ready_for_review" || job.status === "approved") {
      const preview = await api("/v1/jobs/" + encodeURIComponent(jobId) + "/preview");
      const video = document.createElement("video"); video.className = "video"; video.controls = true; video.playsInline = true; video.preload = "metadata"; video.src = preview.url;
      $("previewArea").append(video);
    }
    if (job.status === "ready_for_review") {
      const approve = document.createElement("button"); approve.textContent = "Approve this render";
      approve.addEventListener("click", async () => {
        approve.disabled = true;
        try { await api("/v1/jobs/" + encodeURIComponent(jobId) + "/approve", {method:"POST"}); await selectJob(jobId); await loadJobs(); showNotice("Render approved. Download is now available.","ok"); }
        catch (error) { showNotice(error.message); approve.disabled = false; }
      });
      $("jobActions").append(approve);
    }
    if (job.status === "approved") {
      const download = document.createElement("button"); download.textContent = "Download final video";
      download.addEventListener("click", async () => {
        download.disabled = true;
        try { const result = await api("/v1/jobs/" + encodeURIComponent(jobId) + "/download"); window.location.href = result.url; }
        catch (error) { showNotice(error.message); download.disabled = false; }
      });
      $("jobActions").append(download);
    }
    if (job.status === "queued" || job.status === "running" || job.status === "cancel_requested") {
      const cancel = document.createElement("button"); cancel.className = "danger"; cancel.textContent = "Cancel job";
      cancel.addEventListener("click", async () => { try { await api("/v1/jobs/" + encodeURIComponent(jobId) + "/cancel",{method:"POST"}); await selectJob(jobId); } catch(e) { showNotice(e.message); } });
      $("jobActions").append(cancel);
    }
    if (["queued","running","cancel_requested"].includes(job.status)) schedulePoll();
    else if (pollHandle) { clearTimeout(pollHandle); pollHandle = null; }
  }
  function schedulePoll() {
    if (pollHandle) clearTimeout(pollHandle);
    pollHandle = setTimeout(async () => {
      if (!selectedJob) return;
      try { await selectJob(selectedJob); await loadJobs(); }
      catch(error) { showNotice(error.message); }
    }, 3500);
  }
  $("connect").addEventListener("click", async () => {
    const value = $("token").value.trim();
    if (!value) { showNotice("Paste your private API token to connect."); return; }
    authToken = value;
    $("connect").disabled = true;
    try {
      const capabilities = await api("/v1/capabilities");
      $("aiUpscale").disabled = !capabilities.ai_upscale_enabled;
      $("aiHint").textContent = capabilities.ai_upscale_enabled
        ? "AI requests are enabled by the operator; the worker still verifies its hardware-backed Vulkan device before processing."
        : "AI Restore is disabled on this deployment. A GPU worker and operator enablement are required.";
      await loadJobs();
      $("token").value = "";
      $("login").style.display = "none";
      $("workspace").style.display = "block";
      clearNotice();
    } catch(error) {
      authToken = "";
      showNotice(error.message);
    } finally { $("connect").disabled = false; }
  });
  $("jobForm").addEventListener("submit", async (event) => {
    event.preventDefault(); clearNotice(); setBusy(true,"Preparing uploads…"); $("uploadBar").style.width="0%";
    try {
      const video = await mediaSource("video","videoFile","videoUrl","source video");
      const music = await mediaSource("music","musicFile","musicUrl","music");
      const reference = await mediaSource("reference","referenceFile","referenceUrl","reference");
      $("uploadProgress").textContent = "Queueing render job…";
      const job = await api("/v1/jobs",{
        method:"POST",
        body:JSON.stringify({video,music,reference,layout_mode:$("layout").value,ai_upscale_enabled:$("aiUpscale").checked})
      });
      selectedJob = job.job_id;
      await loadJobs(); await selectJob(job.job_id);
      $("uploadProgress").textContent = "Job queued. Follow the Agent Room for live progress.";
      showNotice("Your render job was queued successfully.","ok");
    } catch(error) { showNotice(error.message); }
    finally { setBusy(false); }
  });
  $("refreshJobs").addEventListener("click", async () => { try { await loadJobs(); if(selectedJob) await selectJob(selectedJob); } catch(e) { showNotice(e.message); } });
  $("logout").addEventListener("click", () => {
    authToken = ""; selectedJob = "";
    if (pollHandle) clearTimeout(pollHandle); pollHandle = null;
    $("workspace").style.display = "none"; $("login").style.display = "block";
    $("jobs").replaceChildren(); $("events").replaceChildren(); $("previewArea").replaceChildren();
    showNotice("Disconnected. The access token was cleared from page memory.","ok");
  });
})();
