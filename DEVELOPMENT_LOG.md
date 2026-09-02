# Kişisel Geliştirme Günlüğü

Bu belge, case çalışmasının hangi ortamlarda ve hangi doğrulama yaklaşımıyla
ilerlediğini kişisel bir süreç notu olarak kaydeder. Teknik kararların ayrıntılı
gerekçeleri diğer plan ve tasarım belgelerinde yer alır.

## 1. Part A'ya Windows üzerinde başlama

Projenin Part A aşamasına Windows işletim sisteminde başladım. Bu ortamda
`python` komutu kullanılabildiği için ilk uygulama, dokümantasyon ve test
çalışmaları Windows üzerinden yürütüldü.

## 2. İlk uygulamadaki sorunları fark etme

Windows ortamındaki önlemler, ortam farklılıkları ve karşılaşılan hatalar
nedeniyle Codex'in Part A'yı beklediğim güvenilirlikte ve eksiksizlikte
yazamadığını fark ettim. Kodun ve testlerin tamamlandı olarak işaretlenmiş
olması, başka bir ortamda yeniden doğrulanmadan yeterli kabul edilmemeliydi.
Bu nedenle mevcut sonucu doğrudan teslim etmek yerine Part B incelemesindeki
bulguları Part A'ya geri uygulayarak kapsamlı bir revizyon yapmaya karar verdim.

## 3. Ubuntu'ya geçme

Revizyon ve yeniden doğrulama için Ubuntu ortamına geçtim. Bu ortamda
`python3` mevcut olsa da `python` komutu ve proje bağımlılıkları sistem
genelinde hazır değildi. İlk `./test.sh` denemesi bu nedenle testleri
başlatamadan `python: command not found` hatası verdi. Bu sonuç bir uygulama
testi başarısızlığı değil, çalıştırma ortamı ve script taşınabilirliği
problemidir; yine de teslimatın temiz Ubuntu ortamında doğrudan
çalışmadığını göstermiştir.

## 4. İzole sanal ortam kurma

Sistem Python kurulumunu değiştirmemek ve bağımlılıkları tekrarlanabilir
biçimde izole etmek için depo kökünde `.venv` oluşturdum:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

`.venv` zaten `.gitignore` kapsamındadır; kişisel makinede kalır ve depoya
eklenmez.

## 5. Bundan sonraki çalışma biçimi

Ubuntu üzerindeki uygulama ve test komutlarını proje sanal ortamıyla
çalıştıracağım:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8080
```

Scriptlerin yalnızca aktif edilmiş bir sanal ortama veya Windows'taki
`python` adına bağlı kalmaması da Part A revizyonunda ayrıca ele alınacaktır.
Her anlamlı revizyon test edilecek, ayrı commitlenecek ve pushlanacaktır.
