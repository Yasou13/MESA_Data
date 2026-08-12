# MESA Data — Kullanım Kılavuzu

**Sürüm:** 0.1.0 (MVP Frozen)  
**Son Güncelleme:** 2026-08-12  

---

## 1. MESA Data Nedir?

MESA Data, Türkiye resmî hukuk kaynaklarından (Resmî Gazete, Mevzuat Bilgi Sistemi, Anayasa Mahkemesi vb.) hukuki metin ve içtihat verilerini **toplayan, ham dosyaları saklayan, ayrıştıran, kanonikleştiren, doğrulayan ve MESA staging veritabanına aktaran** veri platformudur.

Platform temel olarak şu akışla çalışır:

```text
Resmî Hukuk Kaynağı (HTTPS / Manuel PDF)
          ↓
     Veri Toplama (Collect / Harvest)
          ↓
Ham Veri Deposu (Raw Artifact — SHA-256 İmmutable)
          ↓
  Ayrıştırma & Kanonikleştirme Pipeline'ı
          ↓
İnsan İncelemesi ve Onay (Human Review)
          ↓
Release Paketi Derleme & Doğrulama (Build / Verify / Publish)
          ↓
MESA Staging Import & İzlenebilirlik (Provenance)
```

---

## 2. Temel Kavramlar

- **Source (Kaynak):** Verinin toplandığı resmî kurum veya platform (örn. `resmi_gazete`, `mevzuat`).
- **Raw Artifact (Ham Dosya):** Kaynaktan indirilen veya yüklenen değiştirilemez ham PDF/HTML dosyası.
- **Document & Version (Belge ve Sürüm):** Hukuki belgenin üst düzey tanımı ve pipeline sonucunda üretilen kanonik sürümü.
- **Human Review (İnsan İncelemesi):** Üretilen kanonik verilerin doğruluğunu ve gizlilik taramasını insan operatör onayından geçirme mekanizması.
- **Release:** Onaylı kanonik verilerin manifest ve SHA-256 hash'leri ile paketlendiği yayın birimi.
- **Staging Import:** Yayınlanmış bir release paketinin MESA staging SQLite veritabanına güvenli ve idempotent aktarımı.
- **Provenance (Veri Kökeni):** Bir kaydın hangi kaynaktan, hangi artifact'tan ve aktif release içindeki gerçek varlığını izleyen köken zinciri.
- **Harvest:** Resmî kaynaklardan otomatik veri keşfi ve kuyruk tabanlı toplama altsistemi.

---

## 3. Kurulum ve Disk Gereksinimleri

### Sistem Gereksinimleri
- **OS:** Linux (Ubuntu 22.04 LTS+) / macOS
- **Python:** 3.11 – 3.13 (`uv` yönetimi ile)
- **Bağımlılık Yöneticisi:** `uv` (v0.5+)
- **Disk Alanı:**
  - **Temel / Manuel Kullanım:** Birkaç GB boş disk alanı.
  - **Harvest Otomatik Toplama Safety Guardrail:** Varsayılan olarak minimum **50 GiB** boş disk alanı gereklidir (`minimum_free_disk_bytes: 53687091200`).

### Kurulum Adımları

```bash
# Repoyu klonlayın
git clone https://github.com/Yasou13/MESA_Data.git mesa-legal-data
cd mesa-legal-data

# Bağımlılıkları yükleyin
uv sync --frozen

# Örnek ortam değişkenleri dosyasını kopyalayın
cp .env.example .env

# Veri dizin yapısını hazırlayın
uv run mesa-data init

# Katalog veritabanı tablolarını oluşturun
uv run mesa-data migrate
```

---

## 4. Yapılandırma

Çalışma zamanı yapılandırması `.env` dosyası ve `MESA_DATA_*` ortam değişkenleri üzerinden yönetilir (`config/settings.yaml` yalnızca koda özel dosya yolu parametresi verildiğinde tüketilir).

| Parametre / Ortam Değişkeni | Zorunlu | Kabul Edilen Değerler / Açıklama |
|---|---|---|
| `MESA_DATA_OPERATOR_CONTACT` | **Otomatik Web İçin Evet** | Otomatik web aramalarında User-Agent başlığına eklenen operatör e-posta adresi (`contact@yourdomain.org`). Yer tutucular kabul edilmez. |
| `MESA_DATA_DATA_ROOT` | Hayır | Verilerin saklanacağı ana kök dizin (Varsayılan: `/storage/mesa-legal-data/data`). |
| `MESA_DATA_ENVIRONMENT` | Hayır | `development`, `production`, veya `testing`. |
| `MESA_DATA_LOG_LEVEL` | Hayır | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `MESA_DATA_WEB_ADMIN_TOKEN` | *Dış ağ için Evet* | Web arayüzünün dış ağa (`0.0.0.0`) açılması durumunda zorunlu güvenlik tokeni. |

---

## 5. Veri Toplama

MESA Data iki farklı veri toplama yöntemi sunar:

### A. Manuel Toplama (CLI & Web UI)
Tekil bir PDF/HTML dosyasını veya belirli bir URL'yi doğrudan sisteme ham artifact olarak ekler:

```bash
# Yerel dosyadan yükleme (Manuel modda operator_contact opsiyoneldir)
uv run mesa-data collect manual \
  --source mevzuat \
  --file /yol/belge.pdf \
  --document-id tr:legislation:law:4721 \
  --family legislation \
  --document-type law \
  --title "Türk Medeni Kanunu"

# Doğrudan URL'den güvenli indirme
uv run mesa-data collect url \
  --source mevzuat \
  --url https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf \
  --document-id tr:legislation:constitution:2709 \
  --title "T.C. Anayasası"
```

### B. Otomatik Toplama (Harvest Subsystem)
Resmî kaynaklarda otomatik keşif yapar ve indirme kuyruğunu yönetir (geçerli `MESA_DATA_OPERATOR_CONTACT` zorunludur):

```bash
# Harvest veritabanını hazırlayın
uv run mesa-data harvest init

# Yapılandırmayı ve guardrail bütçelerini kontrol edin
uv run mesa-data harvest config-check

# Resmî Gazete keşfi çalıştırın (Keşfedilen belgeler kuyruğa eklenir)
uv run mesa-data harvest discover --source resmi_gazete

# Kuyruktaki belgeleri indirip pipeline'a aktarın
uv run mesa-data harvest run --once --limit 25
```

---

## 6. Harvest Kuyruk Durumları

Harvest kuyruğundaki her öge aşağıdaki durumlardan birindedir:

| Durum | Açıklama | Operatör Müdahalesi Gerekir mi? |
|---|---|---|
| `queued` | İndirilmeyi bekliyor. | Hayır |
| `leased` | Bir harvest çalışanı tarafından kilitlendi. | Hayır |
| `downloading` | İndirme işlemi devam ediyor. | Hayır |
| `processing` | Pipeline işlemi yürütülüyor. | Hayır |
| `needs_review` | Pipeline başarıyla tamamlandı, insan onayı bekliyor. | **Evet** (İnceleme Masası) |
| `retry_wait` | Geçici hata alındı, tekrar deneme süresi bekleniyor. | Hayır (Otomatik tekrar dener) |
| `failed` | Kalıcı hata oluştu (ör. HTTP 404, bozuk PDF). | **Evet** (`mesa-data harvest retry`) |
| `blocked` | Güvenlik/bütçe engeline takıldı. | **Evet** |
| `completed` | İnceleme ve işleme başarıyla tamamlandı. | Hayır |
| `duplicate` | Mükerrer içerik tespit edildi ve atlandı. | Hayır |

*Başarısız ögeleri operatör komutuyla yeniden kuyruğa almak için:*
```bash
uv run mesa-data harvest retry --item-id <ITEM_ID>
```

---

## 7. İnsan İncelemesi (Human Review)

Pipeline çıktısı olan kanonik kayıtlar doğrudan yayınlanamaz; insan operatör onayından geçmek zorundadır.

### CLI İle İnceleme ve Onay
```bash
# İnceleme bekleyen kayıtları listeleyin
uv run mesa-data review list --status pending

# Tekil bir kaydı onaylayın
uv run mesa-data review approve <RECORD_ID> --reviewer "contact@yourdomain.org" --note "Kontrol edildi"

# Sürüm altındaki tüm kayıtları topluca onaylayın (Gizlilik durumu 'approved' olarak güncellenir)
uv run mesa-data review approve-version <VERSION_ID> --reviewer "contact@yourdomain.org" --note "Toplu onay verildi"

# Hatalı kaydı reddedin
uv run mesa-data review reject <RECORD_ID> --reviewer "contact@yourdomain.org" --note "Metin eksik"
```

### Web UI İle İnceleme
Web arayüzünü (`uv run mesa-data web`) başlatıp **İnceleme Masası** ekranından metin önizlemelerini inceleyebilir ve onay/ret verebilirsiniz.

---

## 8. Release İşlemleri

Onaylı kayıtlardan yayın paketi derleme, doğrulama ve güvenli yayınlama aşamalarıdır.

```bash
# 1. Onaylı kayıtlardan release paketi derleyin (0 kayıt varsa ReleaseBuildError verir)
uv run mesa-data release build --release-id release-v0.1.0

# 2. Release paketi manifestini ve SHA-256 hash'lerini doğrulayın
uv run mesa-data release verify --release-id release-v0.1.0

# 3. Release paketini yayınlayın (Domain güvenli publish_release fonksiyonu çağrılır)
uv run mesa-data release publish --release-id release-v0.1.0
```

> **Güvenlik Notu:** `build` adımı yalnızca `approved` durumundaki kayıtları pakete dahil eder. Onaylanmamış veya `flagged` gizlilik durumundaki veriler release paketine alınmaz.

---

## 9. MESA'ya Aktarma (Staging Import) ve Provenance

Yayınlanan release paketleri MESA staging veritabanına aktarılır:

```bash
uv run mesa-data release import --release-id release-v0.1.0
```

### Özellikler:
- **Atomik:** İşlem ya tamamen başarılı olur ya da hiçbir veriyi değiştirmeden geri çekilir.
- **Idempotent:** Aynı release paketi tekrar import edildiğinde mükerrer kayıt oluşturmaz, sistem güvenle `already_imported` yanıtı verir.
- **Provenance (İzlenebilirlik):** Aktarılan her kaydın köken zinciri ve aktif release içindeki gerçek varlığı sorgulanabilir:
  ```bash
  uv run mesa-data provenance <RECORD_ID>
  ```

---

## 10. Rollback

MESA staging DB üzerinde aktif release pointer'ını daha önce import edilmiş eski bir release paketine geri döndürür.

- **Kullanım Amacı:** Hatalı bir release staging ortamına alındığında sistemi anında bilinen kararlı son release'e geri çekmek.
- **Uygulama:** Web UI **Release Merkezi** ekranındaki **Rollback** seçeneği veya Web API (`POST /api/releases/{release_id}/rollback`) üzerinden gerçekleştirilir.
- **Etki:** Staging DB'deki `active_release` pointer'ı güncellenir; geçmiş veriler silinmez. `get_record_provenance()` sorguları rollback sonrasında kaydın aktif release içinde bulunma durumunu (`in_active_release: false`) doğru yansıtır.

---

## 11. Durum ve Sağlık Kontrolü

Sistem bütünlüğünü ve katalog sağlığını kontrol etmek için şu araçları kullanın:

```bash
# Sistem sağlık ve bütünlük denetimi (Doctor)
uv run mesa-data doctor

# Raw artifact SHA-256 bütünlük kontrolü (Audit)
uv run mesa-data audit

# Katalog özet raporu (Report)
uv run mesa-data report

# Katalog veritabanı yedeği alma (Backup)
uv run mesa-data backup --target-dir /yedek/dizini
```

---

## 12. Sık Karşılaşılan Sorunlar

| Sorun / Hata | Olası Neden | Çözüm |
|---|---|---|
| `OPERATOR_CONTACT_MISSING / OPERATOR_CONTACT_INVALID` | `.env` içinde `MESA_DATA_OPERATOR_CONTACT` tanımlı değil veya yer tutucu var. | Geçerli operasyonel e-posta adresi yazın. |
| `CERTIFICATE_VERIFY_FAILED` | Sunucu TLS sertifika zinciri eksik. | MESA Data paketli GeoTrust CA deposunu otomatik kullanır; harici `SSL_CERT_FILE` ortam değişkenini kontrol edin. `verify=False` kullanmayın. |
| `SSRF_ERROR / HOST_NOT_ALLOWED` | URL izin verilen alan adları listesinde değil. | `config/sources.yaml` içindeki `allowed_hosts` alanına ekleyin. |
| `RELEASE_NOT_PUBLISHED` | Release henüz `publish` edilmeden `import` denenmiş. | Önce `release verify` ve `release publish` çalıştırın. |
| `ReleaseBuildError` | Derlenecek release için onaylanmış kayıt bulunamadı (0 kayıt). | İnceleme Masasından inceleme bekleyen kayıtları onaylayın. |
| `NON_LOOPBACK_DISABLED` | Web UI `--host 0.0.0.0` ile token'sız başlatılmış. | `export MESA_DATA_WEB_ADMIN_TOKEN="..."` değişkenini tanımlayın. |
| `ALREADY_IMPORTED` | Release zaten staging DB'ye import edilmiş. | Hata değildir; idempotency güvencesidir. |

---

## 13. Güvenli Kullanım Kuralları

1. **TLS Doğrulamasını Kapatmayın:** `verify=False`, `curl -k` veya `PYTHONHTTPSVERIFY=0` kesinlikle kullanılmamalıdır.
2. **Ham Veriyi (Raw Artifacts) Değiştirmeyin:** `raw/` altındaki dosyalar değişmezdir. Dosya değişirse SHA-256 audit denetimi başarısız olur.
3. **Manuel SQL Müdahalesi Yapmayın:** Veritabanı durumunu veya review süreçlerini SQL sorguları ile güncellemeyin; daima CLI veya Web UI kullanın.
4. **Release Manifest Bütünlüğünü Koruyun:** Derlenmiş release paket dosyalarını elle düzenlemeyin.

---

## 14. Günlük Operatör Akışı (Cheat Sheet)

Günlük operasyonlarda takip edilecek standart adım sırası:

```text
1. Keşif & İndirme:   uv run mesa-data harvest discover --source resmi_gazete
                      uv run mesa-data harvest run --once --limit 25

2. Durum Kontrolü:    uv run mesa-data harvest status

3. İnceleme & Onay:   uv run mesa-data review list --status pending
                      uv run mesa-data review approve-version <VERSION_ID>

4. Release Paketleme: uv run mesa-data release build --release-id rel-$(date +%Y%m%d)
                      uv run mesa-data release verify --release-id rel-$(date +%Y%m%d)
                      uv run mesa-data release publish --release-id rel-$(date +%Y%m%d)

5. Staging Aktarımı:  uv run mesa-data release import --release-id rel-$(date +%Y%m%d)

6. Sağlık Denetimi:   uv run mesa-data doctor
```

---

*İleri seviye teknik sözleşmeler için [docs/IMPORT_CONTRACT.md](IMPORT_CONTRACT.md) ve final freeze doğrulama kanıtları için [docs/MVP_CLOSURE_REPORT.md](MVP_CLOSURE_REPORT.md) dosyalarına başvurabilirsiniz.*
