# Release, Onay ve Değişmezlik

Release builder yalnız current, valid, privacy-clean/approved, quality PASS, version-approved ve record-approved üyeleri seçer. Yeni temporal filtre, gelecekte başlamamış veya sona ermiş explicit aralıkları release dışında bırakır. REVIEW/BLOCK veya açık candidate-scoped error/blocker issue release'e giremez.

## H1 eşdeğeri insan onayı

Panel `prepare` adımında exact frozen release oluşturur ve doğrular; kullanıcıya `release_id`, `manifest_sha256`, `target_config_sha256`, hedef scope ve sayımlar döner. `publish` aynı manifest ve hedef hash'i yeniden karşılaştırır. Onarım sonrası authorization audit olayı gerçek actor, manifest, target hash, delivery/operation ID ve frozen scope'u saklar. Stale veya değiştirilmiş manifest/hedef 409 ile kapanır.

## Değişmezlik ve negatif durumlar

- Manifestte olmayan dosya, symlink/path traversal, payload/index hash veya count değişikliği reddedilir.
- Release-index, record → version → document üyeliğini dondurur; canlı katalog sonradan değişse bile plan frozen sürümden kurulur.
- Release revoked olduğunda devam eden delivery yeni item göndermez.
- HTTP 200/202 başarı sayılmaz; yalnız açık terminal `COMMITTED` ledger başarısıdır.
- Timeout/poll penceresi `AWAITING_MUTATION` olarak korunur; retry önce aynı remote mutation'ı uzlaştırır ve aynı idempotency key'i kullanır.

Kanıt: `tests/integration/test_master_mvp_closure.py`, `test_release_tamper.py`, `test_release_atomicity.py`, `test_mesa_v4_publisher_e2e.py` ve final 413-test koşusu.
