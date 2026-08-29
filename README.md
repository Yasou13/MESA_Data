# MESA Legal Data

MESA Legal Data; resmî mevzuat, içtihat ve hukuki atıf verilerini otomatik toplayan, ham dosyaları değiştiremez biçimde saklayan, kanonikleştiren ve kalite kapılarından geçiren veri platformudur. Güvenli koşulları sağlayan sürümler otomatik onaylanabilir; istisnalar insan incelemesine gider. Gerçek MESA gönderimi yalnız insan başlatınca, otomatik oluşturulup doğrulanan immutable release paketinden yapılır. Yerel staging yalnız development aracıdır ve gerçek MESA değildir.

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
Kalite Kapıları + Gizlilik + Hukuki Metadata Doğrulaması
              ↓
Güvenli Otomatik Onay / İnsan İstisna İncelemesi
              ↓
Immutable Release (otomatik build → verify → frozen summary → insan onayı)
              ↓
Gerçek MESA Publisher (idempotent, yalnız COMMITTED başarı)
              └─ Yerel Development Staging (ayrı, isteğe bağlı)
```

---

## Veri Dizin Yapısı (Workspace)

Sistem tüm verilerini `MESA_DATA_DATA_ROOT` ortam değişkeninin gösterdiği dizinde saklar (Öncelik: Yapılandırılan `MESA_DATA_DATA_ROOT` → Varsayılan: `/storage/mesa-legal-data/data` → İzin hatasında yedek: `~/.mesa-data/data`).


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
- Yalnız sertifikalı kaynak/parser ve PASS kalite koşullarını sağlayan sürümler güvenli biçimde otomatik onaylanabilir; diğerleri insan incelemesine gider.
- MESA'ya gönderim hiçbir zaman otomatik başlamaz.

---

## Web Yönetim Paneli (FastAPI + HTML/CSS/JS)

MESA Legal Data, veri toplama, kalite/istisna incelemesi, immutable release ve insan başlatmalı gerçek MESA gönderimini yönetebileceğiniz web tabanlı bir arayüze sahiptir. Panel normal akışta kullanıcıdan release ID istemez; exact release ve manifest özetini otomatik hazırlar.

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

# E. Yalnız geliştirme amaçlı yerel staging importu (gerçek MESA değildir)
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
