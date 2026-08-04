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

## Hızlı Başlangıç

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
