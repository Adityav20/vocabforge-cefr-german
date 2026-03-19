const CATEGORY_LABELS = {
  nouns: "Nouns",
  verbs: "Verbs",
  adjectives: "Adjectives",
  adverbs: "Adverbs",
  prepositions: "Prepositions",
  phrases: "Phrases",
};

const elements = {
  themeToggle: document.getElementById("themeToggle"),
  uploadForm: document.getElementById("uploadForm"),
  dropzone: document.getElementById("dropzone"),
  fileInput: document.getElementById("fileInput"),
  fileName: document.getElementById("fileName"),
  levelSelect: document.getElementById("levelSelect"),
  submitButton: document.getElementById("submitButton"),
  statusBadge: document.getElementById("statusBadge"),
  currentTitle: document.getElementById("currentTitle"),
  progressFill: document.getElementById("progressFill"),
  progressValue: document.getElementById("progressValue"),
  stageText: document.getElementById("stageText"),
  detailText: document.getElementById("detailText"),
  errorBanner: document.getElementById("errorBanner"),
  previewSections: document.getElementById("previewSections"),
  summaryStats: document.getElementById("summaryStats"),
  notesList: document.getElementById("notesList"),
  downloadPdf: document.getElementById("downloadPdf"),
  downloadCsv: document.getElementById("downloadCsv"),
  historyList: document.getElementById("historyList"),
  refreshHistory: document.getElementById("refreshHistory"),
};

const state = {
  file: null,
  pollTimer: null,
  activeJobId: null,
};

function init() {
  bindTheme();
  bindUpload();
  bindRefresh();
  fetchHistory();
}

function bindTheme() {
  const root = document.documentElement;
  const storedTheme = window.localStorage.getItem("ger-translator-theme");
  if (storedTheme) {
    root.dataset.theme = storedTheme;
  }

  elements.themeToggle.addEventListener("click", () => {
    const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
    root.dataset.theme = nextTheme;
    window.localStorage.setItem("ger-translator-theme", nextTheme);
  });
}

function bindUpload() {
  elements.fileInput.addEventListener("change", (event) => {
    const [file] = event.target.files;
    setFile(file || null);
  });

  ["dragenter", "dragover"].forEach((eventName) => {
    elements.dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      elements.dropzone.classList.add("is-active");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    elements.dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      elements.dropzone.classList.remove("is-active");
    });
  });

  elements.dropzone.addEventListener("drop", (event) => {
    const [file] = event.dataTransfer.files;
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    elements.fileInput.files = transfer.files;
    setFile(file);
  });

  elements.uploadForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideError();

    const file = state.file || elements.fileInput.files[0];
    if (!file) {
      showError("Select a PDF, DOCX, or PPTX document to begin.");
      return;
    }

    setBusy(true);
    renderProgress({
      status: "processing",
      progress: 8,
      stage: "Uploading",
      message: "Uploading your document and creating a processing job.",
      original_filename: file.name,
    });

    const formData = new FormData();
    formData.append("file", file);
    formData.append("level", elements.levelSelect.value);

    try {
      const response = await fetch("/api/v1/jobs", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const payload = await safeJson(response);
        throw new Error(payload.detail || "Upload failed. Please try again.");
      }

      const payload = await response.json();
      state.activeJobId = payload.id;
      startPolling(payload.id);
    } catch (error) {
      setBusy(false);
      renderProgress({
        status: "failed",
        progress: 100,
        stage: "Upload failed",
        message: "The processing job could not be created.",
        original_filename: file.name,
      });
      showError(error.message);
    }
  });
}

function bindRefresh() {
  elements.refreshHistory.addEventListener("click", () => {
    fetchHistory();
  });
}

function setFile(file) {
  state.file = file;
  elements.fileName.textContent = file ? file.name : "No file selected";
}

function setBusy(isBusy) {
  elements.submitButton.disabled = isBusy;
  elements.submitButton.textContent = isBusy ? "Processing..." : "Generate Vocabulary";
}

function showError(message) {
  elements.errorBanner.textContent = message;
  elements.errorBanner.classList.remove("hidden");
}

function hideError() {
  elements.errorBanner.classList.add("hidden");
  elements.errorBanner.textContent = "";
}

function renderProgress(job) {
  const normalizedStatus = job.status || "idle";
  elements.statusBadge.textContent = formatStatus(normalizedStatus);
  elements.statusBadge.className = `status-badge ${normalizedStatus}`;
  elements.currentTitle.textContent = job.original_filename || "Waiting for a document";
  elements.progressFill.style.width = `${job.progress || 0}%`;
  elements.progressValue.textContent = `${job.progress || 0}%`;
  elements.stageText.textContent = job.stage || "Ready";
  elements.detailText.textContent =
    job.message || "The app will extract text, classify vocabulary, and prepare your export files.";
}

async function startPolling(jobId) {
  stopPolling();
  await pollJob(jobId);
  state.pollTimer = window.setInterval(() => {
    pollJob(jobId);
  }, 1200);
}

function stopPolling() {
  if (state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function pollJob(jobId) {
  try {
    const response = await fetch(`/api/v1/jobs/${jobId}`);
    if (!response.ok) {
      throw new Error("Could not read the job status.");
    }
    const job = await response.json();
    renderProgress(job);

    if (job.status === "completed") {
      stopPolling();
      setBusy(false);
      renderResult(job.result);
      fetchHistory();
      return;
    }

    if (job.status === "failed") {
      stopPolling();
      setBusy(false);
      showError(job.error || "Processing failed. Try a cleaner document export and upload again.");
    }
  } catch (error) {
    stopPolling();
    setBusy(false);
    showError(error.message || "Polling failed.");
  }
}

function renderResult(result) {
  elements.previewSections.classList.remove("empty-state");
  elements.previewSections.innerHTML = "";
  updateDownloads(result.available_downloads || {});
  renderSummary(result.summary);
  renderNotes(result.summary.notes || []);

  Object.entries(CATEGORY_LABELS).forEach(([category, label]) => {
    const entries = result.sections?.[category] || [];
    if (!entries.length) return;
    const section = document.createElement("section");
    section.className = "preview-section";
    section.innerHTML = `
      <div class="preview-head">
        <h4>${label}</h4>
        <span class="preview-count">${entries.length} item${entries.length === 1 ? "" : "s"}</span>
      </div>
      <div class="entry-list">
        ${entries
          .map(
            (entry) => `
              <article class="entry-row">
                <div>
                  <div class="entry-term">${escapeHtml(entry.term)}</div>
                  <div class="entry-meta">${escapeHtml(entry.translation)}${
                    entry.example ? ` • ${escapeHtml(trimExample(entry.example))}` : ""
                  }</div>
                </div>
                <span class="entry-tag">${entry.cefr_level}</span>
              </article>
            `,
          )
          .join("")}
      </div>
    `;
    elements.previewSections.appendChild(section);
  });

  if (!elements.previewSections.children.length) {
    elements.previewSections.classList.add("empty-state");
    elements.previewSections.innerHTML = `
      <div class="empty-card">
        <span class="empty-kicker">No matching vocabulary</span>
        <p>The document did not produce translated entries within the selected CEFR range.</p>
      </div>
    `;
  }

  document.querySelector(".result-panel").classList.add("is-ready");
}

function renderSummary(summary) {
  const levelMix = Object.entries(summary.detected_level_mix || {})
    .map(([level, count]) => `${level} (${count})`)
    .join(", ") || "None";

  elements.summaryStats.innerHTML = `
    <article class="stat-card">
      <span class="stat-value">${summary.total_entries || 0}</span>
      <span class="stat-label">Entries</span>
    </article>
    <article class="stat-card">
      <span class="stat-value">${escapeHtml(levelMix)}</span>
      <span class="stat-label">Level Mix</span>
    </article>
    <article class="stat-card">
      <span class="stat-value">${escapeHtml(summary.translation_mode || "-")}</span>
      <span class="stat-label">Translation</span>
    </article>
  `;
}

function renderNotes(notes) {
  const allNotes = Array.from(notes);
  if (!allNotes.length) {
    allNotes.push("Your generated pack is ready.");
  }
  elements.notesList.innerHTML = allNotes.map((note) => `<li>${escapeHtml(note)}</li>`).join("");
}

function updateDownloads(downloads) {
  setDownloadLink(elements.downloadPdf, downloads.pdf);
  setDownloadLink(elements.downloadCsv, downloads.csv);
}

function setDownloadLink(anchor, href) {
  if (!href) {
    anchor.classList.add("disabled");
    anchor.setAttribute("aria-disabled", "true");
    anchor.setAttribute("href", "#");
    return;
  }
  anchor.classList.remove("disabled");
  anchor.setAttribute("aria-disabled", "false");
  anchor.setAttribute("href", href);
}

async function fetchHistory() {
  try {
    const response = await fetch("/api/v1/jobs");
    if (!response.ok) {
      throw new Error("Could not load job history.");
    }
    const jobs = await response.json();
    renderHistory(jobs);
  } catch (error) {
    elements.historyList.innerHTML = `<article class="history-empty">${escapeHtml(error.message)}</article>`;
  }
}

function renderHistory(jobs) {
  if (!jobs.length) {
    elements.historyList.innerHTML =
      '<article class="history-empty">No jobs yet. Your recent exports will appear here.</article>';
    return;
  }

  elements.historyList.innerHTML = jobs
    .map((job) => {
      const created = new Date(job.created_at).toLocaleString();
      const links =
        job.status === "completed"
          ? `<span class="history-links">
              <a href="/api/v1/jobs/${job.id}/download/pdf">PDF</a>
              <a href="/api/v1/jobs/${job.id}/download/csv">CSV</a>
            </span>`
          : `<span class="history-links">${escapeHtml(formatStatus(job.status))}</span>`;

      return `
        <article class="history-item">
          <div class="history-top">
            <div>
              <p class="history-name">${escapeHtml(job.original_filename)}</p>
              <span class="history-meta">Level ${escapeHtml(job.level)} • ${created}</span>
            </div>
            <span class="status-badge ${job.status}">${escapeHtml(formatStatus(job.status))}</span>
          </div>
          <div class="history-bottom">
            <span class="history-meta">${escapeHtml(job.stage || "Queued")}</span>
            ${links}
          </div>
        </article>
      `;
    })
    .join("");
}

function formatStatus(status) {
  switch (status) {
    case "queued":
      return "Queued";
    case "processing":
      return "Processing";
    case "completed":
      return "Ready";
    case "failed":
      return "Failed";
    default:
      return "Idle";
  }
}

function trimExample(example) {
  return example.length > 92 ? `${example.slice(0, 89)}...` : example;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

init();
