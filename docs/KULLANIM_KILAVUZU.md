# MESA Legal Data — Kullanım Kılavuzu

**Sürüm:** 0.1.0 (V1 MVP)
**Son güncelleme:** 2026-08-06

---

## İçindekiler

1. [MESA Legal Data nedir?](#1-mesa-legal-data-nedir)
2. [Sistem gereksinimleri](#2-sistem-gereksinimleri)
3. [Kurulum](#3-kurulum)
4. [İlk yapılandırma](#4-ilk-yapılandırma)
5. [Sistemi başlatma](#5-sistemi-başlatma)
6. [Arayüz genel tanıtımı](#6-arayüz-genel-tanıtımı)
7. [Açık ve koyu tema](#7-açık-ve-koyu-tema)
8. [Dosya yükleme](#8-dosya-yükleme)
9. [URL'den veri alma](#9-urlden-veri-alma)
10. [Pipeline çalıştırma](#10-pipeline-çalıştırma)
11. [Belgeler ve Veri Gezgini](#11-belgeler-ve-veri-gezgini)
12. [İnceleme ve onay](#12-inceleme-ve-onay)
13. [Sorunlar ekranı](#13-sorunlar-ekranı)
14. [Kaynaklar ekranı](#14-kaynaklar-ekranı)
15. [Dışa aktarma](#15-dışa-aktarma)
16. [Release oluşturma](#16-release-oluşturma)
17. [MESA staging import](#17-mesa-staging-import)
18. [Rollback](#18-rollback)
19. [Operasyonlar](#19-operasyonlar)
20. [Audit](#20-audit)
21. [Doctor ve sistem kontrolü](#21-doctor-ve-sistem-kontrolü)
22. [Backup](#22-backup)
23. [İndirme işlemleri](#23-indirme-işlemleri)
24. [Sık karşılaşılan hatalar](#24-sık-karşılaşılan-hatalar)
25. [Güvenli kullanım kuralları](#25-güvenli-kullanım-kuralları)
26. [Örnek baştan sona kullanım senaryosu](#26-örnek-baştan-sona-kullanım-senaryosu)
27. [Hızlı komut referansı](#27-hızlı-komut-referansı)
28. [V1 sınırları](#28-v1-sınırları)

---

## 1. MESA Legal Data nedir?

MESA Legal Data, Türkiye hukuk mevzuatı ve içtihat verilerini **toplayan, kanonikleştiren, doğrulayan ve MESA staging veritabanına aktaran** uçtan uca bir veri platformudur.

**Ne işe yarar?**

- Resmî Gazete, Mevzuat Bilgi Sistemi ve Anayasa Mahkemesi gibi resmî kaynaklardan PDF veya HTML dosyaları toplanır.
- Toplanan ham dosyalar otomatik olarak ayrıştırılır ve standart JSONL formatına (canonical kayıt) dönüştürülür.
- Her kayıt JSON Schema doğrulamasından, gizlilik taramasından ve insan onayından geçer.
- Onaylı kayıtlar bir release paketinde derlenir ve MESA staging veritabanına aktarılır.

**MESA ile ilişkisi:** MESA Legal Data, MESA hukuk ekosisteminin veri besleme katmanıdır. Ürettiği release paketleri doğrudan MESA staging DB'ye import edilir.

**Bu sistemle yapabilecekleriniz:**

- Yerel dosya veya HTTPS URL üzerinden ham veri yüklemek
- Pipeline ile otomatik ayrıştırma ve doğrulama çalıştırmak
- Canonical kayıtları inceleyip onaylamak veya reddetmek
- Onaylı kayıtlardan release paketi oluşturmak ve MESA'ya aktarmak
- Filtrelenmiş JSONL/CSV export dosyaları üretmek
- Audit logları ile tüm işlemleri takip etmek

---

## 2. Sistem gereksinimleri

| Gereksinim | Değer |
|---|---|
| İşletim sistemi | Ubuntu Linux (test edilen ortam) |
| Python | 3.11 – 3.13 (`.python-version` dosyasında 3.13 belirtilmiştir) |
| Paket yöneticisi | [uv](https://docs.astral.sh/uv/) |
| Disk alanı | Veri büyüklüğüne bağlıdır; `config/settings.yaml` içinde varsayılan olarak toplam ~50 GB sınır tanımlanmıştır |
| İnternet | URL üzerinden veri çekmek için HTTPS erişimi gereklidir; yalnız dosya yükleme modunda internet gerekmez |
| Tarayıcı | Web paneli için güncel bir masaüstü veya mobil tarayıcı (Chrome, Firefox, Safari, Edge) |
| Dosya izinleri | `data_root` dizininde okuma ve yazma izni |

---

## 3. Kurulum

Aşağıdaki adımları Ubuntu terminalinde sırasıyla uygulayın.

### 3.1 Repoyu klonlama

```bash
git clone <REPO_URL> mesa-legal-data
cd mesa-legal-data
```

> Repo URL'sini proje yöneticinizden edinebilirsiniz.

### 3.2 Bağımlılıkları yükleme

```bash
uv sync --frozen
```

Bu komut `uv.lock` dosyasındaki sabitlenmiş sürümleri kullanarak tüm Python bağımlılıklarını yükler.

### 3.3 Veri dizinlerini oluşturma

```bash
uv run mesa-data init
```

`MESA_DATA_DATA_ROOT` ortam değişkeni ile belirtilen dizinde `raw/`, `canonical/`, `releases/` ve `tmp/` klasörlerini oluşturur. Varsayılan konum: `/storage/mesa-legal-data/data` (veya `~/.mesa-data/data`).

### 3.4 Veritabanı tablolarını hazırlama

```bash
uv run mesa-data migrate
```

Catalog SQLite veritabanını oluşturur ve şema güncellemelerini uygular.

### 3.5 Kurulumu doğrulama

```bash
uv run mesa-data --help
```

Yardım çıktısında `init`, `migrate`, `doctor`, `backup`, `restore`, `audit`, `report`, `provenance`, `web`, `collect`, `review`, `release`, `pipeline` komutları görünüyorsa kurulum başarılıdır.

---

## 4. İlk yapılandırma

### 4.1 Data root

Sistem tüm verisini `MESA_DATA_DATA_ROOT` ortam değişkeninin gösterdiği dizinde saklar. Bu değişken ayarlanmazsa `config/settings.yaml` içindeki `data_root` değeri kullanılır. Varsayılan: `/storage/mesa-legal-data/data`.

```text
$DATA_ROOT/
  raw/                    # Değişmez ham artifact dosyaları
  canonical/              # Değişmez JSONL canonical kayıtlar
  releases/               # Değişmez release paketleri (manifest + JSONL)
  exports/                # Dışa aktarma dosyaları
  tmp/                    # Geçici dosyalar
  catalog.sqlite          # Ana veritabanı
```

### 4.2 config/sources.yaml

Bu dosya, hangi resmî kaynaklardan veri alınabileceğini ve her kaynağa ait politikaları tanımlar.

```yaml
version: "1.0.0"

sources:
  mevzuat:
    name: "Mevzuat Bilgi Sistemi"
    authority: "T.C. Cumhurbaşkanlığı"
    base_url: "https://www.mevzuat.gov.tr/"
    access_mode: "manual"
    enabled: true
    families: ["legislation"]
    source_role: "consolidated_text"
    policy_version: "1.0.0"
    http:
      user_agent: "MESA-Legal-Data/1.0 (+operator-contact)"
      concurrency: 1
      min_interval_seconds: 5
      timeout_seconds: 30
      retries: 3
      max_requests_per_run: 25
      max_download_bytes: 52428800
    allowed_content_types:
      - "application/pdf"
      - "text/html"
    allowed_hosts:
      - "mevzuat.gov.tr"
      - "www.mevzuat.gov.tr"
```

**Önemli alanlar:**

| Alan | Açıklama |
|---|---|
| `enabled` | `true` ise bu kaynaktan veri alınabilir; `false` ise devre dışıdır |
| `allowed_hosts` | Yalnız bu alan adlarına HTTP isteği gönderilir |
| `allowed_content_types` | Yalnız bu MIME türleri kabul edilir |
| `timeout_seconds` | Bağlantı zaman aşımı (saniye) |
| `retries` | Başarısız isteklerde tekrar deneme sayısı |
| `max_download_bytes` | İndirme boyut sınırı (bayt); varsayılan ~50 MB |
| `min_interval_seconds` | Ardışık istekler arasında minimum bekleme süresi (hız sınırı) |
| `user_agent` | Resmî kaynaklara gönderilen istemci tanımlayıcısı |

### 4.3 config/settings.yaml

Sistem ayarlarını içerir:

```yaml
version: "1.0.0"

settings:
  data_root: "/storage/mesa-legal-data/data"
  mesa_staging_db: "/storage/mesa-legal-data/data/mesa_staging.sqlite"
  environment: "development"
  log_level: "INFO"
  operator_contact: "operatör@example.com"
```

### 4.4 Admin token

Dış ağdan erişimde güvenlik için `MESA_DATA_WEB_ADMIN_TOKEN` ortam değişkenini ayarlayın:

```bash
export MESA_DATA_WEB_ADMIN_TOKEN="gizli-ve-güçlü-bir-token"
```

Bu değişken ayarlanmadığında web paneli yalnızca `127.0.0.1` (yerel bilgisayar) adresinden erişilebilir. Dış ağa açmak istediğinizde bu değişken **zorunludur**.

> ⚠️ Gerçek token değerini başkalarıyla paylaşmayın. Güçlü ve rastgele bir değer kullanın.

---

## 5. Sistemi başlatma

### 5.1 Web panelini başlatma

```bash
uv run mesa-data web --host 127.0.0.1 --port 8765
```

| Parametre | Varsayılan | Açıklama |
|---|---|---|
| `--host` | `127.0.0.1` | Dinlenecek IP adresi |
| `--port` | `8765` | Dinlenecek port |
| `--reload` | Kapalı | Geliştirme sırasında dosya değişikliklerinde otomatik yeniden başlatma |

Tarayıcınızda şu adresi açın:

```
http://127.0.0.1:8765
```

> **Ekran görüntüsü:** Genel Bakış ekranı — açık tema

**Kapatmak için:** Terminalde `Ctrl + C` tuşlarına basın.

**Dış ağa açma:** `--host 0.0.0.0` kullanmak istiyorsanız `MESA_DATA_WEB_ADMIN_TOKEN` ayarlanmış olmalıdır; aksi halde sunucu başlamaz.

### 5.2 Yalnız CLI ile çalışma

Web paneli açmadan doğrudan CLI komutları ile çalışabilirsiniz. Tüm işlemler (veri toplama, pipeline, review, release, export) CLI üzerinden de yürütülebilir.

---

## 6. Arayüz genel tanıtımı

Web panelinin sol kenar çubuğunda dört ana grup ve toplam 12 ekran bulunur.

### VERİ grubu

#### 📊 Genel Bakış (Dashboard)

Bu ekran sistemin anlık durumunu özetler.

- **Görünen bilgiler:** Toplam belge, raw artifact, canonical kayıt, inceleme bekleyen kayıt, onaylı kayıt, açık blocker, açık error, yayınlanmış release sayısı, aktif MESA release ID'si.
- **Son 10 belge** ve **son 10 işlem** listelenir.
- **Yapılabilecek işlem:** Genel durumu izleme; doğrudan veri değiştirme yapılmaz.

#### ➕ Veri Ekle

Ham veri aktarım ekranıdır.

- **Dosya yükleme:** Bilgisayarınızdaki PDF veya HTML dosyasını sürükle-bırak veya dosya seçici ile yüklersiniz.
- **URL'den alma:** İzinli HTTPS URL girerek ham dosyayı indirirsiniz.
- Kaynak (source), belge ailesi (family), document ID ve başlık bilgilerini doldurursunuz.

#### 📄 Belgeler (Documents)

- **Görünen bilgiler:** Document ID, aile, tür, yetki alanı, başlık, durum, artifact sayısı, güncellenme tarihi.
- **Filtreler:** Duruma (`lifecycle_status`), aileye (`family`) ve arama metnine (`q`) göre filtreleme.
- **Yapılabilecek işlemler:** Belge detayını görüntüleme, artifact indirme, pipeline çalıştırma, ham ve canonical dosya indirme.

#### 🔍 Veri Gezgini (Explorer)

- **Amaç:** Tüm canonical kayıtları detaylı filtrelerle arama.
- **Filtreler:** Metin arama, kayıt türü (`record_type`), kaynak (`source_id`), onay durumu (`approval_status`), doğrulama durumu (`validation_status`).
- **Facet sayıları:** Her filtre değeri için kayıt sayısı gösterilir.

> **Ekran görüntüsü:** Veri Gezgini ekranı — koyu tema

### KALİTE grubu

#### ✅ İnceleme Masası (Reviews)

- **Amaç:** İnceleme bekleyen (`pending`) canonical kayıtların onaylanması veya reddedilmesi.
- **Görünen bilgiler:** Kayıt ID, tür, metin önizlemesi, blocker sorun uyarıları.
- **Yapılabilecek işlemler:** Tek tek kayıt onayı (`approve`), tekli ret (`reject`), version bazlı toplu onay.

#### ⚠️ Sorunlar (Issues)

- **Amaç:** Pipeline sırasında üretilen doğrulama sorunlarını listeleme.
- **Bu ekran salt okunurdur;** sorunları doğrudan kapatma veya yeniden açma özelliği yoktur.
- **Filtreler:** Durum (`open`/`resolved`), önem derecesi (`blocker`/`error`/`warning`/`info`), konu türü (`subject_type`), konu ID'si.

### DAĞITIM grubu

#### 🌐 Kaynaklar (Sources)

- **Amaç:** Tanımlı veri kaynaklarını ve politikalarını görüntüleme.
- **Bu ekran salt okunurdur.** Kaynak ekleme veya düzenleme web panelinden yapılmaz; değişiklikler `config/sources.yaml` dosyası üzerinden elle yapılır.

#### 📦 Release Merkezi

- **Amaç:** Onaylı kayıtlardan release paketi oluşturma, doğrulama, yayınlama, MESA staging DB'ye aktarma, rollback ve iptal.
- **Görünen bilgiler:** Release ID, durum, oluşturulma tarihi, yayınlanma tarihi, kayıt sayıları, manifest SHA-256.
- **Yapılabilecek işlemler:** Build, verify, publish, import, rollback, revoke, paket indirme.

> **Ekran görüntüsü:** Release Merkezi ekranı

#### 📤 Dışa Aktarma (Exports)

- **Amaç:** Filtrelenmiş JSONL, CSV veya belge paketi üretme ve indirme.
- **Desteklenen formatlar:** `records_jsonl`, `records_csv`, `issues_csv`, `audit_jsonl`, `audit_csv`, `provenance_jsonl`, `document_package`.

### SİSTEM grubu

#### 🔄 Operasyonlar

- **Amaç:** Arka planda çalışan uzun süreli işlemleri izleme ve iptal etme.
- **Desteklenen işlem türleri:** `filtered_export`, `release_build`, `integrity_audit`.

#### 📋 Audit

- **Amaç:** Sistemdeki tüm veri yazma ve indirme olaylarının denetim kayıtlarını listeleme.
- **Filtreler:** Konu türü, konu ID'si, eylem türü, aktör.

#### ⚙️ Sistem

- **Amaç:** Sistem teşhisi (`doctor`), bütünlük denetimi ve yedekleme (`backup`).
- **Yapılabilecek işlemler:** Doctor kontrolü çalıştırma, backup alma.

> **Ekran görüntüsü:** Sistem ekranı — doctor kontrolü sonuçları

---

## 7. Açık ve koyu tema

Web panelinin sağ üst köşesindeki tema seçici ile üç seçenek sunulur:

| Seçenek | Davranış |
|---|---|
| **Sistem Teması** | İşletim sisteminizin açık/koyu tercihini takip eder |
| **Açık Tema** | Her zaman açık (beyaz) arka plan kullanır |
| **Koyu Tema (Siyah)** | Her zaman koyu (siyah) arka plan kullanır |

- Seçiminiz tarayıcının `localStorage`'ında saklanır ve kalıcıdır.
- Sistem teması seçiliyken işletim sisteminiz koyu moda geçerse panel de otomatik olarak koyu moda geçer.
- Mobil tarayıcılarda da aynı şekilde çalışır; arayüz responsive tasarımdır.

> **Ekran görüntüsü:** Koyu tema — Genel Bakış ekranı

---

## 8. Dosya yükleme

### Web panelinden yükleme

1. Sol menüden **Veri Ekle** ekranını açın.
2. **Dosya seç** alanına dosyanızı sürükleyin veya tıklayıp dosya seçin.
3. **Kaynak** açılır listesinden uygun kaynağı seçin (örn. `mevzuat`).
4. **Belge ailesi** alanını doldurun (örn. `legislation`).
5. **Document ID** alanına kanonik belge kimliğini girin (örn. `tr:legislation:law:4721`).
6. İsteğe bağlı olarak **Başlık** alanını doldurun.
7. **Yükle** butonuna tıklayın.
8. Başarılı ise artifact ID ve SHA-256 hash gösterilir.

### CLI ile yükleme

```bash
uv run mesa-data collect manual \
  --source mevzuat \
  --file /tam/yol/belge.pdf \
  --document-id tr:legislation:law:4721 \
  --family legislation \
  --document-type law \
  --title "Türk Medeni Kanunu"
```

### Bilmeniz gerekenler

- **Desteklenen dosya türleri:** Kaynak yapılandırmasındaki `allowed_content_types` alanı ile belirlenir. Varsayılan olarak `application/pdf` ve `text/html` desteklenir.
- **Dosya boyut sınırı:** `max_download_bytes` parametresi ile sınırlıdır; varsayılan 50 MB (52.428.800 bayt). Web yüklemelerinde de 50 MB sınırı uygulanır.
- **Raw artifact değişmez:** Yüklenen dosya `raw/` dizinine yazılır ve bir daha değiştirilmez.
- **SHA-256 hesaplanır:** Dosyanın bütünlük doğrulaması için SHA-256 hash değeri hesaplanır ve veritabanına kaydedilir.
- **Duplicate kontrolü:** Aynı SHA-256 hash değerine sahip dosya zaten yüklenmişse artifact ID değişmez (`sha256:<hash>` formatındadır).
- **MIME doğrulaması:** Dosyanın gerçek içerik türü (magic bytes) kontrol edilir; izin verilen listede yoksa yükleme reddedilir.

---

## 9. URL'den veri alma

### Web panelinden URL ile alma

1. **Veri Ekle** ekranını açın.
2. URL alanına tam HTTPS adresini girin.
3. Kaynak, belge ailesi ve Document ID'yi doldurun.
4. **URL'den Al** butonuna tıklayın.

### CLI ile URL alma

```bash
uv run mesa-data collect url \
  --source mevzuat \
  --url https://www.mevzuat.gov.tr/MevzuatMetin/1.5.2709.pdf \
  --document-id tr:legislation:constitution:2709 \
  --title "Türkiye Cumhuriyeti Anayasası"
```

### URL güvenlik politikası

Sistem, URL isteklerinde aşağıdaki kuralları uygular:

| Kural | Açıklama |
|---|---|
| **Yalnız HTTPS** | HTTP şeması reddedilir |
| **Yalnız izinli host** | URL'nin alan adı, kaynağın `allowed_hosts` listesinde olmalıdır |
| **Kaynak etkin olmalı** | Kaynağın `enabled: true` olması gerekir |
| **Private IP engeli** | localhost, 10.x.x.x, 192.168.x.x gibi özel IP adresleri engellenir (SSRF koruması) |
| **Redirect doğrulaması** | Yönlendirme (301/302/307) durumunda hedef URL tekrar aynı politikalarla doğrulanır; en fazla 3 yönlendirme izlenir |
| **Boyut sınırı** | İndirme `max_download_bytes` parametresini aşamaz |
| **MIME sınırı** | Sunucunun döndüğü Content-Type, `allowed_content_types` listesinde olmalıdır |
| **Hız sınırı** | Ardışık istekler arasında `min_interval_seconds` kadar beklenir |
| **Standart dışı port** | 443 dışındaki portlar reddedilir |

### URL başarısız olduğunda kontrol edin

- URL'nin `https://` ile başladığını doğrulayın.
- Alan adının `allowed_hosts` listesinde olduğunu kontrol edin.
- Kaynağın `enabled: true` olduğunu doğrulayın.
- Dosya boyutunun sınırı aşmadığından emin olun.
- Sunucunun erişilebilir olduğunu kontrol edin (timeout hatası alıyorsanız internet bağlantınızı kontrol edin).

---

## 10. Pipeline çalıştırma

Pipeline, ham bir artifact'ı alıp canonical kayıtlara dönüştüren otomatik işlem sürecidir.

### Akış

```text
raw artifact (PDF/HTML)
  → transport doğrulaması (SHA-256, boyut, MIME)
  → ayrıştırma (parse: PDF → metin; HTML → metin)
  → canonical model üretimi (legislation, article, decision, citation)
  → JSON Schema doğrulaması
  → hukuki metadata doğrulaması
  → gizlilik taraması (TCKN, IBAN vb.)
  → JSONL dosya yazımı (canonical/)
  → veritabanına version ve record kayıtları
```

### Web panelinden çalıştırma

1. **Belgeler** ekranında ilgili belgeyi bulun.
2. Belge detayına girin.
3. **Pipeline Çalıştır** butonuna tıklayın.
4. İşlem tamamlandığında durum gösterilir.

### CLI ile çalıştırma

```bash
uv run mesa-data pipeline run --artifact-id sha256:abc123...
```

### Başarılı işlem

Pipeline `needs_review` durumunda tamamlanırsa canonical kayıtlar üretilmiştir ve inceleme beklemektedir. Gizlilik sorunları bulunamazsa durum `needs_review` olarak kalır; blocker düzeyinde gizlilik sorunu bulunursa `rejected` olur.

### Başarısız işlem

Pipeline `failed` durumunda tamamlanırsa:

- Transport doğrulaması başarısız olmuştur (dosya bozuk, hash uyuşmazlığı).
- Ayrıştırma başarısız olmuştur (desteklenmeyen format veya boş metin).
- Schema doğrulaması başarısız olmuştur.

Hatanın detayı **Sorunlar** ekranında ilgili artifact'ın issue kaydında görülebilir.

---

## 11. Belgeler ve Veri Gezgini

### Temel kavramlar

| Kavram | Açıklama |
|---|---|
| **Document** | Bir hukuki belgenin üst düzey kaydı (örn. 4721 sayılı Türk Medeni Kanunu) |
| **Artifact** | Belgeye ait ham dosya; değişmez olarak `raw/` dizininde saklanır |
| **Version** | Bir artifact'ın pipeline sonucu üretilen kanonikleştirilmiş sürümü |
| **Record** | Version içindeki tekil bir canonical kayıt (legislation, article, decision veya citation) |
| **Issue** | Pipeline sırasında tespit edilen doğrulama sorunu |
| **Release** | Onaylı kayıtların bir araya getirildiği yayın paketi |

### Belgeler ekranı

- Belgeleri **duruma**, **aileye** ve **arama metnine** göre filtreleyebilirsiniz.
- Sayfalama mevcuttur (varsayılan sayfa boyutu: 20).
- Belge detayında artifact listesi ve açık sorunlar görüntülenir.

### Veri Gezgini ekranı

- Tüm kayıtları **metin arama**, **kayıt türü**, **kaynak**, **onay durumu** ve **doğrulama durumu** ile arayabilirsiniz.
- Sol tarafta facet sayıları (her filtre değeri için kaç kayıt olduğu) gösterilir.
- Kayıt detayında metin önizlemesi, SHA-256 ve blocker sorun listesi yer alır.

> **Ekran görüntüsü:** Belgeler listesi — filtre uygulanmış

---

## 12. İnceleme ve onay

### Tekli onay (web paneli)

1. **İnceleme Masası** ekranını açın.
2. İnceleme bekleyen kayıtlar listelenir.
3. Bir kaydın detayına girin; metin önizlemesini ve varsa blocker sorunlarını inceleyin.
4. **Onayla** butonuna tıklayın. İnceleme yapan kişi adı ve isteğe bağlı not girin.
5. Kayıt `approved` durumuna geçer.

### Tekli ret

1. Aynı detay ekranında **Reddet** butonuna tıklayın.
2. Ret nedeni girin.
3. Kayıt `rejected` durumuna geçer.

### Toplu onay (version bazlı)

Web panelinden veya CLI ile bir version altındaki tüm kayıtları topluca onaylayabilirsiniz:

```bash
uv run mesa-data review approve-version VERSION_ID --reviewer "yasin" --note "Toplu kontrol edildi"
```

### CLI ile onay/ret

```bash
# Tekli onay
uv run mesa-data review approve RECORD_ID --reviewer "yasin" --note "Kontrol edildi"

# Tekli ret
uv run mesa-data review reject RECORD_ID --reviewer "yasin" --note "Hatalı kayıt"
```

### Önemli kurallar

- Blocker düzeyinde açık sorunu olan kayıtlar onaylanamaz.
- Yalnız `pending` durumundaki kayıtlar onaylanabilir veya reddedilebilir.
- Onaylanmamış kayıtlar release paketine dahil edilmez.
- Her onay/ret işlemi audit loguna kaydedilir.

> **Ekran görüntüsü:** İnceleme Masası — metin önizlemesi ve onay butonları

---

## 13. Sorunlar ekranı

### Genel bilgi

Sorunlar ekranı, pipeline sırasında üretilen doğrulama sorunlarını **salt okunur** olarak listeler. V1 sürümünde bu ekrandan sorun kapatma, yeniden açma veya waive işlemi yapılamaz.

### Önem dereceleri

| Seviye | Anlamı |
|---|---|
| `blocker` | Kayıt onaylanamaz; release'e dahil edilemez. Hemen müdahale gerekir. |
| `error` | Ciddi bir doğrulama hatası var; kayıt incelenmelidir. |
| `warning` | Olası bir sorun tespit edildi; kontrol önerilir. |
| `info` | Bilgilendirme amaçlıdır; işlem engellenmez. |

### Sorunlu kaydı bulma ve yeniden işleme

1. **Sorunlar** ekranında `subject_id` sütunundaki artifact veya record ID'sini not edin.
2. **Belgeler** ekranında ilgili belgeyi açın.
3. Ham dosyayı kontrol edin; gerekirse düzeltilmiş dosyayı yeni bir artifact olarak yükleyin.
4. Yeni artifact için pipeline'ı tekrar çalıştırın.

---

## 14. Kaynaklar ekranı

**Kaynaklar** ekranı, `config/sources.yaml` dosyasında tanımlanan veri kaynaklarını ve politikalarını **salt okunur** olarak görüntüler.

- Kaynak adı, yetki makamı, etkin durumu, aileleri ve izinli host'ları listelenir.

**Kaynak yapılandırmasını değiştirmek için:**

1. `config/sources.yaml` dosyasını bir metin editörü ile açın.
2. Gerekli değişiklikleri yapın.
3. Dosyayı kaydedin.
4. Web sunucusunu yeniden başlatın.

> V1 sürümünde web üzerinden kaynak düzenleme özelliği yoktur.

---

## 15. Dışa aktarma

### Desteklenen export türleri

| Tür | İçerik | Format | Kullanım amacı |
|---|---|---|---|
| `records_jsonl` | Canonical kayıtlar | JSONL | Veri analizi, harici sistem besleme |
| `records_csv` | Kayıt meta bilgileri | CSV | Tablo uygulamalarında (Excel vb.) inceleme |
| `issues_csv` | Doğrulama sorunları | CSV | Sorun takibi ve raporlama |
| `audit_jsonl` | Denetim logları | JSONL | Detaylı denetim kaydı arşivleme |
| `audit_csv` | Denetim logları | CSV | Tablo uygulamalarında denetim incelemesi |
| `provenance_jsonl` | Veri kökeni zinciri | JSONL | Her kaydın hangi kaynaktan geldiğini izleme |
| `document_package` | Ham belge paketleri | tar.gz | Belgelerin toplu arşivlenmesi |

### Web panelinden export oluşturma

1. **Dışa Aktarma** ekranını açın.
2. Export türünü seçin.
3. İsteğe bağlı filtreler uygulayın (kayıt türü, onay durumu, kaynak vb.).
4. **Oluştur** butonuna tıklayın.
5. İşlem tamamlandığında **İndir** bağlantısı görünür.

### Export'un operation olarak çalışması

Export işlemleri bir **operation** (arka plan işi) olarak çalışır. Büyük veri setleri için **Operasyonlar** ekranından ilerlemeyi izleyebilirsiniz.

### Filtreleme seçenekleri

Export oluştururken kullanabileceğiniz filtreler:

- `record_type` — Kayıt türü (article, legislation, decision, citation)
- `approval_status` — Onay durumu (pending, approved, rejected)
- `validation_status` — Doğrulama durumu
- `source_id` — Kaynak ID'si
- `document_id` — Belge ID'si
- `version_id` — Sürüm ID'si

---

## 16. Release oluşturma

Release, onaylı kayıtların bir JSONL paketinde derlendiği ve MESA staging DB'ye aktarılmaya hazır hale getirildiği süreçtir.

### Adım adım

1. **Tüm kayıtları onaylayın:** Release yalnız `approved` durumundaki kayıtları içerir.
2. **Blocker sorunlarını çözün:** Açık blocker issue varsa release build başarısız olur.
3. **Release build:** Web panelinde **Release Merkezi** ekranından veya CLI ile:

```bash
uv run mesa-data release build --release-id release-v1.0
```

4. **Verify:** Build tamamlandıktan sonra doğrulayın:

```bash
uv run mesa-data release verify --release-id release-v1.0
```

5. **Publish:** Doğrulanmış release'i yayınlayın:

```bash
uv run mesa-data release publish --release-id release-v1.0
```

6. **Paket indirme:** Web panelinden release manifest veya tar.gz paketi indirilebilir.

### Release durumları

| Durum | Anlamı |
|---|---|
| `preparing` | Release build sürüyor (.building- dizini oluşturuldu) |
| `verified` | Build tamamlandı ve SHA-256 doğrulaması geçti |
| `published` | Release yayınlandı ve MESA staging import'a hazır |
| `revoked` | Yayınlanan release iptal edildi; import yapılamaz |
| `failed` | Build sırasında hata oluştu |

> **Ekran görüntüsü:** Release oluşturma işlemi

### Build sırasında ne olur

- Yalnız `approved` durumundaki kayıtlar seçilir.
- Her kayıt canonical JSONL dosyasından okunur ve kayıt türüne göre (`legislation.jsonl`, `articles.jsonl`, `decisions.jsonl`, `citations.jsonl`) ayrı dosyalara yazılır.
- `manifest.json` ve `release.json` dosyaları oluşturulur.
- Tüm dosyaların SHA-256 hash'leri manifest'e yazılır.
- Atomik rename ile `.building-` dizini `releases/{release_id}` olarak taşınır.

---

## 17. MESA staging import

### Genel bilgi

Yayınlanmış bir release paketi MESA staging SQLite veritabanına aktarılır. Bu işlem **atomik** ve **idempotent**'tir.

### Adım adım

1. Release'in durumunun `published` olduğundan emin olun.
2. Web panelinden **Release Merkezi** ekranında ilgili release'in yanındaki **Import** butonuna tıklayın, veya:

```bash
uv run mesa-data release import --release-id release-v1.0
```

3. İşlem başarılı olduğunda staging DB'de `active_release` pointer'ı güncellenir.

### Kurallar

- **Yalnız `published` release** import edilebilir. `verified`, `revoked` veya başka durumdaki release'ler reddedilir.
- **Idempotent import:** Aynı release aynı manifest SHA-256 ile tekrar import edilmeye çalışılırsa `already_imported` mesajı döner ve veri tekrar yazılmaz.
- **Farklı manifest SHA-256:** Aynı ID ile farklı SHA-256 tespit edilirse hata oluşur (veri bütünlüğü koruması).
- **Aktif release:** Import sonrası staging DB'deki `active_release` pointer'ı bu release'e güncellenir. Dashboard'da aktif release gösterilir.

---

## 18. Rollback

### Rollback ne yapar

Rollback, staging DB'deki aktif release pointer'ını **daha önce import edilmiş** bir release'e geri çevirir. **Veri silmez;** yalnız hangi release'in aktif olduğunu değiştirir.

### Adım adım

1. Geri dönmek istediğiniz release'in ID'sini belirleyin (daha önce import edilmiş olmalıdır).
2. Web panelinden **Release Merkezi** ekranında ilgili release'in yanındaki **Rollback** butonuna tıklayın, veya:

```bash
uv run mesa-data release rollback --release-id release-v0.9
```

3. İşlem başarılı olduğunda `active_release` pointer'ı belirtilen release'e döner.

### Beklenen sonuç

- Staging DB'deki `active_release` değeri eski release'i gösterir.
- Dashboard'da aktif release güncellenmiş olarak görünür.
- Yeni release'in staging kayıtları silinmez; yalnız aktif pointer değişir.

---

## 19. Operasyonlar

### Desteklenen işlem türleri

| İşlem türü | Açıklama |
|---|---|
| `filtered_export` | Filtrelenmiş veri dışa aktarma işlemi |
| `release_build` | Release paketi oluşturma işlemi |
| `integrity_audit` | SHA-256 bütünlük denetimi |

### İşlem durumları

| Durum | Açıklama |
|---|---|
| `queued` | İşlem kuyruğa alındı, henüz başlamadı |
| `running` | İşlem çalışıyor |
| `succeeded` | İşlem başarıyla tamamlandı |
| `failed` | İşlem hata ile sonlandı |
| `cancelled` | İşlem kullanıcı tarafından iptal edildi |
| `interrupted` | Sunucu yeniden başlatılması sırasında çalışan işlem kesildi |

### Web panelinden kullanım

- **Operasyonlar** ekranında tüm işlemler listelenr.
- Çalışan bir işlemi **İptal Et** butonu ile durdurabilirsiniz.
- İşlem detayında ilerleme, sonuç ve hata özeti görüntülenir.

### İptal edilen veya kesilen işlemler

- İptal edilen işlem `cancelled` durumuna geçer ve tekrar başlatılamaz.
- Sunucu beklenmedik biçimde kapanırsa çalışan işlemler bir sonraki başlatmada otomatik olarak `interrupted` durumuna alınır.

---

## 20. Audit

### Audit kaydı alanları

| Alan | Açıklama |
|---|---|
| `event_id` | Benzersiz olay kimliği |
| `actor` | İşlemi yapan kişi veya sistem |
| `action` | Yapılan eylem (örn. `download_artifact`, `export_create`, `operation_submit`) |
| `subject_type` | Etkilenen nesne türü (artifact, record, release, export, operation) |
| `subject_id` | Etkilenen nesnenin ID'si |
| `reason` | İşlem nedeni (varsa) |
| `old_sha256` | Önceki SHA-256 değeri (varsa) |
| `new_sha256` | Yeni SHA-256 değeri (varsa) |
| `request_id` | İstek izleme kimliği (varsa) |
| `created_at` | Olay zaman damgası (ISO 8601) |

### Bir işlemin geçmişini bulma

1. **Audit** ekranını açın.
2. **Konu türü** ve **Konu ID'si** filtrelerini kullanarak aradığınız nesneyi bulun.
3. Sonuçlar zaman sırasına göre (en yeni en üstte) listelenir.

### Önemli

- Audit kayıtları **değiştirilemez** ve **silinemez**.
- Her veri yazma, onay, ret, indirme, export, release ve import işlemi otomatik olarak kaydedilir.

---

## 21. Doctor ve sistem kontrolü

### Doctor ne kontrol eder

`doctor` komutu sistemin sağlık durumunu kontrol eder:

| Kontrol | Açıklama |
|---|---|
| Data root yazılabilirliği | Veri dizinine yazma izni var mı |
| Catalog SQLite durumu | Veritabanı dosyası mevcut ve sağlıklı mı |
| Eksik artifact'lar | Veritabanında kayıtlı olup disk üzerinde bulunmayan raw dosyalar |
| Stale `.building` release'ler | Tamamlanmamış release build dizinleri |
| Orphaned release'ler | `.orphaned` olarak işaretlenmiş eski release dizinleri |
| Disk/katalog uyuşmazlığı | Disk üzerinde olan ama veritabanında olmayan (veya tersi) release'ler |
| Manifest hataları | `manifest.json` dosyası eksik veya bozuk olan release'ler |
| Release item count uyuşmazlığı | Manifest'te bildirilen kayıt sayısı ile gerçek satır sayısı arasındaki farklar |
| Dosya yolları | Veritabanı sağlıklı değilse disk üzerindeki raw ve canonical dosyalar taranır |

### CLI ile çalıştırma

```bash
uv run mesa-data doctor
```

### Web panelinden çalıştırma

**Sistem** ekranında **Doctor** butonuna tıklayın.

### Önemli

- Doctor **otomatik olarak veri silmez**. Yalnız sorunları raporlar.
- Tespit edilen sorunları elle düzeltmeniz gerekir.

---

## 22. Backup

### Backup ne yapar

Backup komutu `catalog.sqlite` veritabanının zaman damgalı bir kopyasını oluşturur. SQLite'ın online backup özelliğini kullanır; veritabanı açıkken güvenle çalıştırılabilir.

### CLI ile backup

```bash
uv run mesa-data backup
```

Varsayılan olarak yedek dosya `$DATA_ROOT/../backups/` dizinine yazılır. Farklı bir dizin belirtmek için:

```bash
uv run mesa-data backup --target-dir /yedek/dizin
```

### Web panelinden backup

**Sistem** ekranında **Yedekle** butonuna tıklayın.

### CLI ile geri yükleme

```bash
uv run mesa-data restore --backup-file /yedek/dizin/catalog_backup_20260806T120000Z.sqlite
```

### Backup'ın kapsamadıkları

- `raw/`, `canonical/`, `releases/` dizinlerindeki dosyalar yedeklenmez; yalnız catalog SQLite yedeklenir.
- Bu dosyaların ayrıca dosya sistemi düzeyinde yedeklenmesi önerilir.
- Staging DB (`mesa_staging.sqlite`) ayrı bir dosyadır ve backup komutu kapsamına girmez.

---

## 23. İndirme işlemleri

Web panelinden aşağıdaki varlıkları indirebilirsiniz:

| İndirme türü | Açıklama |
|---|---|
| Artifact (ham dosya) | Raw artifact dosyası (PDF, HTML) |
| Artifact metadata | Artifact'ın JSON metadata dosyası |
| Canonical record | Tekil canonical kayıt (JSON veya metin) |
| Provenance | Kaydın veri kökeni zinciri (JSON) |
| Export dosyası | Oluşturulmuş export dosyası |
| Release manifest | Release manifest.json dosyası |
| Release paketi | Release dizininin tar.gz arşivi |

### Güvenlik korumaları

Tüm indirmeler şu güvenlik katmanından geçer:

- **Exact ID lookup:** Doğrudan dosya yolu kullanılmaz; yalnız veritabanındaki ID ile eşleşen dosya sunulur (path traversal engeli).
- **Symlink kontrolü:** Sembolik bağlantı dosyaları reddedilir.
- **Data root sınırı:** Veri dizini dışına erişim engellenir.
- **SHA-256 doğrulaması:** İndirme anında dosyanın hash'i veritabanındaki kayıtla karşılaştırılır.
- **Audit kaydı:** Her indirme audit loguna yazılır.

---

## 24. Sık karşılaşılan hatalar

| Hata | Anlamı | Çözüm |
|---|---|---|
| `SOURCE_DISABLED` | Kaynak `config/sources.yaml` dosyasında `enabled: false` olarak ayarlanmış | `sources.yaml` dosyasında ilgili kaynağın `enabled` alanını `true` yapın ve sunucuyu yeniden başlatın |
| `SOURCE_HOST_NOT_ALLOWED` | URL'nin alan adı kaynağın `allowed_hosts` listesinde değil | `sources.yaml` dosyasında ilgili kaynağın `allowed_hosts` listesine alan adını ekleyin |
| URL scheme must be HTTPS | HTTP şeması kullanılmış | URL'yi `https://` ile başlatın |
| Access to private/local IP is forbidden | URL özel bir IP adresine (localhost, 10.x, 192.168.x) yönlendiriyor | Geçerli bir kamu IP adresi kullanan URL kullanın |
| `FILE_TOO_LARGE` | Dosya boyutu sınırı aşıyor | Daha küçük bir dosya yükleyin veya `max_download_bytes` değerini artırın |
| `SOURCE_CONTENT_TYPE_NOT_ALLOWED` | Dosyanın MIME türü izin verilen listede değil | `allowed_content_types` listesini kontrol edin; dosyanın gerçekten beklenen formatta olduğunu doğrulayın |
| Duplicate artifact | Aynı SHA-256 hash'e sahip artifact zaten mevcut | Bu beklenen bir durumdur; dosya zaten yüklenmiştir |
| `TRANSPORT_VERIFICATION_FAILED` | Pipeline sırasında dosyanın SHA-256'sı veya boyutu beklenenle eşleşmedi | Dosyanın bozulmadığını kontrol edin; gerekirse yeniden yükleyin |
| `PARSING_FAILED` | Dosya ayrıştırılamadı (boş metin veya desteklenmeyen format) | Dosyanın geçerli bir PDF veya HTML olduğunu doğrulayın |
| `SCHEMA_VALIDATION_FAILED` | Üretilen canonical kayıt JSON Schema doğrulamasından geçemedi | Pipeline çıktısını inceleyin; kaynak dosyanın yapısında sorun olabilir |
| Open blocker issues exist | Release build sırasında çözülmemiş blocker issue var | **Sorunlar** ekranından blocker issue'ları tespit edin; ilgili kaydı düzeltin veya reddedin |
| `RELEASE_NOT_PUBLISHED` | Import edilmek istenen release henüz `published` durumunda değil | Önce `verify` ve ardından `publish` komutunu çalıştırın |
| `RELEASE_REVOKED` | İptal edilmiş bir release import edilmeye çalışılıyor | İptal edilmiş release import edilemez; yeni bir release oluşturun |
| `UNAUTHORIZED` | Admin token eksik veya hatalı | `MESA_DATA_WEB_ADMIN_TOKEN` ortam değişkenini doğru ayarlayın |
| `CSRF_HEADER_MISSING` | Yazma isteğinde `X-MESA-Requested-With` header'ı eksik | Web panelini tarayıcıdan normal kullanın; özel istemci kullanıyorsanız header'ı ekleyin |
| `NON_LOOPBACK_DISABLED` | Dış ağa açık başlatma yapılmış ama admin token ayarlanmamış | `MESA_DATA_WEB_ADMIN_TOKEN` ortam değişkenini ayarlayın |
| `WRITE_LOCK_CONFLICT` | Başka bir yazma işlemi devam ediyor | Önceki işlemin tamamlanmasını bekleyin ve tekrar deneyin |
| `RATE_LIMIT_EXCEEDED` | Çok fazla istek gönderildi | Birkaç saniye bekleyip tekrar deneyin |
| `OPERATION_TYPE_NOT_SUPPORTED` | Desteklenmeyen bir operasyon türü belirtildi | Desteklenen türler: `filtered_export`, `release_build`, `integrity_audit` |
| `FILE_NOT_FOUND` | İstenen dosya disk üzerinde bulunamadı | `doctor` komutunu çalıştırarak eksik dosyaları tespit edin |
| `HASH_MISMATCH` | Dosyanın SHA-256 hash'i veritabanındaki kayıtla eşleşmiyor | Dosya bozulmuş olabilir; `audit` komutunu çalıştırın ve gerekirse yedekten geri yükleyin |

---

## 25. Güvenli kullanım kuralları

1. **`raw/` dizinindeki dosyaları elle değiştirmeyin.** Bu dosyalar değişmez (immutable) olarak saklanır; değişiklik SHA-256 doğrulama hatalarına neden olur.
2. **`catalog.sqlite` dosyasını sunucu açıkken elle düzenlemeyin.** SQLite kilitleme mekanizması bozulabilir.
3. **`releases/` klasörünü elle değiştirmeyin.** Release paketleri manifest ile korunur; elle değişiklik doğrulama hatalarına neden olur.
4. **`config/sources.yaml` değişikliğinden önce yedek alın.** Hatalı yapılandırma veri alımını engelleyebilir.
5. **Admin token'ı başkalarıyla paylaşmayın.** Token tüm yazma işlemlerine erişim sağlar.
6. **Production verisini test ortamına kopyalamayın.** Ayrı data root'lar kullanın.

---

## 26. Örnek baştan sona kullanım senaryosu

Aşağıda, Türk Medeni Kanunu PDF'inin yüklenmesinden MESA staging import'a kadar tam bir iş akışı gösterilmektedir.

### Adım 1 — PDF yükleme

```bash
uv run mesa-data collect manual \
  --source mevzuat \
  --file /home/operator/belgeler/4721.pdf \
  --document-id tr:legislation:law:4721 \
  --family legislation \
  --document-type law \
  --title "Türk Medeni Kanunu"
```

**Beklenen sonuç:** `Successfully imported artifact sha256:abc123... -> raw/legislation/mevzuat/2026/...`

### Adım 2 — Pipeline çalıştırma

```bash
uv run mesa-data pipeline run --artifact-id sha256:abc123...
```

**Beklenen sonuç:** `Pipeline finished with status 'needs_review'`

### Adım 3 — Canonical kayıtları kontrol etme

```bash
uv run mesa-data review list --status pending
```

**Beklenen sonuç:** Oluşturulan legislation, article ve citation kayıtları listelenir.

### Adım 4 — Toplu onay

```bash
uv run mesa-data review approve-version VERSION_ID --reviewer "operator" --note "Medeni Kanun kontrol edildi"
```

**Beklenen sonuç:** `Successfully APPROVED version VERSION_ID (N records)`

### Adım 5 — JSONL export (isteğe bağlı)

Web panelinde **Dışa Aktarma** ekranından `records_jsonl` formatında, `approval_status: approved` filtresiyle export oluşturun.

### Adım 6 — Release build

```bash
uv run mesa-data release build --release-id release-v1.0
```

**Beklenen sonuç:** Release paketi `releases/release-v1.0/` dizinine oluşturulur.

### Adım 7 — Verify ve publish

```bash
uv run mesa-data release verify --release-id release-v1.0
uv run mesa-data release publish --release-id release-v1.0
```

**Beklenen sonuç:** `Release release-v1.0 verification PASSED.` ve `Release release-v1.0 successfully PUBLISHED.`

### Adım 8 — MESA staging import

```bash
uv run mesa-data release import --release-id release-v1.0
```

**Beklenen sonuç:** `Successfully IMPORTED release release-v1.0 into staging DB (status: imported)`. Dashboard'da aktif release: `release-v1.0`.

> **Ekran görüntüsü:** Genel Bakış — aktif release gösterimi

---

## 27. Hızlı komut referansı

| Amaç | Komut | Açıklama |
|---|---|---|
| Kurulum | `uv sync --frozen` | Bağımlılıkları yükler |
| Dizin oluşturma | `uv run mesa-data init` | Data root dizinlerini oluşturur |
| Veritabanı hazırlama | `uv run mesa-data migrate` | Şema tablolarını oluşturur/günceller |
| Sağlık kontrolü | `uv run mesa-data doctor` | Sistem bütünlüğünü kontrol eder |
| Bütünlük denetimi | `uv run mesa-data audit` | Tüm artifact'ların SHA-256'sını doğrular |
| Katalog raporu | `uv run mesa-data report` | Belge, artifact ve sorun sayılarını gösterir |
| Dosya yükleme | `uv run mesa-data collect manual --source ... --file ... --document-id ...` | Yerel dosya import eder |
| URL'den alma | `uv run mesa-data collect url --source ... --url ... --document-id ...` | URL'den dosya indirir |
| Seed veri yükleme | `uv run mesa-data collect seed` | 12 temel mevzuat verisini yükler |
| Pipeline çalıştırma | `uv run mesa-data pipeline run --artifact-id ...` | Artifact'ı canonical kayıtlara dönüştürür |
| Kayıt listeleme | `uv run mesa-data review list --status pending` | İnceleme bekleyen kayıtları listeler |
| Kayıt detayı | `uv run mesa-data review show RECORD_ID` | Kayıt detayını gösterir |
| Tekli onay | `uv run mesa-data review approve RECORD_ID --reviewer "ad"` | Kaydı onaylar |
| Toplu onay | `uv run mesa-data review approve-version VERSION_ID --reviewer "ad"` | Version altındaki tüm kayıtları onaylar |
| Tekli ret | `uv run mesa-data review reject RECORD_ID --reviewer "ad"` | Kaydı reddeder |
| Release build | `uv run mesa-data release build --release-id ...` | Release paketi oluşturur |
| Release doğrulama | `uv run mesa-data release verify --release-id ...` | Release bütünlüğünü kontrol eder |
| Release yayınlama | `uv run mesa-data release publish --release-id ...` | Release'i yayınlar |
| Release iptal | `uv run mesa-data release revoke --release-id ...` | Yayınlanan release'i iptal eder |
| Staging import | `uv run mesa-data release import --release-id ...` | Release'i MESA staging DB'ye aktarır |
| Rollback | `uv run mesa-data release rollback --release-id ...` | Aktif release'i belirtilen ID'ye geri alır (işlem adı `rollback` olarak kullanılır) |
| Provenance sorgusu | `uv run mesa-data provenance RECORD_ID` | Kaydın veri kökeni zincirini gösterir |
| Yedekleme | `uv run mesa-data backup` | Catalog veritabanını yedekler |
| Geri yükleme | `uv run mesa-data restore --backup-file ...` | Yedekten catalog'u geri yükler |
| Web paneli başlatma | `uv run mesa-data web --host 127.0.0.1 --port 8765` | Web yönetim panelini başlatır |

---

## 28. V1 sınırları

Aşağıdaki özellikler V1 (MVP) kapsamında bulunmamaktadır ve V2 sürümü kapsamında planlanmıştır:

| Özellik | Durum |
|---|---|
| Kayıt revizyon editörü (record revision UI) | V2 kapsamı |
| Kaynak yapılandırma web editörü (source config web editörü) | V2 kapsamı; yapılandırma `config/sources.yaml` üzerinden yapılır |
| Sorun yönetimi (issue waive/reopen/resolve) | V2 kapsamı; sorunlar şu an salt okunurdur |
| Ek açıklama ve etiketleme (annotation) yönetimi | V2 kapsamı |
| Release karşılaştırma (release diff) | V2 kapsamı |
| Snapshot merkezi (full snapshot) | V2 kapsamı |
| Çok kullanıcılı yetkilendirme (OAuth/OIDC) | V2 kapsamı; şu an token tabanlı tek kullanıcı erişimi mevcuttur |

> **Ekran görüntüsü:** Veri Ekle ekranı — dosya yükleme formu

---

*Bu kılavuz, MESA Legal Data v0.1.0 kaynak kodundan doğrulanarak hazırlanmıştır.*
