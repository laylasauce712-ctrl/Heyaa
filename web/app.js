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
  agentLiveStatus: $("#agent-live-status"), agentLiveTitle: $("#agent-live-title"),
  agentLiveCopy: $("#agent-live-copy"), agentFeedMode: $("#agent-feed-mode"),
  agentTyping: $("#agent-typing"),
  render: $("#render-button"), preview: $("#preview-button"),
};
let currentState = null;
let settingsInitialized = false;
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
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = slot === "reference"
    ? "No reference selected"
    : (slot === "video" ? "Select source video" : "Select soundtrack");
  select.append(placeholder);
  for (const file of files) {
    const option = document.createElement("option");
    option.value = file.path;
    option.textContent = file.name;
    select.append(option);
  }
  // Preserve an actual prior choice; never auto-select a sample or arbitrary file.
  select.value = selectedPath && files.some((file) => file.path === selectedPath)
    ? selectedPath : "";
  return files.find((file) => file.path === select.value) || null;
}

function updateMediaMeta() {
  const findFile = (path) => currentState?.media?.find((file) => file.path === path);
  const source = findFile(els.source.value);
  const music = findFile(els.music.value);
  const reference = findFile(els.reference.value);
  els.sourceMeta.textContent = source ? `${source.size_label} · local input` : "Choose a source file or paste a source URL below.";
  els.musicMeta.textContent = music ? `${music.size_label} · local soundtrack` : "Choose a soundtrack or paste a music URL below.";
  els.referenceMeta.textContent = reference
    ? reference.size_label + " · selected pacing reference (validated before render)"
    : "Optional. When selected, usable cut pacing is required; reference audio stays separate.";
}

function updateAIStatus(status = {}) {
  if (status.available) {
    els.aiStatus.textContent = "Ready · " + (status.model || "Real-ESRGAN") + " " + (status.scale || 2) + "×";
  } else if (!status.binary_exists) {
    els.aiStatus.textContent = "Not installed · standard render available";
  } else if (!status.model_weights_exist) {
    els.aiStatus.textContent = "Model weights missing · standard render available";
  } else {
    els.aiStatus.textContent = "GPU unavailable · standard render available";
  }
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
    if (!settingsInitialized) {
      applySettings(state.settings || {});
      settingsInitialized = true;
    }
    if (!source && !els.source.value) els.sourceMeta.textContent = "No source file found · upload one or use a URL.";
    if (!music && !els.music.value) els.musicMeta.textContent = "No soundtrack found · upload one or use a URL.";
    updateMediaMeta();
    updateAIStatus(state.ai_upscale || {});
    renderRunState(state);
    renderAgentEvents(state.events || [], state);
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
    $("#monitor-footer-text").textContent = "Process " + (state.process_id || "") +
      " · started " + new Date(state.started_at).toLocaleTimeString();
  } else if (state.exit_code !== null && state.exit_code !== undefined) {
    const ok = state.exit_code === 0;
    els.statePill.className = "state-pill " + (ok ? "state-success" : "state-error");
    els.statePill.innerHTML = "<i></i> " + (ok ? "COMPLETED" : "CHECK RUN");
    els.monitorTitle.textContent = ok ? "Render process finished" : "Render needs attention";
    els.monitorDescription.textContent = ok
      ? "Review the video below before approving it as a local release."
      : "Open the latest run events and report to see what blocked the render.";
    $("#monitor-footer-text").textContent = ok
      ? "Human visual review is still required." : "Process exit code " + state.exit_code;
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
    const tools = state.tools || {};
    const toolSummary = [
      tools.ffmpeg ? "FFmpeg ready" : "FFmpeg missing",
      tools.ffprobe ? "ffprobe ready" : "ffprobe missing",
      tools.opencv ? "OpenCV ready" : "OpenCV optional",
    ].join(" · ");
    $("#monitor-footer-text").textContent = toolSummary;
  }

  const events = state.events || [];
  const latest = events.length ? events[events.length - 1] : null;
  const active = [...events].reverse().find((event) =>
    String(event.status || "").toLowerCase() === "running");

  // The renderer emits no reliable percentage today. Show an indeterminate sweep
  // while the process is alive; do not manufacture progress from event counts.
  els.progressFill.classList.toggle("is-running", Boolean(state.running));
  els.progressFill.style.width = state.running ? "34%" :
    (state.exit_code !== null && state.exit_code !== undefined ? "100%" : "0%");
  els.progressStage.textContent = state.running
    ? (active ? "ACTIVE · " + stageLabel(active.stage).toUpperCase() : "RENDER PROCESS ACTIVE")
    : (state.exit_code === 0 ? "PROCESS COMPLETE" :
      state.exit_code !== null && state.exit_code !== undefined ? "PROCESS STOPPED · CHECK REPORT" :
      latest ? "LAST EVENT · " + stageLabel(latest.stage).toUpperCase() : "WAITING FOR RUN");
  els.progressCount.textContent = events.length + " RECORDED EVENTS";

  if (state.running) {
    const conversation = active ? eventConversation(active) : null;
    els.agentLiveStatus.dataset.mode = "running";
    els.agentFeedMode.textContent = conversation
      ? conversation.speaker.toUpperCase() + " · ACTIVE" : "RENDER PROCESS · ACTIVE";
    els.agentLiveTitle.textContent = conversation
      ? conversation.speaker + " is working" : "Renderer is working between events";
    els.agentLiveCopy.textContent = active
      ? (active.summary || "This stage has started; waiting for its result.")
      : "The render process is still active. Its next recorded pipeline update will appear here.";
    els.agentTyping.hidden = false;
  } else {
    els.agentTyping.hidden = true;
    if (latest) {
      const conversation = eventConversation(latest);
      els.agentLiveStatus.dataset.mode =
        latest.status === "blocked" || latest.status === "error" ? "error" : "idle";
      els.agentFeedMode.textContent = "LATEST REPORT · " + statusLabel(latest.status);
      els.agentLiveTitle.textContent = conversation.speaker;
      els.agentLiveCopy.textContent = latest.summary || "The latest event has no summary.";
    } else {
      els.agentLiveStatus.dataset.mode = "idle";
      els.agentFeedMode.textContent = "ENGINE STANDBY";
      els.agentLiveTitle.textContent = "Agents standing by";
      els.agentLiveCopy.textContent =
        "When a render starts, the current task and recorded agent messages will appear here.";
    }
  }
}

function stageLabel(stage) {
  const key = String(stage || "").replace(/^agent:/, "").replaceAll("_", " ");
  return key.split(" ").map((word) => word ? word[0].toUpperCase() + word.slice(1) : word).join(" ");
}

function eventConversation(item) {
  const details = item && item.details && typeof item.details === "object" ? item.details : {};
  const agentEvent = details.agent_event && typeof details.agent_event === "object"
    ? details.agent_event : null;
  const agentName = details.speaker || (agentEvent && agentEvent.agent) || item.stage || "Pipeline";
  const speaker = stageLabel(String(agentName).replace(/^agent:/, ""));
  const data = agentEvent && agentEvent.data && typeof agentEvent.data === "object"
    ? agentEvent.data : {};
  const finding = Array.isArray(data.findings)
    ? data.findings.find((value) => typeof value === "string" && value.trim()) : null;
  const recommendation = Array.isArray(data.recommendations)
    ? data.recommendations.find((value) => typeof value === "string" && value.trim()) : null;
  return {
    speaker: speaker,
    recipient: typeof details.to === "string" ? details.to : "",
    isAgent: Boolean(details.speaker || agentEvent),
    finding: finding || "",
    recommendation: recommendation || "",
  };
}

function statusLabel(status) {
  const map = {
    completed: "DONE", success: "DONE", ok: "OK", running: "LIVE",
    needs_review: "REVIEW", blocked: "BLOCKED", error: "ERROR",
    fallback: "FALLBACK", skipped: "SKIPPED", cancelled: "STOPPED",
  };
  return map[status] || String(status || "INFO").toUpperCase();
}

function renderAgentEvents(events, state = {}) {
  els.events.replaceChildren();
  if (!events.length && !state.running) {
    const empty = document.createElement("div");
    empty.className = "empty-events";
    empty.textContent =
      "Agent notes and pipeline updates will appear here as Heyaa records them. No simulated chat is shown.";
    els.events.append(empty);
    return;
  }

  const list = expandedEvents ? events : events.slice(-8);
  for (const item of list.slice().reverse()) {
    const conversation = eventConversation(item);
    const status = String(item.status || "info").replace(/[^a-z_]/g, "");
    const row = document.createElement("article");
    row.className = "event-row " +
      (conversation.isAgent ? "agent-message " : "pipeline-message ") + status;

    const avatar = document.createElement("span");
    avatar.className = "event-avatar";
    const initials = conversation.speaker.split(/\s+).filter(Boolean)
      .slice(0, 2).map((part) => part[0]).join("");
    avatar.textContent = (initials || "HP").toUpperCase();

    const copy = document.createElement("div");
    copy.className = "event-copy";
    const head = document.createElement("div");
    head.className = "event-head";
    const title = document.createElement("strong");
    title.textContent = conversation.speaker;
    const route = document.createElement("span");
    route.className = "event-route";
    route.textContent = conversation.recipient
      ? "→ " + conversation.recipient
      : (conversation.isAgent ? "AGENT REPORT" : "PIPELINE");
    head.append(title, route);

    const summary = document.createElement("p");
    summary.textContent = item.summary || "No summary was recorded.";
    copy.append(head, summary);

    if (conversation.finding) {
      const finding = document.createElement("small");
      finding.className = "event-detail";
      finding.textContent = "Finding · " + conversation.finding;
      copy.append(finding);
    }
    if (conversation.recommendation) {
      const recommendation = document.createElement("small");
      recommendation.className = "event-detail";
      recommendation.textContent = "Next step · " + conversation.recommendation;
      copy.append(recommendation);
    }

    const footer = document.createElement("div");
    footer.className = "event-footer";
    const time = document.createElement("small");
    time.textContent = item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : "";
    const pill = document.createElement("span");
    pill.className = "event-status " + status;
    pill.textContent = statusLabel(item.status);
    footer.append(time, pill);
    copy.append(footer);
    row.append(avatar, copy);
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
    let previewPlayer = null;
    if (output.is_preview) {
      previewPlayer = document.createElement("video");
      previewPlayer.className = "output-preview-player";
      previewPlayer.src = `/api/artifact?path=${encodeURIComponent(output.path)}`;
      previewPlayer.controls = true;
      previewPlayer.preload = "metadata";
      previewPlayer.playsInline = true;
      previewPlayer.setAttribute("aria-label", "Quick preview render");
      card.classList.add("preview-output-card");
    }
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
    if (previewPlayer) card.append(info, previewPlayer, actions);
    else card.append(info, actions);
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
    const request = renderRequest(preview);
    if (!request.video_path && !request.video_url) {
      throw new Error("Select a source video or provide a video URL before rendering.");
    }
    if (!request.music_path && !request.music_url) {
      throw new Error("Select a soundtrack or provide a music URL before rendering.");
    }
    await saveSettings();
    if (!preview && els.ai.checked && !currentState?.ai_upscale?.available) {
      const status = currentState?.ai_upscale || {};
      const reason = !status.binary_exists ? "the Real-ESRGAN executable is missing"
        : !status.model_weights_exist ? "the configured model weights are missing"
        : (status.vulkan_probe?.reason || "hardware-backed Vulkan is unavailable");
      throw new Error("AI Restore is unavailable because " + reason + ". Turn it off to run the standard renderer.");
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
    const urlField = slot === "source" ? els.videoUrl : slot === "music" ? els.musicUrl : els.referenceUrl;
    urlField.value = "";
    select.disabled = false;
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
  ["source", "music", "reference"].forEach((slot) => {
    $(`#upload-${slot}`).addEventListener("change", (event) => {
      // Keep the UI slot consistent through upload and selection. The backend
      // maps "source" to its internal "video" media kind.
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
