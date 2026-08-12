# MESA Data — Hızlı Başlangıç

MESA Data; Türkiye resmî hukuk kaynaklarından (Resmî Gazete, Mevzuat Bilgi Sistemi vb.) veri toplayan, kanonikleştiren, doğrulayan ve onaylı paketleri MESA staging veritabanına aktaran veri platformudur.

Bu rehber, sistemi ilk kez kuran teknik bir kullanıcının dakikalar içinde MESA Data'yı çalıştırıp ilk uçtan uca veri aktarımını tamamlamasını sağlar.

---

## 1. Gereksinimler

- **İşletim Sistemi:** Linux (Ubuntu 22.04+ önerilir) veya macOS
- **Python Sürümü:** 3.11 – 3.13 (Python 3.13 önerilir)
- **Paket Yöneticisi:** [uv](https://docs.astral.sh/uv/) (v0.5+)
- **Disk ve Depolama:**
  - **Temel / Manuel Kullanım:** Birkaç GB boş disk alanı yeterlidir.
  - **Varsayılan Harvest Otomatik Veri Toplama Guardrail:** Yaklaşık **50 GiB** boş disk alanı gereklidir (`minimum_free_disk_bytes: 53687091200`).

---

## 2. Kurulum ve Ortam Yapılandırması

```bash
# Repoyu klonlayın ve proje dizinine geçin
git clone https://github.com/Yasou13/MESA_Data.git mesa-legal-data
cd mesa-legal-data

# Bağımlılıkları kilit dosyasından yükleyin
uv sync --frozen

# Ortam değişkenleri dosyasını kopyalayın
cp .env.example .env
```

---

## 3. Yapılandırma Sözleşmesi (.env)

MESA Data ayarları çalışma zamanında `.env` dosyası ve `MESA_DATA_*` ortam değişkenleri üzerinden yüklenir (`config/settings.yaml` dosyası yalnızca kod içinden özel yol ile çağrıldığında tüketilir).

`.env` dosyanızı açın ve aşağıdaki temel değişkenleri tanımlayın:

```env
# Operatör İletişim Bilgisi (Otomatik web aramalarında zorunludur; yer tutucu kabul edilmez)
MESA_DATA_OPERATOR_CONTACT=contact@yourdomain.org

# Veri Kök Dizin (Opsiyonel)
MESA_DATA_DATA_ROOT=/storage/mesa-legal-data/data

# Çalışma Ortamı (Kabul edilen değerler: development | production | testing)
MESA_DATA_ENVIRONMENT=development
```

> **Önemli:** Otomatik web aramalarında (`approved_web` / `licensed_api`), `MESA_DATA_OPERATOR_CONTACT` içinde yer tutucu adresler (`operator@example.com`, `test@example.com` vb.) kabul edilmez ve istek `SourcePolicyError` ile reddedilir.

---

## 4. İlk Başlatma

```bash
# Veri dizinlerini (raw, canonical, releases, tmp) oluşturun
uv run mesa-data init

# Katalog veritabanı şemasını hazırlayın
uv run mesa-data migrate

# Kurulumu ve yardım menüsünü doğrulayın
uv run mesa-data --help
```

---

## 5. İlk Çalıştırma (Veri Toplama ve Pipeline)

Yerel bir PDF belgesini sisteme ham veri (artifact) olarak yükleyin ve ayrıştırma pipeline'ını çalıştırın:

```bash
# 1. Ham veriyi sisteme ekleyin
uv run mesa-data collect manual \
  --source mevzuat \
  --file /yol/belge.pdf \
  --document-id tr:legislation:law:4721 \
  --family legislation \
  --document-type law \
  --title "Türk Medeni Kanunu"

# 2. Üretilen artifact ID ile pipeline'ı çalıştırın
uv run mesa-data pipeline run --artifact-id sha256:<ARTIFACT_HASH>
```

Pipeline tamamlandığında kanonik kayıtlar üretilir ve durum `needs_review` (inceleme bekliyor) olarak güncellenir.

---

## 6. İnceleme ve Onay

Verilerin release paketine dahil edilebilmesi için onaylanması gerekir.

```bash
# İnceleme bekleyen sürümleri onaylayın
uv run mesa-data review approve-version <VERSION_ID> --reviewer "contact@yourdomain.org" --note "İlk kontrol tamamlandı"
```

*Alternatif olarak web arayüzünü başlatarak (`uv run mesa-data web`) **İnceleme Masası** üzerinden görsel onay verebilirsiniz.*

---

## 7. Release Oluşturma ve Yayınlama

Onaylanan kayıtlardan doğrulanmış bir MESA release paketi derleyin ve yayınlayın:

```bash
# 1. Release paketini derleyin
uv run mesa-data release build --release-id release-v0.1.0

# 2. Release paket bütünlüğünü ve SHA-256 manifestini doğrulayın
uv run mesa-data release verify --release-id release-v0.1.0

# 3. Release paketini güvenli yayınlama fonksiyonuyla yayınlayın
uv run mesa-data release publish --release-id release-v0.1.0
```

---

## 8. MESA Staging Import

Yayınlanan release paketini MESA staging veritabanına aktarın:

```bash
uv run mesa-data release import --release-id release-v0.1.0
```

*Not: Import işlemi **idempotent**'tir; aynı release paketi tekrar import edildiğinde mükerrer veri üretmez ve güvenle tamamlanır.*

---

## 9. Sorun Giderme Hızlı İpuçları

- **Operatör İletişim Hatası (`OPERATOR_CONTACT_MISSING` / `OPERATOR_CONTACT_INVALID`):** `.env` dosyasındaki `MESA_DATA_OPERATOR_CONTACT` değişkenine geçerli operasyonel e-posta adresinizi girin.
- **TLS / Sertifika Hatası:** MESA Data, TLS doğrulaması ve alan adı kontrolünü zorunlu tutar (`verify=False` kesinlikle kullanılmaz). Sunucu sertifika zincirleri pakete dahil edilen güvenli GeoTrust CA deposuyla otomatik doğrulanır.
- **Yetersiz Disk Alanı Hatası:** Harvest otomatik toplama mekanizması varsayılan olarak ~50 GiB boş disk alanı denetler. Disk alanınızı artırın veya Harvest yapılandırmasını güncelleyin.

---

Ayrıntılı kullanım kılavuzu, arayüz tanıtımı, Harvest otomatik toplama mekanizması ve tüm CLI komut referansı için:  
👉 **[docs/KULLANIM_KILAVUZU.md](KULLANIM_KILAVUZU.md)**
