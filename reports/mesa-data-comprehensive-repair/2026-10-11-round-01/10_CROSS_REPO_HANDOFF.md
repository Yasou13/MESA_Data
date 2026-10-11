# Çapraz Depo Teslimi

## Erişim durumu

`/storage` altında sibling `MESA` veya `MESA_E2E_Certification` checkout bulunmadı; `MESA_SOURCE_ROOT` ayarlı değildi. Bu iki depo read-only bile incelenemedi ve hiçbir dosyaları değiştirilmedi. Resmî Profile B evidence/TEST verisine dokunulmadı.

## MESA sahibine doğrulatılacak sözleşme

1. Session start request: tenant/workspace, `dataset_ids`, agent; 201 ve nonempty `session_id`.
2. Memory insert: document/revision/chunk identity, source_ref, content/evidence_span ≤4096, revision/finalize/supersedes, metadata, body `idempotency_key`.
3. Mutation response: açık state; queued/processing ise nonempty mutation ID; status route ve session yaşam döngüsü.
4. Server-side duplicate key semantiği, response-loss/restart sonrası aynı mutation'a dönüş.
5. Citation metadata'nın graph projection'a typed/versioned edge olarak nasıl alındığı; `EXTRACTED`/null target version'ın graph'a kesin edge yapılmaması.
6. Representation/model version değişiminde gerçek reindex/re-embed ve canonical provenance korunumu.

## E2E sahibine önerilen takip

- Yeni producer branch SHA'sını MESA ile aynı DEV scope'ta checkout edin.
- İzole DEV release'i native akışla yayınlayın; gerçek mutation ID'leri terminale kadar kaydedin.
- SQL canonical, vector metadata ve graph edge'lerinde document/version/article/span/hash provenance'ını kontrol edin.
- Aynı release'i tekrar ve process restart sonrası gönderip logical duplicate oluşmadığını kanıtlayın.
- Bu sonuçları yeni bir DEV evidence run olarak saklayın; mevcut Profile B TEST sonucunu yeniden etiketlemeyin.

Çapraz-depo testi, `MESA_SOURCE_ROOT` sağlandığında çalıştırılmaya hazırdır; bu turdaki tek skip budur.
