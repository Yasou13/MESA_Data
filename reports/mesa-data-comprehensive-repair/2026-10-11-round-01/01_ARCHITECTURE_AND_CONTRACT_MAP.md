# Mimari ve Sözleşme Haritası

## Gerçek veri hattı

`resmî/manual kaynak → raw immutable dosya + SHA-256 → artifact/catalog → MIME/encoding çıkarımı → normalize canonical text → legislation/decision parser → version + article + citation JSONL → quality/privacy/validation → insan/otomatik onay → frozen release + manifest + release-index → verified publish authorization → SourceChunk → MESA v4 session/insert/mutation ledger`

Kritik sahiplik sınırı: raw, canonical, kalite, release ve HTTP producer davranışı MESA_Data'ya aittir. MESA'nın SQL/vector/graph tüketici uygulaması ile MESA_E2E_Certification bu çalışma alanında yoktur ve değiştirilmemiştir.

## Alan matrisi

| Aşama | Kimlik/provenance alanları | Koruma |
|---|---|---|
| Artifact | `artifact_id`, `document_id`, `source_id`, `source_url`, `retrieved_at`, `sha256`, `raw_path`, `metadata_json` | dosya SHA ve immutable artifact collision |
| Version | `version_id`, `snapshot_date`, `effective_from/to`, `canonical_sha256`, parser/schema sürümü, onay/kalite | hukuk tarihi edinim zamanından türetilmez |
| Article | kanun ID, version ID, `article_number`, `article_kind`, exact `source_span`, etkinlik | `GEÇİCİ/EK/MÜKERRER/ordinary` ayrımı |
| Citation | source record/version, target law/article/version (doğrulanmamışsa null), exact span, status, relation hint | sentaks tek başına `RESOLVED` yapmaz |
| Release | manifest SHA, payload SHA, release-index'te version/document/record bağları | unmanifested/symlink/tamper reddi |
| Native payload | session/dataset/document/revision/chunk, content=evidence_span, revision, metadata, body idempotency | yalnız terminal `COMMITTED` başarıdır |

## Mevcut MESA producer sözleşmesi

- Sağlık: yapılandırılabilir, varsayılan `/health`
- Oturum: `POST /v4/sessions/start`
- Yazma: `POST /v4/memory/insert`
- Mutasyon: `GET /v4/mutations/{mutation_id}`
- Oturum kapatma: `POST /v4/sessions/{session_id}/end`
- Kimlik doğrulama: ortamdan `X-API-Key`; sır depoya/ledger'a yazılmaz.
- Kapsam: tenant/workspace/dataset/agent; hedef yapılandırma SHA ile insan onayına bağlanır.

Bu rota ve alanlar MESA_Data producer testleriyle doğrulandı. Gerçek MESA consumer kaynağı ve DEV runtime erişilemediği için consumer uyumu `CONTRACT_ONLY` durumundadır.

## Temsil ayrımı

Canonical metin ve SHA release'in otoritesidir. `SourceChunk` MESA'ya taşınan türetilmiş retrieval temsilidir; içerik canonical span'dan gelir, 4.096 karakter evidence sınırına göre bölünür ve canonical dosyayı yeniden yazmaz. Embedding modeli/representation-version ve gerçek re-embed davranışı bu depoda tüketici tarafı olarak doğrulanamamıştır.
