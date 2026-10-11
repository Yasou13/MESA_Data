# Hukuki Kaynak, Encoding ve Kapsama

## Doğrulananlar

- Raw artifact SHA uyuşmazlığı pipeline/release'i durdurur; canonical satır SHA'ları release sırasında tekrar okunur.
- UTF-8 ve cp1254 fixture'ları geçti (`tests/unit/test_encoding_cp1254.py`, `tests/integration/test_pipeline_encoding.py`). Null byte/ağır replacement loss BLOCK, mojibake anomalisi REVIEW üretir.
- Sıfır makale legislation için BLOCK; düşük coverage ve büyük açıklanamayan boşluklar REVIEW/BLOCK üretir.
- Tüm madde kayıtları sadece parser fallback başlığından ibaretse PASS değildir.
- Article span'ları canonical koordinatlarında sınır ve içerik tutarlılığıyla denetlenir; publisher ayrıca out-of-range ve overlap'i reddeder.

## Ölçülen sentetik denetim özeti

Bu tur resmî corpus veya Profile B TEST kullanmadı. Yeni bir küçük DEV fixture setinde 5 genişletilmiş madde kimliği (`ordinary`, `EK`, `GEÇİCİ`, `MÜKERRER`, `1/A`), 1 yapısal gap örneği, 1 overlap saldırısı, 1 header-only kaynak ve 2 etkinlik aralığı senaryosu doğrulandı. Sonuçlar `source_quality_summary.csv` içindedir; bu sayılar üretim corpus toplamı değildir.

## Destek/kısıt

Kaynak politikaları `config/sources.yaml` ve MIME/URL güvenlik katmanıyla uygulanır. Erişilemeyen veya hukuken doğrulanmamış kaynak için başarı iddiası yoktur. Eksik orta sayfa gibi fiziksel belge bütünlüğü, kaynağın beklenen sayfa/madde sayısı bilinmiyorsa otomatik olarak ispatlanamaz; mevcut sistem coverage/gap sinyali üretir ve insan incelemesi gerekir.
