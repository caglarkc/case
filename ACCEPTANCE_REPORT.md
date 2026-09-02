# Part A Nihai Kabul ve Revizyon Raporu

Tarih: 2 Eylül 2026  
Ortam: Ubuntu, Python 3.12.3, depo içi `.venv`

## Sonuç

Part B'de tanımlanan müşteri etkili beş revizyon grubu Part A'ya uygulandı.
Final kapısında 63 unit/contract testi ve gerçek `run.sh` process sınırını
kullanan 7 kabul kontrolü geçti. Testler dış internete çıkmadı: unit testleri
`httpx.MockTransport`, process testi yalnız yerel loopback sahte upstream
kullandı. Part A bu revizyon turu sonunda case kapsamı için teslim edilebilir
durumdadır.

## Başlangıç bulguları ve oluşturulan düzeltmeler

| Alan | Beklenen | Revizyon öncesi oluşturulan | Revizyon sonrası oluşturulan | Kanıt |
|---|---|---|---|---|
| Ubuntu test başlangıcı | `./test.sh` testleri başlatır | `python: command not found` | Script yerel `.venv`, Windows venv, `python3`, `python` sırasıyla yorumlayıcı buluyor | Depo dışından test ve process kabulü geçti |
| Public query sözleşmesi | `amount`, `from`, `to`, `date` zorunlu | Alias'lar vardı fakat açık cevap modeli yoktu | Dört zorunlu query adı, başarı modeli ve tüm hata modelleri OpenAPI'de açık | OpenAPI regresyon testi |
| Finansal hassasiyet | Kabul edilen Decimal değer aynı kalır | `9999999999999999.99`, cevapta `1e+16` oluyordu | Decimal JSON number token olarak kayıpsız yazılıyor | Büyük tutar regresyon testi |
| Para kodu | Tam üç ASCII harf | `" EUR "` sessizce `EUR` yapılıyordu | Boşluklu/deforme kod 422 `invalid_currency` | Input parametrik testleri |
| Upstream kur türü | Yalnız güvenli JSON number | `"1.25"` string'i geçerli kur sayılıyordu | String, boolean, non-finite, fazla büyük/hassas sayı 502 | Strict upstream testleri |
| Upstream aritmetik sınırı | Kontrollü hata | `1e999`, genel 500 üretiyordu | Güvenli sayı sınırı dışında 502 `invalid_upstream_response` | Unsafe number token testleri |
| Tarih provenance'ı | Gerçek kur tarihi görünür | Temel Part A doğruydu, ek kanıt eksikti | Hafta sonunda tek tarihli çağrı; `asked_date` ve `rate_date` ayrı; `/latest` yok | Unit ve process kabul testi |
| Cache | Tarih/çift izolasyonu, hata cache'lenmez | Sıralı cache vardı | Source/target/date LRU izolasyonu ve eşzamanlı istek birleştirme var | 10 eşzamanlı istek = 1 upstream; hata sonrası retry |
| Hata güvenliği | Hiçbir upstream hatası sahte 200 olmaz | Temel sınıflar vardı, uç sayılar 500'e kaçıyordu | Not-found, status, timeout, bağlantı, JSON, şema ve sayı hataları ayrı non-2xx | 63 testin hata matrisi |

## Process kabul testi: beklenen ve oluşturulan

| Kontrol | Beklenen | Oluşturulan | Durum |
|---|---|---|---|
| `PORT` ayarı | Özel portta `fx-tool` OpenAPI 200 | 200, başlık `fx-tool` | Geçti |
| Dönüşüm | 10 EUR × 1.2345 = 12.35 TRY | Alanlar ve 12.35 sonucu birebir | Geçti |
| Tarih görünürlüğü | İstenen 2024-08-31, kur 2024-08-30 | İki tarih ayrı ve doğru | Geçti |
| Tekrar/cache | İkinci tutarda aynı kur, toplam 1 upstream | Sonuç 24.69, upstream çağrısı 1 | Geçti |
| Geçersiz input | 422 ve upstream çağrısı yok | `invalid_amount`, yeni çağrı 0 | Geçti |
| Bulunamayan kur | 404 hata gövdesi | `rate_not_found` | Geçti |
| Fake upstream ve fallback | Yalnız `/v1/2024-08-31`, `/latest` yok | İki cache-miss yolu da tarihli; `latest` yok | Geçti |

## Çalıştırılan final kapıları

```bash
FX_UPSTREAM_BASE=http://127.0.0.1:1 .venv/bin/python -W error -m pytest -q
FX_UPSTREAM_BASE=http://127.0.0.1:1 .venv/bin/python tests/acceptance.py
.venv/bin/python -m compileall -q app.py tests
bash -n run.sh test.sh
git diff 7cff11b -- tool.py
git diff --check
```

Oluşturulan sonuçlar:

- Unit/contract: **63 passed**, warning yok.
- Process kabulü: **7/7 passed**.
- Python derleme ve shell sözdizimi: geçti.
- Başlangıçtan beri `tool.py` diff'i: boş; Part B örnek kodu değiştirilmedi.
- Final test sırasında `main` ve `origin/main`: senkrondu.

## Revizyon commitleri

| Commit | Anlamlı aşama |
|---|---|
| `cf242a3` | Windows → Ubuntu ve `.venv` çalışma günlüğü |
| `2544de4` | Tam kapsamlı revizyon planı |
| `bfff407` | Taşınabilir run/test scriptleri |
| `6315550` | Açık API sözleşmesi ve kayıpsız finansal çıktı |
| `974eec9` | Strict upstream doğrulaması |
| `d422a7b` | Eşzamanlı cache miss birleştirme |
| `5101897` | Part B regresyon matrisi |
| `f14ebdf` | Dokümantasyon senkronizasyonu |
| `7872710` | Process-seviyesi kabul testi |

## Bilinen ve bilinçli sınırlar

Cache ve in-flight harita process içindedir; çok worker'lı dağıtımda ortak
cache sağlamaz. Auth, veritabanı, UI, Docker, CI ve deployment brief dışında
bırakılmıştır. Bunlar bu case'in kabul sonucunu engelleyen açıklar değildir.
