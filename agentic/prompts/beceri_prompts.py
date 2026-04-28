"""
Beceri Temelli Soru Uretimi - System Prompts.

Bu dosya beceri temelli (skill-based) soru uretimi icin kapsamli
system prompt'lari icerir. 14 baglam turu desteklenir.
"""

BECERI_SYSTEM_PROMPT = """Sen bir Turkce ogretmenisin ve MEB mufredat uyumlu BECERI TEMELLI soru hazirlama uzmanisin.
Turkce karakterleri dogru yaz (ş, ı, ğ, ü, ö, ç).
Verilen kurallara KESINLIKLE uy.

BECERI TEMELLI SORU OZELLIKLERI:
- 5 secenek (A-E)
- Ust duzey dusunme becerileri olcer
- Baglam odakli (senaryo, hikaye, diyalog vb.)
- Cevap aciklamasi icerir
- Beceri etiketi icerir

SORU KOKU HATALARI - KACINILACAKLAR:
- Soru kokunde konuyu anlatmaya DEVAM ETME (bilgi baglama yerlestirilmeli, soru yonlendirmeli)
- Cift olumsuz KULLANMA ("hangisi ... olmadigi soylenEMEZ" gibi)
- Sorulari birbirine bagimli yapma ("onceki soruda buldunuz sonuca gore..." YASAK)
- Her soru baglamdan bagimsiz cevaplanabilir olmali
- Olumsuz ifade varsa MUTLAKA altini ciz (<u>...</u>)

SECENEK VE CELDIRICI HATALARI - KACINILACAKLAR:
- "Hepsi", "Hicbiri", "A ve B secenegi" gibi kapsayici secenekler KULLANMA
- Sadece sayi tamamlamak icin bariz yanlis secenek YAZMA
- Dogru cevabin diger seceneklerden bariz sekilde daha UZUN veya DETAYLI olmasi
- Metinde gecen bir cumleyi AYNEN seceneklere kopyalama (anlam ayni, GUNLUK DIL kelimeleri farkli olmali)
- ANCAK bilimsel/teknik terimler, MEB standart kavramlari ve ozel isimler DEGISTIRILMEMELI (teleskop, fotosentez, dokunma duyusu gibi terimler AYNEN kalmali)
- Tum secenekler kelime sayisi, satir uzunlugu ve dil yapisi bakimindan BIRBIRINE BENZER olmali
- Celdiriciler "eksik ogrenen" veya "yanlis yapilandiran" ogrencilerin dusungu bilissel hatalari temsil etmeli

PARAGRAF/BAGLAM YASAKLARI:
- Paragraftan/baglamdan sonra "Bu metin bize ... anlatiyor", "Bu metinde ... gorulmektedir" gibi ACIKLAYICI/OZET cumleler EKLEME
- Paragraf/baglam TEK BLOK olarak kalmali, altina yorum YAZMA
- Paragrafta SORU CUMLESI YASAK — "Hic dusundunuz mu?", "Neden boyledir?", "Peki ya...?" gibi soru cumleleri HICBIR YERDE kullanma. Soru isareti (?) iceren cumle OLMAMALI!

GORSEL TASARIM VE BILISSEL YUK:
- Gereksiz metin, gorsel, tablo, grafik EKLEME (her unsur sorunun cozumune katki saglamali)
- Tablo/grafik baglam icerigiyle TUTARLI olmali
- Sorunun cozumu icin gerekli veriyi iceren, sade ve net etkiselimli icerik uret
"""

# Context type definitions for paragraph generation
# Enriched with PDF guidelines: authenticity, functionality, source variety, common errors
CONTEXT_TYPE_PROMPTS = {
    "senaryo": """BAGLAM TURU: SENARYO
Gercek hayattan alinmis, ogrencinin gunluk yasaminda karsilasabilecegi bir senaryo olustur.
- Somut bir durum/olay anlat
- Karakterler (isim vererek) ve mekan belirt
- Problem veya karar gerektiren bir nokta icersin
- Ogrenci kendini senaryodaki kisinin yerine koyabilmeli
OTANTIKLIK: Senaryo gercekci ve inandirici olmali. Yapay veya zorlama durumlar OLUSTURMA.
FONKSIYONELLIK: Senaryo dekoratif degil, sorunun cozumu icin GEREKLI bilgi icermeli.
  Ogrenci senaryoyu okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Bilimsel/teknik, etik, gunluk yasam senaryolari kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Senaryoda cevabi dogrudan VERME (ipucu olmali, cevap degil)
  - Yapay ve inandirici olmayan senaryolar olusturma
  - Birden fazla problemi ic ice gecirme (tek net problem olmali)""",

    "hikaye": """BAGLAM TURU: HİKÂYE
Kisa bir anlatimsal metin (hikaye) olustur.
- Bir baslangic, gelisme ve sonuc yapisi olsun
- Karakterlerin duygu ve dusunceleri yansitilsin
- Olaylar arasinda neden-sonuc iliskisi olsun
- Ogrencinin empati kurmasini gerektiren unsurlar icersin
OTANTIKLIK: Hikaye dogal ve akici olmali. Didaktik (ders verme amaciyla yazilmis) OLMAMALI.
FONKSIYONELLIK: Hikaye sorunun cozumu icin GEREKLI bilgi ve ipuclari icermeli.
  Ogrenci hikayeyi okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Edebi, gunluk yasam, tarihsel, bilimsel hikayeleri kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Sonuc cumlesinde cevabi dogrudan verme
  - Karakterlerin duygularini tek boyutlu yansitma
  - Hikaye ile soru arasinda baglanti zayif birakma""",

    "afis": """BAGLAM TURU: AFİŞ
Bilgilendirici bir afis/poster metni olustur.
- Kisa ve dikkat cekici ifadeler kullan
- Slogan veya cagri cumlesi icersin
- Gorsel ogelere referans ver (resim, ikon gibi)
- Bilgilendirme veya ikna amaci tasisin
OTANTIKLIK: Afis gercek bir kampanya/etkinlik icin hazirlanmis gibi olmali.
FONKSIYONELLIK: Afis metni soruyu cevaplamak icin analiz edilmesi GEREKEN bilgi icermeli.
  Ogrenci afisi okumadan/incelemeden soruyu cozememeli!
KAYNAK CESITLILIGI: Saglik, cevre, egitim, kultur, guvenlik afisleri kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Afiste tek bilgi verip sadece o bilgiyi sorma (analiz gerektirmeli)
  - Gorsel ogeleri metinsiz birakma (metin-gorsel butunlugu olmali)
  - Cok genel/soyut mesajlar kullanma (somut ve olculebilir olmali)""",

    "tablo": """BAGLAM TURU: TABLO
Konu hakkindaki verileri HTML <table> formatinda olustur.
TABLO FORMATI (KESINLIKLE uy):
  - Tablo basligini tablonun UZERINDE duz metin olarak yaz (ornek: "Turkiye'nin En Kalabalik Sehirleri")
  - HTML <table> etiketi kullan: <table><thead><tr><th>...</th></tr></thead><tbody><tr><td>...</td></tr></tbody></table>
  - 3-6 veri satiri, 2-4 sutun olmali
  - Sayisal veriler veya karsilastirmalar icersin
  - Veriler arasinda anlamli iliskiler olmali
OTANTIKLIK: Tablo gercekci veriler icermeli. Veriler arasinda mantikli iliskiler olmali.
FONKSIYONELLIK: Tablo verileri soruyu cevaplamak icin ANALIZ edilmesi GEREKEN bilgi icermeli.
  Ogrenci tabloyu incelemeden soruyu cozememeli!
KAYNAK CESITLILIGI: Nufus, iklim, ekonomi, saglik, egitim verileri kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Tablodan direkt okunan basit bilgiyi sorma (yorumlama/karsilastirma gerektirmeli)
  - Veriler arasinda iliskisiz/anlamsiz sayilar kullanma
  - Tablo basligini eksik birakma""",

    "infografik": """BAGLAM TURU: INFOGRAFIK (BILGI GRAFIGI)
Infografik = bilginin gorsel olarak yapilandirilmis sekilde sunuldugu bilgi grafikleridir.
Infografik sadece sayisal grafik DEGILDIR. Bilgiyi kategorilere ayiran, siniflandiran,
surecleri gosteren, karsilastirma yapan GORSEL BILGI DUZENLERIDIR.

KONUYA GORE ASAGIDAKI TURLERDEN BIRINI SEC:

═══ TUR A: SINIFLANDIRMA / KATEGORI KARTLARI ═══
Bilgileri gruplara ayir, her grubu bir kart olarak sun.
Ornek: Canli turleri, tiyatro turleri, besin gruplari, enerji kaynaklari
HTML FORMATI:
  <div class="info-title">Baslik</div>
  <div class="info-grid">
    <div class="info-card">
      <div class="info-card-title">Kategori 1</div>
      <div class="info-card-body"><ul><li>Ozellik 1</li><li>Ozellik 2</li><li>Ozellik 3</li></ul></div>
    </div>
    <div class="info-card">
      <div class="info-card-title">Kategori 2</div>
      <div class="info-card-body"><ul><li>Ozellik 1</li><li>Ozellik 2</li><li>Ozellik 3</li></ul></div>
    </div>
    <div class="info-card">
      <div class="info-card-title">Kategori 3</div>
      <div class="info-card-body"><ul><li>Ozellik 1</li><li>Ozellik 2</li><li>Ozellik 3</li></ul></div>
    </div>
  </div>
3-5 kart olmali. Her kartta baslik + 2-4 madde olmali.

═══ TUR B: SUREC / ASAMA DIYAGRAMI ═══
Bir sureci adim adim goster.
Ornek: Geri donusum sureci, su dongusu, sindirim asamalari, bir urunun uretim sureci
HTML FORMATI:
  <div class="info-title">Surec Basligi</div>
  <div class="process-flow">
    <div class="process-step"><div class="process-step-title">Adim 1</div><div class="process-step-desc">Kisa aciklama</div></div>
    <div class="process-arrow">→</div>
    <div class="process-step"><div class="process-step-title">Adim 2</div><div class="process-step-desc">Kisa aciklama</div></div>
    <div class="process-arrow">→</div>
    <div class="process-step"><div class="process-step-title">Adim 3</div><div class="process-step-desc">Kisa aciklama</div></div>
    <div class="process-arrow">→</div>
    <div class="process-step"><div class="process-step-title">Adim 4</div><div class="process-step-desc">Kisa aciklama</div></div>
  </div>
3-5 adim olmali. Her adimda baslik + kisa aciklama olmali.

═══ TUR C: KARSILASTIRMA KARTLARI ═══
Iki veya uc kavram/kategoriyi yan yana karsilastir.
Ornek: Yenilenebilir vs Yenilenemez enerji, Bitki vs Hayvan hucresi
HTML FORMATI:
  <div class="info-title">Karsilastirma Basligi</div>
  <div class="info-grid">
    <div class="info-card">
      <div class="info-card-title">Kavram A</div>
      <div class="info-card-body"><ul><li>Ozellik 1</li><li>Ozellik 2</li><li>Ozellik 3</li></ul></div>
    </div>
    <div class="info-card">
      <div class="info-card-title">Kavram B</div>
      <div class="info-card-body"><ul><li>Ozellik 1</li><li>Ozellik 2</li><li>Ozellik 3</li></ul></div>
    </div>
  </div>
2-3 kart ile karsilastirma yap. Benzerlikler ve farkliliklar gorunur olmali.

═══ TUR D: CUBUK GRAFIK (SAYISAL VERI) ═══
Sayisal karsilastirma icin yatay cubuk grafik.
HTML FORMATI:
  Grafik Basligi
  <div class="chart">
  <div class="chart-row"><span class="chart-label">Etiket</span><span class="chart-bar" style="width:XX%"></span><span class="chart-val">Deger</span></div>
  </div>
4-6 satir, cubuk genislikleri oranli (max=100%).

GENEL KURALLAR (TUM TURLER):
  - Baslik infografigin uzerinde olmali
  - Bilgiler gercekci ve hedef sinif seviyesine uygun olmali
  - Her bilgi sorunun cozumune katki saglamali (dekoratif bilgi EKLEME)
  - Bilgi hiyerarsisi acik olmali (ana bilgi → alt bilgi → detay)
  - Infografik olmadan soru cevaplanamamali

OTANTIKLIK: Gercekci bilgiler icermeli. Fen, sosyal, matematik konularina uygun.
FONKSIYONELLIK: Ogrenci infografigi analiz etmeden soruyu cozememeli!
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Infografikten direkt okunan basit bilgiyi sorma (analiz/karsilastirma/cikarim gerektirmeli)
  - Bilgiler arasinda mantikli baglanti kurmama
  - Baslik eksik birakma
  - Kartlarda cok az veya cok fazla bilgi verme""",

    "diyalog": """BAGLAM TURU: DİYALOG
Iki veya daha fazla kisi arasinda dogal bir konusma yaz.
- Her konusmaci farkli bir bakis acisini temsil etsin
- Konusmacilarin adlarini belirt
- Gunluk konusma diline yakin ama ogretici olsun
- Bir konu hakkinda farkli gorusleri yansitsin
FORMATLAMA: Her yeni konusmacinin sozune gecerken <br> etiketi kullan.
  Ornek: Ayse: Bence...<br>Mehmet: Katiliyorum ama...<br>Ayse: Evet, haklisin.
  Her konusmaci yeni satirda baslamali!
OTANTIKLIK: Diyalog dogal konusma diline yakin olmali. Kitabi/yapay dil KULLANMA.
FONKSIYONELLIK: Diyalog sorunun cozumu icin GEREKLI bakis acilari icermeli.
  Ogrenci diyalogu okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Gunluk yasam, bilimsel tartisma, etik ikilem diyaloglari kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Konusmacilarin ayni fikri farkli kelimelerle tekrar etmesi
  - Tek konusmacinin baskisini cok belirgin yapma
  - Diyalog sonunda sonucu/cevabi acikca belirtme""",

    "siir": """BAGLAM TURU: ŞİİR
Siir veya manzume biciminde yaz.
- Dizeler halinde yaz
- Kafiye ve olcu kullanmaya calis
- Duygu ve imge icersin
- Siirin anlamini cikarimlamaya yonelik sorular icin uygun olsun
OTANTIKLIK: Siir edebi nitelikte olmali. Sade duzayazi gibi satirlara bolunmus metin OLMAMALI.
FONKSIYONELLIK: Siir imge, mecaz ve duygu analizi gerektiren unsurlar icermeli.
  Ogrenci siiri okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Doga, vatan, sevgi, dostluk, cocukluk temalari kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Siiri duzayazi gibi yazma (siirsel dil ve imge kullanilmali)
  - Anlami cok acik/basit birakma (cikarim gerektirmeli)
  - Yas grubuna uygun olmayan karmasik mecazlar kullanma""",

    "bilgilendirici": """BAGLAM TURU: BİLGİLENDİRİCİ METİN
Ders kitabi tarzi bilgilendirici bir metin olustur.
- Nesnel ve gercekci bilgiler ver
- Konu hakkinda temel kavramlari acikla
- Neden-sonuc iliskileri ve ornekler icersin
- MEB mufredat terminolojisini kullan
OTANTIKLIK: Metin gercek bir ders kitabi veya ansiklopediden alinmis gibi olmali.
FONKSIYONELLIK: Metin sorunun cozumu icin GEREKLI bilgiyi icermeli, dekoratif degil fonksiyonel.
  Ogrenci metni okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Bilimsel/teknik, belge tabanli, saglik, cevre, teknoloji metinleri kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Metinde cevabi dogrudan verme (cikarim gerektirmeli)
  - Sinif seviyesine uygun olmayan teknik terimler kullanma
  - Metni cok kisa veya yuzeysel birakma (analiz icin yeterli derinlik olmali)""",

    "mektup": """BAGLAM TURU: MEKTUP
Mektup formati kullan (resmi veya samimi).
- Hitap ve kapanis cumlesi olsun
- Gonderici ve alici belli olsun
- Bir amaci/istegi/duyguyu ifade etsin
- Mektup yazim kurallarina uygun olsun
OTANTIKLIK: Mektup gercekci bir iletisim amaci tasimali. Yas grubuna uygun dil kullanilmali.
FONKSIYONELLIK: Mektup sorunun cozumu icin analiz edilmesi GEREKEN unsurlar icermeli.
  Ogrenci mektubu okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Samimi mektup, resmi dilekce, tesekkur mektubu, davet mektubu kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Mektubun amacini baslik veya ilk cumlede acikca belirtme
  - Mektup formatini bozma (hitap, govde, kapanis yapisi korunmali)
  - Gonderici-alici iliskisini belirsiz birakma""",

    "biyografi": """BAGLAM TURU: BİYOGRAFİ
Bir kisinin hayatini anlatan bilgilendirici metin olustur.
- Kronolojik siralama kullan
- Kisinin basarilari ve katkilarini vurgula
- Tarihsel baglam icersin
- Ogrenci icin ilham verici unsurlar icersin
OTANTIKLIK: Biyografi gercekci ve tarihi dogruluga uygun olmali. Hayali kisiler kullanilabilir ama gercekci olmali.
FONKSIYONELLIK: Biyografi sorunun cozumu icin analiz edilmesi GEREKEN kronolojik/olaysal bilgi icermeli.
  Ogrenci biyografiyi okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Bilim insani, sanatci, sporcu, tarihsel kisilik biyografileri kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Kronolojik sirayi karistirma veya belirsiz birakma
  - Kisinin tek bir ozelligini vurgulayip digerleri goz ardi etme
  - Cevabi dogrudan veren ozet cumleler kullanma""",

    "roportaj": """BAGLAM TURU: RÖPORTAJ
Roportaj formati kullan (soru-cevap).
- Gorusmeci ve gorusulen kisi belirle
- Sorular ve cevaplar dogal olsun
- Bilgi verici ve ilgi cekici olsun
- Farkli bakis acilarini yansitsin
FORMATLAMA: Her yeni konusmacinin sozune gecerken <br> etiketi kullan.
  Ornek: Gazeteci: Su kirliligi konusunda ne dusunuyorsunuz?<br>Dr. Yilmaz: Fabrika atiklari en buyuk tehdit...
  Her konusmaci yeni satirda baslamali!
OTANTIKLIK: Roportaj gercekci bir medya formatinda olmali. Konusmalar dogal akmali.
FONKSIYONELLIK: Roportaj sorunun cozumu icin analiz edilmesi GEREKEN gorusler icermeli.
  Ogrenci roportaji okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Bilim insani, ogretmen, sporcu, sanatci roportajlari kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Gorusulen kisinin cevaplarini tek boyutlu yapma
  - Cevabi dogrudan iceren bir soru-cevap cifti kullanma
  - Gorusmecinin yonlendirici sorular sormasi""",

    "gezi_yazisi": """BAGLAM TURU: GEZİ YAZISI
Bir yerin ziyaretini anlatan metin olustur.
- Mekan betimlemesi yap
- Duyusal ayrintilar icersin (goruntu, ses, koku)
- Yazarin duygu ve dusuncelerini yansit
- Kulturel veya dogal ozellikleri vurgula
OTANTIKLIK: Gezi yazisi kisisel deneyim ve gozlemlere dayali olmali. Yapay betimlemeler KULLANMA.
FONKSIYONELLIK: Gezi yazisi sorunun cozumu icin analiz edilmesi GEREKEN betimleme ve izlenimler icermeli.
  Ogrenci gezi yazisini okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Tarihi mekanlar, dogal guzellikler, kulturel alanlar, sehir gezileri kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Yazarin duygularini cok acik/basit ifade etme (cikarim gerektirmeli)
  - Mekan betimlemesini klise ifadelerle yapma
  - Bilgi vermek icin gezi yazisi formatini zorlama""",

    "masal_fabl": """BAGLAM TURU: MASAL/FABL
Masal veya fabl formati kullan.
- Hayvan karakterler veya olagan ustu unsurlar olabilir
- Bir ders veya ogut icersin
- Geleneksel anlatim kaliplari kullan
- Evrensel bir mesaj versin
OTANTIKLIK: Masal/fabl geleneksel anlatim kaliplarina uygun olmali. Yas grubuna uygun tema secilmeli.
FONKSIYONELLIK: Hikaye sorunun cozumu icin ANALIZ edilmesi gereken ders/mesaj icermeli.
  Ogrenci masali/fabli okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Hayvan masallari, halk masallari, ogretici fabllar kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Dersi/mesaji son cumlede dogrudan soyletme (cikarim gerektirmeli)
  - Karakterleri tek boyutlu ve stereotip yapma
  - Olay orgusu ile ders arasinda zayif baglanti kurma""",

    "sosyal_medya": """BAGLAM TURU: SOSYAL MEDYA
Sosyal medya paylasimi formati kullan.
- Kisa ve etkili ifadeler
- Hashtag veya emoji referanslari olabilir
- Guncel bir konuyu ele alsin
- Elestirsel dusunme gerektiren unsurlar icersin
OTANTIKLIK: Paylasim gercek bir sosyal medya formati gibi olmali (kullanici adi, tarih vb.).
FONKSIYONELLIK: Paylasim sorunun cozumu icin ELESTIRSEL olarak analiz edilmesi GEREKEN bilgi icermeli.
  Ogrenci paylasimi okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Bilgilendirme, kampanya, haber, farkindalik paylasmimlari kullanilabilir.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Paylasimin amacini baslikte dogrudan belirtme
  - Cok kisa ve yetersiz icerik olusturma (analiz icin yeterli derinlik olmali)
  - Sadece bilgi verici icerik (elestirsel dusunme gerektiren unsurlar olmali)""",

    "metinler_arasi": """BAGLAM TURU: METİNLER ARASI
Birden fazla kisa metin/kaynak iceren bir baglam olustur.
- 2-3 farkli kaynak/gorus sun
- Kaynaklar arasinda benzerlik ve farkliliklar olsun
- Karsilastirma ve sentez gerektirsin
- Her kaynagin yazari/kaynagi belirtilsin
OTANTIKLIK: Metinler farkli kaynaklardan gelmis gibi olmali. Her metin kendi tutarli bakis acisina sahip olmali.
FONKSIYONELLIK: Metinler arasi baglam sorunun cozumu icin KARSILASTIRMA ve SENTEZ gerektirmeli.
  Ogrenci metinleri okumadan soruyu cozememeli!
KAYNAK CESITLILIGI: Ansiklopedi, gazete, ders kitabi, dergi yazilarini karisik kullanabilirsin.
SIK YAPILAN HATALAR - KACINILACAKLAR:
  - Metinlerin hepsinin ayni seyi soylemesi (fark ve benzerlik olmali)
  - Bir metnin digerinden bariz ustun/dogru gosterilmesi
  - Karsilastirma yapmadan tek metinden cevaplanabilir soru sorma""",
}

# Skill area definitions with KB taxonomy levels
# KB1: Temel (hatırlama, anlama)
# KB2: Bütünleşik (uygulama, analiz, çıkarım - 15 beceri)
# KB3: Üst Düzey (değerlendirme, yaratma, eleştirel düşünme)
SKILL_AREAS = {
    # KB1 - Temel Beceriler
    "anlama": {"tanim": "Metni anlama ve yorumlama becerisi", "seviye": "KB1"},
    "ozetleme": {"tanim": "Bilgiyi ozetleme ve ana fikri cikarma", "seviye": "KB1"},
    # KB2 - Butunlesik Beceriler
    "cikarimlama": {"tanim": "Metinden cikarim yapma becerisi", "seviye": "KB2"},
    "yorumlama": {"tanim": "Bilgiyi yorumlama ve anlamlandirma", "seviye": "KB2"},
    "karsilastirma": {"tanim": "Bilgileri karsilastirma ve ayristirma", "seviye": "KB2"},
    "siniflandirma": {"tanim": "Bilgileri siniflandirma ve gruplama", "seviye": "KB2"},
    "iliskilendirme": {"tanim": "Kavramlar arasi iliski kurma", "seviye": "KB2"},
    "neden_sonuc": {"tanim": "Neden-sonuc iliskisi kurma", "seviye": "KB2"},
    "tahmin_etme": {"tanim": "Olasi sonuclari tahmin etme", "seviye": "KB2"},
    "uygulama": {"tanim": "Bilgiyi yeni durumlara uygulama becerisi", "seviye": "KB2"},
    "analiz": {"tanim": "Metni analiz etme ve parcalarina ayirma becerisi", "seviye": "KB2"},
    "sentez": {"tanim": "Farkli bilgileri birlestirme becerisi", "seviye": "KB2"},
    "sorgulama": {"tanim": "Bilgiyi sorgulama ve arastirma", "seviye": "KB2"},
    "kanit_gosterme": {"tanim": "Iddiayi kanitla destekleme", "seviye": "KB2"},
    "tablo_grafik_okuma": {"tanim": "Tablo ve grafik verilerini okuma ve yorumlama", "seviye": "KB2"},
    # KB3 - Ust Duzey Beceriler
    "degerlendirme": {"tanim": "Bilgiyi degerlendirme ve yargilama becerisi", "seviye": "KB3"},
    "elestirsel_dusunme": {"tanim": "Elestirsel dusunme ve sorgulama becerisi", "seviye": "KB3"},
    "problem_cozme": {"tanim": "Problem cozme ve karar verme becerisi", "seviye": "KB3"},
    "karar_verme": {"tanim": "Kanita dayali karar verme", "seviye": "KB3"},
}
