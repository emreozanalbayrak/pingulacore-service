# Pingula Core Service - Agent Handoff Notes

Bu dosya, yeni bir thread'e veya yeni bir agente geçerken hızlı context aktarımı icin tutulur.

## Son Durum Ozeti

### 1. Terminoloji ve Veri Modeli
- `taxonomy` terminolojisi tum projede `curriculum` olarak degistirildi.
- `curriculum_nodes` yapisi ikiye ayrildi:
  - `curriculum_constant_nodes`: degismeyen sabit node'lar (`root`, `grade`, `subject`, `theme`)
  - `curriculum_folder_nodes`: dinamik klasor node'lari
- `curriculum_folder_nodes` tablosunda eski kolonlara ek olarak `grade`, `subject`, `theme` alanlari var.
- `yaml_templates` artik `curriculum_folder_nodes` tablosuna baglaniyor.
- `property_definitions` tablosuna `label` ve `description` kolonlari eklendi.

### 2. Curriculum Seed Isleri
- Docker icindeki Postgres `pingula` veritabani kullaniliyor.
- `1`-`12` grade node'lari ve ilgili subject node'lari olusturuldu.
- Subject slug'lari grade prefix'li olacak sekilde guncellendi:
  - `2-matematik`
  - `3-fen`
  - `12-fizik`
- `toc_tymm_links_no_ders.csv` kullanilarak theme node'lari `curriculum_constant_nodes` tablosuna yazildi.
- Gerekli yerlerde `felsefe` subject node'lari eklendi.
- Geometri temalari matematikten ayrilarak `geometri` subject altina yerlestirildi.

### 3. Property Definitions
- Root seviyesinde temel property'ler ve hiyerarsileri eklendi:
  - `etik_kurallar`
  - `gorsel`
  - `gorsel.exists`
  - `format_class`
  - `sik_sayisi`
- Grade / grade-subject / theme seviyelerinde draft mantiga gore cok sayida `property_definition` seed edildi.
- Property hiyerarsisi root -> grade -> grade-subject -> theme mantigina gore genisletildi.

### 4. `ortak/` YAML Importu
- `ortak/` altindaki 23 YAML icin DB-first import script'i yazildi.
- Script su islemleri yapiyor:
  - YAML dosyalarini okuyor
  - uygun theme'e esliyor
  - gerekirse folder node olusturuyor
  - template upsert ediyor
  - instance upsert ediyor
  - property value kayitlarini yaziyor
- Script dosyasi:
  - `app/scripts/import_ortak_yaml.py`
- Import sonucu:
  - 11 template
  - 23 instance
  - ilgili `yaml_instance_property_values` kayitlari

### 5. Backend CRUD Endpointleri
UI tarafindan kullanilmak uzere CRUD endpointleri eklendi.

#### Property Definitions
- `POST /v1/properties`
- `GET /v1/properties`
- `GET /v1/properties/{property_id}`
- `PATCH /v1/properties/{property_id}`
- `DELETE /v1/properties/{property_id}`
- `GET /v1/properties/effective/{curriculum_node_id}`

#### YAML Templates
- `POST /v1/yaml-templates`
- `GET /v1/yaml-templates`
- `GET /v1/yaml-templates/{template_id}`
- `PATCH /v1/yaml-templates/{template_id}`
- `DELETE /v1/yaml-templates/{template_id}`

#### YAML Instances
- `POST /v1/yaml-instances`
- `GET /v1/yaml-instances`
- `GET /v1/yaml-instances/{instance_id}`
- `PATCH /v1/yaml-instances/{instance_id}`
- `DELETE /v1/yaml-instances/{instance_id}`
- `POST /v1/yaml-instances/{instance_id}/render`

### 6. Pipeline Input Modeli
- Pipeline'lar artik DB-first input modeliyle calisiyor.

#### Full Pipeline
- input: `yaml_instance_id`

#### Sub-Pipelines
- `yaml -> question`: `yaml_instance_id`
- `question -> layout`: `question_artifact_id`
- `layout -> html`: `question_artifact_id + layout_artifact_id`

- Eski file-based input akisi ana kullanim yolundan cikarildi.

### 7. Frontend: Yeni Icerik Yonetimi Ekrani
- Yeni route: `/content`
- `/templates` route'u artik `/content`'e redirect ediyor.
- Sayfa adi: `Icerik Yonetimi`

#### Sekmeler
- `Property Definitions`
- `YAML Templates`
- `YAML Instances`

#### Ozellikler
- goruntuleme
- ekleme
- duzenleme
- silme
- yenileme

#### Ek detaylar
- Property sekmesinde curriculum tree + effective parent property secimi var.
- Template sekmesinde recursive schema builder var.
- Instance sekmesinde template schema'dan dinamik form uretimi var.
- Delete confirm modal var.
- YAML render aksiyonu var.
- Basari / hata banner'lari var.

#### Ana frontend dosyalari
- `frontend/src/pages/ContentManagementPage.tsx`
- `frontend/src/components/CurriculumTreePicker.tsx`
- `frontend/src/components/DeleteConfirmModal.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/types.ts`
- `frontend/src/App.tsx`

### 8. Test ve Build Durumu
- Frontend test suite gecti:
  - 9 test file
  - 17 test
  - tumu pass
- Frontend build gecti:
  - `npm run build`
- `useLogStream` icine `EventSource` olmayan ortamlar icin guard eklendi.
- Vite tarafinda chunk size warning var ama bloklayici degil.

### 9. Sistemin Su Anki Genel Durumu
- Curriculum / property / template / instance veri modeli DB-first calisiyor.
- `ortak/` YAML'lar database'e tasinmis durumda.
- UI uzerinden property definitions, yaml templates ve yaml instances yonetilebiliyor.
- Pipeline ekranlari DB input modeliyle uyumlu.
- Frontend test ve build temiz.

### 10. Muhtemel Sonraki Isler
1. Icerik Yonetimi ekraninin UX polish'i
2. Inline validation ve daha guclu yardimci aciklamalar
3. Backend tarafinda kalan eski file-based kod kirintilarinin tamamen temizlenmesi
4. Browser uzerinden manuel smoke test
5. Curriculum / property / template / instance edit akislarinda daha gelismis filtreleme veya bulk islemler

## Onemli Dosyalar
- `app/db/models.py`
- `app/db/repository.py`
- `app/api/content.py`
- `app/scripts/import_ortak_yaml.py`
- `frontend/src/pages/ContentManagementPage.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/types.ts`

## Not
Bu ozet, yeni bir agent'in projeye hizli giris yapabilmesi icin yazildi. Yeni thread'de ozellikle `curriculum`, `property_definitions`, `yaml_templates`, `yaml_instances` ve `/content` ekranini referans almak yeterli olacaktir.
