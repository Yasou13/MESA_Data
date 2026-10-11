# Ölçek ve Operasyon Hazırlığı

Scale işaretli 4 testin tamamı geçti. Ölçülen birleşik koşu 46.53 saniye duvar zamanı, 171,784 KiB maksimum RSS ve 735,504 filesystem output block kullandı. En yavaş testler: 10.000 article hardening 21.44 s, bulk review streaming 13.55 s, operations scale 10.35 s.

Mevcut mimari canonical JSONL'yi streaming işler; release seçimini geçici SQLite spool ile yapar ve canonical part dosyasını tek geçişte okuyan testlere sahiptir. Approval streaming, bounded fetchmany ve operasyon recovery testleri geçti. Immutable canonical core'dan derived staging/projection yeniden kurulabilir.

Bu ölçüm küçük sentetik ölçektir. 10–20 GB artifact/canonical corpus, gerçek disk baskısı, backup/restore süresi, MESA vector/graph rebuild ve eşzamanlı operasyon davranışı çalıştırılmadı. Sonuç: `CAPACITY_NOT_PROVEN_AT_TARGET_SCALE`.

Önerilen sonraki ölçüm, resmî TEST'ten bağımsız sabit DEV corpus ile 1x/5x/20x koşularında wall time, peak RSS, disk amplification, release spool boyutu ve restart recovery ölçmektir. Üretim verisi üzerinde destructive stress önerilmez.
