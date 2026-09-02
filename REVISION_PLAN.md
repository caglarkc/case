# Part A Tam Kapsamlı Revizyon Planı

Bu plan, 2 Eylül 2026 tarihinde tüm depo belgeleri, ilk brief, commit geçmişi,
Part B'deki `tool.py` incelemesi ve mevcut Part A kodu yeniden incelendikten
sonra hazırlanmıştır. Amaç yalnızca mevcut testleri geçirmek değil, Part B'de
tanımlanan müşteri risklerinin Part A'da gerçekten kapatıldığını kanıtlamaktır.

## İncelenen kaynaklar

- İlk brief ve başlangıç dosyaları (`7cff11b` commit'i)
- `PROJECT_PLAN.md`, `IMPLEMENTATION_DESIGN.md` ve
  `FRANKFURTER_API_REPORT.md`
- Part B bulguları ve ek revizyon önerileri (`REVIEW.md`)
- Part A uygulaması, scriptleri, testleri ve kullanıcı dokümantasyonu
- Tüm commit geçmişi ve mevcut `main` / `origin/main` durumu

## Baz çizgi sonucu

Ubuntu üzerinde depo kökünde `.venv` oluşturuldu ve bağımlılıklar
`requirements.txt` üzerinden kuruldu.

| Kontrol | Beklenen | Mevcut sonuç | Durum |
|---|---|---|---|
| `./test.sh` temiz Ubuntu ortamında | Testleri başlatmalı | `python` bulunamadığı için başlamıyor | Başarısız |
| `.venv/bin/python -m pytest -q` | Tüm testler geçmeli | 40 test geçiyor | Başarılı ama yetersiz kapsam |
| OpenAPI 200 şeması | Alanları tanımlı cevap sözleşmesi | Serbest `object` | Eksik |
| Büyük ama kurala uygun tutar | Aynı tutar korunmalı | `9999999999999999.99`, `1e+16` oluyor | Başarısız |
| Upstream kur alanının türü | Yalnız JSON number kabul edilmeli | `"1.25"` string'i kabul ediliyor | Başarısız |
| Aşırı büyük upstream kur | Kontrollü 502 | Genel 500 | Başarısız |
| Tam üç harfli para kodu | Boşluklu değer reddedilmeli | `" EUR "` kabul ediliyor | Başarısız |

Bu nedenle `PROJECT_PLAN.md` içindeki eski “Part A tamamlandı” kaydı artık
nihai durum olarak kabul edilmeyecektir.

## Part B bulgularının Part A karşılığı

| Part B revizyonu | Part A'daki mevcut durum | Yapılacak revizyon |
|---|---|---|
| Açık public sözleşme, alias ve ortam ayarı | Alias ve zorunlu alanlar var; cevap modeli ve tam OpenAPI hata sözleşmesi yok | Query/cevap/hata modellerini açıklaştır, gerçek host ayarının uçtan uca kullanıldığını test et |
| Tarih ve cache provenance doğruluğu | Tarih anahtara dahil, upstream tarihi korunuyor | Eşzamanlı aynı cache miss'lerini birleştir; hiçbir `/latest` çağrısı olmadığını ayrıca kanıtla |
| Hataların sahte başarıya çevrilmemesi | Ana hata sınıfları non-2xx | Şema/arithmetic uçlarını da kontrollü hataya dönüştür; her hata yolunda başarı şemasını yasakla |
| Decimal ve input doğruluğu | Hesap Decimal; JSON sınırında `float` hassasiyet kaybediyor | Wire formatında sayısal değeri bozmadan koru, katı para kodu ve tutar sınırlarını test et |
| HTTP yaşam döngüsü ve şema doğrulaması | Lifespan ve timeout var; upstream tür doğrulaması gevşek | Strict upstream model/doğrulama, güvenli sayı sınırları ve tüm istemci yaşam döngüsü testleri ekle |

## Uygulama aşamaları ve commit kapıları

### R0 — Ortam geçmişi

Durum: **Tamamlandı** (`cf242a3`)

- Windows'tan Ubuntu'ya geçiş ve `.venv` kullanımı kişisel geliştirme günlüğüne
  yazıldı.

### R1 — Plan ve kanıtlanmış açıkların kaydı

Durum: **Tamamlandı** (`2544de4`)

- Bu ana revizyon planı eklenecek.
- Eski proje planında Part A yeniden “revizyonda” olarak işaretlenecek.
- Commit öncesi Markdown diff ve çalışma ağacı kontrol edilecek.

### R2 — Taşınabilir çalıştırma ve yapılandırma

Durum: **Tamamlandı**

- `run.sh` ve `test.sh`, depo içindeki `.venv` yorumlayıcısını tercih edecek;
  yoksa kullanılabilir `python3` / `python` yorumlayıcısına güvenli biçimde
  düşecek.
- Scriptler farklı çalışma dizininden çağrıldığında da depo kökünü doğru
  bulacak.
- `FX_UPSTREAM_BASE` ve `PORT` kullanımının gerçek process sınırında çalıştığı
  test edilecek.

### R3 — Public API sözleşmesi ve kayıpsız finansal çıktı

Durum: **Bekliyor**

- Query alanları ve dış alias'lar açık bir sözleşmeye bağlanacak.
- Başarı ve hata cevap modelleri eklenecek; OpenAPI gerçek alanları ve hata
  gövdelerini gösterecek.
- Para kodu yalnızca üç ASCII harf kabul edecek, küçük harf büyük harfe
  çevrilecek fakat gizli boşluklar onarılmayacak.
- Tutar ve sonuç Decimal ile hesaplanacak ve JSON number olarak değer
  kaybetmeden yazılacak; string veya binary-float kaynaklı sessiz yuvarlama
  yapılmayacak.

### R4 — Strict upstream güven sınırı

Durum: **Bekliyor**

- HTTP status, JSON nesne yapısı, `base`, `date`, hedef alanı ve kur türü katı
  biçimde doğrulanacak.
- String, boolean, sıfır, negatif, non-finite ve güvenli hesap/cevap sınırını
  aşan kurlar reddedilecek.
- JSON sayıları metinden Decimal'a hassasiyet kaybetmeden ayrıştırılacak.
- Doğrulama veya hesap sınırı hataları güvenli
  `invalid_upstream_response`/502 cevabına dönüşecek.

### R5 — Cache ve eşzamanlı istek güvenilirliği

Durum: **Bekliyor**

- Cache anahtarı `(from, to, asked_date)` ve değer provenance'ı korunacak.
- Aynı anahtar için eşzamanlı cache miss'leri tek upstream isteğinde
  birleştirilecek.
- Başarısız görevlerin cache'e girmediği ve sonraki isteğin yeniden denediği
  doğrulanacak.
- LRU sınırı ve tarih/kur çifti izolasyonu korunacak.

### R6 — Eksik otomatik testlerin tamamlanması

Durum: **Bekliyor**

- Büyük tutar hassasiyeti, strict upstream sayıları, OpenAPI sözleşmesi,
  eşzamanlı cache, `/latest` yasağı ve script taşınabilirliği için regresyon
  testleri eklenecek.
- Her Part B bulgusu en az bir pozitif ve/veya negatif testle eşlenecek.
- `FX_UPSTREAM_BASE` kapalı porta ayarlıyken tüm unit/contract testleri dış ağa
  çıkmadan geçecek.

### R7 — Kullanıcı dokümantasyonu ve planların senkronizasyonu

Durum: **Bekliyor**

- README komutları Ubuntu, Windows ve aktif/pasif `.venv` açısından açık hale
  getirilecek.
- Gerçek doğrulama kuralları, hata kodları ve cache davranışı kodla birebir
  eşlenecek.
- `NOTES.md`, `IMPLEMENTATION_DESIGN.md` ve `PROJECT_PLAN.md` nihai uygulamayla
  senkronize edilecek; tamamlanmayan hiçbir iş tamamlandı gösterilmeyecek.

### R8 — Process-seviyesi kabul testi ve final raporu

Durum: **Bekliyor**

- Sahte upstream ve `run.sh` ile gerçek process sınırını kullanan ek bir kabul
  testi oluşturulacak.
- Bu test başarı, gerçek `rate_date`, cache, hata gövdesi, fake upstream
  yönlendirmesi ve port ayarını birlikte sınayacak.
- `ACCEPTANCE_REPORT.md` içinde her madde için “beklenen” ve “oluşturulan”
  sonuçları, çalıştırılan komutları ve test sayılarını raporlayacak.
- Son kapıda unit/contract, process kabul testi, derleme kontrolü, diff kontrolü
  ve temiz Git durumu birlikte doğrulanacak.

## Her revizyon için zorunlu akış

1. Yalnız o aşamanın kapsamındaki değişikliği yap.
2. İlgili dar testleri çalıştır.
3. Tam offline test takımını çalıştır.
4. `git diff --check` ve diff incelemesi yap.
5. Tek anlamlı conventional commit oluştur.
6. Commit'i hemen `origin/main` dalına pushla.
7. Push başarısızsa sonraki revizyona geçmeden nedeni gider veya açıkça
   raporla.

## Nihai tamamlanma ölçütü

Part A ancak tüm R aşamaları tamamlandığında; dış ağ kapalı testler, gerçek
process kabul testi ve beklenen/oluşturulan raporu birlikte başarılı olduğunda
yeniden “tamamlandı” olarak işaretlenecektir. Mevcut testlerin yalnızca geçiyor
olması tek başına yeterli değildir.
