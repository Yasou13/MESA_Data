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
