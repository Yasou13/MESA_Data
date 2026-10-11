# Regresyon ve Adversarial Sonuçlar

## Son koşular

| Komut | Sonuç |
|---|---|
| `.venv/bin/pytest -ra --durations=20 --tb=short` | 413 passed, 1 skipped, 78.95 s |
| `.venv/bin/pytest -m "not scale" -ra --durations=20 --tb=short` | 409 passed, 1 skipped, 4 deselected, 33.45 s |
| `/usr/bin/time -v .venv/bin/pytest -m scale ...` | 4 passed, 1 skipped, 409 deselected, 46.53 s, peak RSS 171,784 KiB |
| `.venv/bin/ruff format --check .` | 217 files formatted |
| `.venv/bin/ruff check .` | PASS |
| `.venv/bin/mypy src` | 78 source files, 0 issue |
| `.venv/bin/pip-audit` | bilinen açık yok; yerel paket PyPI'da olmadığı için skip |
| `git diff --check` | PASS |

Tek skip: `tests/integration/test_mesa_v4_vector_cross_repo.py`; `MESA_SOURCE_ROOT` ayarlı değil ve sibling MESA checkout bulunmadı. TestClient koşuları managed filesystem sandbox dışında çalıştırıldı; sandbox AF_UNIX wakeup yazmasını EPERM ile engelliyordu. Aynı minimal probe dışarıda 200 döndü; bağımlılık lock'u değiştirilmedi.

## 38 maddelik negatif matris

| # | Sonuç | Kanıt/Not |
|---|---|---|
| 1 | PASS | raw/canonical SHA ve tamper testleri |
| 2 | PASS | zero article/coverage/header-only gate |
| 3 | PASS | cp1254/UTF-8 testleri |
| 4 | PASS | mojibake/replacement quality testleri |
| 5 | PASS | parent law ID dahil article ID |
| 6 | PASS | header-only BLOCK |
| 7 | PASS | chunk parent metadata testi |
| 8 | PASS | ordinary/EK/GEÇİCİ/MÜKERRER ayrımı |
| 9 | PASS | overlap/mixed span redde kapalı |
| 10 | PASS | long split/reconstruction |
| 11 | PASS | overlap duplicate üretmez |
| 12 | PASS | fetched_at hukuk tarihi değildir |
| 13 | PASS | out-of-order historical import |
| 14 | PASS | effective interval/current filtreleri |
| 15 | PASS | bounded overlap REVIEW |
| 16 | PASS | content hash/version/manifest kimliği |
| 17 | PASS | deterministik hash/chunk/release |
| 18 | PASS | approval/quality/release seçimi |
| 19 | PASS | manifest+target+actor+scope yeniden doğrulama |
| 20 | PASS | manifest tamper/unmanifested/order bağları |
| 21 | PASS | schema/response validation |
| 22 | PASS | unknown route/contract FAIL |
| 23 | PASS | 200/202 tek başına COMMITTED değil |
| 24 | PASS | AWAITING_MUTATION reconcile |
| 25 | CONTRACT_ONLY | body idempotency producer testi; gerçek consumer yok |
| 26 | PASS | cross-release dedup/repeat publish |
| 27 | PASS | response-loss/ledger retry |
| 28 | PASS | auth ve target-scope fail-closed |
| 29 | PASS | finite retry/poll |
| 30 | PASS | ambiguous citation UNRESOLVED |
| 31 | PASS | target version doğrulanmadan RESOLVED değil |
| 32 | PASS | out-of-range span redde kapalı |
| 33 | PASS | chunking canonical/raw'u değiştirmez |
| 34 | UNVERIFIED_ENV | consumer representation version/re-embed yok |
| 35 | PASS | rapor canlı başarı iddia etmiyor |
| 36 | PASS | yalnız sentetik DEV fixture; resmî TEST çalıştırılmadı |
| 37 | PASS | release path/symlink güvenlik testleri |
| 38 | PASS | pipeline/release atomicity ve rollback |

## Önce/sonra

İlk hedefli koşu 6/6 kırmızıydı; ilgili hedefli son koşu 27/27 yeşil oldu. İlk full onarım koşusundaki 25 hata ve ilk scale koşusundaki 3 hata, tarih beyan etmeyen sentetik release fixture'larını gösterdi; gate düşürülmeden fixture metadata'sı düzeltildi. Nihai full koşu 413/413 geçti. Resmî Recall@5/MRR karşılaştırması yapılmadı.
