# Proje Çalışma Planı

Bu belge proje boyunca geliştirici ve kod yazan AI için ana çalışma planıdır.
Gereksinimler değişmedikçe aşağıdaki teknik kararlar sabit kabul edilecektir.

## Sabit kararlar

- Dil ve framework: **Python + FastAPI**
- Kur kaynağı: **Frankfurter v1 API (ECB verisi)**
- Upstream adresi: `FX_UPSTREAM_BASE`
- Varsayılan upstream: `https://api.frankfurter.dev`
- Port: `PORT`, varsayılan `8080`
- Finansal hesap: `float` yerine `Decimal`
- İlke: Yanlış kur döndürmek yerine açık bir hata döndürmek
- Kapsam: Brief'te istenmeyen UI, veritabanı, auth, Docker ve deployment
  eklenmeyecek
- AI aracı: Çalışma boyunca Codex/GPT kullanılacak; ürettiği kod ve kararlar
  test edilmeden doğru kabul edilmeyecek

## Görev ayrımı

### Part A — Uygulama

Döviz çeviri endpoint'inin yazılması, doğrulanması, test edilmesi ve kullanım
dokümantasyonunun hazırlanmasıdır.

### Part B — Kod incelemesi

Verilen `tool.py` dosyasının müşteri etkisi açısından incelenmesi ve bulguların
`REVIEW.md` içine önem sırasıyla yazılmasıdır. Part A tamamlandıktan sonra ayrı
bir değerlendirme olarak ele alınacaktır.

> Not: Otomatik testler Part A'nın zorunlu parçasıdır. Part B ise bu testlerden
> ayrı olan kod inceleme görevidir.

## Çalışma aşamaları

### 1. Brief ve ilk doküman incelemesi

Durum: **Tamamlandı**

- `README.md`, `NOTES.md`, `REVIEW.md`, `run.sh`, `test.sh` ve `tool.py` incelendi.
- İki ayrı görev ve teslim beklentileri belirlendi.
- Mevcut deponun yalnızca başlangıç şablonu olduğu doğrulandı.

Çıktı: Bu çalışma planı ve proje gereksinimlerinin net listesi.

### 2. Frankfurter API araştırması

Durum: **Tamamlandı**

- Resmî v1 ve v2 dokümantasyonları incelendi.
- Case için v1 kullanımının daha uygun olduğu belirlendi.
- Tarihli kur, son kur, para birimleri ve hata cevapları araştırıldı.
- Hafta sonu, gelecek tarih, eski tarih ve geçersiz para birimi davranışları
  canlı isteklerle kontrol edildi.

Çıktı: `FRANKFURTER_API_REPORT.md`

### 3. Proje gereksinimlerini ve riskleri değerlendirme

Durum: **Tamamlandı**

Aşağıdaki maddeler kod yazılmadan önce kesinleştirilecek:

- Endpoint parametreleri: `amount`, `from`, `to`, `date`
- Başarı cevabındaki tüm alanlar ve veri türleri
- Uygulamanın destekleyeceği tutar hassasiyeti
- Hafta sonu/tatil gününde önceki yayımlanmış kuru kullanma kararı
- Gelecek ve veri serisi öncesi tarihler için hata davranışı
- Geçersiz ve aynı para birimi kontrolleri
- Timeout, bağlantı hatası, HTTP 5xx, bozuk JSON ve eksik alan davranışları
- Cache anahtarı, cache süresi ve hangi cevapların cache'lenmeyeceği
- HTTP status ve makine tarafından okunabilir hata kodları

Temel riskler:

| Risk | Alınacak önlem |
|---|---|
| Yanlış tarihe ait kur göstermek | `rate_date` yalnızca upstream `date` alanından alınacak |
| Geçmiş istek için güncel kur kullanmak | Tarihli v1 endpoint kullanılacak; sessiz `/latest` fallback yapılmayacak |
| Cache'in farklı tarihleri karıştırması | Anahtar `from`, `to` ve `asked_date` içerecek |
| Finansal yuvarlama hatası | Kur erken yuvarlanmayacak; hesap `Decimal` ile yapılacak |
| Upstream hatasını başarılı sonuç göstermek | Non-2xx ve standart hata gövdesi dönülecek |
| Test sırasında gerçek internete çıkmak | Sahte upstream kullanılacak |
| Reviewer'ın sahte adresini atlamak | Gerçek host hiçbir yerde sabit kullanılmayacak |

### 4. API sözleşmesini araştırma dokümanından ayırma

Durum: **Tamamlandı**

`FRANKFURTER_API_REPORT.md` içinden yalnızca uygulama için gerekli bilgiler
çıkarılacak:

1. Ana çağrı:
   `GET /v1/{date}?base={from}&symbols={to}`
2. Kullanılacak alanlar:
   `base`, `date`, `rates.{to}`
3. Opsiyonel doğrulama çağrısı:
   `GET /v1/currencies`
4. Upstream hata sınıfları:
   404, 422, 5xx, timeout, bağlantı hatası, JSON/şema hatası
5. Hafta sonu kuralı:
   Upstream'in döndürdüğü gerçek `date`, `rate_date` olarak korunacak

Bu bilgiler uygulamanın veri modellerine, doğrulama kurallarına ve hata eşleme
tablosuna dönüştürülecek. Genel v2 özellikleri Part A koduna taşınmayacak.

Çıktı: `IMPLEMENTATION_DESIGN.md`

### 5. Part A uygulamasını yazma

Durum: **Sıradaki aşama**

- Bağımlılık dosyası oluşturulacak.
- FastAPI uygulaması ve `/tools/convert` endpoint'i yazılacak.
- Query alias kullanılarak dışarıdan tam olarak `from` parametresi alınacak.
- Ortam değişkenleri okunacak.
- Girdi doğrulamaları upstream çağrısından önce yapılacak.
- Timeout ve upstream cevap doğrulaması eklenecek.
- Başarı ve hata modelleri oluşturulacak.
- Tarih duyarlı in-memory cache eklenecek.
- `run.sh` çalışır hale getirilecek.

Kod küçük, okunabilir ve brief kapsamıyla sınırlı tutulacak.

### 6. Uygulamayı ilk kez çalıştırma ve kontrol etme

Kontrol sırası:

1. Uygulamayı `run.sh` ile başlat.
2. Health veya OpenAPI erişimini kontrol et.
3. Geçerli bir conversion isteği gönder.
4. Cevap alanlarını ve hesap sonucunu kontrol et.
5. Aynı isteği tekrar göndererek upstream'in ikinci kez çağrılmadığını doğrula.
6. Hafta sonu isteğinde `asked_date != rate_date` davranışını kontrol et.

Başarılıysa test aşamasına geçilecek.

Başarısızsa:

1. Hata sınıflandırılacak.
2. Brief ve `FRANKFURTER_API_REPORT.md` tekrar kontrol edilecek.
3. Varsayım yerine dokümante edilmiş API davranışı esas alınacak.
4. Kod en küçük gerekli değişiklikle revize edilecek.
5. İlk çalışma kontrolleri yeniden yapılacak.

### 7. Part A otomatik testleri

Tüm testler gerçek ağ kapalıyken çalışmalıdır. En az şu senaryolar test
edilecek:

- Normal başarılı dönüşüm
- Hafta sonu/tatil ve farklı `rate_date`
- Aynı istekte cache kullanımı
- Eksik, sıfır, negatif ve fazla hassasiyetli tutar
- Geçersiz ve aynı para birimi
- Gelecek ve seri öncesi tarih
- Upstream 404, 422 ve 500
- Timeout ve bağlantı hatası
- JSON olmayan cevap
- Eksik veya geçersiz JSON alanları
- Sonucun ve yuvarlamanın doğruluğu

`test.sh`, `FX_UPSTREAM_BASE` kapalı bir porta ayarlansa bile bütün testleri
başarıyla çalıştırmalıdır.

### 8. Part A dokümantasyonu ve son kontrol

- `README.md`: kurulum, çalıştırma, test komutu, endpoint davranışı ve hata
  kodları
- `NOTES.md`: kararlar, sonraki geliştirmeler, kullanılan AI aracı ve AI'nın
  yaptığı somut bir hata veya ayrıca doğrulanan konu
- `run.sh` ve `test.sh`: temiz ortamda yeniden kontrol
- Git diff: gereksiz dosya veya kapsam dışı değişiklik kontrolü

Part A ancak uygulama ve ağsız testler birlikte başarılı olduğunda tamamlanmış
sayılacaktır.

### 9. Part B'yi ayrı değerlendirme

Part A bittikten sonra `tool.py` yeniden, bağımsız biçimde incelenecek.

- Bulgular müşteri zararına göre sıralanacak.
- Her bulgunun etkisi ve doğrulama yöntemi yazılacak.
- Bu gece düzeltilecek tek kritik sorun seçilecek.
- Şüpheli görünüp aslında doğru olan noktalar belirtilecek.
- Sonuç `REVIEW.md` içine yazılacak.

Part B sırasında `tool.py`, Part A çözümünün temeli olarak kullanılmayacak ve
iki görevin kodları birbirine karıştırılmayacaktır.

## Tamamlanma ölçütü

- `./run.sh` servisi doğru portta başlatıyor.
- Endpoint brief ile birebir uyumlu cevap veriyor.
- Yanlış veya uydurma kur hiçbir koşulda başarı olarak dönmüyor.
- Aynı sorgu upstream'e tekrar gitmiyor.
- `./test.sh` internet olmadan geçiyor.
- README bir dakikadan kısa sürede takip edilebiliyor.
- `NOTES.md` ve `REVIEW.md` tamamlanmış durumda.
- Değişiklikler küçük ve anlamlı Git commit'lerine ayrılmış durumda.
