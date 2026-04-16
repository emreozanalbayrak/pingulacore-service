# UI Kullanım Kılavuzu

Bu doküman sadece arayüz kullanımı içindir. Kurulum veya altyapı ayarlarını anlatmaz.

## 1. Genel Ekran Yapısı

Uygulama iki ana alandan oluşur:

- Sol sidebar (menü)
- Sağ içerik alanı (seçtiğin sayfanın ekranı)

Sidebar menüleri:

- `Ana Sayfa`
- `Full Pipeline`
- `Sub-Pipelines`
- `Standalone Agents`

Sidebar altındaki `Agent Mode` göstergesi backend modunu gösterir:

- `Real Model`
- `Stub Mode`

## 2. Ana Sayfa

`Ana Sayfa` ekranında üç kart görürsün:

- `Full Pipeline`
- `Sub-Pipelines`
- `Standalone Agents`

Kullanım:

1. İlgili karta tıkla.
2. Doğrudan o çalışma ekranına geçilir.

## 3. Full Pipeline Ekranı

Bu ekran YAML dosyasından tek seferde tüm akışı çalıştırır.

### 3.1 Çalıştırma Adımları

1. Sol menüden `Full Pipeline` seç.
2. `Pipeline Configuration` kartında `YAML Dosyası` alanından dosya seç.
3. Gerekirse retry alanlarını düzenle:
   - `Question Retry`
   - `Layout Retry`
   - `HTML Retry`
4. `Full Pipeline Çalıştır` butonuna tıkla.
5. Çalışma sırasında alt sağdaki `Live Logs` butonuna tıklayarak canlı logları aç.
6. Sonuçlar geldikçe aşağıdaki panelleri incele.

### 3.2 Sonuç Alanları

- `Pipeline Özeti`: `pipeline_id` ve durum bilgisi
- `Question JSON`
- `Layout Plan JSON`
- `Full Pipeline HTML`:
  - `Raw` sekmesi ham HTML
  - `Rendered` sekmesi iframe önizleme
- `Full Pipeline Final Render PNG`: final görsel

### 3.3 Ara Adım İnceleme

`Sub-Pipeline Ara Çıktılar` bölümünde her adımı ayrı görürsün:

- adım durumu (`StatusBadge`)
- adım `Output` JSON
- uygun adımda `Ara Adım HTML`
- uygun adımda `Ara Adım Final Render PNG`
- adım event logları

### 3.4 Log ve Agent Detayı

- `Pipeline Event Logları` panelini başlıktaki oka tıklayarak aç/kapat.
- `Yenile` ile logları tazele.
- `Pipeline Agent Runs` panelinde:
  - satıra tıklayarak tek run detayını aç
  - `Detayları Yükle` ile tüm run detaylarını çek
  - `Attempt Grupları` bölümünden deneme bazlı sonucu gör

## 4. Sub-Pipelines Ekranı

Bu ekranı adımları tek tek kontrol ederek çalıştırmak için kullanırsın.

Üstte 3 sekme vardır:

- `YAML → Question`
- `Question → Layout`
- `Layout → HTML`

### 4.1 1. Adım: YAML → Question

1. `YAML → Question` sekmesini aç.
2. `YAML Dosyası` seç.
3. `Question Retry` değerini ayarla (opsiyonel).
4. Gerekirse:
   - `Refresh now`
   - `Dosya Listesini Yenile`
5. `Çalıştır` butonuna bas.
6. `Question Output` panelini kontrol et:
   - `Raw JSON` ile görünümü değiştir
   - `Kopyala` ile çıktıyı panoya al

### 4.2 2. Adım: Question → Layout

1. `Question → Layout` sekmesine geç.
2. `Kayıtlı Question JSON` dosyası seç.
3. `Question Dosyasını Yükle` ile editöre aktar.
4. Gerekirse `Question JSON Input` alanını düzenle.
5. `Çalıştır` butonuna bas.
6. `Layout Output` panelini incele:
   - `Raw JSON` görünümü
   - `Asset Library`
   - `Layout Tree`
   - `Summary`

Not: JSON editörünün altında doğrulama satırı görünür:

- `✓ Geçerli JSON`
- `⚠ JSON doğrulanamadı`

### 4.3 3. Adım: Layout → HTML

1. `Layout → HTML` sekmesine geç.
2. `Kayıtlı Question JSON` ve `Kayıtlı Layout JSON` seç.
3. Gerekirse:
   - `Question Dosyasını Yükle`
   - `Layout Dosyasını Yükle`
4. `Question JSON Input` ve `Layout JSON Input` alanlarını kontrol et.
5. `Çalıştır` butonuna bas.
6. Sonuçları incele:
   - `HTML Iterations` (iterasyon bazlı render/validation)
   - `Sub-Pipeline HTML Preview` (`Raw` / `Rendered`)
   - `Final Render PNG`

## 5. Standalone Agents Ekranı

Bu ekran tek bir agenti bağımsız test etmek içindir.

### 5.1 Basic Mod ile Çalıştırma

1. `Standalone Agents` ekranına gir.
2. `Agent` listesinden agent seç.
3. `Basic Form` açık değilse `Basic Moda Dön` ile geri dön.
4. Alanları doldur:
   - JSON alanları
   - metin alanları (`Feedback` vb.)
5. `Agent Çalıştır` butonuna tıkla.
6. `Agent Sonucu` bölümünde:
   - `run_id`
   - durum
   - `Result`
   - `Run Detail`
   bilgilerini kontrol et.

### 5.2 YAML’den Input Doldurma (main_generate_question)

`Main / Generate Question` seçiliyse ek bir blok görünür:

1. `YAML Listesini Yenile`
2. listeden dosya seç
3. `YAML İçeriğini Yükle`

Bu işlem `yaml_content` alanını otomatik doldurur.

### 5.3 Advanced JSON Mod

1. `Advanced JSON Aç` butonuna tıkla.
2. `Advanced Raw JSON Payload` alanına doğrudan payload yaz.
3. İstersen `Raw Sync` ile basic alandan payload yenile.
4. `Agent Çalıştır` ile isteği gönder.

### 5.4 Run Geçmişi

Ekranın altındaki `Run Geçmişi` bölümünde:

1. Eski run satırına tıkla.
2. İlgili run detayı tekrar yüklenir.

## 6. Ortak UI Bileşenleri

### 6.1 Canlı Log Kutusu (sağ alt)

- Buton adı: `Logs` / `Live Logs`
- Tıklayınca log penceresi açılır.
- Üst sağdaki ok ile küçültülür.
- Bağlantı durumları:
  - `live`
  - `done`
  - `Connecting…`

### 6.2 HTML Viewer

Her HTML panelinde 2 sekme vardır:

- `Raw`
- `Rendered`

`Rendered` sekmesi, HTML’i iframe içinde gösterir.

### 6.3 Event Log Panelleri

`PipelineLogsPanel` tipindeki panellerde:

1. Başlığa tıklayarak paneli aç/kapat.
2. `Yenile` butonuyla yeni logları çek.
3. Log satırındaki `Detay` varsa altındaki JSON panelinden incele.

### 6.4 Agent Run Panelleri

`AgentRunsPanel` tipindeki panellerde:

1. Başlığa tıklayıp paneli aç.
2. Run satırına tıklayıp tek run detayını gör.
3. `Detayları Yükle` ile toplu detay getir.
4. `Attempt Grupları` bölümünden deneme bazlı sonuçları takip et.

## 7. Hızlı Kullanım Senaryoları

### Senaryo A: YAML’den final HTML’e hızlı gitmek

1. `Full Pipeline`
2. YAML seç
3. `Full Pipeline Çalıştır`
4. `Full Pipeline HTML` panelinde `Rendered`
5. `Full Pipeline Final Render PNG` kontrolü

### Senaryo B: Sadece 2. adımı test etmek (Question → Layout)

1. `Sub-Pipelines` → `Question → Layout`
2. `Question Dosyasını Yükle`
3. `Çalıştır`
4. `Layout Output` ve `Step-2 Event Log` kontrolü

### Senaryo C: Belirli bir agent prompt’unu izole test etmek

1. `Standalone Agents`
2. Agent seç
3. Gerekirse `Advanced JSON Aç`
4. Payload düzenle
5. `Agent Çalıştır`
6. `Run Detail` + `Agent Logs` incele
