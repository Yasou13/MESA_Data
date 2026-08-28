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

    // Health Metrics
    const h = dash.health || {};
    const setElemText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    setElemText("stat-discovered-today", h.discovered_today ?? 0);
    setElemText("stat-processed-today", h.processed_today ?? 0);
    setElemText("stat-auto-approved-today", h.auto_approved_today ?? 0);
    setElemText("stat-needs-review", h.needs_review_count ?? (dash.counts?.pending_reviews || 0));
    setElemText("stat-blocked", h.blocked_count ?? (dash.counts?.open_blockers || 0));
    setElemText("stat-mesa-ready", h.mesa_ready_count ?? (dash.counts?.approved_records || 0));

    const mesaLabelEl = document.getElementById("lbl-home-mesa-status");
    if (mesaLabelEl) {
      mesaLabelEl.textContent = h.mesa_status_label || "MESA entegrasyonu yapılandırılmadı (Yerel Development Staging Aktif)";
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
    const [doc, textRes, verRes] = await Promise.all([
      apiRequest(`/api/documents/${encodeURIComponent(documentId)}`),
      apiRequest(`/api/documents/${encodeURIComponent(documentId)}/text`).catch(() => ({ content: null })),
      apiRequest(`/api/documents/${encodeURIComponent(documentId)}/versions`).catch(() => ({ versions: [] })),
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

    const versions = verRes?.versions || [];
    let versionsTableHtml = "";
    if (versions.length > 0) {
      versionsTableHtml = `
        <div style="margin-top: 14px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
            <label style="font-size: 12px; font-weight: 700; color: var(--color-text-muted);">Versiyon Geçmişi (${versions.length})</label>
            <button class="btn btn-sm btn-outline" onclick="reprocessDocument('${escapeHtml(doc.document_id)}')">Yeniden İşle</button>
          </div>
          <table class="data-table" style="font-size: 12px;">
            <thead>
              <tr>
                <th>Revizyon</th>
                <th>Tarih</th>
                <th>Kalite</th>
                <th>Onay</th>
                <th>Etiketler</th>
              </tr>
            </thead>
            <tbody>
              ${versions.map((v) => {
                const qBadge = v.quality_status === "PASS" ? `<span class="badge badge-success">PASS</span>` : v.quality_status === "BLOCK" ? `<span class="badge badge-danger">BLOCK</span>` : `<span class="badge badge-warning">REVIEW</span>`;
                const aBadge = v.approval_status === "approved" ? `<span class="badge badge-success">Onaylı</span>` : `<span class="badge badge-warning">Bekliyor</span>`;
                const tags = [];
                if (v.auto_approved) tags.push(`<span class="badge badge-info" style="font-size: 10px;">Otomatik</span>`);
                if (v.is_audit_sample) tags.push(`<span class="badge badge-warning" style="font-size: 10px;">Örnek Kontrol</span>`);
                return `
                  <tr>
                    <td><strong>v${v.revision_number || 1}</strong></td>
                    <td>${friendlyDate(v.created_at)}</td>
                    <td>${qBadge}</td>
                    <td>${aBadge}</td>
                    <td>${tags.join(" ") || "-"}</td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      `;
    }

    let mesaStatusBadge = `<span class="badge badge-neutral">MESA: Not Sent</span>`;
    try {
      const mesaRes = await apiRequest(`/api/documents/${encodeURIComponent(documentId)}/mesa-status`);
      const st = mesaRes.status || "Not Sent";
      if (st === "Committed") mesaStatusBadge = `<span class="badge badge-success">MESA: Committed</span>`;
      else if (st === "Sending") mesaStatusBadge = `<span class="badge badge-info">MESA: Sending</span>`;
      else if (st === "Partial") mesaStatusBadge = `<span class="badge badge-warning">MESA: Partial</span>`;
      else if (st === "Failed") mesaStatusBadge = `<span class="badge badge-danger">MESA: Failed</span>`;
      else mesaStatusBadge = `<span class="badge badge-neutral">MESA: Not Sent</span>`;
    } catch (e) {}

    const modalBody = document.getElementById("doc-modal-body");
    modalBody.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 10px;">
        <div>
          <h4>${escapeHtml(doc.title || doc.document_id)}</h4>
          <span style="font-size: 13px; color: var(--color-text-secondary);">${humanTerm(sourceId)} · ${humanTerm(doc.document_type)}</span>
        </div>
        <div style="display: flex; gap: 6px; align-items: center;">
          ${mesaStatusBadge}
          ${statusBadge(docStatus)}
          <button class="btn btn-sm btn-primary" onclick="reprocessDocument('${escapeHtml(doc.document_id)}')">Yeniden İşle</button>
        </div>
      </div>

      ${openIssuesHtml}

      ${versionsTableHtml}

      <div style="margin-top: 10px;">
        <label style="font-size: 12px; font-weight: 700; color: var(--color-text-muted);">Belge Metni</label>
        <pre class="code-box" style="margin-top: 4px; max-height: 240px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;">${escapeHtml(textContent)}</pre>
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

async function reprocessDocument(documentId) {
  if (!confirm(`"${documentId}" belgesi mevcut ham veri kullanılarak yeniden işlensin mi?`)) return;
  setBusy(true);
  try {
    const res = await apiRequest(`/api/documents/${encodeURIComponent(documentId)}/reprocess`, {
      method: "POST",
    });
    showToast(`Yeniden işleme tamamlandı: ${res.pipeline_status || 'başarılı'}`, "success");
    await viewDocDetail(documentId);
    if (state.currentView === "library") await loadLibraryView();
  } catch (err) {
    showToast(`Yeniden işleme hatası: ${err.message || err}`, "danger");
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

      const [verRes, recRes] = await Promise.all([
        apiRequest("/api/reviews/pending-versions?page=1&page_size=50").catch(() => ({ items: [] })),
        apiRequest("/api/records?page=1&page_size=50&approval_status=pending").catch(() => ({ items: [] })),
      ]);

      const versionItems = verRes.items || [];
      const recordItems = recRes.items || [];
      const tbody = document.getElementById("tbl-reviews");
      tbody.innerHTML = "";

      if (versionItems.length === 0 && recordItems.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="6" class="empty-state">
              <div class="empty-state-card" style="padding: 30px; text-align: center;">
                <h4 style="margin: 0 0 6px 0; font-size: 15px;">Şu anda inceleme bekleyen kayıt yok</h4>
                <p style="margin: 0 0 14px 0; color: var(--color-text-secondary); font-size: 13px;">Hazır verilerinizi dışa aktarabilir veya yeni veri toplamaya devam edebilirsiniz.</p>
                <div style="display: flex; gap: 10px; justify-content: center;">
                  <button type="button" class="btn btn-primary btn-sm" onclick="switchView('export')">Yayınla</button>
                  <button type="button" class="btn btn-secondary btn-sm" onclick="switchView('collect')">Veri Topla</button>
                </div>
              </div>
            </td>
          </tr>
        `;
        return;
      }

      // Render pending versions first (document-first review)
      versionItems.forEach((v) => {
        const tr = document.createElement("tr");
        const qBadge = v.quality_status === "PASS" ? `<span class="badge badge-success">PASS</span>` : v.quality_status === "BLOCK" ? `<span class="badge badge-danger">BLOCK</span>` : `<span class="badge badge-warning">REVIEW</span>`;
        const auditBadge = v.is_audit_sample ? `<span class="badge badge-warning" style="margin-left: 4px;">Örnek Kontrol</span>` : "";
        tr.innerHTML = `
          <td><strong>${escapeHtml(v.document_title || v.document_id || "Belge")}</strong> <small class="mono">v${v.revision_number || 1}</small></td>
          <td>${humanTerm(v.family || "legislation")}</td>
          <td>${qBadge} ${auditBadge}</td>
          <td><span class="badge badge-warning">İnceleme Bekliyor</span></td>
          <td>${friendlyDate(v.created_at)}</td>
          <td>
            <button class="btn btn-sm btn-primary" onclick="openVersionReviewModal('${escapeHtml(v.version_id)}')">Belgeyi İncele</button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      // Render individual pending records if any exist without version parent
      if (versionItems.length === 0) {
        recordItems.forEach((rec) => {
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
      }
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
    state.currentRecord = rec;
    state.currentRecordId = recordId;
    state.currentVersionId = rec.version_id;
    state.currentDocTitle = rec.document_title || rec.document_id || "Belge";

    let rawContent = "Ham kaynak içeriği yüklenemedi.";
    let rawCharset = "";
    try {
      const docTextRes = await apiRequest(`/api/documents/${encodeURIComponent(rec.document_id)}/text`);
      if (docTextRes && docTextRes.content) {
        rawContent = docTextRes.content;
      }
      if (docTextRes && docTextRes.charset) {
        rawCharset = ` · Charset: ${escapeHtml(docTextRes.charset)}`;
      }
    } catch (e) {
      console.warn("Failed to load raw document text for comparison:", e);
    }

    const canonicalPreview = rec.text_preview || (typeof rec.data_json === "string" ? rec.data_json : JSON.stringify(rec.data_json, null, 2));

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

      <div class="review-split-view">
        <div class="review-panel">
          <div class="review-panel-header">
            <span>Ham Kaynak (HTML)</span>
            <span style="font-weight: normal; font-size: 11px; color: var(--color-text-muted);">${escapeHtml(rec.source_url || "")}${rawCharset}</span>
          </div>
          <pre class="review-panel-body code-box">${escapeHtml(rawContent)}</pre>
        </div>
        <div class="review-panel">
          <div class="review-panel-header">
            <span>Canonical Kayıt</span>
            <span style="font-weight: normal; font-size: 11px; color: var(--color-text-muted);">${escapeHtml(rec.record_id)}</span>
          </div>
          <pre class="review-panel-body code-box">${escapeHtml(canonicalPreview)}</pre>
        </div>
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

async function openVersionReviewModal(versionId) {
  setBusy(true);
  try {
    const [ver, docTextRes] = await Promise.all([
      apiRequest(`/api/reviews/pending-versions?page=1&page_size=100`).then((res) => {
        return (res.items || []).find((v) => v.version_id === versionId) || { version_id: versionId };
      }),
      apiRequest(`/api/documents/${encodeURIComponent(versionId.split(':')[0])}/text`).catch(() => ({ content: null })),
    ]);

    state.currentVersionId = versionId;
    state.currentRecordId = null;

    const qJson = ver.quality_json || {};
    const checks = qJson.checks || [];
    const cov = qJson.coverage || {};
    const covPct = cov.coverage_ratio != null ? `${Math.round(cov.coverage_ratio * 100)}%` : "N/A";

    let auditBannerHtml = "";
    if (ver.is_audit_sample) {
      auditBannerHtml = `
        <div class="alert alert-warning" style="margin-bottom: 12px; font-size: 13px;">
          <strong>Kalite Örnek Denetimi:</strong> Bu belge otomatik kalite sistemini doğrulamak için örnek kontrole seçildi.
        </div>
      `;
    }

    let qualityChecksHtml = "";
    if (checks.length > 0) {
      qualityChecksHtml = `
        <div style="margin: 10px 0; padding: 10px; background: var(--color-surface-subtle); border-radius: 6px; font-size: 12px;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
            <strong>Kalite Değerlendirmesi: ${ver.quality_status || 'PASS'}</strong>
            <span>Kapsam Oranı: <strong>${covPct}</strong></span>
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 6px;">
            ${checks.map((c) => {
              const icon = c.status === "PASS" ? "✅" : c.status === "BLOCK" ? "❌" : "⚠️";
              return `<div>${icon} <strong>${escapeHtml(c.name || c.check_group || 'Kontrol')}:</strong> ${c.status}</div>`;
            }).join("")}
          </div>
        </div>
      `;
    }

    const rawContent = (docTextRes && docTextRes.content) ? docTextRes.content : "Ham kaynak metni yüklenemedi.";

    const modalBody = document.getElementById("record-modal-body");
    modalBody.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 10px;">
        <div>
          <h4>${escapeHtml(ver.document_title || ver.document_id || "Belge Versiyonu")}</h4>
          <span style="font-size: 13px; color: var(--color-text-secondary);">${humanTerm(ver.source_id || "resmi_gazete")} · Revizyon v${ver.revision_number || 1}</span>
        </div>
        <div style="display: flex; gap: 6px;">
          <span class="badge ${ver.quality_status === "PASS" ? "badge-success" : ver.quality_status === "BLOCK" ? "badge-danger" : "badge-warning"}">${ver.quality_status || 'REVIEW'}</span>
          <span class="badge badge-warning">İnceleme Bekliyor</span>
        </div>
      </div>

      ${auditBannerHtml}
      ${qualityChecksHtml}

      <div class="review-split-view">
        <div class="review-panel">
          <div class="review-panel-header">
            <span>Ham Kaynak İçeriği</span>
            <span style="font-weight: normal; font-size: 11px; color: var(--color-text-muted);">${escapeHtml(ver.source_url || "")}</span>
          </div>
          <pre class="review-panel-body code-box">${escapeHtml(rawContent)}</pre>
        </div>
        <div class="review-panel">
          <div class="review-panel-header">
            <span>Canonical Versiyon</span>
            <span style="font-weight: normal; font-size: 11px; color: var(--color-text-muted);">${escapeHtml(ver.version_id)}</span>
          </div>
          <pre class="review-panel-body code-box">${escapeHtml(rawContent)}</pre>
        </div>
      </div>

      <details class="technical-details">
        <summary>Teknik ayrıntılar</summary>
        <div class="technical-details-content">
          <div><strong>Version ID:</strong> <code class="mono">${escapeHtml(ver.version_id)}</code></div>
          <div><strong>Document ID:</strong> <code class="mono">${escapeHtml(ver.document_id || "-")}</code></div>
          <div><strong>Canonical Path:</strong> <code>${escapeHtml(ver.canonical_path || "-")}</code></div>
        </div>
      </details>
    `;

    document.getElementById("txt-reviewer-note").value = "";
    showModal("modal-record-detail");
  } catch (err) {
    console.error("Open version review modal error:", err);
  } finally {
    setBusy(false);
  }
}

async function handleRecordDecision(decision) {
  const note = document.getElementById("txt-reviewer-note")?.value.trim() || "";
  setBusy(true);
  try {
    if (state.currentVersionId && !state.currentRecordId) {
      const endpoint = `/api/versions/${encodeURIComponent(state.currentVersionId)}/${decision}`;
      await apiRequest(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reviewer: sessionStorage.getItem("mesa_actor") || "web-user",
          note: note || null,
        }),
      });
      showToast(`Belge versiyonu ${decision === "approve" ? "onaylandı" : "reddedildi"}.`, "success");
      closeModal("modal-record-detail");
      await loadReviewView();
    } else if (state.currentRecordId) {
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
    }
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

async function handleVersionBulkDecision(decision) {
  if (!state.currentVersionId) return;
  const versionId = state.currentVersionId;
  const docTitle = state.currentDocTitle || "bu belgenin";
  const note = document.getElementById("txt-reviewer-note")?.value.trim() || "";
  const actionVerb = decision === "approve" ? "onaylayacaktır" : "reddedecektir";
  const actionPast = decision === "approve" ? "onaylandı" : "reddedildi";

  let recordCountText = "tüm";
  try {
    const docId = state.currentRecord?.document_id;
    if (docId) {
      const recsRes = await apiRequest(`/api/records?document_id=${encodeURIComponent(docId)}`);
      const items = recsRes?.items || [];
      const count = items.filter(r => r.version_id === versionId).length || recsRes?.total || "";
      if (count) recordCountText = `${count}`;
    }
  } catch (e) {
    // Non-critical count lookup fallback
  }

  const confirmMsg = `Bu işlem '${docTitle}' belgesinin bu sürümündeki ${recordCountText} kaydın tamamını ${actionVerb}.\n\nDevam etmek istiyor musunuz?`;
  if (!window.confirm(confirmMsg)) {
    return;
  }

  setBusy(true);
  try {
    const endpoint = `/api/versions/${encodeURIComponent(versionId)}/${decision}`;
    const res = await apiRequest(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reviewer: sessionStorage.getItem("mesa_actor") || "web-user",
        note: note || null,
      }),
    });

    const affectedCount = res?.approved_records ?? res?.rejected_records ?? "";
    showToast(`Belge sürümü (${affectedCount} kayıt) başarıyla ${actionPast}.`, "success");
    closeModal("modal-record-detail");
    await loadReviewView();
  } catch (err) {
    console.error("Bulk version decision error:", err);
    const errStr = String(err.message || "");
    const isBlocker = errStr.includes("blocking") || errStr.includes("blocker") || errStr.includes("BLOCKING_ISSUES_EXIST") || errStr.includes("çözülmesi gereken") || errStr.includes("VERSION_APPROVE_FAILED");
    if (isBlocker && decision === "approve") {
      showToast("Bu belge toplu olarak onaylanamaz. Belge içindeki çözülmemiş kritik kayıt sorunları bulunmaktadır.", "danger");
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
              <strong style="color: var(--color-danger);">Bu belge toplu olarak onaylanamaz.</strong>
              <div style="font-size: 13px; color: var(--color-text-secondary); margin-top: 2px;">Belge içindeki çözülmemiş kritik kayıt sorunları bulunmaktadır.</div>
            </div>
            <button type="button" class="btn btn-sm btn-primary" onclick="showRecordIssues('${escapeHtml(state.currentRecordId)}')">Sorunları Gör</button>
          </div>
        `;
      }
    } else {
      showToast(`İşlem gerçekleştirilemedi: ${err.message || "Bilinmeyen hata"}`, "danger");
    }
  } finally {
    setBusy(false);
  }
}

// --- 5. EXPORT / PUBLISH VIEW ---
let activeMesaDeliveryId = null;
let mesaDeliveryPollInterval = null;

async function loadExportView() {
  setBusy(true);
  try {
    const [targetSettings, readySummary, deliveriesRes, exportsList] = await Promise.all([
      apiRequest("/api/publisher/settings").catch(() => null),
      apiRequest("/api/publisher/ready-summary").catch(() => null),
      apiRequest("/api/publisher/deliveries?page=1&page_size=20").catch(() => ({ items: [] })),
      apiRequest("/api/exports").catch(() => []),
    ]);

    // 1. Populate Target Settings
    if (targetSettings) {
      const elUrl = document.getElementById("mesa-target-url");
      const elTenant = document.getElementById("mesa-target-tenant");
      const elWs = document.getElementById("mesa-target-workspace");
      const elDs = document.getElementById("mesa-target-dataset");
      const elAgent = document.getElementById("mesa-target-agent");
      const elLimit = document.getElementById("mesa-target-limit");
      const badgeKey = document.getElementById("badge-mesa-key");

      if (elUrl && targetSettings.base_url) elUrl.value = targetSettings.base_url;
      if (elTenant && targetSettings.tenant_id) elTenant.value = targetSettings.tenant_id;
      if (elWs && targetSettings.workspace_id) elWs.value = targetSettings.workspace_id;
      if (elDs && targetSettings.dataset_id) elDs.value = targetSettings.dataset_id;
      if (elAgent && targetSettings.agent_id) elAgent.value = targetSettings.agent_id;
      if (elLimit && targetSettings.content_limit_chars) elLimit.value = targetSettings.content_limit_chars;

      if (badgeKey) {
        if (targetSettings.api_key_configured) {
          badgeKey.className = "badge badge-success";
          badgeKey.textContent = "API Key: Yapılandırıldı ✅";
        } else {
          badgeKey.className = "badge badge-warning";
          badgeKey.textContent = "API Key: Yapılandırılmadı ❌";
        }
      }
    }

    // 2. Populate Ready Summary Cards
    if (readySummary) {
      const setTxt = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
      };
      setTxt("stat-mesa-ready-docs", readySummary.ready_documents ?? 0);
      setTxt("stat-mesa-ready-vers", readySummary.ready_versions ?? 0);
      setTxt("stat-mesa-ready-chunks", readySummary.estimated_chunks ?? 0);
      const kb = Math.round((readySummary.total_canonical_bytes || 0) / 1024);
      setTxt("stat-mesa-ready-bytes", `${kb} KB`);
      setTxt("stat-mesa-ready-committed", readySummary.already_committed_chunks ?? 0);
      setTxt("stat-mesa-ready-new", readySummary.new_chunks_to_send ?? 0);

      const btnPub = document.getElementById("btn-mesa-publish-trigger");
      if (btnPub) {
        if ((readySummary.new_chunks_to_send ?? 0) === 0 && (readySummary.ready_versions ?? 0) === 0) {
          btnPub.disabled = true;
          btnPub.title = "Aktarılacak hazır versiyon bulunmuyor.";
        } else {
          btnPub.disabled = false;
          btnPub.title = "";
        }
      }
    }

    // 3. Render Deliveries History Table
    const tblDeliveries = document.getElementById("tbl-mesa-deliveries");
    if (tblDeliveries) {
      tblDeliveries.innerHTML = "";
      const deliveries = deliveriesRes.items || [];
      if (deliveries.length === 0) {
        tblDeliveries.innerHTML = `<tr><td colspan="9" class="empty-state">Henüz MESA aktarım kaydı bulunmuyor.</td></tr>`;
      } else {
        deliveries.forEach((del) => {
          let sBadge = `<span class="badge badge-info">${del.status}</span>`;
          if (del.status === "COMMITTED") sBadge = `<span class="badge badge-success">COMMITTED</span>`;
          else if (del.status === "PARTIAL") sBadge = `<span class="badge badge-warning">PARTIAL</span>`;
          else if (del.status === "FAILED") sBadge = `<span class="badge badge-danger">FAILED</span>`;

          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td><a href="javascript:void(0)" onclick="openDeliveryDetailModal('${escapeHtml(del.delivery_id)}')"><code class="mono">${escapeHtml(del.delivery_id)}</code></a></td>
            <td><code class="mono">${escapeHtml(del.target_key)}</code></td>
            <td>${sBadge}</td>
            <td>${del.total_items}</td>
            <td><strong style="color: var(--color-success, green);">${del.committed_items}</strong></td>
            <td><strong style="color: var(--color-danger, red);">${del.failed_items}</strong></td>
            <td>${del.skipped_items}</td>
            <td>${friendlyDate(del.started_at)}</td>
            <td>
              <button class="btn btn-sm btn-secondary" onclick="openDeliveryDetailModal('${escapeHtml(del.delivery_id)}')">Detay</button>
            </td>
          `;
          tblDeliveries.appendChild(tr);
        });
      }
    }

    // 4. Render File Exports Table
    const tbodyExp = document.getElementById("tbl-exports");
    if (tbodyExp) {
      tbodyExp.innerHTML = "";
      if (!exportsList || exportsList.length === 0) {
        tbodyExp.innerHTML = `<tr><td colspan="6" class="empty-state">Henüz oluşturulan dışa aktarma paketi yok.</td></tr>`;
      } else {
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
          tbodyExp.appendChild(tr);
        });
      }
    }
  } catch (err) {
    console.error("Export view error:", err);
  } finally {
    setBusy(false);
  }
}

async function handleMesaSaveSettings() {
  const url = document.getElementById("mesa-target-url")?.value.trim();
  const tenant = document.getElementById("mesa-target-tenant")?.value.trim();
  const ws = document.getElementById("mesa-target-workspace")?.value.trim();
  const ds = document.getElementById("mesa-target-dataset")?.value.trim();
  const agent = document.getElementById("mesa-target-agent")?.value.trim();
  const limit = parseInt(document.getElementById("mesa-target-limit")?.value || "32768", 10);

  if (!url || !tenant || !ws || !ds || !agent) {
    showToast("Lütfen tüm zorunlu hedef alanlarını doldurunuz.", "warning");
    return;
  }

  setBusy(true);
  try {
    const res = await apiRequest("/api/publisher/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        base_url: url,
        tenant_id: tenant,
        workspace_id: ws,
        dataset_id: ds,
        agent_id: agent,
        content_limit_chars: limit,
      }),
    });
    showToast("MESA hedef ayarları kaydedildi.", "success");
    await loadExportView();
  } catch (err) {
    showToast(`Ayar kaydetme hatası: ${err.message || err}`, "danger");
  } finally {
    setBusy(false);
  }
}

async function handleMesaTestConnection() {
  const badgeConn = document.getElementById("badge-mesa-conn");
  if (badgeConn) {
    badgeConn.className = "badge badge-neutral";
    badgeConn.textContent = "Bağlantı test ediliyor...";
  }

  try {
    const res = await apiRequest("/api/publisher/test-connection", { method: "POST" });
    if (res.connected) {
      if (badgeConn) {
        badgeConn.className = "badge badge-success";
        badgeConn.textContent = `Bağlandı (${res.latency_ms}ms) ✅`;
      }
      showToast(`MESA sunucusuna başarıyla bağlanıldı (${res.latency_ms}ms).`, "success");
    } else {
      if (badgeConn) {
        badgeConn.className = "badge badge-danger";
        badgeConn.textContent = "Bağlantı Başarısız ❌";
      }
      showToast(`Bağlantı başarısız: ${res.details || 'Erişilemedi'}`, "danger");
    }
  } catch (err) {
    if (badgeConn) {
      badgeConn.className = "badge badge-danger";
      badgeConn.textContent = "Hata ❌";
    }
    showToast(`Bağlantı testi hatası: ${err.message || err}`, "danger");
  }
}

async function handleMesaPreflight() {
  const boxResults = document.getElementById("box-mesa-preflight-results");
  const listItems = document.getElementById("list-mesa-preflight-items");

  if (listItems) listItems.innerHTML = "<em>Kontroller yapılıyor...</em>";
  if (boxResults) boxResults.classList.remove("hidden");

  try {
    const report = await apiRequest("/api/publisher/preflight", { method: "POST" });
    if (listItems) {
      listItems.innerHTML = report.checks.map((c) => {
        let icon = "✅";
        let color = "var(--color-success, green)";
        if (c.status === "FAIL") {
          icon = "❌";
          color = "var(--color-danger, red)";
        } else if (c.status === "WARN") {
          icon = "⚠️";
          color = "var(--color-warning, orange)";
        }
        return `<div style="display: flex; gap: 8px; align-items: center;">
          <span>${icon}</span>
          <strong style="color: ${color}; text-transform: uppercase; font-size: 11px;">[${c.name}]</strong>
          <span>${escapeHtml(c.message)}</span>
        </div>`;
      }).join("");
    }
    if (report.overall_status === "PASS") {
      showToast("Ön kontrol başarılı (PASS). MESA aktarımına hazır.", "success");
    } else {
      showToast("Ön kontrol başarısız (FAIL). Lütfen uyarıları gideriniz.", "warning");
    }
  } catch (err) {
    if (listItems) listItems.innerHTML = `<span style="color: var(--color-danger, red);">Hata: ${escapeHtml(err.message || err)}</span>`;
    showToast(`Ön kontrol hatası: ${err.message || err}`, "danger");
  }
}

async function handleMesaPublishTrigger() {
  try {
    const summary = await apiRequest("/api/publisher/ready-summary");
    const settings = await apiRequest("/api/publisher/settings");

    const elDocs = document.getElementById("confirm-mesa-docs");
    const elVers = document.getElementById("confirm-mesa-versions");
    const elChunks = document.getElementById("confirm-mesa-chunks");
    const elTarget = document.getElementById("confirm-mesa-target");

    if (elDocs) elDocs.textContent = `${summary.ready_documents} belge`;
    if (elVers) elVers.textContent = `${summary.ready_versions} versiyon`;
    if (elChunks) elChunks.textContent = `${summary.estimated_chunks} chunk (${summary.new_chunks_to_send} yeni gönderilecek)`;
    if (elTarget) elTarget.textContent = `${settings.tenant_id} / ${settings.workspace_id} / ${settings.dataset_id} (${settings.base_url})`;

    showModal("modal-mesa-confirm");
  } catch (err) {
    showToast(`Özet yükleme hatası: ${err.message || err}`, "danger");
  }
}

async function handleMesaConfirmPublish() {
  hideModal("modal-mesa-confirm");
  const boxProg = document.getElementById("box-mesa-delivery-progress");
  const boxPartial = document.getElementById("box-mesa-partial-failure");

  if (boxProg) boxProg.classList.remove("hidden");
  if (boxPartial) boxPartial.classList.add("hidden");

  try {
    const res = await apiRequest("/api/publisher/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_key: "default" }),
    });

    activeMesaDeliveryId = res.delivery_id;
    showToast(`MESA aktarımı başlatıldı (Teslimat: ${activeMesaDeliveryId}).`, "info");
    startMesaDeliveryPolling(activeMesaDeliveryId);
  } catch (err) {
    showToast(`Aktarım başlatılamadı: ${err.message || err}`, "danger");
  }
}

function startMesaDeliveryPolling(deliveryId) {
  if (mesaDeliveryPollInterval) clearInterval(mesaDeliveryPollInterval);

  mesaDeliveryPollInterval = setInterval(async () => {
    try {
      const res = await apiRequest(`/api/publisher/deliveries/${deliveryId}`);
      const del = res.delivery;
      if (!del) return;

      const elStat = document.getElementById("txt-mesa-delivery-status");
      const badgeState = document.getElementById("badge-mesa-delivery-state");
      const valPlanned = document.getElementById("prog-val-planned");
      const valCommitted = document.getElementById("prog-val-committed");
      const valSkipped = document.getElementById("prog-val-skipped");
      const valFailed = document.getElementById("prog-val-failed");
      const boxPartial = document.getElementById("box-mesa-partial-failure");
      const txtPartial = document.getElementById("txt-mesa-partial-msg");

      if (valPlanned) valPlanned.textContent = del.total_items;
      if (valCommitted) valCommitted.textContent = del.committed_items;
      if (valSkipped) valSkipped.textContent = del.skipped_items;
      if (valFailed) valFailed.textContent = del.failed_items;

      if (badgeState) {
        badgeState.textContent = del.status;
        if (del.status === "COMMITTED") badgeState.className = "badge badge-success";
        else if (del.status === "PARTIAL") badgeState.className = "badge badge-warning";
        else if (del.status === "FAILED") badgeState.className = "badge badge-danger";
        else badgeState.className = "badge badge-info";
      }

      if (del.status === "COMMITTED") {
        clearInterval(mesaDeliveryPollInterval);
        if (elStat) elStat.textContent = `MESA Aktarımı Tamamlandı: ${del.committed_items} COMMITTED, ${del.skipped_items} Atlandı ✅`;
        showToast("MESA aktarımı başarıyla tamamlandı.", "success");
        await loadExportView();
      } else if (del.status === "PARTIAL") {
        clearInterval(mesaDeliveryPollInterval);
        if (elStat) elStat.textContent = `MESA Aktarımı Kısmi Başarılı: ${del.committed_items} COMMITTED, ${del.failed_items} Başarısız ⚠️`;
        if (boxPartial) boxPartial.classList.remove("hidden");
        if (txtPartial) txtPartial.textContent = `${del.committed_items} COMMITTED, ${del.failed_items} FAILED. Başarısızlar yeniden denenebilir.`;
        showToast("MESA aktarımı kısmi tamamlandı.", "warning");
        await loadExportView();
      } else if (del.status === "FAILED") {
        clearInterval(mesaDeliveryPollInterval);
        if (elStat) elStat.textContent = `MESA Aktarımı Başarısız Oldu ❌`;
        if (boxPartial) boxPartial.classList.remove("hidden");
        if (txtPartial) txtPartial.textContent = `Aktarım başarısız: ${del.last_error || 'Hata oluştu'}`;
        showToast(`MESA aktarımı başarısız: ${del.last_error || 'Hata'}`, "danger");
        await loadExportView();
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  }, 1000);
}

async function handleMesaRetryFailed() {
  if (!activeMesaDeliveryId) {
    showToast("Aktif teslimat bulunamadı.", "warning");
    return;
  }
  setBusy(true);
  try {
    const res = await apiRequest(`/api/publisher/deliveries/${activeMesaDeliveryId}/retry`, { method: "POST" });
    showToast(`Yeniden deneme başlatıldı: ${res.retried_count} item deneniyor.`, "info");
    startMesaDeliveryPolling(activeMesaDeliveryId);
  } catch (err) {
    showToast(`Yeniden deneme hatası: ${err.message || err}`, "danger");
  } finally {
    setBusy(false);
  }
}

async function openDeliveryDetailModal(deliveryId) {
  setBusy(true);
  try {
    const res = await apiRequest(`/api/publisher/deliveries/${deliveryId}`);
    const del = res.delivery;
    const items = res.items || [];

    const modalBody = document.getElementById("delivery-modal-body");
    if (!modalBody) return;

    modalBody.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div>
          <h4>Teslimat: <code class="mono">${escapeHtml(del.delivery_id)}</code></h4>
          <span style="font-size: 13px; color: var(--color-text-secondary);">Hedef: ${escapeHtml(del.target_key)} · Başlangıç: ${friendlyDate(del.started_at)}</span>
        </div>
        <span class="badge ${del.status === 'COMMITTED' ? 'badge-success' : del.status === 'PARTIAL' ? 'badge-warning' : 'badge-danger'}">${del.status}</span>
      </div>

      <div class="stats-grid" style="grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px;">
        <div class="stat-card"><div class="stat-label">Toplam</div><div class="stat-value">${del.total_items}</div></div>
        <div class="stat-card"><div class="stat-label">COMMITTED</div><div class="stat-value" style="color: var(--color-success, green);">${del.committed_items}</div></div>
        <div class="stat-card"><div class="stat-label">Başarısız</div><div class="stat-value" style="color: var(--color-danger, red);">${del.failed_items}</div></div>
        <div class="stat-card"><div class="stat-label">Atlanan</div><div class="stat-value">${del.skipped_items}</div></div>
      </div>

      <h5>Source Chunk Aktarım Detayları (${items.length} item)</h5>
      <div class="table-responsive" style="max-height: 320px; overflow-y: auto;">
        <table class="data-table">
          <thead>
            <tr>
              <th>Chunk ID</th>
              <th>Belge</th>
              <th>Durum</th>
              <th>Mutation ID</th>
              <th>Idempotency Key</th>
              <th>Hata</th>
            </tr>
          </thead>
          <tbody>
            ${items.map((it) => `
              <tr>
                <td><code class="mono" style="font-size: 11px;">${escapeHtml(it.chunk_id)}</code></td>
                <td><code class="mono" style="font-size: 11px;">${escapeHtml(it.document_id)}</code></td>
                <td><span class="badge ${it.remote_state === 'COMMITTED' ? 'badge-success' : it.remote_state === 'SKIPPED' ? 'badge-neutral' : 'badge-danger'}">${it.remote_state}</span></td>
                <td><code class="mono" style="font-size: 11px;">${escapeHtml(it.remote_mutation_id || '-')}</code></td>
                <td><code class="mono" style="font-size: 10px;">${escapeHtml(it.idempotency_key)}</code></td>
                <td style="font-size: 12px; color: var(--color-danger, red);">${escapeHtml(it.last_error || '-')}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;

    showModal("modal-delivery-detail");
  } catch (err) {
    showToast(`Teslimat detayı yükleme hatası: ${err.message || err}`, "danger");
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
    statusText.textContent = "3/4 Release paketi onaylanıyor...";
    await apiRequest(`/api/releases/${releaseId}/publish`, { method: "POST" });

    // Step 4: Import Staging
    statusText.textContent = "4/4 Yerel Development Staging alanına aktarılıyor...";
    await apiRequest(`/api/releases/${releaseId}/import-staging`, { method: "POST" });

    statusText.textContent = "✓ Yerel Development Staging release paketi oluşturuldu.";
    showToast("Onaylı kayıtlar yerel development staging ortamına aktarıldı. (MESA v4 publisher entegrasyonu sonraki aşamada tamamlanacaktır)", "success");
  } catch (err) {
    console.error("Staging release error:", err);
    statusText.textContent = `İşlem tamamlanamadı: ${err.message}`;
    showToast("Yerel release oluşturulamadı. Oluşturulan paket korundu.", "danger");
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
    const [sources, settingsList] = await Promise.all([
      apiRequest("/api/sources"),
      apiRequest("/api/sources/settings").catch(() => []),
    ]);

    const settingsMap = {};
    (settingsList || []).forEach((item) => {
      settingsMap[item.source_id] = item;
    });

    const container = document.getElementById("sources-list");
    container.innerHTML = "";

    sources.forEach((s) => {
      const opt = settingsMap[s.source_id] || {
        enabled: s.enabled !== false,
        auto_approval_enabled: false,
        weekly_sample_count: 10,
        parsers: [],
      };

      const parsers = opt.parsers || [];

      const card = document.createElement("div");
      card.className = "source-card panel-box";
      card.style.marginBottom = "16px";
      card.innerHTML = `
        <div class="source-card-header" style="display: flex; justify-content: space-between; align-items: flex-start;">
          <div class="source-title-group">
            <h3 style="margin: 0 0 4px 0;">${escapeHtml(s.name)}</h3>
            <p style="margin: 0; font-size: 13px; color: var(--color-text-secondary);">${escapeHtml(s.authority || "-")}</p>
          </div>
          <span class="badge ${opt.enabled ? "badge-success" : "badge-neutral"}">${opt.enabled ? "Kaynak Aktif" : "Devre Dışı"}</span>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--color-border);">
          <div>
            <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600;">
              <input type="checkbox" id="chk-src-enabled-${s.source_id}" ${opt.enabled ? "checked" : ""}>
              Kaynak Veri Alımına İzin Ver
            </label>
            <small style="display: block; color: var(--color-text-muted); margin-top: 2px;">Kaynaktan otomatik ve manuel veri alımını denetler.</small>
          </div>

          <div>
            <label style="display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600;">
              <input type="checkbox" id="chk-src-auto-${s.source_id}" ${opt.auto_approval_enabled ? "checked" : ""}>
              Güvenli Otomatik Onay
            </label>
            <small style="display: block; color: var(--color-text-muted); margin-top: 2px;">Sadece PASS alan ve sertifikalı parser belgeleri otomatik onaylanır.</small>
          </div>

          <div>
            <label style="font-size: 13px; font-weight: 600; display: block;">Haftalık Örnek Denetim Sayısı</label>
            <input type="number" id="num-src-sample-${s.source_id}" value="${opt.weekly_sample_count ?? 10}" min="0" max="1000" style="width: 100px; margin-top: 4px; padding: 4px 8px;">
            <small style="display: block; color: var(--color-text-muted); margin-top: 2px;">Otomasyonu doğrulamak için seçilen audit örnekleri.</small>
          </div>
        </div>

        ${parsers.length > 0 ? `
          <div style="margin-top: 12px; padding: 8px 12px; background: var(--color-surface-subtle); border-radius: 6px; font-size: 12px;">
            <strong>Sertifikalı Parser Sürümleri:</strong>
            <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px;">
              ${parsers.map(p => `
                <span class="badge ${p.certified ? 'badge-success' : 'badge-neutral'}">
                  ${escapeHtml(p.parser_name)} v${escapeHtml(p.parser_version)}: ${p.certified ? 'Sertifikalı' : 'Sertifikasız'}
                </span>
              `).join('')}
            </div>
          </div>
        ` : ''}

        <div style="margin-top: 14px; display: flex; justify-content: space-between; align-items: center;">
          <div style="font-size: 12px; color: var(--color-text-muted);">
            <strong>Güvenlik Politikası:</strong> ${escapeHtml(s.base_url || "-")} · ${humanTerm(s.access_mode || "official_web")}
          </div>
          <button class="btn btn-sm btn-primary" onclick="saveSourceOperationalSettings('${escapeHtml(s.source_id)}')">Ayarları Kaydet</button>
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

async function saveSourceOperationalSettings(sourceId) {
  const enabled = document.getElementById(`chk-src-enabled-${sourceId}`)?.checked ?? true;
  const autoApproval = document.getElementById(`chk-src-auto-${sourceId}`)?.checked ?? false;
  const sampleCount = parseInt(document.getElementById(`num-src-sample-${sourceId}`)?.value || "10", 10);

  setBusy(true);
  try {
    await apiRequest(`/api/sources/${encodeURIComponent(sourceId)}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: enabled,
        auto_approval_enabled: autoApproval,
        weekly_sample_count: isNaN(sampleCount) ? 10 : sampleCount,
      }),
    });
    showToast(`"${sourceId}" ayarları güncellendi.`, "success");
    await loadSourcesView();
  } catch (err) {
    showToast(`Ayar kaydedilemedi: ${err.message || err}`, "danger");
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

  const btnVersionApprove = document.getElementById("btn-version-approve");
  if (btnVersionApprove) {
    btnVersionApprove.addEventListener("click", () => handleVersionBulkDecision("approve"));
  }

  const btnVersionReject = document.getElementById("btn-version-reject");
  if (btnVersionReject) {
    btnVersionReject.addEventListener("click", () => handleVersionBulkDecision("reject"));
  }

  // 13. Export & MESA Publisher Handlers
  const btnExportCreate = document.getElementById("btn-export-create");
  if (btnExportCreate) btnExportCreate.addEventListener("click", createExportAction);

  const btnMesaTransfer = document.getElementById("btn-mesa-transfer");
  if (btnMesaTransfer) btnMesaTransfer.addEventListener("click", runMesaTransferSequence);

  const btnMesaSaveSettings = document.getElementById("btn-mesa-save-settings");
  if (btnMesaSaveSettings) btnMesaSaveSettings.addEventListener("click", handleMesaSaveSettings);

  const btnMesaTestConn = document.getElementById("btn-mesa-test-conn");
  if (btnMesaTestConn) btnMesaTestConn.addEventListener("click", handleMesaTestConnection);

  const btnMesaPreflight = document.getElementById("btn-mesa-preflight");
  if (btnMesaPreflight) btnMesaPreflight.addEventListener("click", handleMesaPreflight);

  const btnMesaPubTrigger = document.getElementById("btn-mesa-publish-trigger");
  if (btnMesaPubTrigger) btnMesaPubTrigger.addEventListener("click", handleMesaPublishTrigger);

  const btnMesaConfirmPub = document.getElementById("btn-mesa-confirm-publish");
  if (btnMesaConfirmPub) btnMesaConfirmPub.addEventListener("click", handleMesaConfirmPublish);

  const btnMesaRetryFailed = document.getElementById("btn-mesa-retry-failed");
  if (btnMesaRetryFailed) btnMesaRetryFailed.addEventListener("click", handleMesaRetryFailed);

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
