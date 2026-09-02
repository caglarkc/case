# Frankfurter API Araştırma Raporu

Araştırma tarihi: 2 Eylül 2026

## Kısa sonuç

Bu case için en uygun seçim **Frankfurter v1 API**'dir. Çünkü case yalnızca Avrupa
Merkez Bankası (ECB) kurlarını istiyor ve beklenen `date`, `base`, `rates` cevap
yapısı v1 ile doğrudan uyuşuyor.

Frankfurter'ın güncel v2 API'si daha fazla para birimi ve veri sağlayıcı sunar,
fakat varsayılan olarak 84 kaynaktan gelen verileri harmanlar. Bu nedenle v2
filtresiz kullanılırsa cevaba `source: "ECB via frankfurter.dev"` yazmak doğru
olmayabilir.

## Frankfurter genel olarak ne sunuyor?

- Ücretsizdir; API anahtarı ve kayıt istemez.
- Açık kaynaklıdır ve istenirse self-host edilebilir.
- Güncel ve geçmiş tarihli günlük döviz kurlarını sunar.
- Zaman aralığı sorguları sağlar.
- Desteklenen para birimlerini listeleyebilir.
- Saatlik veya gerçek zamanlı piyasa kuru sunmaz.
- v1 yalnızca ECB verisini, v2 ise çok sayıda merkez bankası ve resmî kaynağı
  kullanır.
- v2; sağlayıcı filtresi, haftalık/aylık gruplama, CSV ve NDJSON çıktıları gibi
  ek özelliklere sahiptir.

v1 kurları iş günlerinde yaklaşık 16:00 CET civarında güncellenir. Bugünün
verisi yeni kur yayımlandığında değişebileceği için gün içinde sabit kabul
edilmemelidir.

## v1 ve v2 farkı

| Konu | v1 | v2 |
|---|---|---|
| Veri kaynağı | ECB | Varsayılan olarak 84 kaynağın harmanı |
| Para birimi kapsamı | ECB'nin desteklediği yaklaşık 30 aktif döviz | 201 para birimi |
| Cevap şekli | İç içe `rates` nesnesi | Her döviz çifti için düz kayıt |
| Durum | Eski sürüm, fakat çalışmaya devam edecek | Güncel sürüm |
| Case ile uyum | Doğrudan uyumlu | Yalnızca `providers=ECB` ile uygun |

## Bizim ihtiyaç duyduğumuz endpoint'ler

### 1. Belirli tarihteki kur — ana endpoint

```http
GET /v1/2026-08-28?base=EUR&symbols=TRY
```

Örnek cevap:

```json
{
  "amount": 1.0,
  "base": "EUR",
  "date": "2026-08-28",
  "rates": {
    "TRY": 56.1718
  }
}
```

Uygulama:

- `rates.TRY` değerini `rate` olarak kullanmalı.
- Sonucu kendi içinde `amount * rate` ile hesaplamalı.
- Upstream cevabındaki `date` değerini mutlaka `rate_date` yapmalı.
- Kullanıcının gönderdiği tarihi ayrı olarak `asked_date` alanında tutmalı.

Frankfurter'ın ayrı bir conversion endpoint'i yoktur; hesaplama uygulamada
yapılır.

### 2. Son yayımlanan kur — yalnızca tarih opsiyonelse

```http
GET /v1/latest?base=EUR&symbols=TRY
```

Case endpoint'inde `date` zorunlu yapılırsa buna ihtiyaç yoktur. Tarihsiz istek
desteklenecekse kullanılabilir. Dönen `date`, bugünün tarihi varsayılmamalıdır.

### 3. Para birimleri — doğrulama için opsiyonel

```http
GET /v1/currencies
```

Geçerli para birimi kodlarını verir. Liste uygulama başlangıcında veya ihtiyaç
anında alınıp cache'lenebilir. Her conversion isteğinde tekrar çağrılmamalıdır.

## Hafta sonu ve tatil davranışı

Frankfurter, kur yayımlanmayan bir tarih sorulduğunda önceki yayımlanmış kuru
döndürebilir. Örneğin 30 Ağustos 2026 Pazar günü için yapılan canlı sorgu:

```http
GET /v1/2026-08-30?base=EUR&symbols=TRY
```

şu tarihi döndürdü:

```json
{
  "date": "2026-08-28",
  "rates": { "TRY": 56.1718 }
}
```

Bu case için uygun davranış, cevabı kabul edip şunları açıkça göstermektir:

```json
{
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-30"
}
```

Uygulama ayrıca `/latest` çağrısı yapmamalıdır. Tarihli endpoint zaten doğru
önceki kuru ve gerçek tarihini verir. `/latest` kullanmak geçmiş tarihli bir
isteğe bugünkü kuru bağlama riski yaratır.

## Hata ve başarısızlık değerlendirmesi

### Girdi hataları

| Durum | Önerilen servis cevabı | Açıklama |
|---|---:|---|
| `amount` eksik | 422 | FastAPI doğrulaması veya özel hata gövdesi |
| `amount <= 0` | 422 | Upstream'e istek yapılmadan reddedilmeli |
| Fazla ondalık basamak | 422 | `float` yerine `Decimal` ile doğrulanmalı |
| Geçersiz para birimi | 422 | Büyük harfe normalize edilip doğrulanmalı |
| `from == to` | 422 | Case bunu hata olarak ele almamızı istiyor |
| Gelecek tarih | 422 | Upstream çağrısından önce reddedilmeli |
| Desteklenen seriden eski tarih | 422 veya 404 | Karar README'de açıkça belgelenmeli |

Önerilen makine kodları: `invalid_amount`, `invalid_currency`,
`same_currency`, `future_date`, `date_out_of_range`.

### Upstream hataları

| Upstream durumu | Önerilen servis cevabı | Makine kodu |
|---|---:|---|
| Bağlantı kurulamıyor | 502 | `upstream_unavailable` |
| İstek zaman aşımı | 504 | `upstream_timeout` |
| HTTP 5xx | 502 | `upstream_error` |
| JSON olmayan cevap | 502 | `invalid_upstream_response` |
| Eksik/yanlış JSON alanları | 502 | `invalid_upstream_response` |
| Veri bulunamadı | 404 | `rate_not_found` |

Bu hatalarda `rate: 0` veya `result: 0` ile HTTP 200 dönülmemelidir. Müşteri
bunu gerçek bir finansal sonuç sanabilir. Hatalar cache'lenmemeli ve eski bir
kur sessizce başarı cevabı olarak kullanılmamalıdır.

### Canlı API'de gözlenen durumlar

2 Eylül 2026 tarihinde v1 üzerinde yapılan sınırlı kontroller:

| İstek | Gözlenen sonuç |
|---|---|
| Hafta sonu tarihi | 200; önceki iş gününün kuru ve gerçek `date` |
| 2099 gibi gelecek tarih | 404 `not found` |
| 1900 gibi seri öncesi tarih | 404 `not found` |
| Geçersiz base/target | 404 `not found` |
| Aynı base ve target | 422 `bad currency pair` |
| Geçersiz tarih biçimi | 404 `not found` |

Upstream'in hata kodları her nedeni birbirinden ayırmıyor. Bu yüzden gelecek
tarih, aynı para birimi, tarih biçimi ve tutar gibi kontroller bizim servisimizde
upstream çağrısından önce yapılmalıdır.

## Güvenilir uygulama önerisi

1. `FX_UPSTREAM_BASE` değerini oku; varsayılanı
   `https://api.frankfurter.dev` yap.
2. İstek yolunu base URL üzerine `/v1/{asked_date}` ekleyerek oluştur.
3. Para birimlerini ISO biçiminde büyük harfe çevir ve doğrula.
4. Tutar hesabında `Decimal` kullan; kuru çarpmadan önce yuvarlama.
5. HTTP client için açık bağlantı ve okuma timeout'ları belirle.
6. `raise_for_status()` sonrasında JSON şemasını doğrula.
7. `rate_date` değerini yalnızca upstream'in `date` alanından al.
8. Cache anahtarına `(from, to, asked_date)` değerlerinin tamamını koy.
9. Geçmiş tarihli başarılı cevapları cache'le; hataları cache'leme.
10. Testlerde gerçek ağa çıkma; sahte upstream ile 200, 404, 500, timeout ve
    bozuk JSON senaryolarını çalıştır.

## v2 kullanılacaksa

Case için v2 zorunlu değildir. Kullanılacaksa ECB filtresi unutulmamalıdır:

```http
GET /v2/rate/EUR/TRY?date=2026-08-28&providers=ECB
```

Ancak reviewer'ın sahte upstream'i v1 cevap yapısını taklit ediyor olabilir.
Brief ve verilen `tool.py` v1'i işaret ettiği için en düşük riskli seçim v1'dir.

## Kaynaklar

- [Frankfurter v1 resmî dokümantasyonu](https://frankfurter.dev/v1/)
- [Frankfurter v2 resmî dokümantasyonu](https://frankfurter.dev/)
- [Frankfurter v2 OpenAPI şeması](https://api.frankfurter.dev/v2/openapi.json)
- [Frankfurter LLM özeti](https://frankfurter.dev/llms.txt)
- [Frankfurter resmî GitHub deposu](https://github.com/lineofflight/frankfurter)
- [Frankfurter servis durum sayfası](https://frankfurter.instatus.com/)
