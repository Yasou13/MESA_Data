# Kanun, Madde, Chunk ve Zamansal Kimlik

## Kimlik

Madde parser'ı artık `MÜKERRER MADDE`, `EK MADDE`, `GEÇİCİ MADDE`, ordinary `MADDE` ve `1/A` benzeri ekli numaraları ayırır. ID örnekleri:

- `...:article:1`
- `...:article:ek-1`
- `...:article:gecici-1`
- `...:article:mukerrer-1`
- `...:article:1-a`

Aynı “Madde 1”, kanun ID'si parent olduğundan 6098 ve 6102 arasında çakışmaz. Chunk metadata'sı law ID/number/title, version kind/date/aralık, article ID/number/kind ve exact char koordinatını taşır. Başlık tekrar etmese bile parent kimlik korunur.

## Span ve reconstruction

Publisher, article span'larını sıralar; negatif/out-of-range/boş/örtüşen span'ı reddeder. Anlamlı preamble, bölüm/kısım gap'i ve annex/trailing metin ayrı chunk olur. Uzun metin 4.096 karakter MESA evidence sınırında deterministik bölünür; mevcut testler parçaların birleşiminin canonical metne eşit olduğunu doğrular. Yalnız whitespace gap'leri retrieval için ayrı junk chunk yapılmaz; hukuki anlam taşıyan gap'ler korunur.

## Zamansal seçim

Authoritative tarih sırası: kaynak metadata'sındaki publication/source/decision/snapshot ve beyan edilmiş effective interval. `retrieved_at` ile `last_modified` hukuki tarih yerine geçmez. Seçim rank'i bugün yürürlükte > süresi bitmiş tarihsel > gelecekte yürürlüğe girecek > tarihi bilinmeyen şeklindedir; böylece gelecek-effective sürüm aktif sürümü erken değiştirmez.

İki farklı içerik açık ve bounded etkinlik aralıklarıyla çakışıyorsa `VERSION_EFFECTIVE_INTERVAL_AMBIGUITY` açılır, version/records pending ve kalite REVIEW yapılır. Aynı authoritative tarihte farklı içerik ve explicit supersession yoksa mevcut current seçimi korunur ve otomatik onay geri alınır.

Kanıt: `tests/unit/test_comprehensive_legal_identity.py` 8/8; `tests/unit/test_comprehensive_temporal_integrity.py` 6/6; tarihsel chronology kontrolleri tam suite içinde geçti.
