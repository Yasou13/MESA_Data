# MESA Legal Data — Sorun Giderme

Bu belge, MESA Legal Data kullanımı sırasında karşılaşabileceğiniz hata kodlarını ve çözüm yollarını içerir.

---

## Veri Toplama Hataları

| Hata | Sebep | Çözüm |
|---|---|---|
| `SOURCE_DISABLED` | Kaynak `enabled: false` | `config/sources.yaml` → ilgili kaynak → `enabled: true` yapın, sunucuyu yeniden başlatın |
| `SOURCE_NOT_FOUND` | Source ID `sources.yaml`'da tanımlı değil | `sources.yaml` dosyasına kaynağı ekleyin |
| `SOURCE_HOST_NOT_ALLOWED` | URL alan adı `allowed_hosts`'ta yok | `sources.yaml` → ilgili kaynak → `allowed_hosts` listesine alan adını ekleyin |
| `SOURCE_CONTENT_TYPE_NOT_ALLOWED` | Dosyanın MIME türü izin listesinde yok | `allowed_content_types` listesini kontrol edin; dosya formatını doğrulayın |
| `SOURCE_FAMILY_NOT_ALLOWED` | Belge ailesi bu kaynak için tanımlı değil | `families` listesini kontrol edin |
| `FILE_TOO_LARGE` | Dosya boyutu `max_download_bytes` sınırını aşıyor | Daha küçük dosya kullanın veya sınırı artırın |
| URL scheme must be HTTPS | HTTP kullanılmış | URL'yi `https://` ile başlatın |
| Access to private/local IP is forbidden | Private IP'ye erişim (SSRF koruması) | Geçerli bir kamu IP'si olan URL kullanın |
| Non-standard port is forbidden | 443 dışı port | Standart HTTPS portu (443) kullanın |
| Redirect loop detected | URL yönlendirme döngüsüne girdi | URL'nin doğru olduğunu kontrol edin |
| Too many redirects | 3'ten fazla yönlendirme | Nihai URL'yi doğrudan kullanın |
| HTTP connection failed after N retries | Sunucu erişilemiyor | İnternet bağlantınızı ve hedef sunucuyu kontrol edin |
| File is empty | Boş dosya yüklenmiş | Geçerli bir dosya yükleyin |

## Pipeline Hataları

| Hata | Sebep | Çözüm |
|---|---|---|
| `TRANSPORT_VERIFICATION_FAILED` | SHA-256 veya boyut uyuşmazlığı | Dosyayı yeniden yükleyin |
| `PARSING_FAILED` | Dosya ayrıştırılamadı | PDF/HTML formatını doğrulayın; bozuk dosya değilse yeniden yükleyin |
| `SCHEMA_VALIDATION_FAILED` | Canonical kayıt şema doğrulamasından geçemedi | Kaynak dosyanın yapısını kontrol edin |
| Parsed text is empty | Ayrıştırma sonucu boş metin | Dosyanın metin içerdiğini doğrulayın (taranmış PDF'ler OCR gerektirebilir) |

## Otomatik Veri Toplama (Harvest) Hataları

| Hata | Sebep | Çözüm |
|---|---|---|
| Harvest DB bulunamadı | `harvest.sqlite` oluşturulmamış | `uv run mesa-data harvest init` çalıştırın |
| `retry_wait` | Geçici kaynak veya HTTP hatası | Backoff süresi dolunca runner otomatik yeniden dener |
| `failed` | Kalıcı pipeline hatası veya max attempt aşıldı | `uv run mesa-data harvest failures` ile hata kodunu inceleyin |
| `LOW_DISK_SPACE` | Serbest disk alanı güvenlik eşiğinin altında | Disk alanı açmadan runner'ı başlatmayın |
| `TARGET_REACHED` | Global veya kaynak ham veri hedefi doldu | Normal durdurma durumudur; hedefi artırabilir veya mevcudu işleyebilirsiniz |
| `DISCOVERY_STRUCTURE_CHANGED` | Resmî kaynak sayfası beklenen formatta değil | Kaynak sayfasının yapısını kontrol edin; fail-closed kuralı gereği cursor ilerlemez |
| `NO_PUBLICATION` | O tarihte yayımlanmış resmî gazete/sayı yok | Normal durumdur; sistem o günü tamamlandı sayıp sonraki tarihe geçer |

## İnceleme Hataları

| Hata | Sebep | Çözüm |
|---|---|---|
| Blocker issue engeli | Blocker düzeyinde açık sorun var | İlgili sorunun kaynağını çözün; gerekirse yeni dosya yükleyin |
| Kayıt `pending` değil | Zaten onaylanmış veya reddedilmiş kayıt | Yalnız `pending` kayıtlar onaylanabilir/reddedilebilir |

## Release Hataları

| Hata | Sebep | Çözüm |
|---|---|---|
| Release directory already exists | Aynı release ID ile daha önce build yapılmış | Farklı bir release ID kullanın |
| Open blocker issues exist | Çözülmemiş blocker sorunlar var | **Sorunlar** ekranından blocker'ları tespit edip çözün |
| `RELEASE_NOT_FOUND` | Release ID veritabanında yok | Doğru release ID kullandığınızı kontrol edin |
| Cannot publish: must be 'verified' | Henüz verify yapılmamış | Önce `release verify` çalıştırın |
| `RELEASE_NOT_PUBLISHED` | Import için release henüz yayınlanmamış | Önce `release publish` çalıştırın |
| `RELEASE_REVOKED` | İptal edilmiş release import edilmeye çalışılıyor | Yeni release oluşturun |
| `RELEASE_STATE_CHANGED` | Import sırasında release durumu değişmiş | İşlemi tekrar deneyin |
| already_imported (uyarı) | Aynı release aynı manifest ile tekrar import edildi | Bu normal; veri tekrar yazılmaz |
| Manifest SHA-256 collision | Aynı ID farklı manifest | Farklı release ID kullanın |

## Kimlik Doğrulama ve Güvenlik

| Hata | Sebep | Çözüm |
|---|---|---|
| `UNAUTHORIZED` | Admin token eksik veya yanlış | `MESA_DATA_WEB_ADMIN_TOKEN` ortam değişkenini kontrol edin |
| `NON_LOOPBACK_DISABLED` | Dış ağa açık ama token yok | Token ayarlayın veya `--host 127.0.0.1` kullanın |
| `CSRF_HEADER_MISSING` | Yazma isteğinde gerekli header eksik | Tarayıcıdan normal kullanın; özel istemcide `X-MESA-Requested-With: web-admin` ekleyin |
| `RATE_LIMIT_EXCEEDED` | Çok fazla istek (dakikada 30 yazma / 300 okuma) | Birkaç saniye bekleyip tekrar deneyin |
| `AUTH_RATE_LIMIT_EXCEEDED` | Çok fazla hatalı token denemesi | Token'ı doğrulayıp bekleyin |

## Sistem Hataları

| Hata | Sebep | Çözüm |
|---|---|---|
| `WRITE_LOCK_CONFLICT` | Başka bir yazma işlemi çalışıyor | Önceki işlemin tamamlanmasını bekleyin |
| `OPERATION_TYPE_NOT_SUPPORTED` | Desteklenmeyen operation türü | Yalnız `filtered_export`, `release_build`, `integrity_audit` desteklenir |
| `FILE_NOT_FOUND` | Dosya disk üzerinde bulunamadı | `uv run mesa-data doctor` ile eksik dosyaları tespit edin |
| `HASH_MISMATCH` | SHA-256 uyuşmazlığı | `uv run mesa-data audit` çalıştırın; bozuk dosyayı tespit edip yedekten geri yükleyin |
| `PATH_TRAVERSAL_DENIED` | Data root dışına erişim girişimi | Normal kullanımda bu hata oluşmamalıdır; dosya yollarını kontrol edin |
| `SYMLINK_REJECTED` | Sembolik bağlantı dosyaya erişim | Data root içinde symlink kullanmayın |
| Catalog database not found | `catalog.sqlite` mevcut değil | `uv run mesa-data init` ve `uv run mesa-data migrate` çalıştırın |
| No write permission to data root | Data root'a yazma izni yok | Dizin izinlerini kontrol edin: `chmod -R u+rw $DATA_ROOT` |
| Backup file not found | Geri yükleme sırasında yedek dosya bulunamadı | Dosya yolunun doğru olduğunu kontrol edin |

---

## Genel ipuçları

1. Herhangi bir sorunla karşılaştığınızda önce `uv run mesa-data doctor` çalıştırın.
2. Veritabanı sorunlarında `uv run mesa-data backup` ile yedek alın, ardından `uv run mesa-data restore` ile son çalışan yedeğe dönün.
3. Hata mesajlarındaki büyük harfli kodları (örn. `SOURCE_DISABLED`) bu tabloda arayın.
