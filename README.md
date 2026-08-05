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

### Ekranlar ve Fonksiyonlar
1. **📊 Genel Bakış (Dashboard):** Gerçek veritabanı sayaçları, son 10 belge, son işlemler ve aktif MESA release durumu.
2. **➕ Veri Ekle:** Yerel dosya (PDF/HTML) veya resmî HTTPS URL üzerinden ham veri aktarımı (`raw`).
3. **📄 Belgeler:** Tüm belgelerin listelenmesi, filtrelenmesi, artifact detayları ve tek tıkla pipeline orkestrasyonu.
4. **🔍 İnceleme (Review):** İnceleme bekleyen canonical kayıtlar, metin önizlemeleri, blocker sorun uyarıları, insan onayı (`approve`) ve reddetme (`reject`).
5. **📦 Release'ler:** Gerçek JSONL release paketleme (`build`), SHA-256 manifest doğrulaması (`verify`), yayınlama (`publish`), MESA staging DB aktarımı (`import`), geri alma (`rollback`) ve iptal (`revoke`).
6. **⚙️ Sistem:** Sistem teşhisi (`doctor`), bütünlük denetimi (`audit`) ve yedekleme (`backup`).

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
uv run mesa-data pipeline run --artifact-id sha256:...
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

## Actor & Token Yönetimi

Tüm yazma (POST/PUT/DELETE) istekleri aşağıdaki başlıkları gerektirir:

| Başlık | Açıklama |
|---|---|
| `X-MESA-Actor` | İşlemi yapan kişi/servis adı (audit kaydı için zorunlu) |
| `X-MESA-Requested-With` | `web-admin` değeri (CSRF koruması) |
| `Authorization` | `Bearer <MESA_DATA_WEB_ADMIN_TOKEN>` (dış ağ erişiminde zorunlu) |

Web panelinde actor değeri `sessionStorage["mesa_actor"]` üzerinden saklanır. CLI'da `--actor` parametresi veya `MESA_ACTOR` ortam değişkeni kullanılır.

---

## Revision Sistemi

Canonical kayıtlar değişmezdir (immutable). Değişiklik gerektiğinde **revision** oluşturulur:

```bash
# API üzerinden
POST /api/records/{record_id}/revisions
{
  "change_type": "typo_fix",
  "patch": {"op": "replace", "path": "/text", "value": "Düzeltilmiş metin"},
  "reason": "Yazım hatası düzeltmesi",
  "created_by": "yasin"
}

# Onay
POST /api/revisions/{revision_id}/approve
```

Revisionlar `record_revisions` tablosunda saklanır ve audit kaydı oluşturulur. Kaynak yapılandırmaları için de benzer sistem mevcuttur (`/api/source-configs/revisions`).

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
- `records_jsonl` — Tüm kayıtlar (JSONL)
- `records_csv` — Tablo formatı (CSV)
- `legislation_jsonl`, `article_jsonl` — Tür bazlı

Her export `export_packages` tablosunda kaydedilir. SHA-256 doğrulaması, dosya boyutu ve oluşturan aktör bilgisi audit ile birlikte saklanır.

---

## Downloads (İndirmeler)

```text
GET /api/downloads/{export_id}
```

İndirmeler güvenlik katmanından geçer:
- **Exact ID lookup** — Path traversal engeli
- **Symlink kontrolü** — Gerçek dosya doğrulaması
- **SHA-256 doğrulaması** — İndirme anında bütünlük kontrolü
- **Audit kaydı** — Her indirme loglanır

---

## Source Config (Kaynak Yapılandırması)

```bash
# Yeni config revision oluştur
POST /api/source-configs/revisions
{
  "content_yaml": "sources:\n  mevzuat:\n    enabled: true",
  "reason": "Mevzuat kaynağı aktifleştirme",
  "created_by": "yasin"
}

# Aktifleştir (runtime'a uygula)
POST /api/source-configs/revisions/{revision_id}/activate
```

Aktifleştirme, YAML dosyasını `source_configs/active.yaml` yoluna yazar ve audit kaydı oluşturur.

---

## Snapshot & Backup

```bash
# API üzerinden
POST /api/system/backup

# CLI
uv run mesa-data backup
```

Backup, catalog SQLite veritabanının tutarlı bir kopyasını alır. Restore işlemi `restore_catalog()` fonksiyonu ile yapılır.

Full snapshot, raw dosyalar, canonical kayıtlar, release paketleri ve audit loglarını kapsar.

---

## Limitations (Kısıtlamalar)

- **Tek sunucu mimarisi** — SQLite write lock ile korunur, dağıtık dağıtım desteklenmez.
- **Senkron pipeline** — Büyük dosyalarda (>100MB PDF) uzun sürebilir.
- **Tam metin arama yok** — Explorer yalnızca metadata filtresi yapar.
- **Token tabanlı kimlik doğrulama** — OAuth/OIDC entegrasyonu henüz mevcut değil.
- **Rollback sınırı** — Yalnızca en son import edilen release geri alınabilir.

