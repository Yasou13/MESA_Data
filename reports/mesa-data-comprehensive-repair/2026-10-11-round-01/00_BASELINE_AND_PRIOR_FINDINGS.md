# Başlangıç Durumu ve Önceki Bulgular

## Doğrulanmış başlangıç

- Depo: `MESA_Data` (`/storage/data-law/mesa-legal-data`)
- Başlangıç SHA: `38c3fa5d3240cc944e8da611926fd220b7df145c`
- Başlangıç dalı: `main`; çalışma ağacı temizdi.
- Yetkili onarım dalı: `fix/mesa-data-legal-integrity-native-publish`. Yerel/uzak geçmişte birleştirilmemiş ve açıkça devam edilmesi gereken bir onarım dalı bulunmadığı için, talimatta izin verilen adla başlangıç SHA'sından oluşturuldu.
- Denetlenen uygulama ucu: `dfc752a386b9f1287ee42256aa4013b24309ac6c` (rapor ve durum dosyası commit'i hariç).
- Ortam: Linux, Python 3.13.12, pytest 9.1.1, AnyIO 4.15.1, Starlette 1.5.1, FastAPI 0.141.1.

Başlangıçta `reports/` dizini yoktu; dolayısıyla bu dizin altında okunacak ya da korunacak eski rapor bulunmadı. `docs/` altındaki 11 mevcut durum/kullanım/UX belgesi okundu. Bunlar hukuki doğruluk veya canlı MESA sertifikasyonu kanıtı olarak kabul edilmedi. `docs/BUILD_STATE.json` içindeki “360 test geçti” ve `LIVE_MESA_NOT_VERIFIED` kayıtları yalnız tarihsel ipucu olarak ele alındı.

## Önceki iddia uzlaştırma matrisi

| İddia/kaynak | HEAD incelemesi | Kanıt | Sonuç |
|---|---|---|---|
| `docs/BUILD_STATE.json`: MVP kapanmış, testler yeşil | Test sayısı artmıştı; yeşil testler hukuki kimlik uçlarını kapsamıyordu | Ön-fix 6 yeni regresyonun 6'sı başarısız | `CONFIRMED_GAP` |
| Aynı dosya: canlı MESA doğrulanmadı | MESA çalışma kopyası, `MESA_SOURCE_ROOT` ve yetkili DEV uç noktası yok | Çapraz-depo testinin tek skip nedeni | `EXTERNAL` |
| UX kapanış raporları: panel akışları tamam | Panel/operasyon testleri mevcut ve son suite'te geçti | 413/413 test | `ALREADY_FIXED` |
| Prompt'taki tarihsel Profile B sayıları | Resmî TEST/evidence bu depoda çalıştırılmadı ve değiştirilmedi | Bu turda Profile B komutu yok | `UNVERIFIED_EVIDENCE` |
| “Plan raporu” olarak anılan `MESA_Data_Kapsamli_Denetim_Raporu.md` | Çalışma ağacında yok | `find docs`, `find reports` | `UNAVAILABLE` |

## Başlangıçta yeniden üretilen kusurlar

Yeni `tests/unit/test_comprehensive_legal_integrity.py` taslağındaki 6 testin tamamı onarım öncesinde kırmızıydı: mükerrer/harf ekli madde kimliği, yapısal chunk kaybı/örtüşme, chunk yasal üst kimliği, sentaktik atfın yanlış `RESOLVED` olması, edinim zamanının hukuk tarihi yapılması ve etkinlik aralığının atılması. Testler daha sonra kimlik ve zamansal dosyalara ayrıldı; son durumda tamamı yeşildir.

İlk tam onarım-sonrası çalıştırmada 25 test, sentetik releasable fixture'ların hiçbir hukuk tarihi beyan etmemesi nedeniyle beklenen biçimde kapalı kaldı. Gate zayıflatılmadı; yalnız bu sentetik fixture'lara açık `publication_date` eklendi. İlk scale turundaki aynı nedenli 3 hata da aynı yöntemle düzeltildi.
