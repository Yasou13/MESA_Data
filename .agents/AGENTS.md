# MESA Legal Data — Agent Rules

## Placeholder Yasağı

- **Kesinlikle** sahte `write_text("{}")` veya boş JSON export yazılmayacak.
- Her export gerçek JSONL/CSV dosya üretmeli ve `export_packages` tablosuna kaydedilmeli.
- Her API yanıtı gerçek DB sorgusu veya disk işlemi sonucu dönmeli.

## Real Effect Assertion

- Her test, yalnızca HTTP 200 değil, gerçek yan etkiyi de doğrulamalı:
  1. API response kodu
  2. DB satır durumu (ör. `export_packages.status = 'ready'`)
  3. Dosya/disk etkisi (ör. JSONL dosyasının gerçek record içermesi)
- Operation testleri: job oluşturuldu → status succeeded → gerçek sonuç/dosya/DB etkisi oluştu.

## Audit

- Tüm yazma ve silme işlemlerinde `X-MESA-Actor` başlığı zorunludur.
- Her yazma işlemi `audit_events` tablosuna log yazmalıdır.
- İndirmeler dahil tüm veri erişimleri audit loglanmalıdır.
- Audit kaydı olmadan veri değişikliği kabul edilemez.

## Immutability (Değişmezlik)

- Raw artifact dosyaları (`raw/`) değiştirilemez.
- Canonical JSONL kayıtları değiştirilemez; değişiklik yalnızca revision sistemi ile yapılır.
- Release paketleri (`releases/`) finalize edildikten sonra değiştirilemez.
- Manifest SHA-256 hash'leri release verify aşamasında kontrol edilir.

## Scale (Ölçeklenebilirlik)

- `readlines()` kullanılmaz; tüm büyük veri yolları streaming (line-by-line veya `fetchmany`) ile işlenir.
- Canonical dosya işlemleri tek sıralı geçiş (single sequential pass) ile yapılır.
- SQL sorguları batch (`fetchmany(1000)`) ile okunur.
- Release build, export ve approve işlemlerinde spool SQLite kullanılır.
- 500+ kayıt ölçek testi (`test_operations_scale_gate.py`) her değişiklikten sonra geçmelidir.
