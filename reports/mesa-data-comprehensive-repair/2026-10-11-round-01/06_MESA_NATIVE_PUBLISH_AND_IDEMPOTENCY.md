# MESA Native Publish ve Idempotency

## Producer tarafından doğrulanan sözleşme

`MesaClient` yapılandırılabilir v4 session/insert/mutation/end rotalarını kullanır. Payload şu çekirdek bağları taşır: `session_id`, `dataset_id`, `document_id`, `revision_id`, `chunk_id`, `content`, `evidence_span`, `revision_number`, ordinal/finalize/supersedes, metadata ve body içi `idempotency_key`. API anahtarı yalnız environment'tan okunur.

Idempotency anahtarı tenant/workspace/dataset/document/version/chunk/content hash üzerinden deterministiktir. Ledger item gönderilmeden önce yazılır. Yanıt kaybı ve crash-window testleri aynı key ve varsa aynı mutation ID ile uzlaştırır; cross-release aynı mantıksal chunk `SKIPPED` olur.

Durum normalizasyonu yalnız bilinen açık state'leri kabul eder. 200/201/202 içinde state veya gerekli mutation ID yoksa FAIL'dir. `QUEUED/PROCESSING` poll edilir; pencere biterse `AWAITING_MUTATION`; `COMMITTED`, `FAILED`, `REJECTED` terminaldir. 401/403, 429/503, bilinmeyen endpoint/state ve target güvenlik kontrolleri fail-closed test edilmiştir.

## Kanıt düzeyi

- Mock/stateful adapter: doğrulandı (`tests/integration/test_mesa_v4_publisher_e2e.py`, 3/3; post-master publisher kontrolleri).
- Frozen release, actor/manifest/target/scope bağlama: doğrulandı.
- Gerçek MESA source/runtime: yok.
- Canlı mutation ID, gerçek SQL/vector/graph projection ve restart-sonrası server idempotency: `UNVERIFIED_ENV`.

Sonuç: `NATIVE_MESA_INTEGRATION=CONTRACT_ONLY`. Mock başarı canlı entegrasyon başarısı olarak raporlanmamıştır.
