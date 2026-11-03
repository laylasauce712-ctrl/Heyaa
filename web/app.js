const $ = (selector) => document.querySelector(selector);
const els = {
  source: $("#source-select"), music: $("#music-select"), reference: $("#reference-select"),
  sourceMeta: $("#source-meta"), musicMeta: $("#music-meta"), referenceMeta: $("#reference-meta"),
  videoUrl: $("#video-url"), musicUrl: $("#music-url"), referenceUrl: $("#reference-url"),
  edits: $("#edits-select"), clips: $("#clips-select"), duration: $("#duration-select"),
  speed: $("#speed-range"), speedValue: $("#speed-value"), layout: [...document.querySelectorAll("[data-layout]")],
  ai: $("#ai-upscale"), subject: $("#subject-lock"), beat: $("#beat-sync"), skull: $("#ending-skull"),
  referencePacing: $("#reference-pacing"), mirror: $("#mirror"), flash: $("#beat-flash"),
  bass: $("#bass-boost"), loop: $("#music-loop"), sfx: $("#impact-sfx"),
  settingsNote: $("#settings-save-note"), statePill: $("#run-state"),
  monitorTitle: $("#monitor-title"), monitorDescription: $("#monitor-description"),
  progressFill: $("#progress-fill"), progressStage: $("#progress-stage"), progressCount: $("#progress-count"),
  events: $("#agent-events"), outputs: $("#output-list"), outputCount: $("#output-count"),
  sheetWrap: $("#contact-sheet-wrap"), aiStatus: $("#ai-status"),
  render: $("#render-button"), preview: $("#preview-button"),
};
let currentState = null;
let selectedLayout = "blur_fit";
let busy = false;
let expandedEvents = false;
let toastTimer = null;

const icons = {
  download: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/></svg>',
  approve: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>',
  alert: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9v4m0 4h.01"/><path d="M10.3 3.9 2.9 17a2 2 0 0 0 1.7 3h14.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>',
  check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>',
  film: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4m-4 8h4m10-8h4m-4 8h4"/></svg>',
  dots: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>',
};

function toast(message, type = "info") {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast visible ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("visible"), 3600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: { ...(options.headers || {}) },
  });
  const type = response.headers.get("content-type") || "";
  const result = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(result?.error || `Request failed (${response.status})`);
  return result;
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index++;
  }
  return `${value.toFixed(1)} ${units[index]}`;
}

function fillMediaSelect(select, slot, media, selectedPath = "") {
  const files = media.filter((file) => file.slot === slot);
  select.replaceChildren();
  if (slot === "reference") {
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "No reference selected";
    select.append(none);
  }
  for (const file of files) {
    const option = document.createElement("option");
    option.value = file.path;
    option.textContent = file.name;
    select.append(option);
  }
  if (selectedPath && files.some((file) => file.path === selectedPath)) {
    select.value = selectedPath;
  } else if (slot !== "reference") {
    const conventional = slot === "video" ? "input/test_video.mp4" : "input/phonk.mp3";
    select.value = files.some((file) => file.path === conventional)
      ? conventional
      : (files[0]?.path || "");
  } else {
    select.value = files.some((file) => file.path === "input/reference.mp4")
      ? "input/reference.mp4" : "";
  }
  return files.find((file) => file.path === select.value) || null;
}

function updateMediaMeta() {
  const findFile = (path) => currentState?.media?.find((file) => file.path === path);
  const source = findFile(els.source.value);
  const music = findFile(els.music.value);
  const reference = findFile(els.reference.value);
  els.sourceMeta.textContent = source ? `${source.size_label} · local input` : "Choose a source file or paste a source URL below.";
  els.musicMeta.textContent = music ? `${music.size_label} · local soundtrack` : "Choose a soundtrack or paste a music URL below.";
  els.referenceMeta.textContent = reference ? `${reference.size_label} · pacing reference` : "Optional · no selected local reference.";
}

function applySettings(config) {
  const edit = config.edit_settings || {};
  const audio = config.audio_settings || {};
  const video = config.video_settings || {};
  els.duration.value = String(edit.duration_seconds ?? 20);
  els.speed.value = String(edit.speed ?? 1.1);
  els.speedValue.textContent = `${Number(els.speed.value).toFixed(2)}×`;
  selectedLayout = edit.layout_mode || "blur_fit";
  els.layout.forEach((button) => button.classList.toggle("active", button.dataset.layout === selectedLayout));
  els.ai.checked = video.ai_upscale_enabled === true;
  els.subject.checked = edit.subject_lock_enabled === true;
  els.beat.checked = audio.beat_sync === true;
  els.skull.checked = edit.ending_skull_enabled === true;
  els.referencePacing.checked = edit.reference_pacing === true;
  els.mirror.checked = edit.mirror_enabled === true;
  els.flash.checked = audio.beat_flash === true;
  els.bass.checked = audio.bass_boost === true;
  els.loop.checked = audio.music_loop === true;
  els.sfx.checked = edit.impact_sfx_enabled === true;
  els.aiStatus.textContent = currentState?.ai_upscale?.available
    ? `${currentState.ai_upscale.model} ×${currentState.ai_upscale.scale} · installed`
    : "Real-ESRGAN assets not detected";
  $("#settings-file-label").textContent = currentState?.settings_file || "params.json";
  if (currentState?.settings_file === "params.local.json") {
    els.settingsNote.textContent = "Using this PC’s local settings profile.";
  } else {
    els.settingsNote.textContent = "Changes save to params.local.json, never to tracked params.json.";
  }
}

function settingsPayload() {
  return {
    edit_settings: {
      duration_seconds: Number(els.duration.value),
      speed: Number(els.speed.value),
      layout_mode: selectedLayout,
      mirror_enabled: els.mirror.checked,
      reference_pacing: els.referencePacing.checked,
      subject_lock_enabled: els.subject.checked,
      ending_skull_enabled: els.skull.checked,
      impact_sfx_enabled: els.sfx.checked,
    },
    audio_settings: {
      beat_sync: els.beat.checked,
      beat_flash: els.flash.checked,
      bass_boost: els.bass.checked,
      music_loop: els.loop.checked,
    },
    video_settings: { ai_upscale_enabled: els.ai.checked },
  };
}

function bindDirtyState() {
  document.querySelectorAll(".setup-panel input, .setup-panel select").forEach((control) => {
    control.addEventListener("change", () => {
      els.settingsNote.textContent = "Unsaved option changes · they save with your next render.";
      els.settingsNote.classList.add("dirty");
    });
  });
  els.speed.addEventListener("input", () => {
    els.speedValue.textContent = `${Number(els.speed.value).toFixed(2)}×`;
  });
  els.layout.forEach((button) => {
    button.addEventListener("click", () => {
      selectedLayout = button.dataset.layout;
      els.layout.forEach((item) => item.classList.toggle("active", item === button));
      els.settingsNote.textContent = "Unsaved option changes · they save with your next render.";
      els.settingsNote.classList.add("dirty");
    });
  });
  [els.source, els.music, els.reference].forEach((select) => select.addEventListener("change", updateMediaMeta));
}

async function refreshState({ quiet = true } = {}) {
  try {
    const state = await api("/api/state");
    currentState = state;
    const oldSource = els.source.value;
    const oldMusic = els.music.value;
    const oldReference = els.reference.value;
    const source = fillMediaSelect(els.source, "video", state.media || [], oldSource);
    const music = fillMediaSelect(els.music, "music", state.media || [], oldMusic);
    const reference = fillMediaSelect(els.reference, "reference", state.media || [], oldReference);
    if (!currentState._initialized) {
      currentState._initialized = true;
      applySettings(state.settings || {});
    }
    if (!source && !els.source.value) els.sourceMeta.textContent = "No source file found · upload one or use a URL.";
    if (!music && !els.music.value) els.musicMeta.textContent = "No soundtrack found · upload one or use a URL.";
    updateMediaMeta();
    renderRunState(state);
    renderAgentEvents(state.events || []);
    renderOutputs(state);
    els.render.disabled = state.running;
    els.preview.disabled = state.running;
    if (state.running) {
      els.render.innerHTML = '<span class="spinner-mini"></span> Rendering…';
    } else {
      els.render.innerHTML = '<span class="button-spark">✦</span> Start render <span class="button-arrow">→</span>';
    }
  } catch (error) {
    if (!quiet) toast(error.message, "error");
    $("#monitor-title").textContent = "Studio offline";
    $("#monitor-description").textContent = error.message;
    $("#monitor-footer-text").textContent = "Could not reach the local renderer server";
    els.statePill.className = "state-pill state-error";
    els.statePill.innerHTML = "<i></i> OFFLINE";
  }
}

function renderRunState(state) {
  if (state.running) {
    els.statePill.className = "state-pill state-running";
    els.statePill.innerHTML = "<i></i> RENDERING";
    els.monitorTitle.textContent = "Pipeline is running";
    els.monitorDescription.textContent = "Follow each measured stage and renderer event below.";
    els.monitorFooterText = undefined;
    $("#monitor-footer-text").textContent = `Process ${state.process_id || ""} · started ${new Date(state.started_at).toLocaleTimeString()}`;
  } else if (state.exit_code !== null && state.exit_code !== undefined) {
    const ok = state.exit_code === 0;
    els.statePill.className = `state-pill ${ok ? "state-success" : "state-error"}`;
    els.statePill.innerHTML = `<i></i> ${ok ? "COMPLETED" : "CHECK RUN"}`;
    els.monitorTitle.textContent = ok ? "Render process finished" : "Render needs attention";
    els.monitorDescription.textContent = ok
      ? "Review the video below before approving it as a local release."
      : "Open the latest run events and report to see what blocked the render.";
    $("#monitor-footer-text").textContent = ok ? "Human visual review is still required." : `Process exit code ${state.exit_code}`;
  } else if (state.latest_run) {
    els.statePill.className = "state-pill state-idle";
    els.statePill.innerHTML = "<i></i> READY";
    els.monitorTitle.textContent = "Latest run is ready to review";
    els.monitorDescription.textContent = "Technical checks do not replace visual approval.";
    $("#monitor-footer-text").textContent = state.latest_run;
  } else {
    els.statePill.className = "state-pill state-idle";
    els.statePill.innerHTML = "<i></i> IDLE";
    els.monitorTitle.textContent = "Ready when you are";
    els.monitorDescription.textContent = "Choose your media and start a render. Real pipeline events appear here.";
    $("#monitor-footer-text").textContent = "Connected to local Heyaa process";
  }
  const events = state.events || [];
  const done = events.filter((event) => ["completed", "success", "ok"].includes(event.status)).length;
  const percent = state.running ? Math.min(92, Math.max(6, done * 7)) : (events.length ? 100 : 0);
  els.progressFill.style.width = `${percent}%`;
  els.progressStage.textContent = events.length ? (events[events.length - 1].stage || "PIPELINE EVENT").replaceAll("_", " ").toUpperCase() : "WAITING FOR RUN";
  els.progressCount.textContent = `${events.length} EVENTS`;
}

function stageLabel(stage) {
  const key = String(stage || "").replace(/^agent:/, "").replaceAll("_", " ");
  return key.replace(/w/g, (letter) => letter.toUpperCase());
}

function statusLabel(status) {
  const map = {
    completed: "DONE", success: "DONE", ok: "OK", running: "LIVE",
    needs_review: "REVIEW", blocked: "BLOCKED", error: "ERROR",
    fallback: "FALLBACK", skipped: "SKIPPED", cancelled: "STOPPED",
  };
  return map[status] || String(status || "INFO").toUpperCase();
}

function renderAgentEvents(events) {
  els.events.replaceChildren();
  if (!events.length) {
    const empty = document.createElement("div");
    empty.className = "empty-events";
    empty.innerHTML = '<span>✦</span><p>Your agents’ recorded activity will show here.</p>';
    els.events.append(empty);
    return;
  }
  const list = expandedEvents ? events : events.slice(-8);
  for (const item of list.slice().reverse()) {
    const row = document.createElement("article");
    row.className = "event-row";
    const marker = document.createElement("span");
    marker.className = `event-marker ${String(item.status || "info").replace(/[^a-z_]/g, "")}`;
    const copy = document.createElement("div");
    copy.className = "event-copy";
    const title = document.createElement("strong");
    title.textContent = stageLabel(item.stage);
    const summary = document.createElement("p");
    summary.textContent = item.summary || "";
    const time = document.createElement("small");
    time.textContent = item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : "";
    copy.append(title, summary, time);
    const pill = document.createElement("span");
    pill.className = `event-status ${String(item.status || "").replace(/[^a-z_]/g, "")}`;
    pill.textContent = statusLabel(item.status);
    row.append(marker, copy, pill);
    els.events.append(row);
  }
  $("#show-more-events").textContent = expandedEvents ? "Show latest" : "View all";
}

function renderOutputs(state) {
  const outputs = state.outputs || [];
  els.outputs.replaceChildren();
  els.outputCount.textContent = outputs.length ? `${outputs.length} RENDER${outputs.length === 1 ? "" : "S"}` : "NO EXPORTS YET";
  if (!outputs.length) {
    const empty = document.createElement("div");
    empty.className = "empty-outputs";
    empty.textContent = "No completed renders yet. Your latest exports will appear here.";
    els.outputs.append(empty);
  }
  for (const output of outputs.slice(0, 8)) {
    const card = document.createElement("article");
    card.className = "output-card";
    const info = document.createElement("div");
    info.className = "output-info";
    const title = document.createElement("strong");
    title.textContent = output.folder === "edits" ? output.name : output.folder;
    const meta = document.createElement("small");
    meta.textContent = `${output.size_label} · ${output.status.replaceAll("_", " ")}`;
    info.append(title, meta);
    const actions = document.createElement("div");
    actions.className = "output-actions";
    const download = document.createElement("a");
    download.className = "mini-action";
    download.href = `/api/artifact?path=${encodeURIComponent(output.path)}`;
    download.download = output.name;
    download.title = "Download render";
    download.innerHTML = icons.download;
    actions.append(download);
    if (output.can_approve) {
      const approve = document.createElement("button");
      approve.className = "mini-action approve-action";
      approve.type = "button";
      approve.title = "Approve this render for local releases";
      approve.innerHTML = icons.approve;
      approve.addEventListener("click", () => approveOutput(output));
      actions.append(approve);
    }
    card.append(info, actions);
    els.outputs.append(card);
  }

  els.sheetWrap.replaceChildren();
  if (state.contact_sheet) {
    const img = document.createElement("img");
    img.src = state.contact_sheet;
    img.alt = "Latest render contact sheet";
    const badge = document.createElement("span");
    badge.className = "sheet-caption";
    badge.textContent = "LATEST CONTACT SHEET";
    els.sheetWrap.append(img, badge);
  } else {
    const placeholder = document.createElement("div");
    placeholder.className = "contact-placeholder";
    placeholder.innerHTML = '<span>▧</span><strong>Render preview</strong><small>Your contact sheet appears here after a run.</small>';
    els.sheetWrap.append(placeholder);
  }
  const releaseList = state.releases || [];
  if (releaseList.length) {
    const heading = document.createElement("div");
    heading.className = "release-heading";
    heading.textContent = `APPROVED RELEASES · ${releaseList.length}`;
    els.outputs.append(heading);
    for (const release of releaseList.slice(0, 4)) {
      const row = document.createElement("div");
      row.className = "release-row";
      const name = document.createElement("span");
      name.textContent = `${release.run_id || "Run"} / ${release.folder}`;
      const link = document.createElement("a");
      link.href = `/api/artifact?path=${encodeURIComponent(release.path)}`;
      link.download = "final_phonk.mp4";
      link.textContent = "Open";
      row.append(name, link);
      els.outputs.append(row);
    }
  }
}

async function saveSettings() {
  const result = await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settingsPayload()),
  });
  els.settingsNote.textContent = "Saved to params.local.json · tracked params.json untouched.";
  els.settingsNote.classList.remove("dirty");
  $("#settings-file-label").textContent = result.settings_file;
  return result;
}

function renderRequest(preview = false) {
  const videoUrl = els.videoUrl.value.trim();
  const musicUrl = els.musicUrl.value.trim();
  const referenceUrl = els.referenceUrl.value.trim();
  return {
    video_path: videoUrl ? "" : els.source.value,
    music_path: musicUrl ? "" : els.music.value,
    reference_path: referenceUrl ? "" : els.reference.value,
    video_url: videoUrl,
    music_url: musicUrl,
    reference_url: referenceUrl,
    edits: preview ? 1 : Number(els.edits.value),
    clip_count: els.clips.value ? Number(els.clips.value) : null,
    preview,
  };
}

async function startRender(preview = false) {
  if (busy) return;
  busy = true;
  els.render.disabled = true;
  els.preview.disabled = true;
  $("#busy-overlay").hidden = false;
  $("#busy-title").textContent = preview ? "Building quick preview" : "Starting your render";
  $("#busy-copy").textContent = "Saving local options and validating selected media.";
  try {
    await saveSettings();
    const request = renderRequest(preview);
    if (els.ai.checked && !currentState?.ai_upscale?.available) {
      throw new Error("Real-ESRGAN assets are not installed. Turn off AI Restore or install the configured model first.");
    }
    $("#busy-copy").textContent = "Launching the existing Heyaa renderer.";
    const result = await api("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    toast(preview ? "Preview render started." : `${request.edits} edit job started.`, "success");
    await refreshState();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    $("#busy-overlay").hidden = true;
    busy = false;
    await refreshState();
  }
}

async function approveOutput(output) {
  const approved = window.confirm(
    `Have you watched and reviewed this exact render?\n\n${output.path}\n\nApproving copies it to output/releases/.`
  );
  if (!approved) return;
  try {
    const result = await api("/api/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video: output.path, confirm: true }),
    });
    toast("Approved copy saved in output/releases/.", "success");
    await refreshState();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function uploadFile(slot, file) {
  if (!file) return;
  const limit = slot === "music" ? 512 * 1024 * 1024 : 2 * 1024 * 1024 * 1024;
  if (file.size > limit) {
    toast(`File is too large for the ${slot} slot.`, "error");
    return;
  }
  $("#busy-overlay").hidden = false;
  $("#busy-title").textContent = `Adding ${slot} media`;
  $("#busy-copy").textContent = "Validating the uploaded file with ffprobe.";
  try {
    const result = await fetch(`/api/upload?slot=${slot}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Filename": encodeURIComponent(file.name),
      },
      body: file,
    });
    const data = await result.json();
    if (!result.ok) throw new Error(data.error || "Upload failed.");
    await refreshState();
    const select = slot === "source" ? els.source : slot === "music" ? els.music : els.reference;
    select.value = data.file.path;
    updateMediaMeta();
    toast(`${file.name} added to input/.`, "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    $("#busy-overlay").hidden = true;
  }
}

function bindUploads() {
  document.querySelectorAll("[data-upload]").forEach((button) => {
    button.addEventListener("click", () => {
      const slot = button.dataset.upload;
      $(`#upload-${slot}`).click();
    });
  });
  [["source", "video"], ["music", "music"], ["reference", "reference"]].forEach(([control, slot]) => {
    $(`#upload-${control}`).addEventListener("change", (event) => {
      uploadFile(slot, event.target.files?.[0]);
      event.target.value = "";
    });
  });
}

function bindLinkInputs() {
  [[els.videoUrl, els.source], [els.musicUrl, els.music], [els.referenceUrl, els.reference]].forEach(([url, select]) => {
    url.addEventListener("input", () => select.disabled = Boolean(url.value.trim()));
    select.addEventListener("change", () => {
      if (select.value) url.value = "";
      select.disabled = false;
    });
  });
}

function bindActions() {
  els.render.addEventListener("click", () => startRender(false));
  els.preview.addEventListener("click", () => startRender(true));
  $("#refresh-button").addEventListener("click", () => refreshState({ quiet: false }));
  $("#show-more-events").addEventListener("click", () => {
    expandedEvents = !expandedEvents;
    refreshState();
  });
  bindUploads();
  bindLinkInputs();
  bindDirtyState();
}

async function boot() {
  bindActions();
  await refreshState({ quiet: false });
  setInterval(() => refreshState(), 2500);
}

boot();
