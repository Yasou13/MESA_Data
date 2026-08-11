# MESA Legal Data

MESA Legal Data; MESA hukuk ekosistemi için resmî mevzuat, içtihat ve hukuki atıf verilerini toplayan, ham dosyaları değiştiremez biçimde saklayan, ayrıştıran, kanonikleştiren, doğrulayan ve MESA staging veritabanına aktaran uçtan uca veri platformudur.

---

## Katmanlı Mimari

```text
Resmî Kaynak (HTTPS / Manuel PDF)
   ├─ Manuel URL / Yerel Dosya (collect)
   └─ Otomatik Keşif Kuyruğu (harvest discover → run)
              ↓
Ham Veri Deposu (raw/ — Değişmez Artifact + SHA-256 + Metadata)
              ↓
Ayrıştırma & Kanonikleştirme Pipeline'ı (parse → canonical JSONL)
              ↓
Gizlilik Taraması & Hukuki Metadata Doğrulaması (Schema & Privacy)
              ↓
İnsan Onayı (Human Review — approve / reject)
              ↓
Release Derleme & Doğrulama (build → verify → publish)
              ↓
MESA Staging DB (Atomik, Idempotent Import & Provenance)
```

---

## Veri Dizin Yapısı (Workspace)

Sistem tüm verilerini `MESA_DATA_DATA_ROOT` ortam değişkeninin gösterdiği dizinde saklar (Varsayılan: `~/.mesa-data/data` veya `config/settings.yaml` konumu).

```text
$DATA_ROOT/
  raw/                    # Değişmez ham artifact dosyaları (PDF, HTML)
  canonical/              # Sürüm bazlı kanonik JSONL kayıtları
  releases/               # Yayınlanan release paketleri (manifest.json + JSONL)
  exports/                # Üretilen dışa aktarma dosyaları
  backups/                # Katalog veritabanı yedekleri
  harvest/                # Harvest veritabanı (harvest.sqlite) ve yedekleri
  catalog.sqlite          # Ana katalog veritabanı
```

---

## Otomatik Veri Toplama (Harvest)

MESA Legal Data, tanımlı resmî kaynaklardan belge bağlantılarını keşfeden ve indirme kuyruğunu yöneten bir Harvest altsistemine sahiptir. Harvest, ana katalogdan bağımsız `harvest.sqlite` üzerinde çalışır.

### Harvest Komutları
```bash
uv run mesa-data harvest init
uv run mesa-data harvest config-check
uv run mesa-data harvest discover --source resmi_gazete
uv run mesa-data harvest status
uv run mesa-data harvest run --once --limit 25
uv run mesa-data harvest failures
uv run mesa-data harvest maintenance
```

### Güvenlik & Politika
- Keşif ve indirmeler yalnızca `config/sources.yaml` ve `config/harvest.yaml` dosyalarında izin verilen resmi kaynaklarda çalışır.
- İndirme işlemleri SSRF, MIME türü, boyut sınırı (~50 MB) ve hız sınırı denetimlerinden geçer.
- Otomatik onay veya yayınlama yapılmaz; tüm veriler insan onayı (`review`) süzgecinden geçer.

---

## Web Yönetim Paneli (FastAPI + HTML/CSS/JS)

MESA Legal Data, tüm veri toplama, orkestrasyon, inceleme, release ve staging aktarım işlemlerini yönetebileceğiniz web tabanlı bir arayüze sahiptir.

### Web Panelini Başlatma
```bash
uv run mesa-data web --host 127.0.0.1 --port 8765
```
Tarayıcınızda `http://127.0.0.1:8765` adresini açınız.

### Güvenlik & Admin Token
- Web paneli varsayılan olarak yalnızca yerel bilgisayardan (`127.0.0.1`) erişilebilir durumdadır.
- Sunucu dış ağa (`0.0.0.0`) açılacağında `MESA_DATA_WEB_ADMIN_TOKEN` ortam değişkeni zorunludur.

---

## Hızlı Komut Akışı (CLI)

### 1. Kurulum ve Başlatma
```bash
# Bağımlılıkları yükleyin
uv sync --frozen

# Veri dizinlerini ve veritabanı şemasını hazırlayın
uv run mesa-data init
uv run mesa-data migrate
```

### 2. Örnek Kullanım Akışı

```bash
# A. Veri Ekleme (Manuel veya URL)
uv run mesa-data collect url \
  --source mevzuat \
  --url https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf \
  --document-id tr:legislation:constitution:2709 \
  --title "Türkiye Cumhuriyeti Anayasası"

# B. Pipeline Orkestrasyonu
uv run mesa-data pipeline run --artifact-id sha256:<ARTIFACT_HASH>

# C. İnceleme ve Onay
uv run mesa-data review list --status pending
uv run mesa-data review approve-version <VERSION_ID> --reviewer "operator@example.com"

# D. Release Derleme ve Yayınlama
uv run mesa-data release build --release-id release-v1.0
uv run mesa-data release verify --release-id release-v1.0
uv run mesa-data release publish --release-id release-v1.0

# E. MESA Staging DB Import
uv run mesa-data release import --release-id release-v1.0

# F. İzlenebilirlik Sorgusu
uv run mesa-data provenance <RECORD_ID>
```

### 3. Teşhis ve Sağlık Kontrolü
```bash
# Sistem teşhisi ve bütünlük denetimi
uv run mesa-data doctor

# Raw artifact SHA-256 bütünlük kontrolü
uv run mesa-data audit

# Veritabanı yedeği alma
uv run mesa-data backup
```

---

## Dokümantasyon

- 🚀 **[Hızlı Başlangıç Rehberi](docs/HIZLI_BASLANGIC.md)** — 5 dakikada kurulum ve ilk veri aktarımı.
- 📖 **[Kullanım Kılavuzu](docs/KULLANIM_KILAVUZU.md)** — Detaylı operasyon rehberi, Harvest altsistemi, arayüz tanıtımı ve CLI referansı.
- 📐 **[MESA Import Sözleşmesi](docs/IMPORT_CONTRACT.md)** — Staging DB aktarım kuralları ve veri modeli sözleşmesi.
- 🔒 **[MVP Kapanış Raporu](docs/MVP_CLOSURE_REPORT.md)** — MVP freeze doğrulamaları ve TLS güvenlik mimarisi.

---

## Sınırlar ve V2 Kapsamı

Aşağıdaki özellikler MVP kapsamı dışında bırakılmış ve V2 sürümüne ertelenmiştir:
- Kayıt revizyon editörü (record revision UI)
- Web üzerinden kaynak yapılandırma editörü (`config/sources.yaml` üzerinden yönetilir)
- Otomatik sorun kapatma/waive mekanizması (sorunlar salt okunurdur)
- Çok kullanıcılı OAuth/OIDC yetkilendirmesi
