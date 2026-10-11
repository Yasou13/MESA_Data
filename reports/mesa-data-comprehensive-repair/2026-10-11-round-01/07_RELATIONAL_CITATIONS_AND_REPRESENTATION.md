# İlişkisel Atıflar ve Temsil

## Atıf doğruluğu

Parser numbered law ve alias referanslarını exact Unicode span ile çıkarır. `amends`, `repeals`, `adds` fiilleri relation hint üretir. `1/A` article suffix olarak korunur; `27/2` ve `25/II` article 27/25 içindeki alt bölüm olarak parent article ID'ye bağlanır. `EK/GEÇİCİ/MÜKERRER` türleri farklı hedef kimliği üretir.

Sentaktik hedef hiçbir zaman corpus varlığı veya doğru tarihsel version kanıtı değildir. Bu nedenle bilinen kanunlar da `EXTRACTED`, belirsiz genel atıflar `UNRESOLVED` kalır. Yeni kayıtlar `source_version_id` ve nullable `target_version_id` taşır; doğrulanmamış target version uydurulmaz.

Native plan artık release-owned citation kaydını, exact source span ile örtüşen chunk'ın metadata'sına taşır. Alanlar citation/source record/source version/target law/article/version/status/relation/span ve `fully_contained` bilgisidir. Publisher metinden yeniden graph edge tahmin etmez.

## Kalan tüketici bağımlılığı

MESA graph projection kodu yoktur. Metadata'nın gerçek graph edge'e dönüştürülmesi, target version corpus resolver'ı ve version-as-of graph sorgusu canlı consumer ile doğrulanmalıdır. Bu nedenle kabul kapısı G producer tarafında fail-closed `VERIFIED_PASS`, gerçek graph consumption için `UNVERIFIED_ENV` olarak ayrılmıştır.

Canonical metin immutable kalır; retrieval chunk ve gelecekteki embedding/FTS representation türetilmiştir. Bu depoda embedding model/version alanının tüketici tarafından nasıl kullanıldığı görülemediğinden gerçek reindex/re-embed `EMBEDDING_DEPENDENCY_BLOCKED` durumundadır.
