# Türk Lirası Referans Görselleri

Pingulacore görsel üretim pipeline'ı, YAML'da `context.generation.real_currency: true` bayrağı işaretlenmiş sorularda Gemini image modeline bu klasördeki PNG'leri **referans görsel** olarak gönderir. Amaç: "Türk Lirası ve Kuruşlarımızı Tanıyalım" kazanımı gibi tanıma gerektiren sorularda Atatürk portresi, rakam yerleşimi, renk kodu ve madeni para tasarımının gerçek TL ile birebir eşleşmesini sağlamak.

## Klasör içeriği

```
assets/turk_lirasi/
  README.md
  manifest.yaml
  banknotlar/
    5_tl.png
    10_tl.png
    20_tl.png
    50_tl.png
    100_tl.png
    200_tl.png
  madeni_paralar/
    1_kurus.png
    5_kurus.png
    10_kurus.png
    25_kurus.png
    50_kurus.png
    1_tl.png
```

## Dosya gereksinimleri

Her PNG için:

- **Format**: PNG, RGBA (şeffaf alfa kanalı)
- **Arka plan**: Tam şeffaf. Beyaz, gri veya başka bir düz renk **olmamalı**. Sadece paranın kendisi görünür, kenarlar çevresinde halo/gölge/gradient olmadan temiz kesilmiş olmalı.
- **İçerik**: Sadece paranın **ön yüzü**. Arka yüz bu sürümde kapsam dışı.
- **Yön**: Banknotlar yatay, madeni paralar tam dairesel (eğik değil).
- **Çözünürlük**: Kısa kenar en az **600 px**. 1200 px tercih edilir. Upsampling yapılmış bulanık görüntü kabul edilmez.
- **Dosya adı**: Tam olarak yukarıdaki listedeki gibi (küçük harf, alt çizgi, `.png` uzantısı).

## Kaynak önerileri

TCMB resmi banknot görselleri (https://www.tcmb.gov.tr) iyi başlangıç noktasıdır. PDF'den veya web'den alınan görselleri bir görüntü editöründe (Photoshop, GIMP, Affinity) açıp:

1. Arka planı tamamen sil (magic wand + delete).
2. Şeffaflığı koru (Export as PNG → Transparent background).
3. Dosya adını bu README'deki listeye göre ayarla.

Kendi taramanı kullanıyorsan, paranın etrafındaki beyaz kağıt kenarını kesmen kritik — yoksa model o beyaz dikdörtgeni de kopyalar.

## Doğrulama

Asset klasörünü doldurduktan sonra:

```bash
python scripts/verify_tl_assets.py
```

Bu script şunları kontrol eder:
- Manifest'te listelenen her dosya fiziksel olarak mevcut mu
- Her PNG RGBA mı (şeffaf alfa kanalı var mı)
- Kısa kenar ≥600 px mi
- Manifest ID'leri ile dosya yolları tutarlı mı

Eksik veya hatalı dosyalar tek tek listelenir.

## Önemli

- `manifest.yaml`'ın yapısını değiştirme — kod bu formata göre parse ediyor.
- Bir dosyayı eklemeyi unutursan ve YAML'da `real_currency: true` işaretliyse pipeline `CurrencyAssetError` ile fail-fast durur. `scripts/verify_tl_assets.py`'yi önce çalıştır.
- Para tasarımı TCMB tarafından değiştirilirse (yeni seri) buradaki dosyaları güncellemek yeterli; kod tarafı aynı kalır.
