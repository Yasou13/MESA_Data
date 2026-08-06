# MESA Legal Data — Hızlı Başlangıç

Bu kılavuz, MESA Legal Data'yı kurup ilk veri aktarımınızı yapmanız için gereken asgari adımları içerir.

---

## 1. Kurulum

```bash
# Repoyu klonlayın
git clone <REPO_URL> mesa-legal-data
cd mesa-legal-data

# Bağımlılıkları yükleyin
uv sync --frozen

# Veri dizinlerini oluşturun
uv run mesa-data init

# Veritabanını hazırlayın
uv run mesa-data migrate
```

Doğrulama:

```bash
uv run mesa-data --help
```

---

## 2. Web panelini başlatma

```bash
uv run mesa-data web --host 127.0.0.1 --port 8765
```

Tarayıcıda açın: `http://127.0.0.1:8765`

---

## 3. İlk dosya yükleme

Web panelinde **Veri Ekle** ekranını açın veya CLI kullanın:

```bash
uv run mesa-data collect manual \
  --source mevzuat \
  --file /yol/belge.pdf \
  --document-id tr:legislation:law:4721 \
  --family legislation \
  --document-type law \
  --title "Türk Medeni Kanunu"
```

---

## 4. Pipeline çalıştırma

```bash
uv run mesa-data pipeline run --artifact-id sha256:<hash>
```

Pipeline tamamlandığında canonical kayıtlar üretilir ve `pending` (inceleme bekliyor) durumuna geçer.

---

## 5. İnceleme ve onay

Tüm kayıtları topluca onaylayın:

```bash
uv run mesa-data review approve-version VERSION_ID --reviewer "operator" --note "Kontrol edildi"
```

Veya web panelinde **İnceleme Masası** ekranından tekli onay yapabilirsiniz.

---

## 6. Dışa aktarma (isteğe bağlı)

Web panelinde **Dışa Aktarma** ekranından `records_jsonl` formatında bir export oluşturun.

---

## 7. Release oluşturma ve yayınlama

```bash
# Build
uv run mesa-data release build --release-id release-v1.0

# Doğrulama
uv run mesa-data release verify --release-id release-v1.0

# Yayınlama
uv run mesa-data release publish --release-id release-v1.0
```

---

## 8. MESA staging import

```bash
uv run mesa-data release import --release-id release-v1.0
```

İşlem tamamlandığında Dashboard'da aktif release `release-v1.0` olarak görünür.

---

## Sonraki adımlar

- Detaylı kullanım için: `docs/KULLANIM_KILAVUZU.md`
- Sorun giderme için: `docs/SORUN_GIDERME.md`
- Düzenli `uv run mesa-data doctor` ve `uv run mesa-data backup` çalıştırarak sisteminizi sağlıklı tutun.
