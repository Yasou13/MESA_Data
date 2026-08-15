// MESA Legal Data — Frontend Application Logic
// Complete Product & UX Closure Implementation

const state = {
  currentView: "home",
  token: sessionStorage.getItem("mesa_admin_token") || "",
  busy: false,
  libPage: 1,
  libPageSize: 20,
  currentRecordId: null,
  currentDocId: null,
  harvestStatus: null,
  harvestPollTimer: null,
  activeReviewTab: "pending",
  issueFilterSubjectId: null,
};

const VIEW_DESCRIPTIONS = {
  home: "MESA Data ile resmî hukuk verilerini toplayın, inceleyin ve kullanıma hazır hale getirin.",
  collect: "Resmî hukuk kaynaklarından verileri sisteme ekleyin. Otomatik toplama için teknik ayar gerekmez.",
  library: "Sistemde kayıtlı tüm hukuk belgelerini listeleyin, arayın ve inceleyin.",
  review: "İşlenmiş kayıtları doğruluk ve kalite standartlarına göre gözden geçirin.",
  export: "Onaylanan verileri dosya olarak indirin veya doğrudan MESA’ya aktarın.",
  sources: "Resmî veri kaynaklarının kurallarını ve izinlerini görün.",
  explorer: "Ham veri kayıtlarını derinlemesine arayın ve inceleyin.",
  releases: "Sürüm paketleri oluşturun, doğrulayın ve durumlarını yönetin.",
  operations: "Arka planda çalışan sistem görevlerini izleyin.",
  audit: "Sistemde gerçekleşen eylemlerin işlem günlüğünü inceleyin.",
  system: "Sistem durumunu ve veritabanı bütünlüğünü denetleyin.",
};

const SOURCE_CAPABILITIES = {
  resmi_gazete: {
    family: "legislation",
    docTypes: [
      { id: "law", label: "Kanun" },
      { id: "presidential_decree", label: "Cumhurbaşkanlığı Kararnamesi" },
      { id: "presidential_decision", label: "Cumhurbaşkanı Kararı" },
      { id: "regulation", label: "Yönetmelik" },
      { id: "communique", label: "Tebliğ" },
    ],
  },
  mevzuat: {
    family: "legislation",
    docTypes: [
      { id: "law", label: "Kanun" },
      { id: "regulation", label: "Yönetmelik" },
      { id: "communique", label: "Tebliğ" },
    ],
  },
  aym: {
    family: "decision",
    docTypes: [
      { id: "decision", label: "Yargı Kararı (Bireysel Başvuru / Norm Denetimi)" },
    ],
  },
};

// --- Terminology & Presentation Helpers ---
function humanTerm(term) {
  if (!term) return "";
  const map = {
    law: "Kanun",
    presidential_decree: "Cumhurbaşkanlığı Kararnamesi",
    presidential_decision: "Cumhurbaşkanı Kararı",
    regulation: "Yönetmelik",
    communique: "Tebliğ",
    decision: "Yargı Kararı",
    legislation: "Mevzuat",
    article: "Madde",
    citation: "Atıf",
    resmi_gazete: "T.C. Resmî Gazete",
    mevzuat: "Mevzuat Bilgi Sistemi",
    aym: "Anayasa Mahkemesi",
    yargitay: "Yargıtay",
    danistay: "Danıştay",
    idle: "Hazır",
    running: "Çalışıyor",
    paused: "Duraklatıldı",
    up_to_date: "Güncel",
    attention: "Dikkat gerekiyor",
    succeeded: "Tamamlandı",
    failed: "Başarısız",
    cancelled: "İptal edildi",
    queued: "Kuyrukta",
    pending: "İnceleme bekliyor",
    approved: "Onaylandı",
    rejected: "Reddedildi",
    valid: "Geçerli",
    invalid: "Hatalı",
    warning: "Uyarı",
    verified: "Doğrulandı",
    published: "Yayınlandı",
    imported: "MESA'ya aktarıldı",
    revoked: "Geri çekildi",
    open: "Çözüm bekliyor",
    resolved: "Çözüldü",
    blocker: "Kritik",
    critical: "Kritik",
    error: "Yüksek (Hata)",
    high: "Yüksek",
    medium: "Orta",
    low: "Düşük",
    info: "Düşük (Bilgi)",
    record: "Kayıt",
    document: "Belge",
    version: "Belge Sürümü",
    source: "Kaynak",
    artifact: "Kaynak Dosya",
  };
  return map[term] || term;
}

function humanSeverityBadge(severity) {
  const s = String(severity || "error").toLowerCase();
  if (s === "blocker" || s === "critical") {
    return `<span class="badge badge-danger">Kritik</span>`;
  }
  if (s === "error" || s === "high") {
    return `<span class="badge badge-danger">Yüksek</span>`;
  }
  if (s === "warning" || s === "medium") {
    return `<span class="badge badge-warning">Orta</span>`;
  }
  if (s === "info" || s === "low") {
    return `<span class="badge badge-info">Düşük</span>`;
  }
  return `<span class="badge badge-neutral">${escapeHtml(humanTerm(s))}</span>`;
}

function humanIssueMessage(code, message) {
  const codeMap = {
    TRANSPORT_VERIFICATION_FAILED: "Dosya bütünlüğü veya aktarım doğrulaması başarısız oldu. Dosya boyutu veya biçimi beklenenden farklı.",
    PARSING_FAILED: "Belge metni okunamadı. Dosyanın içeriği ayrıştırılamadı; dosya formatını kontrol edin veya yeniden işlemeyi deneyin.",
    SCHEMA_VALIDATION_FAILED: "Belge veri şemasına uymuyor. Hukuki veri alanları veya yapısı standartlara uygun değil.",
    PRIVACY_TCKN_DETECTED: "T.C. Kimlik Numarası (TCKN) tespit edildi. Belgede korunması gereken kişisel veri bulundu.",
    PRIVACY_IBAN_DETECTED: "Banka hesap numarası (IBAN) tespit edildi. Belgede kişisel finansal bilgi bulundu.",
    PRIVACY_PHONE_DETECTED: "Telefon numarası tespit edildi. Belgede kişisel iletişim bilgisi bulundu.",
    PRIVACY_EMAIL_DETECTED: "E-posta adresi tespit edildi. Belgede kişisel iletişim bilgisi bulundu.",
    VALIDATION_DATE_MISSING: "Belgedeki tarih bilgisi okunamadı veya eksik.",
    VALIDATION_TITLE_MISSING: "Belge başlığı tespit edilemedi.",
    VALIDATION_SCHEMA_INVALID: "Belge yapısı veya şema doğrulaması başarısız.",
    HASH_MISMATCH: "Veri bütünlüğü doğrulaması uyuşmadı (SHA256).",
    CANONICAL_LINE_MISSING: "Kanonik veri dosyasında ilgili kayıt satırı bulunamadı.",
    DUPLICATE_ITEM: "Aynı içerikli mükerrer kayıt tespit edildi.",
    PARSER_ERROR: "Belge içeriği ayrıştırılırken hata oluştu.",
    BLOCKING_ISSUES_EXIST: "Çözülmesi gereken kritik doğrulama sorunları bulunuyor.",
    SOURCE_FAMILY_NOT_ALLOWED: "Seçilen kaynak ile belge türü ailesi uyuşmuyor.",
    SOURCE_DISABLED: "Seçilen kaynak şu anda sistemde devre dışı bırakılmış.",
    SOURCE_NOT_FOUND: "Belirtilen kaynak sistemde tanımlı değil.",
    SOURCE_REQUIRED: "Kaynak belirtilmesi zorunludur.",
    SOURCE_FAMILY_REQUIRED: "Belge ailesi belirtilmesi zorunludur.",
    USER_AGENT_INVALID: "Kaynak erişim ayarlarında geçersiz kullanıcı aracısı tespit edildi.",
    WRITE_LOCK_CONFLICT: "Başka bir yazma işlemi devam ediyor. Lütfen birkaç saniye sonra tekrar deneyin.",
    RATE_LIMIT_EXCEEDED: "İstek sınırı aşıldı. Lütfen bir süre bekleyin.",
    RECORD_APPROVE_BLOCKED: "Kayıt üzerinde açık kritik sorunlar bulunduğu için onaylanamaz.",
    VERSION_APPROVE_BLOCKED: "Belge sürümü üzerinde açık kritik sorunlar bulunduğu için onaylanamaz.",
    INVALID_DOCUMENT_TYPES: "En az bir geçerli belge türü seçilmelidir.",
    INVALID_START_DATE: "Geçersiz başlangıç tarihi seçimi.",
    HARVEST_ALREADY_RUNNING: "Veri toplama işlemi zaten devam ediyor.",
  };

  if (code && codeMap[code]) {
    return codeMap[code];
  }
  if (message && !message.startsWith("Validation error in") && !message.startsWith("Cannot approve") && !message.includes("Open blocker issues") && !message.includes("failed:") && !message.includes("expected") && !message.includes("detected") && !message.includes("not allowed")) {
    return message;
  }
  return "Belgenin işlenmesi sırasında bir sorun oluştu.";
}

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
    if (isBusy) spinner.classList.remove("hidden");
    else spinner.classList.add("hidden");
  }
}

function statusBadge(statusStr) {
  const label = humanTerm(statusStr);
  let badgeClass = "badge-neutral";
  if (["approved", "verified", "published", "imported", "succeeded", "up_to_date", "valid", "resolved"].includes(statusStr)) badgeClass = "badge-success";
  if (["needs_review", "pending", "running", "warning", "open"].includes(statusStr)) badgeClass = "badge-warning";
  if (["rejected", "failed", "revoked", "invalid", "attention", "blocker", "critical"].includes(statusStr)) badgeClass = "badge-danger";
  if (["fetched", "queued", "paused", "info", "low"].includes(statusStr)) badgeClass = "badge-info";

  return `<span class="badge ${badgeClass}">${escapeHtml(label)}</span>`;
}

function friendlyDate(isoStr) {
  if (!isoStr) return "-";
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    return d.toLocaleString("tr-TR", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch (e) {
    return isoStr;
  }
}

// --- API Client ---
async function apiRequest(endpoint, options = {}) {
  const headers = options.headers || {};

  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }

  const method = (options.method || "GET").toUpperCase();
  if (["POST", "PUT", "DELETE", "PATCH"].includes(method)) {
    headers["X-MESA-Requested-With"] = "web-admin";
    headers["X-MESA-Actor"] = sessionStorage.getItem("mesa_actor") || "web-user";
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
      if (response.status >= 500) {
        setApiStatus("offline");
      }
      const msg = result.error?.message || `API Hatası: ${response.status}`;
      showToast(msg, "danger");
      throw new Error(msg);
    }

    return result.data;
  } catch (err) {
    if (err.name === "TypeError" || err.message.includes("Failed to fetch") || err.message.includes("NetworkError")) {
      setApiStatus("offline");
    }
    if (!err.message.includes("API Hatası")) {
      console.error(err);
    }
    throw err;
  }
}

function setApiStatus(status) {
  const el = document.getElementById("api-status");
  const textEl = document.getElementById("api-status-text");
  if (!el || !textEl) return;

  el.className = "status-indicator api-status";
  if (status === "online") {
    el.classList.add("status-online");
    textEl.textContent = "API erişilebilir";
  } else if (status === "offline") {
    el.classList.add("status-offline");
    textEl.textContent = "API erişilemiyor";
  } else {
    el.classList.add("status-checking");
    textEl.textContent = "Durum kontrol ediliyor…";
  }
}

async function refreshApiStatus() {
  try {
    const res = await fetch("/api/health");
    if (res.ok) {
      setApiStatus("online");
    } else {
      setApiStatus("offline");
    }
  } catch (e) {
    setApiStatus("offline");
  }
}

// --- Navigation & View Switching ---
function switchView(viewName) {
  state.currentView = viewName;

  // Update URL hash without reload
  history.replaceState(null, "", `#${viewName}`);

  // Update Header Title & Description
  const titleEl = document.getElementById("view-title");
  const descEl = document.getElementById("view-desc");
  if (titleEl) {
    const titles = {
      home: "Ana Sayfa",
      collect: "Veri Topla",
      library: "Kütüphane",
      review: "İnceleme",
      export: "Dışa Aktar",
      sources: "Kaynaklar",
      explorer: "Veri Gezgini",
      releases: "Release Geçmişi",
      operations: "Arka Plan İşlemleri",
      audit: "İşlem Geçmişi",
      system: "Sistem",
    };
    titleEl.textContent = titles[viewName] || "MESA Data";
  }
  if (descEl) {
    descEl.textContent = VIEW_DESCRIPTIONS[viewName] || "";
  }

  // Update Nav Buttons
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    if (btn.dataset.view === viewName) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });

  // Switch View Panel
  document.querySelectorAll(".view-panel").forEach((panel) => {
    if (panel.id === `view-${viewName}`) {
      panel.classList.remove("hidden");
      panel.classList.add("active");
    } else {
      panel.classList.add("hidden");
      panel.classList.remove("active");
    }
  });

  closeMobileSidebar();

  // Route View Loaders
  if (viewName === "home") loadHomeView();
  else if (viewName === "collect") loadCollectView();
  else if (viewName === "library") loadLibraryView();
  else if (viewName === "review") loadReviewView();
  else if (viewName === "export") loadExportView();
  else if (viewName === "sources") loadSourcesView();
  else if (viewName === "explorer") loadExplorerView();
  else if (viewName === "releases") loadReleasesView();
  else if (viewName === "operations") loadOperationsView();
  else if (viewName === "audit") loadAuditView();
  else if (viewName === "system") loadSystemView();
}

function closeMobileSidebar() {
  const sidebar = document.getElementById("app-sidebar");
  const overlay = document.getElementById("sidebar-overlay");
  const mobileBtn = document.getElementById("btn-mobile-menu");
  if (sidebar) sidebar.classList.remove("open");
  if (overlay) overlay.classList.remove("open");
  if (mobileBtn) mobileBtn.setAttribute("aria-expanded", "false");
  document.body.classList.remove("drawer-open");
}

// --- 1. HOME VIEW ---
async function loadHomeView() {
  setBusy(true);
  try {
    const [dash, harvest] = await Promise.all([
      apiRequest("/api/dashboard"),
      apiRequest("/api/harvest/status"),
    ]);

    state.harvestStatus = harvest;

    const totalDocs = dash.counts?.documents || 0;
    const isFirstRun = totalDocs === 0 && harvest.state === "not_started";

    const welcomeCard = document.getElementById("home-welcome-card");
    const normalContainer = document.getElementById("home-normal-container");

    if (isFirstRun) {
      if (welcomeCard) welcomeCard.classList.remove("hidden");
      if (normalContainer) normalContainer.classList.add("hidden");
      return;
    }

    if (welcomeCard) welcomeCard.classList.add("hidden");
    if (normalContainer) normalContainer.classList.remove("hidden");

    // Metrics
    document.getElementById("stat-docs").textContent = totalDocs;
    document.getElementById("stat-pending").textContent = dash.counts?.pending_reviews || 0;
    document.getElementById("stat-issues").textContent = (dash.counts?.open_blockers || 0) + (dash.counts?.open_errors || 0);

    const lastHarvestEl = document.getElementById("stat-last-harvest");
    if (lastHarvestEl) {
      lastHarvestEl.textContent = harvest.last_discovery_at ? friendlyDate(harvest.last_discovery_at) : (harvest.state === "running" ? "Şu anda çalışıyor" : "-");
    }

    // Recommended Next Action Card
    const nextActionCard = document.getElementById("home-next-action");
    const nextTitle = document.getElementById("next-action-title");
    const nextDesc = document.getElementById("next-action-desc");
    const nextBtn = document.getElementById("btn-next-action");

    nextActionCard.className = "next-action-card";
    if (harvest.state === "running") {
      nextTitle.textContent = "Veri toplama işlemi devam ediyor";
      nextDesc.textContent = harvest.message || "Resmî Gazete verileri arka planda taranıyor ve sisteme ekleniyor.";
      nextBtn.textContent = "Toplamayı Gör";
      nextBtn.onclick = () => switchView("collect");
    } else if (harvest.state === "attention" || (dash.counts?.open_blockers || 0) > 0) {
      nextActionCard.classList.add("attention");
      nextTitle.textContent = "Dikkat gerektiren sorunlar var";
      nextDesc.textContent = "Veri kalitesi veya toplama sırasında incelenmesi gereken sorunlar oluştu.";
      nextBtn.textContent = "Sorunları Gör";
      nextBtn.onclick = () => {
        state.activeReviewTab = "issues";
        switchView("review");
      };
    } else if ((dash.counts?.pending_reviews || 0) > 0) {
      nextActionCard.classList.add("warning");
      nextTitle.textContent = `${dash.counts.pending_reviews} kayıt inceleme bekliyor`;
      nextDesc.textContent = "Dışa aktarmadan önce işlenmiş hukuk kayıtlarını onaylayınız.";
      nextBtn.textContent = "İncelemeye Git";
      nextBtn.onclick = () => {
        state.activeReviewTab = "pending";
        switchView("review");
      };
    } else if (totalDocs === 0) {
      nextTitle.textContent = "Veri toplamaya başlayın";
      nextDesc.textContent = "Resmî Gazete'den otomatik olarak veri toplayabilir veya dosya yükleyebilirsiniz.";
      nextBtn.textContent = "Veri Topla";
      nextBtn.onclick = () => switchView("collect");
    } else {
      nextTitle.textContent = "Tüm veriler güncel ve hazır";
      nextDesc.textContent = "Onaylanan verileri dosya olarak indirebilir veya MESA'ya aktarabilirsiniz.";
      nextBtn.textContent = "Dışa Aktar";
      nextBtn.onclick = () => switchView("export");
    }

    // Harvest summary card
    document.getElementById("home-harvest-message").textContent = harvest.message;
    document.getElementById("home-harvest-badge").innerHTML = statusBadge(harvest.state);
    document.getElementById("home-harvest-coverage").textContent = `${harvest.coverage_percent || 0}%`;
    document.getElementById("home-harvest-completed").textContent = harvest.completed || 0;
    document.getElementById("home-harvest-review").textContent = harvest.needs_review || 0;
    document.getElementById("home-harvest-progress-bar").style.width = `${harvest.coverage_percent || 0}%`;

    const ctaBtn = document.getElementById("btn-home-harvest-cta");
    if (harvest.state === "running") {
      ctaBtn.textContent = "Toplamayı Gör";
    } else if (harvest.state === "up_to_date") {
      ctaBtn.textContent = "Güncel Verileri Kontrol Et";
    } else {
      ctaBtn.textContent = "Veri Topla";
    }
    ctaBtn.onclick = () => switchView("collect");

    // Recent Documents
    const docsTbody = document.getElementById("tbl-recent-docs");
    if (docsTbody) {
      docsTbody.innerHTML = "";
      if (dash.recent_documents && dash.recent_documents.length > 0) {
        dash.recent_documents.forEach((d) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td><strong>${escapeHtml(d.title || d.document_id)}</strong></td>
            <td>${humanTerm(d.document_type)}</td>
            <td>${statusBadge(d.status)}</td>
            <td>${friendlyDate(d.updated_at)}</td>
          `;
          docsTbody.appendChild(tr);
        });
      } else {
        docsTbody.innerHTML = `<tr><td colspan="4" class="empty-state">Henüz eklenen belge yok.</td></tr>`;
      }
    }

    // Recent Runs
    const runsTbody = document.getElementById("tbl-recent-runs");
    if (runsTbody) {
      runsTbody.innerHTML = "";
      if (dash.recent_runs && dash.recent_runs.length > 0) {
        dash.recent_runs.forEach((r) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${humanTerm(r.operation_type || r.target_type)}</td>
            <td>${statusBadge(r.status)}</td>
            <td>${friendlyDate(r.created_at)}</td>
          `;
          runsTbody.appendChild(tr);
        });
      } else {
        runsTbody.innerHTML = `<tr><td colspan="3" class="empty-state">Henüz işlem geçmişi yok.</td></tr>`;
      }
    }
  } catch (err) {
    console.error("Home view error:", err);
  } finally {
    setBusy(false);
  }
}

// --- 2. COLLECT VIEW ---
async function loadCollectView() {
  setBusy(true);
  try {
    updateDocTypesForSource("file-source", "file-doc-type");
    updateDocTypesForSource("url-source", "url-doc-type");
    await updateHarvestCardState();
  } catch (err) {
    console.error("Collect view error:", err);
  } finally {
    setBusy(false);
  }
}

async function updateHarvestCardState() {
  const harvest = await apiRequest("/api/harvest/status");
  state.harvestStatus = harvest;

  // Status badge
  const badgeEl = document.getElementById("collect-status-badge");
  if (badgeEl) badgeEl.innerHTML = statusBadge(harvest.state);

  // Progress UI
  const progressText = document.getElementById("collect-progress-text");
  const progressPct = document.getElementById("collect-progress-pct");
  const progressBar = document.getElementById("collect-progress-bar");
  const cursorText = document.getElementById("collect-cursor-text");

  const pct = harvest.coverage_percent || 0;
  if (progressPct) progressPct.textContent = `${pct}%`;
  if (progressBar) progressBar.style.width = `${pct}%`;

  if (progressText) {
    if (harvest.state === "running") {
      progressText.textContent = harvest.mode === "incremental" ? "Güncel veriler kontrol ediliyor" : "Geçmiş veriler toplanıyor";
    } else if (harvest.state === "up_to_date") {
      progressText.textContent = "Veriler güncel";
    } else if (harvest.state === "paused") {
      progressText.textContent = "Toplama duraklatıldı";
    } else if (harvest.state === "attention") {
      progressText.textContent = "Güvenlik duraklaması";
    } else {
      progressText.textContent = "Henüz başlanmadı";
    }
  }

  if (cursorText) {
    if (harvest.cursor_date) {
      cursorText.textContent = `Şu anda: ${harvest.cursor_date} civarı taranıyor`;
    } else {
      cursorText.textContent = `Şu anda: -`;
    }
  }

  document.getElementById("collect-stat-found").textContent = harvest.total_items || 0;
  document.getElementById("collect-stat-completed").textContent = harvest.completed || 0;
  document.getElementById("collect-stat-review").textContent = harvest.needs_review || 0;

  // Buttons
  const startBtn = document.getElementById("btn-collect-start");
  const stopBtn = document.getElementById("btn-collect-stop");

  if (harvest.state === "running") {
    if (startBtn) {
      startBtn.textContent = "Toplama Devam Ediyor";
      startBtn.disabled = true;
    }
    if (stopBtn) stopBtn.classList.remove("hidden");

    // Start auto polling if not running
    if (!state.harvestPollTimer) {
      state.harvestPollTimer = setInterval(async () => {
        if (state.currentView === "collect" || state.currentView === "home") {
          await updateHarvestCardState();
        }
      }, 4000);
    }
  } else {
    if (startBtn) {
      startBtn.disabled = false;
      if (harvest.state === "up_to_date") {
        startBtn.textContent = "Güncel Verileri Kontrol Et";
      } else if (harvest.state === "paused" || harvest.state === "attention") {
        startBtn.textContent = "Devam Et";
      } else {
        startBtn.textContent = "Toplamayı Başlat";
      }
    }
    if (stopBtn) stopBtn.classList.add("hidden");

    // Clear polling
    if (state.harvestPollTimer) {
      clearInterval(state.harvestPollTimer);
      state.harvestPollTimer = null;
    }
  }
}

async function startHarvestAction() {
  const startDateInput = document.getElementById("collect-start-date");
  const startDate = startDateInput ? startDateInput.value.trim() : "2015-01-01";

  const docTypes = [];
  ["law", "decree", "decision", "regulation", "communique"].forEach((key) => {
    const chk = document.getElementById(`chk-type-${key}`);
    if (chk && chk.checked) docTypes.push(chk.value);
  });

  if (docTypes.length === 0) {
    showToast("En az bir belge türü seçmelisiniz.", "warning");
    return;
  }

  setBusy(true);
  try {
    await apiRequest("/api/harvest/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_id: "resmi_gazete",
        start_date: startDate || null,
        document_types: docTypes,
      }),
    });
    showToast("Veri toplama işlemi başlatıldı.", "success");
    await updateHarvestCardState();
  } catch (err) {
    console.error("Start harvest error:", err);
  } finally {
    setBusy(false);
  }
}

async function stopHarvestAction() {
  setBusy(true);
  try {
    await apiRequest("/api/harvest/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    showToast("Veri toplama durduruldu.", "warning");
    await updateHarvestCardState();
  } catch (err) {
    console.error("Stop harvest error:", err);
  } finally {
    setBusy(false);
  }
}

// --- 3. LIBRARY VIEW ---
async function loadLibraryView() {
  setBusy(true);
  try {
    const q = document.getElementById("filter-lib-q")?.value.trim() || "";
    const source = document.getElementById("filter-lib-source")?.value || "";
    const status = document.getElementById("filter-lib-status")?.value || "";

    const params = new URLSearchParams({
      page: state.libPage,
      page_size: state.libPageSize,
    });
    if (q) params.set("q", q);
    if (source) params.set("source", source);
    if (status) params.set("status", status);

    const res = await apiRequest(`/api/documents?${params.toString()}`);
    const items = res.items || [];
    const total = res.total || 0;

    const tbody = document.getElementById("tbl-library");
    tbody.innerHTML = "";

    if (items.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="6" class="empty-state">
            <div class="empty-state-card" style="padding: 30px; text-align: center;">
              <h4 style="margin: 0 0 6px 0; font-size: 15px;">Henüz kütüphanenizde belge yok</h4>
              <p style="margin: 0 0 14px 0; color: var(--color-text-secondary); font-size: 13px;">Resmî Gazete'den veri toplayabilir veya kendi belgenizi ekleyebilirsiniz.</p>
              <div style="display: flex; gap: 10px; justify-content: center;">
                <button type="button" class="btn btn-primary btn-sm" onclick="switchView('collect')">Veri Topla</button>
                <button type="button" class="btn btn-secondary btn-sm" onclick="switchView('collect'); setTimeout(() => { document.querySelector('[data-tab=\&quot;tab-manual-file\&quot;]')?.click(); document.getElementById('manual-ingestion-box')?.scrollIntoView({behavior:'smooth'}); }, 100);">Dosya Yükle</button>
              </div>
            </div>
          </td>
        </tr>
      `;
      document.getElementById("lbl-lib-page").textContent = "Sayfa 1 / 1 (0 Belge)";
      document.getElementById("btn-lib-prev").disabled = true;
      document.getElementById("btn-lib-next").disabled = true;
      return;
    }

    items.forEach((doc) => {
      const tr = document.createElement("tr");
      const docStatus = doc.lifecycle_status || doc.status || "fetched";
      const sourceId = doc.source_id || "resmi_gazete";
      tr.innerHTML = `
        <td><strong>${escapeHtml(doc.title || doc.document_id)}</strong></td>
        <td>${humanTerm(doc.document_type)}</td>
        <td>${humanTerm(sourceId)}</td>
        <td>${statusBadge(docStatus)}</td>
        <td>${friendlyDate(doc.updated_at)}</td>
        <td>
          <button class="btn btn-sm btn-secondary" onclick="viewDocDetail('${escapeHtml(doc.document_id)}')">Detay</button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    const totalPages = Math.ceil(total / state.libPageSize) || 1;
    document.getElementById("lbl-lib-page").textContent = `Sayfa ${state.libPage} / ${totalPages} (${total} Belge)`;
    document.getElementById("btn-lib-prev").disabled = state.libPage <= 1;
    document.getElementById("btn-lib-next").disabled = state.libPage >= totalPages;
  } catch (err) {
    console.error("Library view error:", err);
  } finally {
    setBusy(false);
  }
}

async function viewDocDetail(documentId) {
  setBusy(true);
  try {
    const [doc, textRes] = await Promise.all([
      apiRequest(`/api/documents/${encodeURIComponent(documentId)}`),
      apiRequest(`/api/documents/${encodeURIComponent(documentId)}/text`).catch(() => ({ content: null })),
    ]);
    state.currentDocId = documentId;

    const sourceId = doc.source_id || (doc.artifacts && doc.artifacts[0]?.source_id) || "resmi_gazete";
    const docStatus = doc.lifecycle_status || doc.status || "fetched";
    const textContent = (textRes && textRes.content && textRes.content !== "Metin içeriği bulunamadı.")
      ? textRes.content
      : (doc.text_preview || doc.raw_text || (textRes && textRes.content) || "Metin içeriği henüz işlenmedi.");

    let openIssuesHtml = "";
    if (doc.open_issues && doc.open_issues.length > 0) {
      openIssuesHtml = `
        <div class="alert alert-warning" style="margin-top: 10px; font-size: 13px;">
          <strong>Açık Sorunlar (${doc.open_issues.length}):</strong>
          <ul style="margin: 4px 0 0 16px; padding: 0;">
            ${doc.open_issues.map((i) => `<li>${humanSeverityBadge(i.severity)} ${escapeHtml(humanIssueMessage(i.code, i.message))}</li>`).join("")}
          </ul>
        </div>
      `;
    }

    const modalBody = document.getElementById("doc-modal-body");
    modalBody.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 10px;">
        <div>
          <h4>${escapeHtml(doc.title || doc.document_id)}</h4>
          <span style="font-size: 13px; color: var(--color-text-secondary);">${humanTerm(sourceId)} · ${humanTerm(doc.document_type)}</span>
        </div>
        ${statusBadge(docStatus)}
      </div>

      ${openIssuesHtml}

      <div style="margin-top: 10px;">
        <label style="font-size: 12px; font-weight: 700; color: var(--color-text-muted);">Belge Metni</label>
        <pre class="code-box" style="margin-top: 4px; max-height: 280px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;">${escapeHtml(textContent)}</pre>
      </div>

      <details class="technical-details">
        <summary>Teknik ayrıntılar</summary>
        <div class="technical-details-content">
          <div><strong>Belge Kimliği:</strong> <code class="mono">${escapeHtml(doc.document_id)}</code></div>
          <div><strong>Aile:</strong> ${escapeHtml(doc.family || "-")}</div>
          <div><strong>Artifact ID:</strong> <code class="mono">${escapeHtml(doc.artifacts?.[0]?.artifact_id || "-")}</code></div>
          <div><strong>SHA256:</strong> <code class="mono">${escapeHtml(doc.artifacts?.[0]?.sha256 || "-")}</code></div>
          <div><strong>Kayıt Sayısı:</strong> ${doc.record_count || 0}</div>
        </div>
      </details>
    `;

    showModal("modal-doc-detail");
  } catch (err) {
    console.error("View doc detail error:", err);
  } finally {
    setBusy(false);
  }
}

// --- 4. REVIEW VIEW ---
async function loadReviewView() {
  setBusy(true);
  try {
    // Activate current review tab
    document.querySelectorAll("[data-review-tab]").forEach((btn) => {
      if (btn.dataset.reviewTab === state.activeReviewTab) btn.classList.add("active");
      else btn.classList.remove("active");
    });

    if (state.activeReviewTab === "pending") {
      document.getElementById("review-tab-pending").classList.remove("hidden");
      document.getElementById("review-tab-issues").classList.add("hidden");

      const res = await apiRequest("/api/records?page=1&page_size=50&approval_status=pending");
      const items = res.items || [];
      const tbody = document.getElementById("tbl-reviews");
      tbody.innerHTML = "";

      if (items.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="6" class="empty-state">
              <div class="empty-state-card" style="padding: 30px; text-align: center;">
                <h4 style="margin: 0 0 6px 0; font-size: 15px;">Şu anda inceleme bekleyen kayıt yok</h4>
                <p style="margin: 0 0 14px 0; color: var(--color-text-secondary); font-size: 13px;">Hazır verilerinizi dışa aktarabilir veya yeni veri toplamaya devam edebilirsiniz.</p>
                <div style="display: flex; gap: 10px; justify-content: center;">
                  <button type="button" class="btn btn-primary btn-sm" onclick="switchView('export')">Dışa Aktar</button>
                  <button type="button" class="btn btn-secondary btn-sm" onclick="switchView('collect')">Veri Topla</button>
                </div>
              </div>
            </td>
          </tr>
        `;
        return;
      }

      items.forEach((rec) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><strong>${escapeHtml(rec.document_title || rec.document_id || "Belge")}</strong></td>
          <td>${humanTerm(rec.record_type)}</td>
          <td>${statusBadge(rec.validation_status || "valid")}</td>
          <td>${statusBadge(rec.approval_status || "pending")}</td>
          <td>${friendlyDate(rec.created_at)}</td>
          <td>
            <button class="btn btn-sm btn-primary" onclick="openRecordReviewModal('${escapeHtml(rec.record_id)}')">İncele</button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    } else {
      document.getElementById("review-tab-pending").classList.add("hidden");
      document.getElementById("review-tab-issues").classList.remove("hidden");

      let url = "/api/issues";
      if (state.issueFilterSubjectId) {
        url += `?subject_id=${encodeURIComponent(state.issueFilterSubjectId)}`;
      }

      const res = await apiRequest(url);
      const items = Array.isArray(res) ? res : (res?.items || []);
      const tbody = document.getElementById("tbl-issues-list");
      tbody.innerHTML = "";

      if (items.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="5" class="empty-state">
              <div class="empty-state-card" style="padding: 30px; text-align: center;">
                <h4 style="margin: 0 0 6px 0; font-size: 15px;">Çözülmesi gereken sorun yok</h4>
                <p style="margin: 0; color: var(--color-text-secondary); font-size: 13px;">Sistem şu anda kullanıcı müdahalesi gerektiren bir sorun bildirmiyor.</p>
                ${state.issueFilterSubjectId ? `<div style="margin-top: 12px;"><button type="button" class="btn btn-sm btn-secondary" onclick="state.issueFilterSubjectId=null; loadReviewView();">Tüm Sorunları Göster</button></div>` : ""}
              </div>
            </td>
          </tr>
        `;
        return;
      }

      items.forEach((iss) => {
        const tr = document.createElement("tr");
        let docTitle = iss.document_title;
        if (!docTitle) {
          if (iss.subject_type === "artifact" || iss.subject_id?.startsWith("sha256:")) {
            const srcLabel = iss.source_id ? ` (${humanTerm(iss.source_id)})` : "";
            docTitle = `İşlenemeyen kaynak dosya${srcLabel}`;
          } else {
            docTitle = `İşlenemeyen veri kaydı`;
          }
        }
        const issueMsg = humanIssueMessage(iss.code, iss.message);
        const statusLabel = iss.status === "resolved" ? "Çözüldü" : "Çözüm bekliyor";
        const statusBadgeHtml = iss.status === "resolved" ? `<span class="badge badge-success">${statusLabel}</span>` : `<span class="badge badge-warning">${statusLabel}</span>`;

        let actionHtml = "";
        if (iss.document_id) {
          actionHtml += `<button type="button" class="btn btn-sm btn-secondary" onclick="viewDocDetail('${escapeHtml(iss.document_id)}')">Belgeyi Gör</button> `;
        }
        if (iss.subject_type === "record" || iss.subject_id?.startsWith("rec-")) {
          actionHtml += `<button type="button" class="btn btn-sm btn-secondary" onclick="openRecordReviewModal('${escapeHtml(iss.subject_id)}')">Kaydı İncele</button> `;
        }
        if (iss.status === "open") {
          actionHtml += `<button type="button" class="btn btn-sm btn-outline" onclick="openResolveIssueModal('${escapeHtml(iss.issue_id)}', '${escapeHtml(iss.severity || '')}', '${escapeHtml(iss.code || '')}')">Manuel Çözüldü Kabul Et</button>`;
        }

        tr.innerHTML = `
          <td>
            <strong>${escapeHtml(docTitle)}</strong>
            <div style="font-size: 12px; color: var(--color-text-secondary);">${humanTerm(iss.subject_type || "kayıt")}</div>
          </td>
          <td>
            <div>${escapeHtml(issueMsg)}</div>
            <details class="technical-details" style="margin-top: 4px;">
              <summary style="font-size: 11px;">Teknik ayrıntılar</summary>
              <div class="technical-details-content" style="font-size: 11px; padding: 4px 8px;">
                <code>${escapeHtml(iss.code || "-")}</code> · ID: <code class="mono">${escapeHtml(iss.issue_id)}</code>
                ${iss.subject_id ? ` · Konu: <code class="mono">${escapeHtml(iss.subject_id)}</code>` : ""}
              </div>
            </details>
          </td>
          <td>${humanSeverityBadge(iss.severity)}</td>
          <td>${statusBadgeHtml}</td>
          <td><div style="display: flex; flex-wrap: wrap; gap: 4px;">${actionHtml || "-"}</div></td>
        `;
        tbody.appendChild(tr);
      });
    }
  } catch (err) {
    console.error("Review view error:", err);
  } finally {
    setBusy(false);
  }
}

function showRecordIssues(recordId) {
  closeModal("modal-record-detail");
  state.activeReviewTab = "issues";
  state.issueFilterSubjectId = recordId;
  switchView("review");
}

let pendingResolveIssueState = null;

function openResolveIssueModal(issueId, severity, code) {
  pendingResolveIssueState = { issueId, severity, code };
  const warningEl = document.getElementById("resolve-modal-warning");
  const noteInput = document.getElementById("txt-resolve-note");
  if (noteInput) noteInput.value = "";

  const isBlockerOrPrivacy = (severity === "blocker" || severity === "critical" || String(code).startsWith("PRIVACY_"));
  if (warningEl) {
    if (isBlockerOrPrivacy) {
      warningEl.className = "alert alert-danger";
      warningEl.innerHTML = `
        <strong>DİKKAT (Kritik / Kişisel Veri Doğrulama Uyarısı):</strong><br>
        Bu sorun <strong>${escapeHtml(humanTerm(severity) || "Kritik")}</strong> seviyesindedir. Manuel onay vermek, ilgili kaydın doğrulama engelini kaldırarak yayına girmesine izin verir. Lütfen geçerli bir gerekçe belirtin.
      `;
    } else {
      warningEl.className = "alert alert-warning";
      warningEl.innerHTML = `
        Bu işlem sorunu otomatik olarak düzeltmez. Kaydı inceleyen uzman tarafından manuel olarak çözüldü kabul eder.
      `;
    }
  }

  showModal("modal-resolve-issue");
}

async function confirmResolveIssueAction() {
  if (!pendingResolveIssueState) return;
  const noteInput = document.getElementById("txt-resolve-note");
  const note = noteInput ? noteInput.value.trim() : "";
  if (!note) {
    showToast("Lütfen çözüldü kabul etme gerekçesini belirtiniz.", "warning");
    if (noteInput) noteInput.focus();
    return;
  }

  const { issueId } = pendingResolveIssueState;
  setBusy(true);
  try {
    await apiRequest(`/api/issues/${encodeURIComponent(issueId)}/resolve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status: "resolved",
        resolved_by: sessionStorage.getItem("mesa_actor") || "web-user",
        resolution_note: note,
      }),
    });
    closeModal("modal-resolve-issue");
    showToast("Sorun manuel olarak çözüldü kabul edildi.", "success");
    pendingResolveIssueState = null;
    await loadReviewView();
  } catch (err) {
    console.error("Resolve issue error:", err);
    showToast("Sorun durumu güncellenemedi. İşlem kaydedilmedi.", "danger");
  } finally {
    setBusy(false);
  }
}

async function openRecordReviewModal(recordId) {
  setBusy(true);
  try {
    const rec = await apiRequest(`/api/records/${encodeURIComponent(recordId)}`);
    state.currentRecordId = recordId;
    state.currentVersionId = rec.version_id;

    const modalBody = document.getElementById("record-modal-body");
    modalBody.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 10px;">
        <div>
          <h4>${escapeHtml(rec.document_title || rec.document_id || "Kayıt")}</h4>
          <span style="font-size: 13px; color: var(--color-text-secondary);">${humanTerm(rec.record_type)} · ${humanTerm(rec.source_id || "resmi_gazete")}</span>
        </div>
        <div style="display: flex; gap: 6px;">
          ${statusBadge(rec.validation_status || "valid")}
          ${statusBadge(rec.approval_status || "pending")}
        </div>
      </div>

      <div style="margin-top: 10px;">
        <label style="font-size: 12px; font-weight: 700; color: var(--color-text-muted);">Kayıt İçeriği</label>
        <pre class="code-box" style="margin-top: 4px; max-height: 240px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;">${escapeHtml(rec.text_preview || (typeof rec.data_json === "string" ? rec.data_json : JSON.stringify(rec.data_json, null, 2)))}</pre>
      </div>

      <details class="technical-details">
        <summary>Teknik ayrıntılar</summary>
        <div class="technical-details-content">
          <div><strong>Kayıt Kimliği (Record ID):</strong> <code class="mono">${escapeHtml(rec.record_id)}</code></div>
          <div><strong>Belge Kimliği:</strong> <code class="mono">${escapeHtml(rec.document_id)}</code></div>
          <div><strong>Version ID:</strong> <code class="mono">${escapeHtml(rec.version_id)}</code></div>
        </div>
      </details>
    `;

    document.getElementById("txt-reviewer-note").value = "";
    showModal("modal-record-detail");
  } catch (err) {
    console.error("Open record review error:", err);
  } finally {
    setBusy(false);
  }
}

async function handleRecordDecision(decision) {
  if (!state.currentRecordId) return;
  const note = document.getElementById("txt-reviewer-note")?.value.trim() || "";

  setBusy(true);
  try {
    const endpoint = `/api/reviews/records/${encodeURIComponent(state.currentRecordId)}/${decision}`;
    await apiRequest(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reviewer: sessionStorage.getItem("mesa_actor") || "web-user",
        note: note || null,
      }),
    });

    showToast(`Kayıt ${decision === "approve" ? "onaylandı" : "reddedildi"}.`, "success");
    closeModal("modal-record-detail");
    await loadReviewView();
  } catch (err) {
    console.error("Record decision error:", err);
    const errStr = String(err.message || "");
    const isBlocker = errStr.includes("çözülmesi gereken") || errStr.includes("blocker") || errStr.includes("BLOCKING_ISSUES_EXIST");
    if (isBlocker) {
      showToast("Bu kayıt henüz onaylanamaz. Çözülmesi gereken doğrulama sorunları bulunuyor.", "danger");
      const modalBody = document.getElementById("record-modal-body");
      if (modalBody) {
        let blockerNotice = document.getElementById("record-blocker-notice");
        if (!blockerNotice) {
          blockerNotice = document.createElement("div");
          blockerNotice.id = "record-blocker-notice";
          blockerNotice.style.cssText = "margin-top: 12px; padding: 12px; background: rgba(239, 68, 68, 0.1); border: 1px solid var(--color-danger); border-radius: 6px;";
          modalBody.appendChild(blockerNotice);
        }
        blockerNotice.innerHTML = `
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 10px;">
            <div>
              <strong style="color: var(--color-danger);">Bu kayıt henüz onaylanamaz.</strong>
              <div style="font-size: 13px; color: var(--color-text-secondary); margin-top: 2px;">Çözülmesi gereken doğrulama sorunları bulunuyor.</div>
            </div>
            <button type="button" class="btn btn-sm btn-primary" onclick="showRecordIssues('${escapeHtml(state.currentRecordId)}')">Sorunları Gör</button>
          </div>
        `;
      }
    }
  } finally {
    setBusy(false);
  }
}

// --- 5. EXPORT VIEW ---
async function loadExportView() {
  setBusy(true);
  try {
    const [exportsList, stats] = await Promise.all([
      apiRequest("/api/exports"),
      apiRequest("/api/dashboard/stats").catch(() => null),
    ]);

    const approvedCount = stats?.counts?.approved_records || 0;
    const btnCreateExport = document.getElementById("btn-export-create");
    const btnMesaTransfer = document.getElementById("btn-mesa-transfer");

    let emptyNotice = document.getElementById("export-empty-notice");
    if (approvedCount === 0) {
      if (!emptyNotice) {
        emptyNotice = document.createElement("div");
        emptyNotice.id = "export-empty-notice";
        emptyNotice.style.cssText = "margin-bottom: 16px; padding: 14px 18px; border-left: 4px solid var(--color-warning); background: var(--color-surface-subtle); border-radius: 6px;";
        const exportPanel = document.getElementById("view-export");
        if (exportPanel) exportPanel.insertBefore(emptyNotice, exportPanel.firstChild);
      }
      emptyNotice.innerHTML = `
        <h4 style="margin: 0 0 4px 0; font-size: 14px;">Henüz dışa aktarılabilecek hazır kayıt yok</h4>
        <p style="margin: 0 0 10px 0; font-size: 13px; color: var(--color-text-secondary);">Dışa aktarma yapabilmek için önce veri toplayın ve gerekiyorsa inceleme adımını tamamlayın.</p>
        <div style="display: flex; gap: 8px;">
          <button type="button" class="btn btn-primary btn-sm" onclick="switchView('collect')">Veri Topla</button>
          <button type="button" class="btn btn-secondary btn-sm" onclick="switchView('review')">İncelemeye Git</button>
        </div>
      `;
      if (btnCreateExport) {
        btnCreateExport.disabled = true;
        btnCreateExport.title = "Dışa aktarma oluşturmak için önce en az 1 onaylanmış kayıt gereklidir.";
      }
      if (btnMesaTransfer) {
        btnMesaTransfer.disabled = true;
        btnMesaTransfer.title = "MESA transferi için önce en az 1 onaylanmış kayıt gereklidir.";
      }
    } else {
      if (emptyNotice) emptyNotice.remove();
      if (btnCreateExport) {
        btnCreateExport.disabled = false;
        btnCreateExport.title = "";
      }
      if (btnMesaTransfer) {
        btnMesaTransfer.disabled = false;
        btnMesaTransfer.title = "";
      }
    }

    const tbody = document.getElementById("tbl-exports");
    tbody.innerHTML = "";

    if (!exportsList || exportsList.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Henüz oluşturulan dışa aktarma paketi yok.</td></tr>`;
      return;
    }

    exportsList.forEach((exp) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code class="mono">${escapeHtml(exp.export_id)}</code></td>
        <td>${humanTerm(exp.export_type)}</td>
        <td>${statusBadge(exp.status)}</td>
        <td>${exp.record_count ? `${exp.record_count} Kayıt` : "-"}</td>
        <td>${friendlyDate(exp.created_at)}</td>
        <td>
          <a class="btn btn-sm btn-secondary" href="/api/exports/${encodeURIComponent(exp.export_id)}/download" target="_blank" download>İndir</a>
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Export view error:", err);
  } finally {
    setBusy(false);
  }
}

async function createExportAction() {
  const sel = document.getElementById("sel-export-format");
  const exportType = sel ? sel.value : "records_jsonl";

  setBusy(true);
  try {
    await apiRequest("/api/exports", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ export_type: exportType }),
    });
    showToast("Dışa aktarma paketi hazırlandı.", "success");
    await loadExportView();
  } catch (err) {
    console.error("Create export error:", err);
  } finally {
    setBusy(false);
  }
}

async function runMesaTransferSequence() {
  const progressBox = document.getElementById("mesa-transfer-progress-box");
  const statusText = document.getElementById("mesa-transfer-status-text");
  const transferBtn = document.getElementById("btn-mesa-transfer");

  progressBox.classList.remove("hidden");
  transferBtn.disabled = true;

  const releaseId = `mesa-transfer-${Date.now()}`;

  try {
    // Step 1: Build
    statusText.textContent = "1/4 Paket hazırlanıyor...";
    await apiRequest("/api/releases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ release_id: releaseId }),
    });

    // Step 2: Verify
    statusText.textContent = "2/4 Veri bütünlüğü doğrulanıyor...";
    await apiRequest(`/api/releases/${releaseId}/verify`, { method: "POST" });

    // Step 3: Publish
    statusText.textContent = "3/4 Yayına alınıyor...";
    await apiRequest(`/api/releases/${releaseId}/publish`, { method: "POST" });

    // Step 4: Import Staging
    statusText.textContent = "4/4 MESA aktarım alanına aktarılıyor...";
    await apiRequest(`/api/releases/${releaseId}/import-staging`, { method: "POST" });

    statusText.textContent = "✓ MESA'ya aktarım başarıyla tamamlandı.";
    showToast("Onaylı kayıtlar MESA aktarım alanına başarıyla gönderildi.", "success");
  } catch (err) {
    console.error("MESA transfer error:", err);
    statusText.textContent = `Aktarım tamamlanamadı: ${err.message}`;
    showToast("MESA aktarımı tamamlanamadı. Oluşturulan paket korundu.", "danger");
  } finally {
    transferBtn.disabled = false;
    setTimeout(() => {
      if (progressBox) progressBox.classList.add("hidden");
    }, 6000);
  }
}

// --- 6. ADVANCED SUB-VIEWS ---
async function loadSourcesView() {
  setBusy(true);
  try {
    const sources = await apiRequest("/api/sources");
    const container = document.getElementById("sources-list");
    container.innerHTML = "";

    sources.forEach((s) => {
      const card = document.createElement("div");
      card.className = "source-card";
      card.innerHTML = `
        <div class="source-card-header">
          <div class="source-title-group">
            <h3>${escapeHtml(s.name)}</h3>
            <p>${escapeHtml(s.authority || "-")}</p>
          </div>
          <span class="badge ${s.automation === "supported" ? "badge-success" : s.automation === "manual" ? "badge-info" : "badge-neutral"}">${escapeHtml(s.automation === "supported" ? "Otomatik Toplama" : s.automation === "manual" ? "Manuel Ekleme" : "Devre Dışı")}</span>
        </div>
        <div style="font-size: 13px; color: var(--color-text-secondary);">
          <strong>Kaynak ID:</strong> <code>${escapeHtml(s.source_id)}</code>
        </div>
      `;
      container.appendChild(card);
    });
  } catch (err) {
    console.error("Sources view error:", err);
  } finally {
    setBusy(false);
  }
}

async function loadExplorerView() {
  setBusy(true);
  try {
    const q = document.getElementById("filter-explorer-q")?.value.trim() || "";
    const type = document.getElementById("filter-explorer-type")?.value || "";
    const approval = document.getElementById("filter-explorer-approval")?.value || "";

    const params = new URLSearchParams({ page: 1, page_size: 50 });
    if (q) params.set("q", q);
    if (type) params.set("type", type);
    if (approval) params.set("approval_status", approval);

    const res = await apiRequest(`/api/explorer/search?${params.toString()}`);
    const items = res.items || [];
    const tbody = document.getElementById("tbl-explorer");
    tbody.innerHTML = "";

    if (items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-state">Kayıt bulunamadı.</td></tr>`;
      return;
    }

    items.forEach((rec) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code class="mono">${escapeHtml(rec.record_id)}</code></td>
        <td>${humanTerm(rec.record_type)}</td>
        <td>${escapeHtml(rec.document_title || rec.document_id || "-")}</td>
        <td>${humanTerm(rec.source_id || "resmi_gazete")}</td>
        <td>${statusBadge(rec.approval_status || "pending")}</td>
        <td>${statusBadge(rec.validation_status || "valid")}</td>
        <td>${friendlyDate(rec.created_at)}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Explorer view error:", err);
  } finally {
    setBusy(false);
  }
}

async function loadReleasesView() {
  setBusy(true);
  try {
    const releases = await apiRequest("/api/releases");
    const tbody = document.getElementById("tbl-releases");
    tbody.innerHTML = "";

    if (!releases || releases.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty-state">Henüz oluşturulmuş release paketi yok.</td></tr>`;
      return;
    }

    releases.forEach((rel) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code class="mono">${escapeHtml(rel.release_id)}</code></td>
        <td>${statusBadge(rel.status)}</td>
        <td>${rel.record_counts?.legislation || 0}</td>
        <td>${rel.record_counts?.article || 0}</td>
        <td>${rel.record_counts?.decision || 0}</td>
        <td>${rel.record_counts?.citation || 0}</td>
        <td>${friendlyDate(rel.created_at)}</td>
        <td>
          ${rel.status === "draft" ? `<button class="btn btn-sm btn-primary" onclick="verifyRelease('${escapeHtml(rel.release_id)}')">Doğrula</button>` : ""}
          ${rel.status === "verified" ? `<button class="btn btn-sm btn-success" onclick="publishRelease('${escapeHtml(rel.release_id)}')">Yayınla</button>` : ""}
          ${rel.status === "published" ? `<button class="btn btn-sm btn-secondary" onclick="importRelease('${escapeHtml(rel.release_id)}')">MESA'ya Aktar</button>` : ""}
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Releases view error:", err);
  } finally {
    setBusy(false);
  }
}

async function verifyRelease(releaseId) {
  setBusy(true);
  try {
    await apiRequest(`/api/releases/${releaseId}/verify`, { method: "POST" });
    showToast("Release doğrulandı.", "success");
    await loadReleasesView();
  } catch (err) {
    console.error(err);
  } finally {
    setBusy(false);
  }
}

async function publishRelease(releaseId) {
  setBusy(true);
  try {
    await apiRequest(`/api/releases/${releaseId}/publish`, { method: "POST" });
    showToast("Release yayınlandı.", "success");
    await loadReleasesView();
  } catch (err) {
    console.error(err);
  } finally {
    setBusy(false);
  }
}

async function importRelease(releaseId) {
  setBusy(true);
  try {
    await apiRequest(`/api/releases/${releaseId}/import-staging`, { method: "POST" });
    showToast("Release MESA staging ortamına aktarıldı.", "success");
    await loadReleasesView();
  } catch (err) {
    console.error(err);
  } finally {
    setBusy(false);
  }
}

async function loadOperationsView() {
  setBusy(true);
  try {
    const ops = await apiRequest("/api/operations/jobs");
    const tbody = document.getElementById("tbl-operations");
    tbody.innerHTML = "";

    if (!ops || ops.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-state">İşlem geçmişi bulunamadı.</td></tr>`;
      return;
    }

    ops.forEach((op) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><code class="mono">${escapeHtml(op.operation_id || op.job_id || "-")}</code></td>
        <td>${humanTerm(op.operation_type || op.source_id)}</td>
        <td>${statusBadge(op.status)}</td>
        <td>${op.progress_current !== null && op.progress_current !== undefined ? `${op.progress_current}%` : "-"}</td>
        <td>${friendlyDate(op.created_at || op.started_at)}</td>
        <td>${friendlyDate(op.finished_at || op.completed_at)}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Operations view error:", err);
  } finally {
    setBusy(false);
  }
}

async function loadAuditView() {
  setBusy(true);
  try {
    const actor = document.getElementById("filter-audit-actor")?.value.trim() || "";
    const params = new URLSearchParams({ limit: 50 });
    if (actor) params.set("actor", actor);

    const logs = await apiRequest(`/api/audit-events?${params.toString()}`);
    const tbody = document.getElementById("tbl-audit");
    tbody.innerHTML = "";

    if (!logs || logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-state">Audit kaydı bulunamadı.</td></tr>`;
      return;
    }

    logs.forEach((ev) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${friendlyDate(ev.created_at)}</td>
        <td><strong>${escapeHtml(ev.actor || "system")}</strong></td>
        <td>${escapeHtml(ev.action || "-")}</td>
        <td><code class="mono">${escapeHtml(ev.target_type || "")}:${escapeHtml(ev.target_id || "")}</code></td>
        <td><pre style="font-size: 11px; margin: 0;">${escapeHtml(typeof ev.details_json === "string" ? ev.details_json : JSON.stringify(ev.details_json))}</pre></td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Audit view error:", err);
  } finally {
    setBusy(false);
  }
}

async function loadSystemView() {
  setBusy(true);
  try {
    const cfg = await apiRequest("/api/config/public");
    const pre = document.getElementById("sys-status-output");
    if (pre) pre.textContent = JSON.stringify(cfg, null, 2);
  } catch (err) {
    console.error("System view error:", err);
  } finally {
    setBusy(false);
  }
}

// --- DOM Ready Event Bindings ---
document.addEventListener("DOMContentLoaded", () => {
  // 1. Initial Hash Route
  const initialHash = window.location.hash.replace("#", "") || "home";
  switchView(initialHash);

  // 2. Navigation Click Handlers
  document.querySelectorAll(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const v = btn.dataset.view;
      if (v) switchView(v);
    });
  });

  // 3. Toggle Advanced Subnav
  const btnToggleAdv = document.getElementById("btn-toggle-advanced");
  const advSubnav = document.getElementById("advanced-subnav");
  if (btnToggleAdv && advSubnav) {
    btnToggleAdv.addEventListener("click", () => {
      const isOpen = !advSubnav.classList.contains("hidden");
      if (isOpen) {
        advSubnav.classList.add("hidden");
        btnToggleAdv.setAttribute("aria-expanded", "false");
      } else {
        advSubnav.classList.remove("hidden");
        btnToggleAdv.setAttribute("aria-expanded", "true");
      }
    });
  }

  // 4. Mobile Drawer Controls
  const mobileBtn = document.getElementById("btn-mobile-menu");
  const sidebar = document.getElementById("app-sidebar");
  const overlay = document.getElementById("sidebar-overlay");

  if (mobileBtn && sidebar && overlay) {
    mobileBtn.addEventListener("click", () => {
      const isOpen = sidebar.classList.contains("open");
      if (isOpen) {
        closeMobileSidebar();
      } else {
        sidebar.classList.add("open");
        overlay.classList.add("open");
        mobileBtn.setAttribute("aria-expanded", "true");
        document.body.classList.add("drawer-open");
      }
    });

    overlay.addEventListener("click", closeMobileSidebar);
  }

  // 5. Global Escape Key Listener
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeMobileSidebar();
      document.querySelectorAll(".modal-backdrop:not(.hidden)").forEach((m) => {
        closeModal(m.id);
      });
    }
  });

  // 6. Modal Close Buttons
  document.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const modalId = btn.dataset.close;
      if (modalId) closeModal(modalId);
    });
  });

  // 7. Token Modal
  const btnToken = document.getElementById("btn-token");
  if (btnToken) {
    btnToken.addEventListener("click", () => {
      document.getElementById("txt-token-input").value = state.token;
      showModal("modal-token");
    });
  }

  const btnSysToken = document.getElementById("btn-sys-token");
  if (btnSysToken) {
    btnSysToken.addEventListener("click", () => {
      document.getElementById("txt-token-input").value = state.token;
      showModal("modal-token");
    });
  }

  const btnSaveToken = document.getElementById("btn-save-token");
  if (btnSaveToken) {
    btnSaveToken.addEventListener("click", () => {
      const t = document.getElementById("txt-token-input").value.trim();
      state.token = t;
      if (t) sessionStorage.setItem("mesa_admin_token", t);
      else sessionStorage.removeItem("mesa_admin_token");
      closeModal("modal-token");
      showToast("Yönetici token'ı kaydedildi.", "success");
      refreshApiStatus();
    });
  }

  // 8. Welcome Card CTAs
  const btnWelcomeStart = document.getElementById("btn-welcome-start");
  if (btnWelcomeStart) {
    btnWelcomeStart.addEventListener("click", () => switchView("collect"));
  }
  const btnWelcomeUpload = document.getElementById("btn-welcome-upload");
  if (btnWelcomeUpload) {
    btnWelcomeUpload.addEventListener("click", () => {
      switchView("collect");
      setTimeout(() => {
        document.getElementById("manual-ingestion-box")?.scrollIntoView({ behavior: "smooth" });
      }, 100);
    });
  }

  // 9. Collect Actions
  const btnCollectStart = document.getElementById("btn-collect-start");
  if (btnCollectStart) btnCollectStart.addEventListener("click", startHarvestAction);

  const btnCollectStop = document.getElementById("btn-collect-stop");
  if (btnCollectStop) btnCollectStop.addEventListener("click", stopHarvestAction);

  // 10. Manual Ingestion Tabs & Forms
  function updateDocTypesForSource(sourceSelectId, typeSelectId) {
    const sourceSelect = document.getElementById(sourceSelectId);
    const typeSelect = document.getElementById(typeSelectId);
    if (!sourceSelect || !typeSelect) return;

    const selectedSource = sourceSelect.value;
    const currentVal = typeSelect.value;
    const cap = SOURCE_CAPABILITIES[selectedSource];

    typeSelect.innerHTML = `<option value="" disabled selected>— Belge türünü seçin —</option>`;
    if (cap && cap.docTypes) {
      let currentStillValid = false;
      cap.docTypes.forEach((dt) => {
        const opt = document.createElement("option");
        opt.value = dt.id;
        opt.textContent = dt.label;
        if (dt.id === currentVal) {
          opt.selected = true;
          currentStillValid = true;
        }
        typeSelect.appendChild(opt);
      });

      if (currentVal && !currentStillValid) {
        typeSelect.value = "";
        showToast("Kaynak değiştirildi. Bu kaynak için belge türünü yeniden seçin.", "info");
      }
    }
  }

  const fileSourceEl = document.getElementById("file-source");
  if (fileSourceEl) {
    fileSourceEl.addEventListener("change", () => {
      updateDocTypesForSource("file-source", "file-doc-type");
    });
  }

  const urlSourceEl = document.getElementById("url-source");
  if (urlSourceEl) {
    urlSourceEl.addEventListener("change", () => {
      updateDocTypesForSource("url-source", "url-doc-type");
    });
  }

  document.querySelectorAll("#manual-ingestion-box .tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#manual-ingestion-box .tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");

      const tabId = btn.dataset.tab;
      if (tabId === "tab-manual-file") {
        document.getElementById("form-upload-file").classList.remove("hidden");
        document.getElementById("form-upload-url").classList.add("hidden");
        updateDocTypesForSource("file-source", "file-doc-type");
      } else {
        document.getElementById("form-upload-file").classList.add("hidden");
        document.getElementById("form-upload-url").classList.remove("hidden");
        updateDocTypesForSource("url-source", "url-doc-type");
      }
    });
  });

  const formUploadFile = document.getElementById("form-upload-file");
  if (formUploadFile) {
    formUploadFile.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fileInput = document.getElementById("file-input");
      if (!fileInput.files || fileInput.files.length === 0) {
        showToast("Lütfen bir dosya seçiniz.", "warning");
        return;
      }

      const sourceId = document.getElementById("file-source").value;
      const docType = document.getElementById("file-doc-type").value;
      if (!sourceId) {
        showToast("Lütfen belgenin kaynağını seçin.", "warning");
        document.getElementById("file-source")?.focus();
        return;
      }
      if (!docType) {
        showToast("Lütfen belge türünü seçin.", "warning");
        document.getElementById("file-doc-type")?.focus();
        return;
      }

      const sourceCap = SOURCE_CAPABILITIES[sourceId] || { family: "legislation" };
      const family = sourceCap.family || "legislation";

      const title = document.getElementById("file-title").value.trim();
      const docNum = document.getElementById("file-doc-number")?.value.trim();
      const customDocId = document.getElementById("file-doc-id")?.value.trim();

      let documentId = customDocId;
      if (!documentId) {
        if (family === "decision") {
          const safeNum = (docNum || String(Date.now())).replace(/[\/\s]/g, "-");
          documentId = `tr:case-law:${sourceId}:${docType}:${safeNum}`;
        } else {
          documentId = `tr:legislation:${docType}:${docNum || Date.now()}`;
        }
      }

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      formData.append("source_id", sourceId);
      formData.append("document_id", documentId);
      formData.append("document_type", docType);
      formData.append("family", family);
      formData.append("jurisdiction", "TR");
      if (title) formData.append("title", title);

      setBusy(true);
      try {
        const uploadRes = await apiRequest("/api/artifacts/upload", {
          method: "POST",
          body: formData,
        });

        // Automatically process uploaded artifact into catalog records
        const artifactId = uploadRes.artifact_id;
        if (artifactId) {
          await apiRequest(`/api/artifacts/${artifactId}/process`, { method: "POST" });
        }

        showToast("Belge yüklendi ve işlendi. Kütüphane’de görüntüleyebilirsiniz.", "success");
        formUploadFile.reset();
        updateDocTypesForSource("file-source", "file-doc-type");
      } catch (err) {
        console.error("Upload file error:", err);
      } finally {
        setBusy(false);
      }
    });
  }

  const formUploadUrl = document.getElementById("form-upload-url");
  if (formUploadUrl) {
    formUploadUrl.addEventListener("submit", async (e) => {
      e.preventDefault();
      const sourceId = document.getElementById("url-source").value;
      const docType = document.getElementById("url-doc-type").value;
      if (!sourceId) {
        showToast("Lütfen belgenin kaynağını seçin.", "warning");
        document.getElementById("url-source")?.focus();
        return;
      }
      if (!docType) {
        showToast("Lütfen belge türünü seçin.", "warning");
        document.getElementById("url-doc-type")?.focus();
        return;
      }

      const sourceCap = SOURCE_CAPABILITIES[sourceId] || { family: "legislation" };
      const family = sourceCap.family || "legislation";

      const url = document.getElementById("url-input").value.trim();
      const title = document.getElementById("url-title").value.trim();
      const docNum = document.getElementById("url-doc-number")?.value.trim();
      const customDocId = document.getElementById("url-doc-id")?.value.trim();

      let documentId = customDocId;
      if (!documentId) {
        if (family === "decision") {
          const safeNum = (docNum || String(Date.now())).replace(/[\/\s]/g, "-");
          documentId = `tr:case-law:${sourceId}:${docType}:${safeNum}`;
        } else {
          documentId = `tr:legislation:${docType}:${docNum || Date.now()}`;
        }
      }

      setBusy(true);
      try {
        await apiRequest("/api/documents/import-url", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_id: sourceId,
            url: url,
            document_id: documentId,
            document_type: docType,
            family: family,
            jurisdiction: "TR",
            title: title || null,
          }),
        });

        showToast("Belge başarıyla indirildi ve işlendi.", "success");
        formUploadUrl.reset();
        updateDocTypesForSource("url-source", "url-doc-type");
      } catch (err) {
        console.error("Import URL error:", err);
      } finally {
        setBusy(false);
      }
    });
  }

  const btnConfirmResolve = document.getElementById("btn-confirm-resolve-issue");
  if (btnConfirmResolve) {
    btnConfirmResolve.addEventListener("click", confirmResolveIssueAction);
  }

  // 11. Library Filters & Pagination
  const btnLibFilter = document.getElementById("btn-lib-filter");
  if (btnLibFilter) {
    btnLibFilter.addEventListener("click", () => {
      state.libPage = 1;
      loadLibraryView();
    });
  }

  const btnLibPrev = document.getElementById("btn-lib-prev");
  if (btnLibPrev) {
    btnLibPrev.addEventListener("click", () => {
      if (state.libPage > 1) {
        state.libPage--;
        loadLibraryView();
      }
    });
  }

  const btnLibNext = document.getElementById("btn-lib-next");
  if (btnLibNext) {
    btnLibNext.addEventListener("click", () => {
      state.libPage++;
      loadLibraryView();
    });
  }

  // 12. Review Tabs & Decision Handlers
  document.querySelectorAll("[data-review-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.activeReviewTab = btn.dataset.reviewTab;
      loadReviewView();
    });
  });

  const btnRecordApprove = document.getElementById("btn-record-approve");
  if (btnRecordApprove) {
    btnRecordApprove.addEventListener("click", () => handleRecordDecision("approve"));
  }

  const btnRecordReject = document.getElementById("btn-record-reject");
  if (btnRecordReject) {
    btnRecordReject.addEventListener("click", () => handleRecordDecision("reject"));
  }

  // 13. Export Handlers
  const btnExportCreate = document.getElementById("btn-export-create");
  if (btnExportCreate) btnExportCreate.addEventListener("click", createExportAction);

  const btnMesaTransfer = document.getElementById("btn-mesa-transfer");
  if (btnMesaTransfer) btnMesaTransfer.addEventListener("click", runMesaTransferSequence);

  // 14. Advanced Release Build
  const btnBuildRelease = document.getElementById("btn-build-release");
  if (btnBuildRelease) {
    btnBuildRelease.addEventListener("click", async () => {
      const relId = document.getElementById("txt-release-id")?.value.trim();
      if (!relId) {
        showToast("Lütfen bir release ID giriniz.", "warning");
        return;
      }
      setBusy(true);
      try {
        await apiRequest("/api/releases", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ release_id: relId }),
        });
        showToast(`Release '${relId}' oluşturuldu.`, "success");
        await loadReleasesView();
      } catch (err) {
        console.error(err);
      } finally {
        setBusy(false);
      }
    });
  }

  // 15. Advanced Audit & Explorer Search
  const btnAuditFilter = document.getElementById("btn-audit-filter");
  if (btnAuditFilter) btnAuditFilter.addEventListener("click", loadAuditView);

  const btnExplorerSearch = document.getElementById("btn-explorer-search");
  if (btnExplorerSearch) btnExplorerSearch.addEventListener("click", loadExplorerView);

  // 16. System Actions
  const btnSysDoctor = document.getElementById("btn-sys-doctor");
  if (btnSysDoctor) {
    btnSysDoctor.addEventListener("click", async () => {
      setBusy(true);
      try {
        const res = await apiRequest("/api/system/doctor", { method: "POST" });
        document.getElementById("sys-status-output").textContent = JSON.stringify(res, null, 2);
        showToast("Doctor kontrolü tamamlandı.", "success");
      } catch (err) {
        console.error(err);
      } finally {
        setBusy(false);
      }
    });
  }

  const btnSysBackup = document.getElementById("btn-sys-backup");
  if (btnSysBackup) {
    btnSysBackup.addEventListener("click", async () => {
      setBusy(true);
      try {
        const res = await apiRequest("/api/system/backup", { method: "POST" });
        document.getElementById("sys-status-output").textContent = JSON.stringify(res, null, 2);
        showToast("Backup başarıyla alındı.", "success");
      } catch (err) {
        console.error(err);
      } finally {
        setBusy(false);
      }
    });
  }

  // 17. Initial setup & API Status Check
  updateDocTypesForSource("file-source", "file-doc-type");
  updateDocTypesForSource("url-source", "url-doc-type");
  refreshApiStatus();
});
