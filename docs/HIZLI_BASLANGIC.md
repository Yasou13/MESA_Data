# MESA Data — Hızlı Başlangıç

MESA Data; Türkiye resmî hukuk kaynaklarından (T.C. Resmî Gazete, Mevzuat Bilgi Sistemi vb.) hukuk verilerini toplayan, işleyen, doğrulayan ve kullanıma hazır veri paketleri olarak dışa aktaran modern bir veri platformudur.

---

## 1. Tek Komutla Web Arayüzünü Başlatma (Önerilen)

MESA Data web arayüzü tek bir komutla tüm veritabanlarını ve dizinleri otomatik hazırlar:

```bash
uv run mesa-data web
```

Komut çalıştıktan sonra tarayıcınızda açın:
👉 **`http://127.0.0.1:8000`**

---

## 2. 3 Adımda Normal Kullanıcı Akışı

Web arayüzünde herhangi bir teknik terim veya karmaşık ayar bilmenize gerek yoktur:

```
[ 1. Veri Topla ]  ───►  [ 2. İncele ]  ───►  [ 3. Dışa Aktar ]
```

### Adım 1: Veri Topla
1. Sol menüden **Veri Topla** ekranına gidin.
2. **T.C. Resmî Gazete** kartındaki **"Toplamayı Başlat"** butonuna tıklayın.
   - Sistem arka planda Resmî Gazete verilerini otomatik olarak tarar ve işler.
   - Dilerseniz *"Belgeyi kendim eklemek istiyorum"* bölümünden PDF/HTML dosyası yükleyebilir veya resmî bağlantı adresi verebilirsiniz.

### Adım 2: İncele
1. Sol menüden **İnceleme** ekranına gidin.
2. İşlenen kayıtların metin önizlemesini ve durumunu görün.
3. Tek tıklamayla **"Onayla"** butonuna basarak kaydı doğrulayın.

### Adım 3: Dışa Aktar
1. Sol menüden **Dışa Aktar** ekranına gidin.
2. **"Dosya olarak indir"**: JSONL (model eğitimi ve veri bilimi için) veya CSV (Excel için) biçimini seçip **"Dışa aktarmayı oluştur"** butonuna tıklayın.
3. **"MESA'ya aktar"**: Tek tıkla doğrulanmış paketi MESA veri havuzuna gönderin.

---

## 3. Geliştiriciler İçin Komut Satırı (CLI)

Geliştiriciler ve terminal kullanıcıları tüm işlemleri CLI üzerinden de yönetebilir:

```bash
# Otomatik Resmî Gazete taramasını başlatma
uv run mesa-data harvest run --once

# Manuel dosya yükleme ve işleme
uv run mesa-data collect manual \
  --source mevzuat \
  --file /yol/belge.pdf \
  --document-id tr:legislation:law:4721 \
  --family legislation \
  --document-type law \
  --title "Türk Medeni Kanunu"

# Durum ve teşhis kontrolü
uv run mesa-data doctor
```

---

## 4. Sistem Gereksinimleri

- **İşletim Sistemi:** Linux (Ubuntu 22.04+ önerilir) veya macOS
- **Python Sürümü:** 3.11 – 3.13 (Python 3.13 önerilir)
- **Paket Yöneticisi:** [uv](https://docs.astral.sh/uv/)
- **Tarayıcı:** Modern herhangi bir tarayıcı (Chrome, Firefox, Safari, Edge)
