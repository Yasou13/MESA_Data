# MESA Data — Hızlı Başlangıç

MESA Data; Türkiye resmî hukuk kaynaklarından (Resmî Gazete, Mevzuat Bilgi Sistemi vb.) veri toplayan, kanonikleştiren, doğrulayan ve onaylı paketleri MESA staging veritabanına aktaran veri platformudur.

Bu rehber, sistemi ilk kez kuran teknik bir kullanıcının dakikalar içinde MESA Data'yı çalıştırıp ilk uçtan uca veri акtarımını tamamlamasını sağlar.

---

## 1. Gereksinimler

- **İşletim Sistemi:** Linux (Ubuntu 22.04+ önerilir) veya macOS
- **Python Sürümü:** 3.11 – 3.13 (Python 3.13 önerilir)
- **Paket Yöneticisi:** [uv](https://docs.astral.sh/uv/) (v0.5+)
- **Disk ve Depolama:** Minimum 2 GB boş disk alanı, SQLite3

---

## 2. Kurulum

```bash
# Repoyu klonlayın ve proje dizinine geçin
git clone https://github.com/Yasou13/MESA_Data.git mesa-legal-data
cd mesa-legal-data

# Bağımlılıkları sabitlenmiş kilit dosyasından yükleyin
uv sync --frozen

# Veri dizinlerini (raw, canonical, releases, tmp) oluşturun
uv run mesa-data init

# Katalog veritabanı şemasını hazırlayın
uv run mesa-data migrate
```

---

## 3. İlk Kontrol

Sistemin ve CLI komutlarının doğru kurulduğunu doğrulayın:

```bash
uv run mesa-data --help
```

---

## 4. Temel Yapılandırma

MESA Data, varsayılan ayarlarıyla çalışmaya hazırdır. Değişiklik yapmak isterseniz `config/settings.yaml` ve `config/sources.yaml` dosyalarını düzenleyebilirsiniz.

### Zorunlu / Önemli Ayarlar
- **Operator İletişim Bilgisi (Zorunlu):** `config/settings.yaml` içindeki `operator_contact` değeri varsayılan olarak tanımlıdır. Production ortamında yer tutucu adresler kabul edilmez.
  - Örnek: `operator_contact: "operator@example.com"` (Lütfen kendi e-posta adresinizi girin)
- **Data Root (Opsiyonel):** Varsayılan veri depolama konumu `MESA_DATA_DATA_ROOT` ortam değişkeni ile özelleştirilebilir.

### Güvenlik Ayarları
- **Admin Token (Opsiyonel / Dış Ağ İçin Zorunlu):** Web panelini yerel bilgisayar dışında (`0.0.0.0`) çalıştırmak için ortam değişkenini ayarlayın:
  ```bash
  export MESA_DATA_WEB_ADMIN_TOKEN="güçlü-bir-gizli-token"
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
# (Çıktıdaki artifact ID örneğin sha256:abc123... formatındadır)
uv run mesa-data pipeline run --artifact-id sha256:<ARTIFACT_HASH>
```

Pipeline tamamlandığında canonical kayıtlar üretilir ve durum `needs_review` (inceleme bekliyor) olarak güncellenir.

---

## 6. İnceleme ve Onay

Verilerin release paketine dahil edilebilmesi için onaylanması gerekir.

```bash
# İnceleme bekleyen sürümleri onaylayın
uv run mesa-data review approve-version <VERSION_ID> --reviewer "operator@example.com" --note "İlk kontrol tamamlandı"
```

*Alternatif olarak web arayüzünü başlatarak (`uv run mesa-data web`) **İnceleme Masası** üzerinden görsel onay verebilirsiniz.*

---

## 7. Release Oluşturma ve Yayınlama

Onaylanan kayıtlardan doğrulanmış bir MESA release paketi derleyin:

```bash
# 1. Release paketini derleyin
uv run mesa-data release build --release-id release-v1.0

# 2. Release paket bütünlüğünü ve SHA-256 manifestini doğrulayın
uv run mesa-data release verify --release-id release-v1.0

# 3. Release paketini yayınlayın
uv run mesa-data release publish --release-id release-v1.0
```

---

## 8. MESA Staging Import

Yayınlanan release paketini MESA staging veritabanına aktarın:

```bash
uv run mesa-data release import --release-id release-v1.0
```

*Not: Import işlemi **idempotent**'tir; aynı release paketi tekrar import edildiğinde mükerrer veri üretmez ve güvenle tamamlanır.*

---

## 9. Sorun Olursa

- **Geliştirici İletişim Adresi Hatası (`OPERATOR_CONTACT_INVALID`):** `config/settings.yaml` içindeki yer tutucu adresi gerçek operasyonel adresinizle değiştirin.
- **TLS / Sertifika Hatası:** MESA Data, TLS doğrulaması ve alan adı kontrolünü zorunlu tutar (`verify=False` kabul edilmez). Resmî Gazete dâhil tüm sertifika zincirleri dâhili güvenli CA deposuyla doğrulanır.
- **İnceleme Bekleyen Kayıt Uyarısı:** Onaylanmamış (`pending`) veya engellenmiş (`blocker issue`) kayıtlar release paketine dahil edilmez.
- **Dış Ağ Erişim Engeli:** Web sunucusu `--host 0.0.0.0` ile başlatılacaksa `MESA_DATA_WEB_ADMIN_TOKEN` ortam değişkeni ayarlanmalıdır.

---

Ayrıntılı kullanım kılavuzu, arayüz tanıtımı, Harvest otomatik toplama mekanizması ve tüm CLI komut referansı için:  
👉 **[docs/KULLANIM_KILAVUZU.md](KULLANIM_KILAVUZU.md)**
