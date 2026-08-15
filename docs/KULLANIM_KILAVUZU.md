# MESA Data — Kullanım Kılavuzu

**Sürüm:** 0.1.0  
**Hedef Kitle:** Hukuk veri analistleri, geliştiriciler ve sistem yöneticileri  

---

## 1. MESA Data Nedir?

MESA Data, Türkiye resmî hukuk kaynaklarından (T.C. Resmî Gazete, Mevzuat Bilgi Sistemi, Anayasa Mahkemesi vb.) hukuki metinleri ve kararları **toplayan, düzenleyen, kontrol etmenizi sağlayan ve kullanıma hazır veri paketleri olarak sunan** modern bir veri yönetim platformudur.

Sistem, teknik terim veya karmaşık komut satırı bilgisine ihtiyaç duymadan herkesin kullanabileceği insan odaklı bir arayüze sahiptir.

```
 ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
 │ 1. Veri Topla │  ───► │  2. İncele   │  ───► │ 3. Dışa Aktar│
 └──────────────┘       └──────────────┘       └──────────────┘
```

---

## 2. Hızlı Başlatma

Sistemi çalıştırmak için terminalden tek bir komut vermeniz yeterlidir:

```bash
uv run mesa-data web
```

Bu komut:
1. Gerekli veri dizinlerini otomatik olarak hazırlar.
2. Katalog ve toplama veritabanlarını günceller.
3. Web sunucusunu başlatır: 👉 **`http://127.0.0.1:8000`**

---

## 3. Web Arayüzü ve Ekran Rehberi

Web arayüzü 5 ana bölümden ve teknik kullanıcılar için daraltılabilir bir **Gelişmiş** menüsünden oluşur:

### 1. Ana Sayfa
- **İlk Kullanım Kartı (Onboarding):** Sistemde henüz belge bulunmadığında sizi 3 adımlı akışla karşılar ve doğrudan ilk veri toplamayı başlatmanızı önerir.
- **Önerilen İşlem Kartı:** Sistem durumuna göre yapılması gereken en öncelikli işi (örn. *"3 kayıt inceleme bekliyor"* veya *"Toplama devam ediyor"*) bildirir.
- **Özet Metrikler:** Toplam belge sayısı, inceleme bekleyen kayıtlar, açık sorunlar ve son toplama zamanını gösterir.
- **Veri Toplama Durumu:** Resmî Gazete taramasının kapsam ilerlemesini ve durumunu özetler.

### 2. Veri Topla
Hukuk kaynaklarından sisteme veri ekleme merkezidir:
- **T.C. Resmî Gazete (Otomatik):**
  - Tek tıkla `Toplamayı Başlat` butonuna basarak 2015'ten bugüne kanun, kararname, yönetmelik ve tebliğlerin taranmasını başlatabilirsiniz.
  - *Kapsamı değiştir* alanından başlangıç tarihini veya toplanacak belge türlerini özelleştirebilirsiniz.
- **Diğer Resmî Kaynaklar:**
  - *Mevzuat Bilgi Sistemi* ve *Anayasa Mahkemesi* için manuel ekleme desteklenir.
- **Belgeyi Kendim Eklemek İstiyorum (Manuel Ekleme):**
  - **Dosya Yükle:** Bilgisayarınızdaki PDF veya HTML dosyasını seçip başlık girerek tek tıkla yükleyip işleyebilirsiniz.
  - **Resmî Bağlantı:** Mevzuat veya Resmî Gazete HTTPS bağlantısı vererek belgenin indirilip işlenmesini sağlayabilirsiniz.

### 3. Kütüphane
Sistemde kayıtlı olan tüm belgelerin listelendiği alandır:
- Başlık, belge türü (Kanun, Yönetmelik vb.), kaynak ve duruma göre filtreleme ve arama yapabilirsiniz.
- **Detay** butonu ile belgenin metin önizlemesini inceleyebilir, varsa teknik ayrıntılarını açabilirsiniz.

### 4. İnceleme
İşlenen kayıtların doğruluk kontrolünden geçirildiği yerdir:
- **İnceleme Bekleyenler Sekmesi:** Kaydın metnini okuyabilir, tek tıklamayla **"Onayla"** veya **"Reddet"** butonuna basarak işlemi tamamlayabilirsiniz. İnceleyici adı yazmanız zorunlu değildir.
- **Sorunlar Sekmesi:** Ayrıştırma veya veri kalitesi uyarılarını listeler.

### 5. Dışa Aktar
Onaylanmış verileri sistemden çıkarma ve paylaşma ekranıdır:
- **Dosya Olarak İndir:**
  - **JSONL:** Yapay zeka model eğitimi ve veri işleme için ideal format.
  - **CSV:** Excel ve tablo araçları için uygun format.
  - Oluşturulan dosyalar geçmiş tablosundan doğrudan indirilebilir.
- **MESA’ya Aktar:**
  - Onaylı verileri doğrulanmış bir paket olarak MESA aktarım havuzuna gönderir.

### 6. Gelişmiş (Yönetim Menüsü)
Teknik kullanıcılar ve sistem yöneticileri için ek araçlar sunar:
- **Kaynaklar:** Resmî kurum erişim limitleri ve kuralları.
- **Veri Gezgini:** Ham kanonik kayıtları ayrıntılı arama ve inceleme.
- **Release Geçmişi:** Oluşturulan sürümlerin doğrulama, yayınlama ve geri alma süreçleri.
- **Arka Plan İşlemleri:** Uzun süren sistem görevlerinin durum takibi.
- **İşlem Geçmişi (Audit):** Sistemde yapılan tüm değişikliklerin işlem günlüğü.
- **Sistem:** Sistem sağlık taraması (Doctor) ve veritabanı yedekleme (Backup).

---

## 4. Sıkça Karşılaşılan Durumlar ve Çözümler

### S: "Disk alanı yetersiz. Veri toplama güvenlik nedeniyle durduruldu." uyarısı alıyorum.
- **Neden:** Otomatik Resmî Gazete tarayıcısı sistem güvenliği için belirli bir boş disk alanı eşiğine ihtiyaç duyar.
- **Çözüm:** Diskinizde yer açtıktan sonra *Veri Topla* ekranından *Devam Et* butonuna basarak kaldığı yerden devam ettirebilirsiniz.

### S: "Toplama zaten devam ediyor" uyarısı nedir?
- **Neden:** Arka planda aktif bir toplama görevi çalışırken ikinci bir görevin başlatılması veri çakışmalarını önlemek için engellenir.
- **Çözüm:** *Veri Topla* ekranından mevcut görevin tamamlanmasını bekleyebilir veya *Durdur* butonuna basabilirsiniz.

### S: Dışa aktarma yaptığımda neden boş veya az kayıt çıkıyor?
- **Neden:** MESA Data yalnızca **Onaylanmış (Approved)** kayıtları dışa aktarır.
- **Çözüm:** *İnceleme* ekranına giderek inceleme bekleyen kayıtları onaylayınız.

---

## 5. Komut Satırı (CLI) Kısayolları

| Görev | Komut |
|---|---|
| Web Arayüzünü Başlatma | `uv run mesa-data web` |
| Tek Seferlik Resmî Gazete Taraması | `uv run mesa-data harvest run --once` |
| Resmî Gazete Keşif Taraması | `uv run mesa-data harvest discover` |
| Sistem Teşhis Raporu | `uv run mesa-data doctor` |
| Veritabanı Yedekleme | `uv run mesa-data backup full` |
