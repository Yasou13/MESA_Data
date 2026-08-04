const state = {
  currentView: "dashboard",
  token: sessionStorage.getItem("mesa_admin_token") || "",
  busy: false,
  docPage: 1,
  currentRecordId: null,
  currentVersionId: null,
};

// --- Utilities ---
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function showToast(message, type = "success") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 4000);
}

function setBusy(isBusy) {
  state.busy = isBusy;
  const spinner = document.getElementById("busy-spinner");
  if (isBusy) {
    spinner.classList.remove("hidden");
  } else {
    spinner.classList.add("hidden");
  }

  document.querySelectorAll("button, input[type='submit']").forEach((btn) => {
    if (isBusy) {
      btn.setAttribute("disabled", "true");
    } else {
      btn.removeAttribute("disabled");
    }
  });
}

function statusBadge(statusStr) {
  const labels = {
    discovered: "Keşfedildi",
    fetched: "İndirildi",
    transport_verified: "Dosya doğrulandı",
    parsed: "Ayrıştırıldı",
    needs_review: "İnceleme bekliyor",
    approved: "Onaylandı",
    rejected: "Reddedildi",
    verified: "Doğrulandı",
    published: "Yayınlandı",
    revoked: "Geri çekildi",
    failed: "Başarısız",
    imported: "MESA'ya aktarıldı",
  };

  const label = labels[statusStr] || `Bilinmeyen: ${statusStr}`;
  let badgeClass = "badge-info";
  if (["approved", "verified", "published", "imported"].includes(statusStr)) badgeClass = "badge-success";
  if (["needs_review"].includes(statusStr)) badgeClass = "badge-warning";
  if (["rejected", "failed", "revoked"].includes(statusStr)) badgeClass = "badge-danger";

  return `<span class="badge ${badgeClass}">${escapeHtml(label)}</span>`;
}

// --- API Wrapper ---
async function apiRequest(endpoint, options = {}) {
  const headers = options.headers || {};

  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }

  const method = (options.method || "GET").toUpperCase();
  if (["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
    headers["X-MESA-Requested-With"] = "web-admin";
  }

  options.headers = headers;

  try {
    const response = await fetch(endpoint, options);
    const result = await response.json();

    if (response.status === 401) {
      showModal("modal-token");
      throw new Error("Kimlik doğrulama gerekli (Admin Token).");
    }

    if (response.status === 409) {
      const msg = result.error?.message || "Başka bir yazma işlemi devam ediyor.";
      showToast(msg, "warning");
      throw new Error(msg);
    }

    if (!response.ok || !result.ok) {
      const msg = result.error?.message || `API Hatası: ${response.status}`;
      showToast(msg, "danger");
      throw new Error(msg);
    }

    return result.data;
  } catch (err) {
    if (!err.message.includes("API Hatası")) {
      console.error(err);
    }
    throw err;
  }
}

// --- Navigation & View Manager ---
function switchView(viewName) {
  state.currentView = viewName;

  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === viewName);
  });

  document.querySelectorAll(".view-panel").forEach((panel) => {
    panel.classList.add("hidden");
    panel.classList.remove("active");
  });

  const targetPanel = document.getElementById(`view-${viewName}`);
  if (targetPanel) {
    targetPanel.classList.remove("hidden");
    targetPanel.classList.add("active");
  }

  const titles = {
    dashboard: "Genel Bakış",
    add_data: "Veri Ekle",
    documents: "Belgeler",
    reviews: "Kayıt İnceleme",
    releases: "Release Yönetimi",
    system: "Sistem Durumu",
  };
  document.getElementById("view-title").textContent = titles[viewName] || "MESA Panel";

  // Trigger view reload
  if (viewName === "dashboard") loadDashboard();
  if (viewName === "documents") loadDocuments();
  if (viewName === "reviews") loadReviews();
  if (viewName === "releases") loadReleases();
  if (viewName === "system") loadSystemStatus();
}

// --- View Loaders ---

// 1. Dashboard
async function loadDashboard() {
  try {
    const data = await apiRequest("/api/dashboard");
    const counts = data.counts || {};

    document.getElementById("stat-docs").textContent = counts.documents || 0;
    document.getElementById("stat-artifacts").textContent = counts.artifacts || 0;
    document.getElementById("stat-records").textContent = counts.records || 0;
    document.getElementById("stat-pending").textContent = counts.pending_reviews || 0;
    document.getElementById("stat-approved").textContent = counts.approved_records || 0;
    document.getElementById("stat-issues").textContent = (counts.open_blockers || 0) + (counts.open_errors || 0);
    document.getElementById("stat-releases").textContent = counts.published_releases || 0;
    document.getElementById("stat-active-release").textContent = counts.active_release_id || "YOK";

    // Recent docs table
    const tblDocs = document.getElementById("tbl-recent-docs");
    tblDocs.innerHTML = "";
    (data.recent_documents || []).forEach((d) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code>${escapeHtml(d.document_id)}</code></td>
        <td>${escapeHtml(d.family)} / ${escapeHtml(d.document_type)}</td>
        <td>${escapeHtml(d.title || "-")}</td>
        <td>${statusBadge(d.status)}</td>
        <td>${escapeHtml(d.updated_at ? d.updated_at.substring(0, 19) : "")}</td>
      `;
      tblDocs.appendChild(tr);
    });

    // Recent runs table
    const tblRuns = document.getElementById("tbl-recent-runs");
    tblRuns.innerHTML = "";
    (data.recent_runs || []).forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code>${escapeHtml(r.run_id)}</code></td>
        <td><code>${escapeHtml(r.command)}</code></td>
        <td>${statusBadge(r.status)}</td>
        <td>${escapeHtml(r.started_at ? r.started_at.substring(0, 19) : "")}</td>
      `;
      tblRuns.appendChild(tr);
    });
  } catch (e) {
    console.error("Dashboard error:", e);
  }
}

// 2. Add Data
function setupAddDataForms() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => {
        c.classList.add("hidden");
        c.classList.remove("active");
      });

      btn.classList.add("active");
      const targetForm = document.getElementById(btn.dataset.tab === "tab-file" ? "form-upload-file" : "form-upload-url");
      targetForm.classList.remove("hidden");
      targetForm.classList.add("active");
    });
  });

  // Form file upload
  document.getElementById("form-upload-file").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById("file-input");
    if (!fileInput.files.length) return;

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("source_id", document.getElementById("file-source").value);
    formData.append("family", document.getElementById("file-family").value);
    formData.append("document_id", document.getElementById("file-doc-id").value);
    const titleVal = document.getElementById("file-title").value;
    if (titleVal) formData.append("title", titleVal);

    try {
      setBusy(true);
      const res = await apiRequest("/api/artifacts/upload", {
        method: "POST",
        body: formData,
      });
      showToast(`Dosya başarıyla yüklendi! Artifact ID: ${res.artifact_id}`);
      switchView("documents");
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(false);
    }
  });

  // Form URL upload
  document.getElementById("form-upload-url").addEventListener("submit", async (e) => {
    e.preventDefault();
    const reqBody = {
      source_id: document.getElementById("url-source").value,
      url: document.getElementById("url-input").value,
      document_id: document.getElementById("url-doc-id").value,
      title: document.getElementById("url-title").value || null,
    };

    try {
      setBusy(true);
      const res = await apiRequest("/api/artifacts/from-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody),
      });
      showToast(`URL başarıyla içe aktarıldı! Artifact ID: ${res.artifact_id}`);
      switchView("documents");
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(false);
    }
  });
}

// 3. Documents
async function loadDocuments() {
  try {
    const q = document.getElementById("filter-doc-q").value;
    const status = document.getElementById("filter-doc-status").value;

    let url = `/api/documents?page=${state.docPage}&page_size=20`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;

    const data = await apiRequest(url);
    const tbl = document.getElementById("tbl-docs");
    tbl.innerHTML = "";

    (data.items || []).forEach((d) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code>${escapeHtml(d.document_id)}</code></td>
        <td>${escapeHtml(d.family)} / ${escapeHtml(d.document_type)}</td>
        <td>${escapeHtml(d.title || "-")}</td>
        <td>${statusBadge(d.lifecycle_status)}</td>
        <td>${d.artifact_count}</td>
        <td>${escapeHtml(d.updated_at ? d.updated_at.substring(0, 19) : "")}</td>
        <td>
          <button class="btn btn-sm btn-secondary btn-doc-detail" data-id="${escapeHtml(d.document_id)}">Detay</button>
        </td>
      `;
      tbl.appendChild(tr);
    });

    document.getElementById("lbl-doc-page").textContent = `Sayfa ${data.page}`;

    // Detail button clicks
    document.querySelectorAll(".btn-doc-detail").forEach((b) => {
      b.addEventListener("click", () => openDocumentModal(b.dataset.id));
    });
  } catch (err) {
    console.error(err);
  }
}

async function openDocumentModal(documentId) {
  try {
    const doc = await apiRequest(`/api/documents/${encodeURIComponent(documentId)}`);
    document.getElementById("doc-modal-title").textContent = `Belge: ${doc.document_id}`;

    const body = document.getElementById("doc-modal-body");
    body.innerHTML = `
      <p><strong>Başlık:</strong> ${escapeHtml(doc.title || "-")}</p>
      <p><strong>Durum:</strong> ${statusBadge(doc.lifecycle_status)}</p>
      <p><strong>Current Version:</strong> <code>${escapeHtml(doc.current_version_id || "yok")}</code></p>
      <p><strong>Artifact Sayısı:</strong> ${doc.artifacts ? doc.artifacts.length : 0}</p>
      <h4>Artifact Listesi:</h4>
      <ul>
        ${(doc.artifacts || [])
          .map(
            (a) => `
          <li>
            <code>${escapeHtml(a.artifact_id)}</code> (${escapeHtml(a.source_id)}) - ${statusBadge(a.transport_status)}
            <button class="btn btn-sm btn-primary btn-process-art" data-id="${escapeHtml(a.artifact_id)}">Pipeline Çalıştır</button>
          </li>
        `
          )
          .join("")}
      </ul>
    `;

    showModal("modal-doc-detail");

    body.querySelectorAll(".btn-process-art").forEach((b) => {
      b.addEventListener("click", async () => {
        try {
          setBusy(true);
          const res = await apiRequest(`/api/artifacts/${encodeURIComponent(b.dataset.id)}/process`, {
            method: "POST",
          });
          showToast(`Pipeline tamamlandı: status '${res.pipeline_status}'`);
          closeModal("modal-doc-detail");
          loadDocuments();
        } catch (e) {
          console.error(e);
        } finally {
          setBusy(false);
        }
      });
    });
  } catch (err) {
    console.error(err);
  }
}

// 4. Reviews
async function loadReviews() {
  try {
    const status = document.getElementById("filter-review-status").value;
    const data = await apiRequest(`/api/records?approval_status=${encodeURIComponent(status)}`);

    const tbl = document.getElementById("tbl-reviews");
    tbl.innerHTML = "";

    (data.items || []).forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code>${escapeHtml(r.record_id)}</code></td>
        <td>${escapeHtml(r.record_type)}</td>
        <td><code>${escapeHtml(r.document_id)}</code></td>
        <td>${statusBadge(r.validation_status)}</td>
        <td>${statusBadge(r.approval_status)}</td>
        <td>${escapeHtml(r.created_at ? r.created_at.substring(0, 19) : "")}</td>
        <td>
          <button class="btn btn-sm btn-secondary btn-rec-detail" data-id="${escapeHtml(r.record_id)}">İncele</button>
        </td>
      `;
      tbl.appendChild(tr);
    });

    document.querySelectorAll(".btn-rec-detail").forEach((b) => {
      b.addEventListener("click", () => openRecordModal(b.dataset.id));
    });
  } catch (err) {
    console.error(err);
  }
}

async function openRecordModal(recordId) {
  try {
    state.currentRecordId = recordId;
    const rec = await apiRequest(`/api/records/${encodeURIComponent(recordId)}`);
    state.currentVersionId = rec.version_id;

    document.getElementById("record-modal-title").textContent = `Kayıt İnceleme: ${rec.record_id}`;
    const body = document.getElementById("record-modal-body");

    const blockers = rec.open_blockers || [];
    const hasBlockers = blockers.length > 0;

    body.innerHTML = `
      <p><strong>Tür:</strong> ${escapeHtml(rec.record_type)} | <strong>Version:</strong> <code>${escapeHtml(rec.version_id)}</code></p>
      <p><strong>Onay Durumu:</strong> ${statusBadge(rec.approval_status)} | <strong>Validation:</strong> ${statusBadge(rec.validation_status)}</p>
      <p><strong>Record SHA256:</strong> <code>${escapeHtml(rec.record_sha256)}</code></p>
      ${hasBlockers ? `<div class="toast danger">⚠️ Açık Blocker Sorunları Bulunuyor (${blockers.length})</div>` : ""}
      <h4>Metin Önizlemesi (JSONL Line):</h4>
      <pre class="code-box">${escapeHtml(rec.text_preview || "Metin bulunamadı")}</pre>
    `;

    const approveBtn = document.getElementById("btn-record-approve");
    if (hasBlockers) {
      approveBtn.setAttribute("disabled", "true");
    } else {
      approveBtn.removeAttribute("disabled");
    }

    showModal("modal-record-detail");
  } catch (err) {
    console.error(err);
  }
}

// Setup Review Modal Handlers
function setupReviewHandlers() {
  document.getElementById("btn-record-approve").addEventListener("click", async () => {
    if (!state.currentRecordId) return;
    const reviewer = document.getElementById("txt-reviewer-name").value || "yasin";
    const note = document.getElementById("txt-reviewer-note").value || null;

    try {
      setBusy(true);
      await apiRequest(`/api/versions/${encodeURIComponent(state.currentVersionId)}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer, note }),
      });
      showToast(`Kayıt versiyonu başarıyla ONAYLANDI!`);
      closeModal("modal-record-detail");
      loadReviews();
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  });

  document.getElementById("btn-record-reject").addEventListener("click", async () => {
    if (!state.currentRecordId) return;
    const reviewer = document.getElementById("txt-reviewer-name").value || "yasin";
    const note = document.getElementById("txt-reviewer-note").value || null;

    try {
      setBusy(true);
      await apiRequest(`/api/records/${encodeURIComponent(state.currentRecordId)}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer, note }),
      });
      showToast(`Kayıt REDDEDİLDİ!`, "warning");
      closeModal("modal-record-detail");
      loadReviews();
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  });
}

// 5. Releases
async function loadReleases() {
  try {
    const releases = await apiRequest("/api/releases");
    const tbl = document.getElementById("tbl-releases");
    tbl.innerHTML = "";

    (releases || []).forEach((r) => {
      const counts = r.counts || {};
      const tr = document.createElement("tr");

      let actionsHtml = "";
      if (r.status === "verified") {
        actionsHtml = `<button class="btn btn-sm btn-primary btn-rel-pub" data-id="${escapeHtml(r.release_id)}">Publish</button>`;
      } else if (r.status === "published") {
        actionsHtml = `
          <button class="btn btn-sm btn-success btn-rel-imp" data-id="${escapeHtml(r.release_id)}">Import Staging</button>
          <button class="btn btn-sm btn-danger btn-rel-rev" data-id="${escapeHtml(r.release_id)}">Revoke</button>
        `;
      }

      tr.innerHTML = `
        <td><code>${escapeHtml(r.release_id)}</code></td>
        <td>${statusBadge(r.status)}</td>
        <td>${counts.legislation_count || 0}</td>
        <td>${counts.article_count || 0}</td>
        <td>${counts.decision_count || 0}</td>
        <td>${counts.citation_count || 0}</td>
        <td>${escapeHtml(r.created_at ? r.created_at.substring(0, 19) : "")}</td>
        <td>
          <button class="btn btn-sm btn-secondary btn-rel-ver" data-id="${escapeHtml(r.release_id)}">Verify</button>
          ${actionsHtml}
        </td>
      `;
      tbl.appendChild(tr);
    });

    // Attach release action events
    tbl.querySelectorAll(".btn-rel-ver").forEach((b) => {
      b.addEventListener("click", async () => {
        try {
          const res = await apiRequest(`/api/releases/${encodeURIComponent(b.dataset.id)}/verify`, { method: "POST" });
          showToast(`Release ${b.dataset.id} doğrulaması BAŞARILI!`);
        } catch (e) {
          console.error(e);
        }
      });
    });

    tbl.querySelectorAll(".btn-rel-pub").forEach((b) => {
      b.addEventListener("click", async () => {
        try {
          setBusy(true);
          await apiRequest(`/api/releases/${encodeURIComponent(b.dataset.id)}/publish`, { method: "POST" });
          showToast(`Release ${b.dataset.id} YAYINLANDI!`);
          loadReleases();
        } catch (e) {
          console.error(e);
        } finally {
          setBusy(false);
        }
      });
    });

    tbl.querySelectorAll(".btn-rel-imp").forEach((b) => {
      b.addEventListener("click", async () => {
        try {
          setBusy(true);
          const res = await apiRequest(`/api/releases/${encodeURIComponent(b.dataset.id)}/import`, { method: "POST" });
          showToast(`Release ${b.dataset.id} MESA Staging'e AKTARILDI! (${res.status})`);
          loadDashboard();
        } catch (e) {
          console.error(e);
        } finally {
          setBusy(false);
        }
      });
    });

    tbl.querySelectorAll(".btn-rel-rev").forEach((b) => {
      b.addEventListener("click", async () => {
        const reason = prompt("Revoke gerekçesi giriniz:");
        if (!reason) return;
        try {
          setBusy(true);
          await apiRequest(`/api/releases/${encodeURIComponent(b.dataset.id)}/revoke`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason }),
          });
          showToast(`Release ${b.dataset.id} GERİ ÇEKİLDİ (Revoked).`, "warning");
          loadReleases();
        } catch (e) {
          console.error(e);
        } finally {
          setBusy(false);
        }
      });
    });
  } catch (err) {
    console.error(err);
  }
}

// Build Release Setup
function setupReleaseBuildHandler() {
  document.getElementById("btn-build-release").addEventListener("click", async () => {
    const relId = document.getElementById("txt-release-id").value.trim();
    if (!relId) {
      showToast("Lütfen bir Release ID giriniz.", "warning");
      return;
    }

    try {
      setBusy(true);
      const res = await apiRequest("/api/releases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ release_id: relId }),
      });
      showToast(`Release ${res.release_id} başarıyla paketlendi!`);
      document.getElementById("txt-release-id").value = "";
      loadReleases();
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  });
}

// 6. System
async function loadSystemStatus() {
  try {
    const data = await apiRequest("/api/system/status");
    document.getElementById("sys-status-output").textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    console.error(err);
  }
}

function setupSystemHandlers() {
  document.getElementById("btn-sys-doctor").addEventListener("click", async () => {
    try {
      setBusy(true);
      const res = await apiRequest("/api/system/doctor", { method: "POST" });
      document.getElementById("sys-status-output").textContent = JSON.stringify(res, null, 2);
      showToast("Doctor kontrolü tamamlandı.");
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  });

  document.getElementById("btn-sys-backup").addEventListener("click", async () => {
    try {
      setBusy(true);
      const res = await apiRequest("/api/system/backup", { method: "POST" });
      showToast(`Backup alındı: ${res.backup_path}`);
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(false);
    }
  });
}

// --- Modals ---
function showModal(modalId) {
  document.getElementById(modalId)?.classList.remove("hidden");
}

function closeModal(modalId) {
  document.getElementById(modalId)?.classList.add("hidden");
}

function setupModals() {
  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => closeModal(btn.dataset.close));
  });

  document.getElementById("btn-token").addEventListener("click", () => {
    document.getElementById("txt-token-input").value = state.token;
    showModal("modal-token");
  });

  document.getElementById("btn-save-token").addEventListener("click", () => {
    const token = document.getElementById("txt-token-input").value.trim();
    state.token = token;
    sessionStorage.setItem("mesa_admin_token", token);
    closeModal("modal-token");
    showToast("Admin Token kaydedildi.");
    loadDashboard();
  });
}

// --- App Initialization ---
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });

  document.getElementById("btn-doc-filter").addEventListener("click", () => {
    state.docPage = 1;
    loadDocuments();
  });

  document.getElementById("btn-doc-prev").addEventListener("click", () => {
    if (state.docPage > 1) {
      state.docPage--;
      loadDocuments();
    }
  });

  document.getElementById("btn-doc-next").addEventListener("click", () => {
    state.docPage++;
    loadDocuments();
  });

  document.getElementById("btn-review-filter").addEventListener("click", () => {
    loadReviews();
  });

  setupAddDataForms();
  setupReviewHandlers();
  setupReleaseBuildHandler();
  setupSystemHandlers();
  setupModals();

  // Load initial view
  switchView("dashboard");
});
