const state = {
  currentView: "dashboard",
  token: sessionStorage.getItem("mesa_admin_token") || "",
  busy: false,
  docPage: 1,
  currentRecordId: null,
  currentVersionId: null,
};

const VIEW_DESCRIPTIONS = {
  dashboard: "Sistemin veri, kalite ve release durumunu tek yerde izleyin.",
  add_data: "Yerel belge veya izinli resmî HTTPS kaynağı sisteme alın.",
  documents: "Artifact, pipeline ve provenance durumlarını yönetin.",
  explorer: "Filtreler ile canonical veri varlıklarında arama yapın.",
  reviews: "Kayıtları inceleyin, onaylayın veya reddedin.",
  issues: "Veri kalitesi ve işlem hatalarını takip edin.",
  sources: "Resmî veri kaynaklarının kurallarını ve izinlerini görün.",
  releases: "Yayınlanabilir veri paketleri oluşturun ve doğrulayın.",
  exports: "Kayıt, audit ve provenance verilerini dışa aktarın.",
  operations: "Arka plan veri operasyonlarını çalıştırın ve izleyin.",
  audit: "Sistemde gerçekleşen kritik eylemlerin geçmişini inceleyin.",
  system: "Sistem sağlığını ve veritabanı durumunu denetleyin.",
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
  if (window.MesaUI && window.MesaUI.showToast) {
    window.MesaUI.showToast(message, type);
  } else {
    alert(message);
  }
}

function showModal(modalId) {
  if (window.MesaUI && window.MesaUI.showModal) {
    window.MesaUI.showModal(modalId);
  } else {
    const el = document.getElementById(modalId);
    if (el) el.classList.remove("hidden");
  }
}

function closeModal(modalId) {
  if (window.MesaUI && window.MesaUI.closeModal) {
    window.MesaUI.closeModal(modalId);
  } else {
    const el = document.getElementById(modalId);
    if (el) el.classList.add("hidden");
  }
}

function setBusy(isBusy) {
  state.busy = isBusy;
  const spinner = document.getElementById("busy-spinner");
  if (spinner) {
    if (isBusy) {
      spinner.classList.remove("hidden");
    } else {
      spinner.classList.add("hidden");
    }
  }
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

// --- Safe API Wrapper ---
async function apiRequest(endpoint, options = {}) {
  const headers = options.headers || {};

  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }

  const method = (options.method || "GET").toUpperCase();
  if (["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
    headers["X-MESA-Requested-With"] = "web-admin";
    headers["X-MESA-Actor"] = sessionStorage.getItem("mesa_actor") || "operator";
  }

  options.headers = headers;

  try {
    const response = await fetch(endpoint, options);
    const contentType = response.headers.get("content-type") || "";
    const result = contentType.includes("application/json")
      ? await response.json()
      : { ok: response.ok, data: null, error: { message: await response.text() } };

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
    explorer: "Veri Gezgini",
    reviews: "İnceleme Masası",
    issues: "Sorunlar",
    sources: "Kaynaklar",
    releases: "Release Merkezi",
    exports: "Dışa Aktarma",
    operations: "Operasyonlar",
    audit: "Audit",
    system: "Sistem",
  };

  const viewTitle = titles[viewName] || viewName;
  const viewDesc = VIEW_DESCRIPTIONS[viewName] || "";

  document.getElementById("view-title").textContent = viewTitle;
  document.getElementById("view-desc").textContent = viewDesc;

  // Close mobile sidebar if open
  closeMobileSidebar();

  // Load view content
  if (viewName === "dashboard") loadDashboard();
  if (viewName === "documents") loadDocuments();
  if (viewName === "reviews") loadReviews();
  if (viewName === "releases") loadReleases();
  if (viewName === "explorer") loadExplorer();
  if (viewName === "issues") loadIssues();
  if (viewName === "sources") loadSources();
  if (viewName === "exports") loadExports();
  if (viewName === "operations") loadOperations();
  if (viewName === "audit") loadAudit();
  if (viewName === "system") loadSystem();
}

function closeMobileSidebar() {
  const sidebar = document.getElementById("app-sidebar");
  const overlay = document.getElementById("sidebar-overlay");
  if (sidebar) sidebar.classList.remove("open");
  if (overlay) overlay.classList.remove("open");
}

// --- Dashboard Handler ---
async function loadDashboard() {
  try {
    setBusy(true);
    const data = await apiRequest("/api/dashboard/stats");

    document.getElementById("stat-docs").textContent = data.documents_count || 0;
    document.getElementById("stat-artifacts").textContent = data.raw_artifacts_count || 0;
    document.getElementById("stat-records").textContent = data.canonical_records_count || 0;
    document.getElementById("stat-pending").textContent = data.pending_reviews_count || 0;
    document.getElementById("stat-approved").textContent = data.approved_records_count || 0;
    document.getElementById("stat-issues").textContent = data.open_issues_count || 0;
    document.getElementById("stat-releases").textContent = data.published_releases_count || 0;
    document.getElementById("stat-active-release").textContent = data.active_release_id || "YOK";

    // Table: Recent Docs
    const tblDocs = document.getElementById("tbl-recent-docs");
    tblDocs.innerHTML = "";
    if (data.recent_documents && data.recent_documents.length > 0) {
      data.recent_documents.forEach((doc) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${escapeHtml(doc.document_id)}</code></td>
          <td>${escapeHtml(doc.document_type)}</td>
          <td>${escapeHtml(doc.title || "-")}</td>
          <td>${statusBadge(doc.lifecycle_status)}</td>
          <td>${escapeHtml(doc.updated_at ? doc.updated_at.split("T")[0] : "-")}</td>
        `;
        tblDocs.appendChild(tr);
      });
    } else {
      tblDocs.innerHTML = `<tr><td colspan="5" class="text-muted">Henüz belge bulunmuyor.</td></tr>`;
    }

    // Table: Recent Runs
    const tblRuns = document.getElementById("tbl-recent-runs");
    tblRuns.innerHTML = "";
    if (data.recent_runs && data.recent_runs.length > 0) {
      data.recent_runs.forEach((run) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${escapeHtml(run.run_id)}</code></td>
          <td><code>${escapeHtml(run.command)}</code></td>
          <td>${statusBadge(run.status)}</td>
          <td>${escapeHtml(run.started_at ? run.started_at.split("T")[0] : "-")}</td>
        `;
        tblRuns.appendChild(tr);
      });
    } else {
      tblRuns.innerHTML = `<tr><td colspan="4" class="text-muted">Henüz işlem geçmişi yok.</td></tr>`;
    }
  } catch (err) {
    console.error("Dashboard yüklenemedi:", err);
  } finally {
    setBusy(false);
  }
}

// --- Add Data Form Handlers ---
function setupAddDataForms() {
  const tabBtns = document.querySelectorAll("#view-add_data .tab-btn");
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabBtns.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      const targetTab = btn.dataset.tab;
      document.getElementById("form-upload-file").classList.toggle("hidden", targetTab !== "tab-file");
      document.getElementById("form-upload-file").classList.toggle("active", targetTab === "tab-file");
      document.getElementById("form-upload-url").classList.toggle("hidden", targetTab !== "tab-url");
      document.getElementById("form-upload-url").classList.toggle("active", targetTab === "tab-url");
    });
  });

  // File Upload Form Submit
  const formFile = document.getElementById("form-upload-file");
  formFile.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btnSubmit = document.getElementById("btn-submit-file");
    const fileInput = document.getElementById("file-input");
    if (!fileInput.files[0]) return;

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    formData.append("source_id", document.getElementById("file-source").value);
    formData.append("family", document.getElementById("file-family").value);
    formData.append("document_id", document.getElementById("file-doc-id").value.trim());
    formData.append("title", document.getElementById("file-title").value.trim());

    try {
      window.MesaUI.setElementBusy(btnSubmit, true, "Yükleniyor...");
      const headers = {};
      if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
      headers["X-MESA-Requested-With"] = "web-admin";
      headers["X-MESA-Actor"] = sessionStorage.getItem("mesa_actor") || "operator";

      const resp = await fetch("/api/manual/upload-file", {
        method: "POST",
        headers: headers,
        body: formData,
      });

      const res = await resp.json();
      if (!resp.ok || !res.ok) {
        throw new Error(res.error?.message || "Dosya yüklenemedi.");
      }

      showToast("Dosya başarıyla yüklendi!");
      formFile.reset();
      switchView("documents");
    } catch (err) {
      showToast(err.message, "danger");
    } finally {
      window.MesaUI.setElementBusy(btnSubmit, false);
    }
  });

  // URL Import Form Submit
  const formUrl = document.getElementById("form-upload-url");
  formUrl.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btnSubmit = document.getElementById("btn-submit-url");
    const payload = {
      url: document.getElementById("url-input").value.trim(),
      source_id: document.getElementById("url-source").value,
      document_id: document.getElementById("url-doc-id").value.trim(),
      title: document.getElementById("url-title").value.trim(),
      family: "legislation",
    };

    try {
      window.MesaUI.setElementBusy(btnSubmit, true, "İndiriliyor...");
      await apiRequest("/api/manual/import-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      showToast("URL başarıyla indirildi ve içe aktarıldı!");
      formUrl.reset();
      switchView("documents");
    } catch (err) {
      showToast(err.message, "danger");
    } finally {
      window.MesaUI.setElementBusy(btnSubmit, false);
    }
  });
}

// --- Documents Handler ---
async function loadDocuments() {
  try {
    setBusy(true);
    const q = document.getElementById("filter-doc-q").value.trim();
    const status = document.getElementById("filter-doc-status").value;
    const limit = 20;
    const offset = (state.docPage - 1) * limit;

    let url = `/api/documents?limit=${limit}&offset=${offset}`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;

    const data = await apiRequest(url);
    const tbl = document.getElementById("tbl-docs");
    tbl.innerHTML = "";

    document.getElementById("lbl-doc-page").textContent = `Sayfa ${state.docPage}`;

    if (data.items && data.items.length > 0) {
      data.items.forEach((doc) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${escapeHtml(doc.document_id)}</code></td>
          <td>${escapeHtml(doc.family)} / ${escapeHtml(doc.document_type)}</td>
          <td>${escapeHtml(doc.title || "-")}</td>
          <td>${statusBadge(doc.lifecycle_status)}</td>
          <td><code>${escapeHtml(doc.latest_artifact_id || "-")}</code></td>
          <td>${escapeHtml(doc.updated_at ? doc.updated_at.split("T")[0] : "-")}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="viewDocDetail('${escapeHtml(doc.document_id)}')">Detay</button>
            <button class="btn btn-primary btn-sm" onclick="runPipeline('${escapeHtml(doc.document_id)}')">Pipeline Çalıştır</button>
          </td>
        `;
        tbl.appendChild(tr);
      });
    } else {
      tbl.innerHTML = `<tr><td colspan="7" class="text-muted">Kayıt bulunamadı.</td></tr>`;
    }
  } catch (err) {
    console.error("Belgeler yüklenemedi:", err);
  } finally {
    setBusy(false);
  }
}

async function viewDocDetail(docId) {
  try {
    setBusy(true);
    const data = await apiRequest(`/api/documents/${encodeURIComponent(docId)}`);
    document.getElementById("doc-modal-title").textContent = `Belge Detayı: ${docId}`;

    const body = document.getElementById("doc-modal-body");
    body.innerHTML = `
      <div class="panel-box">
        <h4>Genel Bilgiler</h4>
        <p><strong>Belge Ailesi:</strong> ${escapeHtml(data.document.family)}</p>
        <p><strong>Tür:</strong> ${escapeHtml(data.document.document_type)}</p>
        <p><strong>Başlık:</strong> ${escapeHtml(data.document.title || "-")}</p>
        <p><strong>Durum:</strong> ${statusBadge(data.document.lifecycle_status)}</p>
      </div>
      <div class="panel-box">
        <h4>Raw Artifacts (${data.artifacts ? data.artifacts.length : 0})</h4>
        <div class="table-responsive">
          <table class="data-table">
            <thead>
              <tr><th>Artifact ID</th><th>Kaynak</th><th>MIME</th><th>Boyut</th><th>İndir</th></tr>
            </thead>
            <tbody>
              ${
                data.artifacts && data.artifacts.length > 0
                  ? data.artifacts
                      .map(
                        (a) => `
                    <tr>
                      <td><code>${escapeHtml(a.artifact_id)}</code></td>
                      <td>${escapeHtml(a.source_id)}</td>
                      <td>${escapeHtml(a.detected_content_type)}</td>
                      <td>${a.byte_size} B</td>
                      <td><a href="/api/artifacts/${encodeURIComponent(a.artifact_id)}/download" class="btn btn-secondary btn-sm" target="_blank">İndir</a></td>
                    </tr>
                  `
                      )
                      .join("")
                  : '<tr><td colspan="5">Artifact yok.</td></tr>'
              }
            </tbody>
          </table>
        </div>
      </div>
    `;

    showModal("modal-doc-detail");
  } catch (err) {
    console.error(err);
  } finally {
    setBusy(false);
  }
}

async function runPipeline(docId) {
  try {
    setBusy(true);
    await apiRequest(`/api/documents/${encodeURIComponent(docId)}/pipeline`, {
      method: "POST",
    });
    showToast("Pipeline işlemi başarıyla başlatıldı ve tamamlandı!");
    loadDocuments();
  } catch (err) {
    console.error(err);
  } finally {
    setBusy(false);
  }
}

// --- Reviews Handler ---
async function loadReviews() {
  try {
    setBusy(true);
    const status = document.getElementById("filter-review-status").value;
    const data = await apiRequest(`/api/reviews/records?status=${status}`);

    const tbl = document.getElementById("tbl-reviews");
    tbl.innerHTML = "";

    if (data && data.length > 0) {
      data.forEach((rec) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${escapeHtml(rec.record_id)}</code></td>
          <td>${escapeHtml(rec.record_type)}</td>
          <td><code>${escapeHtml(rec.document_id)}</code></td>
          <td>${rec.validation_ok ? '<span class="badge badge-success">OK</span>' : '<span class="badge badge-danger">Hata</span>'}</td>
          <td>${statusBadge(rec.approval_status)}</td>
          <td>${escapeHtml(rec.created_at ? rec.created_at.split("T")[0] : "-")}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="openReviewModal('${escapeHtml(rec.record_id)}')">İncele</button>
          </td>
        `;
        tbl.appendChild(tr);
      });
    } else {
      tbl.innerHTML = `<tr><td colspan="7" class="text-muted">İnceleme kaydı bulunmuyor.</td></tr>`;
    }
  } catch (err) {
    console.error("İncelemeler yüklenemedi:", err);
  } finally {
    setBusy(false);
  }
}

async function openReviewModal(recordId) {
  try {
    setBusy(true);
    state.currentRecordId = recordId;
    const data = await apiRequest(`/api/reviews/records/${encodeURIComponent(recordId)}`);
    state.currentVersionId = data.version_id;

    document.getElementById("record-modal-title").textContent = `Kayıt İnceleme: ${recordId}`;
    const body = document.getElementById("record-modal-body");
    body.innerHTML = `
      <div class="panel-box">
        <p><strong>Tür:</strong> ${escapeHtml(data.record_type)} | <strong>Document ID:</strong> <code>${escapeHtml(data.document_id)}</code></p>
        <p><strong>Validation Status:</strong> ${data.validation_ok ? '<span class="badge badge-success">OK</span>' : '<span class="badge badge-danger">Fail</span>'}</p>
      </div>
      <div class="panel-box">
        <h4>Payload (JSON)</h4>
        <pre class="code-box">${escapeHtml(JSON.stringify(JSON.parse(data.payload_json || "{}"), null, 2))}</pre>
      </div>
    `;

    showModal("modal-record-detail");
  } catch (err) {
    console.error(err);
  } finally {
    setBusy(false);
  }
}

function setupReviewHandlers() {
  document.getElementById("btn-record-approve").addEventListener("click", async () => {
    if (!state.currentRecordId || !state.currentVersionId) return;
    const reviewer = document.getElementById("txt-reviewer-name").value.trim() || "operator";
    const note = document.getElementById("txt-reviewer-note").value.trim();

    try {
      setBusy(true);
      await apiRequest(`/api/reviews/records/${encodeURIComponent(state.currentRecordId)}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: state.currentVersionId, reviewer: reviewer, note: note }),
      });
      showToast("Kayıt onaylandı!");
      closeModal("modal-record-detail");
      loadReviews();
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(false);
    }
  });

  document.getElementById("btn-record-reject").addEventListener("click", async () => {
    if (!state.currentRecordId || !state.currentVersionId) return;
    const reviewer = document.getElementById("txt-reviewer-name").value.trim() || "operator";
    const note = document.getElementById("txt-reviewer-note").value.trim();

    try {
      setBusy(true);
      await apiRequest(`/api/reviews/records/${encodeURIComponent(state.currentRecordId)}/reject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version_id: state.currentVersionId, reviewer: reviewer, note: note }),
      });
      showToast("Kayıt reddedildi!");
      closeModal("modal-record-detail");
      loadReviews();
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(false);
    }
  });
}

// --- Releases Handler ---
async function loadReleases() {
  try {
    setBusy(true);
    const data = await apiRequest("/api/releases");
    const tbl = document.getElementById("tbl-releases");
    tbl.innerHTML = "";

    if (data && data.length > 0) {
      data.forEach((rel) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${escapeHtml(rel.release_id)}</code></td>
          <td>${statusBadge(rel.status)}</td>
          <td>${rel.counts?.legislation || 0}</td>
          <td>${rel.counts?.article || 0}</td>
          <td>${rel.counts?.decision || 0}</td>
          <td>${rel.counts?.citation || 0}</td>
          <td>${escapeHtml(rel.created_at ? rel.created_at.split("T")[0] : "-")}</td>
          <td>
            ${rel.status === "created" ? `<button class="btn btn-primary btn-sm" onclick="publishRelease('${escapeHtml(rel.release_id)}')">Yayınla</button>` : ""}
            ${rel.status === "published" ? `<button class="btn btn-success btn-sm" onclick="importRelease('${escapeHtml(rel.release_id)}')">MESA'ya Aktar</button>` : ""}
            ${rel.status === "imported" ? `<button class="btn btn-danger btn-sm" onclick="rollbackRelease('${escapeHtml(rel.release_id)}')">Rollback</button>` : ""}
            <a href="/api/releases/${encodeURIComponent(rel.release_id)}/package" class="btn btn-secondary btn-sm" target="_blank">İndir</a>
          </td>
        `;
        tbl.appendChild(tr);
      });
    } else {
      tbl.innerHTML = `<tr><td colspan="8" class="text-muted">Release bulunamadı.</td></tr>`;
    }
  } catch (err) {
    console.error("Releaseler yüklenemedi:", err);
  } finally {
    setBusy(false);
  }
}

function setupReleaseBuildHandler() {
  document.getElementById("btn-build-release").addEventListener("click", async () => {
    const releaseId = document.getElementById("txt-release-id").value.trim();
    if (!releaseId) {
      showToast("Lütfen bir Release ID giriniz.", "warning");
      return;
    }

    try {
      setBusy(true);
      await apiRequest("/api/releases/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ release_id: releaseId }),
      });
      showToast("Release başarıyla paketlendi!");
      document.getElementById("txt-release-id").value = "";
      loadReleases();
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(false);
    }
  });
}

async function publishRelease(releaseId) {
  try {
    setBusy(true);
    await apiRequest(`/api/releases/${encodeURIComponent(releaseId)}/publish`, { method: "POST" });
    showToast("Release yayınlandı!");
    loadReleases();
  } catch (err) { console.error(err); } finally { setBusy(false); }
}

async function importRelease(releaseId) {
  try {
    setBusy(true);
    await apiRequest(`/api/releases/${encodeURIComponent(releaseId)}/import-to-mesa`, { method: "POST" });
    showToast("Release MESA'ya aktarıldı!");
    loadReleases();
  } catch (err) { console.error(err); } finally { setBusy(false); }
}

async function rollbackRelease(releaseId) {
  if (!confirm(`Release ${releaseId} geri çekilsin mi?`)) return;
  try {
    setBusy(true);
    await apiRequest(`/api/releases/${encodeURIComponent(releaseId)}/rollback`, { method: "POST" });
    showToast("Release geri çekildi!");
    loadReleases();
  } catch (err) { console.error(err); } finally { setBusy(false); }
}

// --- Explorer Handler ---
let explorerState = { page: 1, limit: 20 };
async function loadExplorer() {
  try {
    setBusy(true);
    const q = document.getElementById("filter-explorer-q").value.trim();
    const type = document.getElementById("filter-explorer-type").value;
    const approval = document.getElementById("filter-explorer-approval").value;
    const sort = document.getElementById("filter-explorer-sort").value;
    const offset = (explorerState.page - 1) * explorerState.limit;

    let url = `/api/explorer/records?limit=${explorerState.limit}&offset=${offset}&sort=${sort}`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    if (type) url += `&type=${encodeURIComponent(type)}`;
    if (approval) url += `&approval=${encodeURIComponent(approval)}`;

    const data = await apiRequest(url);
    document.getElementById("lbl-explorer-page").textContent = `Sayfa ${explorerState.page}`;

    const tbl = document.getElementById("tbl-explorer");
    tbl.innerHTML = "";

    if (data.items && data.items.length > 0) {
      data.items.forEach((item) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><input type="checkbox" value="${escapeHtml(item.record_id)}"></td>
          <td><code>${escapeHtml(item.record_id)}</code></td>
          <td>${escapeHtml(item.record_type)}</td>
          <td><code>${escapeHtml(item.document_id)}</code></td>
          <td>${escapeHtml(item.source_id)}</td>
          <td>${statusBadge(item.approval_status)}</td>
          <td>${item.validation_ok ? '<span class="badge badge-success">OK</span>' : '<span class="badge badge-danger">Fail</span>'}</td>
          <td>${escapeHtml(item.created_at ? item.created_at.split("T")[0] : "-")}</td>
        `;
        tbl.appendChild(tr);
      });
    } else {
      tbl.innerHTML = `<tr><td colspan="8" class="text-muted">Kayıt bulunamadı.</td></tr>`;
    }
  } catch (err) { console.error(err); } finally { setBusy(false); }
}

// --- Issues Handler ---
async function loadIssues() {
  try {
    setBusy(true);
    const status = document.getElementById("filter-issue-status").value;
    const severity = document.getElementById("filter-issue-severity").value;

    let url = "/api/issues?";
    if (status) url += `status=${encodeURIComponent(status)}&`;
    if (severity) url += `severity=${encodeURIComponent(severity)}`;

    const data = await apiRequest(url);
    const tbl = document.getElementById("tbl-issues");
    tbl.innerHTML = "";

    if (data && data.length > 0) {
      data.forEach((issue) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${escapeHtml(issue.issue_id)}</code></td>
          <td>${escapeHtml(issue.subject_type)}</td>
          <td><code>${escapeHtml(issue.subject_id)}</code></td>
          <td><span class="badge badge-${issue.severity === 'blocker' || issue.severity === 'error' ? 'danger' : 'warning'}">${escapeHtml(issue.severity)}</span></td>
          <td><code>${escapeHtml(issue.code)}</code></td>
          <td>${escapeHtml(issue.message)}</td>
          <td>${statusBadge(issue.status)}</td>
        `;
        tbl.appendChild(tr);
      });
    } else {
      tbl.innerHTML = `<tr><td colspan="7" class="text-muted">Sorun bulunmuyor.</td></tr>`;
    }
  } catch (err) { console.error(err); } finally { setBusy(false); }
}

// --- Sources Handler (Read Only) ---
async function loadSources() {
  try {
    setBusy(true);
    const data = await apiRequest("/api/sources");
    const container = document.getElementById("sources-list");
    container.innerHTML = "";

    if (data && data.length > 0) {
      data.forEach((src) => {
        const card = document.createElement("div");
        card.className = "stat-card";
        card.innerHTML = `
          <h4>${escapeHtml(src.name || src.source_id)} <code>(${escapeHtml(src.source_id)})</code></h4>
          <p><strong>Base URL:</strong> ${escapeHtml(src.base_url)}</p>
          <p><strong>Access Mode:</strong> ${escapeHtml(src.access_mode)} | <strong>Enabled:</strong> ${src.enabled ? "Evet" : "Hayır"}</p>
          <p><strong>Concurrency:</strong> ${src.http?.concurrency || 1} | <strong>Min Interval:</strong> ${src.http?.min_interval_seconds || 0}s | <strong>Max Download:</strong> ${Math.round((src.http?.max_download_bytes || 0) / 1024 / 1024)} MB</p>
        `;
        container.appendChild(card);
      });
    } else {
      container.innerHTML = `<p class="text-muted">Kaynak bilgisi yok.</p>`;
    }
  } catch (err) { console.error(err); } finally { setBusy(false); }
}

// --- Exports Handler ---
async function loadExports() {
  try {
    setBusy(true);
    const data = await apiRequest("/api/exports");
    const tbl = document.getElementById("tbl-exports");
    tbl.innerHTML = "";

    if (data && data.length > 0) {
      data.forEach((exp) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${escapeHtml(exp.export_id)}</code></td>
          <td>${escapeHtml(exp.export_type)}</td>
          <td>${statusBadge(exp.status)}</td>
          <td><code>${escapeHtml(exp.filename)}</code></td>
          <td>${escapeHtml(exp.created_at ? exp.created_at.split("T")[0] : "-")}</td>
          <td><a href="/api/exports/${encodeURIComponent(exp.export_id)}/download" class="btn btn-secondary btn-sm" target="_blank">İndir</a></td>
        `;
        tbl.appendChild(tr);
      });
    } else {
      tbl.innerHTML = `<tr><td colspan="6" class="text-muted">Dışa aktarma kaydı yok.</td></tr>`;
    }
  } catch (err) { console.error(err); } finally { setBusy(false); }
}

// --- Operations Handler ---
async function loadOperations() {
  try {
    setBusy(true);
    const data = await apiRequest("/api/operations/jobs");
    const tbl = document.getElementById("tbl-operations");
    tbl.innerHTML = "";

    if (data && data.length > 0) {
      data.forEach((job) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${escapeHtml(job.job_id)}</code></td>
          <td>${escapeHtml(job.operation_type)}</td>
          <td>${statusBadge(job.status)}</td>
          <td>${job.progress_pct || 0}%</td>
          <td>${escapeHtml(job.started_at ? job.started_at.split("T")[0] : "-")}</td>
          <td>${escapeHtml(job.completed_at ? job.completed_at.split("T")[0] : "-")}</td>
        `;
        tbl.appendChild(tr);
      });
    } else {
      tbl.innerHTML = `<tr><td colspan="6" class="text-muted">Operasyon kaydı yok.</td></tr>`;
    }
  } catch (err) { console.error(err); } finally { setBusy(false); }
}

// --- Audit Handler ---
async function loadAudit() {
  try {
    setBusy(true);
    const actor = document.getElementById("filter-audit-actor").value.trim();
    let url = "/api/audit/logs?limit=50";
    if (actor) url += `&actor=${encodeURIComponent(actor)}`;

    const data = await apiRequest(url);
    const tbl = document.getElementById("tbl-audit");
    tbl.innerHTML = "";

    if (data && data.length > 0) {
      data.forEach((log) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${escapeHtml(log.created_at ? log.created_at.replace("T", " ").substring(0, 19) : "-")}</td>
          <td>${escapeHtml(log.actor)}</td>
          <td><code>${escapeHtml(log.action)}</code></td>
          <td><code>${escapeHtml(log.subject_id || "-")}</code></td>
          <td><small>${escapeHtml(log.details_json || "-")}</small></td>
        `;
        tbl.appendChild(tr);
      });
    } else {
      tbl.innerHTML = `<tr><td colspan="5" class="text-muted">Audit kaydı yok.</td></tr>`;
    }
  } catch (err) { console.error(err); } finally { setBusy(false); }
}

// --- System Handler ---
async function loadSystem() {
  try {
    setBusy(true);
    const data = await apiRequest("/api/system/status");
    document.getElementById("sys-status-output").textContent = JSON.stringify(data, null, 2);
  } catch (err) { console.error(err); } finally { setBusy(false); }
}

function setupSystemHandlers() {
  document.getElementById("btn-sys-doctor").addEventListener("click", async () => {
    try {
      setBusy(true);
      const data = await apiRequest("/api/system/doctor", { method: "POST" });
      document.getElementById("sys-status-output").textContent = JSON.stringify(data, null, 2);
      showToast("Doctor kontrolü tamamlandı.");
    } catch (err) { console.error(err); } finally { setBusy(false); }
  });

  document.getElementById("btn-sys-backup").addEventListener("click", async () => {
    try {
      setBusy(true);
      const data = await apiRequest("/api/system/backup", { method: "POST" });
      showToast(`Backup alındı: ${data.backup_path || 'Tamamlandı'}`);
      loadSystem();
    } catch (err) { console.error(err); } finally { setBusy(false); }
  });
}

// --- Setup Modals & Mobile Controls ---
function setupModals() {
  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      closeModal(btn.dataset.close);
    });
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

  // Mobile menu listeners
  const btnMobile = document.getElementById("btn-mobile-menu");
  const overlay = document.getElementById("sidebar-overlay");
  if (btnMobile) {
    btnMobile.addEventListener("click", () => {
      const sidebar = document.getElementById("app-sidebar");
      if (sidebar) sidebar.classList.toggle("open");
      if (overlay) overlay.classList.toggle("open");
    });
  }
  if (overlay) {
    overlay.addEventListener("click", closeMobileSidebar);
  }

  // Theme selector listener
  const themeSelect = document.getElementById("sel-theme-control");
  if (themeSelect && window.MesaTheme) {
    themeSelect.value = window.MesaTheme.get();
    themeSelect.addEventListener("change", (e) => {
      window.MesaTheme.set(e.target.value);
    });
  }

  // Escape key closes modals
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      document.querySelectorAll(".modal-backdrop:not(.hidden)").forEach((m) => {
        closeModal(m.id);
      });
      closeMobileSidebar();
    }
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
  setupNewViewHandlers();

  // Load initial view
  switchView("dashboard");
});

function setupNewViewHandlers() {
  document.getElementById("btn-explorer-search").addEventListener("click", () => {
    explorerState.page = 1;
    loadExplorer();
  });
  document.getElementById("btn-explorer-prev").addEventListener("click", () => {
    if (explorerState.page > 1) { explorerState.page--; loadExplorer(); }
  });
  document.getElementById("btn-explorer-next").addEventListener("click", () => {
    explorerState.page++;
    loadExplorer();
  });
  document.getElementById("chk-explorer-all").addEventListener("change", (e) => {
    document.querySelectorAll("#tbl-explorer input[type='checkbox']").forEach((c) => {
      c.checked = e.target.checked;
    });
  });

  document.getElementById("btn-issue-filter").addEventListener("click", () => loadIssues());

  document.getElementById("btn-export-create").addEventListener("click", async () => {
    const exportType = document.getElementById("sel-export-type").value;
    try {
      setBusy(true);
      await apiRequest("/api/exports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ export_type: exportType }),
      });
      showToast("Export oluşturuldu!");
      loadExports();
    } catch (e) { console.error(e); }
    finally { setBusy(false); }
  });

  document.getElementById("btn-op-create").addEventListener("click", async () => {
    const opType = document.getElementById("sel-op-type").value;
    const scope = document.getElementById("txt-op-scope").value;
    try {
      setBusy(true);
      await apiRequest("/api/operations/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ operation_type: opType, input: { scope: scope } }),
      });
      showToast("İşlem başlatıldı!");
      loadOperations();
    } catch (e) { console.error(e); }
    finally { setBusy(false); }
  });

  document.getElementById("btn-audit-filter").addEventListener("click", () => loadAudit());
}
