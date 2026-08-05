# MESA Legal Data

MESA Legal Data, MESA hukuk ekosistemi için mevzuat, içtihat ve hukuki atıf verilerini toplayan, kanonikleştiren, doğrulayan ve MESA staging veritabanına güvenle aktaran uçtan uca veri platformudur.

## Katmanlı Mimari
```text
Resmî Kaynak / Yerel Dosya
        ↓
raw (Değişmez ham artifact + SHA-256 + metadata)
        ↓
parse & canonical (Değişmez JSONL parçaları)
        ↓
JSON Schema + Legal Metadata + Privacy Taraması
        ↓
İnsan Onayı (Review & Approval)
        ↓
release (Değişmez JSONL paketi + manifest.json)
        ↓
MESA Staging DB (Atomik, Idempotent Import & Rollback)
```

## Workspace (Çalışma Dizini)

MESA Legal Data, tüm verisini `MESA_DATA_DATA_ROOT` ortam değişkeninin gösterdiği dizinde saklar. Varsayılan: `~/.mesa-data/`.

```text
$DATA_ROOT/
  raw/                    # Değişmez ham artifact dosyaları
  canonical/              # Değişmez JSONL canonical kayıtlar
  releases/               # Değişmez release paketleri (manifest + JSONL)
  exports/                # Dışa aktarma dosyaları
  source_configs/         # Kaynak yapılandırma YAML dosyaları
  backups/                # Catalog yedekleri
  catalog.sqlite          # Ana veritabanı
```

## Veri Akışı

```text
1. Collect  → raw/ dizinine ham dosya + SHA-256 + metadata kaydı
2. Pipeline → parse → canonical JSONL üretimi → JSON Schema doğrulama
3. Review   → İnsan onayı (approve/reject) → audit kaydı
4. Release  → JSONL paketi + manifest.json + SHA-256 doğrulama
5. Import   → MESA Staging DB'ye atomik aktarım
6. Export   → Filtrelenmiş JSONL/CSV dışa aktarma
```

## Web Yönetim Paneli (Vanilla HTML/CSS/JS + FastAPI)

MESA Legal Data web yönetim paneli, tüm veri toplama, orkestrasyon, inceleme, release ve staging aktarım işlemlerini kullanıcı dostu sade bir HTML arayüz üzerinden gerçekleştirmenizi sağlar.

### Web Panelini Başlatma
```bash
uv run mesa-data web --host 127.0.0.1 --port 8765
```
Tarayıcınızda `http://127.0.0.1:8765` adresini açınız.

### Güvenlik & Admin Token
- Web paneli varsayılan olarak yalnızca yerel bilgisayardan (`127.0.0.1`) erişilebilir durumdadır.
- Dış ağa açılacak durumlarda `MESA_DATA_WEB_ADMIN_TOKEN` çevre değişkeninin ayarlanması zorunludur.
- Tüm yazma isteklerinde (`POST`/`PUT`/`DELETE`) `X-MESA-Requested-With: web-admin` başlığı zorunlu tutulmaktadır.

### Panel Ekranları
1. **📊 Genel Bakış (Dashboard):** Gerçek veritabanı sayaçları, son 10 belge, son işlemler ve aktif MESA release durumu.
2. **➕ Veri Ekle:** Yerel dosya (PDF/HTML) veya izinli HTTPS URL üzerinden ham veri aktarımı (`raw`).
3. **📄 Belgeler:** Tüm belgelerin listelenmesi, filtrelenmesi, artifact detayları ve tek tıkla pipeline orkestrasyonu.
4. **🔍 Veri Gezgini:** Documents, artifacts, versions, records, issues, releases listeleme ve filtreleme.
5. **İnceleme (Review):** İnceleme bekleyen canonical kayıtlar, metin önizlemeleri, blocker sorun uyarıları, insan onayı (`approve`) ve reddetme (`reject`).
6. **Sorunlar (Issues):** Açık ve çözülmüş doğrulama sorunlarını salt okunur listeleme.
7. **Kaynaklar (Sources):** İzinli kaynakları ve politikaları salt okunur listeleme.
8. **📦 Release'ler:** Gerçek JSONL release paketleme (`build`), SHA-256 manifest doğrulaması (`verify`), yayınlama (`publish`), MESA staging DB aktarımı (`import`), geri alma (`rollback`) ve iptal (`revoke`).
9. **Dışa Aktarma (Export):** Records JSONL/CSV, issues CSV, audit JSONL/CSV, provenance JSONL ve document package export üretme ve indirme.
10. **Operasyonlar:** Filtered export, release build ve integrity audit arka plan işleri.
11. **Audit:** Tüm veri yazma ve indirme audit kayıtlarını listeleme.
12. **⚙️ Sistem:** Sistem teşhisi (`doctor`), bütünlük denetimi (`audit`) ve yedekleme (`backup`).

---

## Hızlı Başlangıç (CLI)

### 1. Ortam Kurulumu
```bash
uv sync --frozen
```

### 2. Veri Dizinlerinin ve Kataloğun Başlatılması
```bash
uv run mesa-data init
uv run mesa-data migrate
```

### 3. Sağlık Kontrolü ve Bütünlük Taraması
```bash
uv run mesa-data doctor
uv run mesa-data audit
```

### 4. Örnek Kullanım Akışı

#### Veri Toplama (Manual URL veya Dosya Import)
```bash
uv run mesa-data collect url --source mevzuat --url https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf --document-id tr:legislation:constitution:2709 --title "Türkiye Cumhuriyeti Anayasası"
```

#### Pipeline Orkestrasyonu (Parsing & Canonical Kayıt Üretimi)
```bash
uv run mesa-data pipeline run --artifact-id art-...
```

#### İnceleme ve Onay (Review & Approval)
```bash
uv run mesa-data review list --status pending
uv run mesa-data review approve RECORD_ID --reviewer "yasin" --note "Kontrol edildi"
```

#### Release Paketi Üretimi ve Yayınlanması
```bash
uv run mesa-data release build --release-id release-v1.0
uv run mesa-data release verify --release-id release-v1.0
uv run mesa-data release publish --release-id release-v1.0
```

#### MESA Staging DB Import & Rollback
```bash
uv run mesa-data release import --release-id release-v1.0
uv run mesa-data release rollback --release-id release-v1.0
uv run mesa-data provenance RECORD_ID
```

---

## Exports (Dışa Aktarma)

```bash
# API üzerinden
POST /api/exports
{
  "export_type": "records_jsonl",
  "filters": {"record_type": "article", "approval_status": "approved"}
}
```

Desteklenen formatlar:
- `records_jsonl` — Canonical kayıtlar (JSONL)
- `records_csv` — Tablo formatı (CSV)
- `issues_csv` — Doğrulama sorunları (CSV)
- `audit_jsonl` / `audit_csv` — Denetim logları
- `provenance_jsonl` — Veri kökeni zihniyeti
- `document_package` — Ham belge paketleri

---

## Downloads (Güvenli İndirmeler)

Tüm indirmeler `resolve_verified_download` güvenlik katmanından geçer:
- **Exact ID lookup** — Path traversal engeli
- **Symlink kontrolü** — Gerçek dosya doğrulaması
- **SHA-256 doğrulaması** — İndirme anında bütünlük kontrolü
- **Audit kaydı** — Her indirme loglanır

---

## Backup & Teşhis

```bash
# Teşhis
uv run mesa-data doctor

# Yedekleme
uv run mesa-data backup
```

---

## Bilinen Sınırlar (Limitations)

- **Tek sunucu mimarisi** — SQLite write lock ile korunur, dağıtık dağıtım desteklenmez.
- **Senkron pipeline** — Büyük dosyalarda (>100MB PDF) uzun sürebilir.
- **Token tabanlı kimlik doğrulama** — OAuth/OIDC entegrasyonu henüz mevcut değil.

---

## V2'ye Ertelenen Özellikler (Scope-Out)

Aşağıdaki deneysel özellikler MVP kapsamından çıkarılmış ve V2 sürümüne ertelenmiştir:
- Record revision (kayıt revizyon) UI ve public API
- Source config web editörü (kaynak ayarları `config/sources.yaml` üzerinden elle yönetilir)
- Issue management (sorun waive/reopen/resolve sistemi)
- Annotations (özel not ve etiket yönetimi API)
- Release diff (release karşılaştırma merkezi)
- Full snapshot merkezi
- Çok kullanıcılı yetkilendirme (OAuth/OIDC)
