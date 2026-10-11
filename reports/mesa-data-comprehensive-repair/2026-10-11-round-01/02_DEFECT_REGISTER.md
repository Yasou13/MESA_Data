# Kusur Kaydı

| ID | Öncelik | Yeniden üretim / kök neden | Onarım | Commit / durum |
|---|---|---|---|---|
| MD-P0-001 | P0 | `MÜKERRER MADDE` ve `MADDE 1/A` parser desenine girmiyor, kimlik çöküyordu | Parser 1.1.0 ve tür-duyarlı ID | `0a5cd5c`, kapalı |
| MD-P0-002 | P0 | Makaleler arasındaki yapısal canonical aralıklar yayın chunk'larından düşüyor; örtüşme kabul ediliyordu | Gap chunk, span sınır/örtüşme reddi, çağıran kayıtlarını mutasyonsuz işleme, parent metadata | `0a5cd5c`, kapalı |
| MD-P0-003 | P0 | `last_modified/retrieved_at`, authoritative hukuk tarihi yerine kullanılıyordu | `unknown-date` + REVIEW + açık error issue; release dışlama | `9500542`, kapalı |
| MD-P0-004 | P0 | `effective_from/to` atılıyor; gelecek sürüm aktif sürümü seçebiliyor; çelişkili bounded aralık sessizdi | Aralık saklama/doğrulama, as-of sıralama, overlap REVIEW, publish filtreleri | `9500542`, kapalı |
| MD-P0-005 | P0 | Parser'ın yalnız fallback “Madde N” üretmesi kalite PASS olabiliyordu | Tümü header-only ise BLOCK, kısmi ise REVIEW | `9500542`, kapalı |
| MD-P0-006 | P0 | Native publish job'u gerçek aktörü kaybetti; operasyon girdisinde manifest ve scope yoktu | Actor + exact manifest + target hash + frozen scope ve audit event | `17ce8f8`, kapalı |
| MD-P1-001 | P1 | Sentaktik bilinen kanun numarası corpus/version kanıtı olmadan `RESOLVED` oluyordu; harfli/türlü madde hedefleri kayıptı | `EXTRACTED`, doğru article identity; target version null kalır | `0a5cd5c`, kapalı/fail-closed |
| MD-P1-002 | P1 | Citation canonical release'te vardı ama native chunk metadata'sına taşınmıyordu | Source/target version alanları ve span-overlap citation metadata | `dfc752a`, kapalı |

Satır örnekleri mevcut checkout içindir: parser `src/mesa_legal_data/parsers/legislation.py:31`; chunk guard `src/mesa_legal_data/publisher/chunker.py:93`; hukuk tarihi `src/mesa_legal_data/pipeline.py:223`; current selection `src/mesa_legal_data/catalog.py:244`; header-only gate `src/mesa_legal_data/quality.py:238`; native authorization `src/mesa_legal_data/web/api.py:2244`; citation handoff `src/mesa_legal_data/publisher/engine.py:338`.

## Dış/kanıtsız kalanlar

- EXTERNAL-P0-001: gerçek MESA tüketici rotası, schema, terminal mutation ve server-side idempotency canlı doğrulanmadı. Sahip: MESA/runtime.
- EXTERNAL-P1-001: corpus-aware citation target-version resolver ve gerçek graph projection tüketimi yok. MESA_Data yanlış çözüm üretmez; doğrulanmış target version olmadan `EXTRACTED` kalır. Sahip: MESA_Data + MESA entegrasyon turu.
- EXTERNAL-P1-002: embedding/FTS representation-version ile gerçek reindex/re-embed geçişi ölçülmedi. Sahip: MESA consumer/runtime.
- CAPACITY-P2-001: 10–20 GB hedef ölçek çalıştırılmadı.
