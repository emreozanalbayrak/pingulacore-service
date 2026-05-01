"""
Prompt templates for the question crafter agent.

Defines question types and their instructions.
"""

__all__ = ["QUESTION_TYPE_INSTRUCTIONS"]

# ============================================================================
# QUESTION TYPE DEFINITIONS
# ============================================================================

QUESTION_TYPE_INSTRUCTIONS = {
    "konu": {
        "name_tr": "Metinde Konu",
        "question_templates": [
            "Bu metnin konusu aşağıdakilerden hangisidir?",
            "Bu metinde aşağıdakilerden hangisi anlatılmaktadır?",
            "Bu metinde aşağıdakilerin hangisinden bahsedilmektedir?",
            "Bu metin aşağıdakilerin hangisinden bahsetmektedir?",
            "Aşağıdakilerden hangisi bu metnin konusunu en iyi ifade eder?",
            "Bu metinde ele alınan konu aşağıdakilerden hangisidir?",
            "Bu metne konu olan durum aşağıdakilerden hangisidir?",
            "Bu metinde aşağıdakilerin hangisinden söz edilmektedir?",
            "Bu metinde aşağıdakilerin hangisine değinilmektedir?",
            "Bu metinde aşağıdakilerin hangisine değinilmiştir?",
            "Bu metinde aşağıdakilerin hangisinden bahsedilmiştir?",
            "Bu metinde aşağıdakilerden hangisine değinilmiştir?",
        ],
        "instruction": """
KONU SORUSU OLUŞTUR:

SORU KALIBI: {selected_template}

ÖNEMLİ: Yukarıdaki soru kalıbını AYNEN kullan. Değiştirme!
"question" alanı SADECE bu soru cümlesini içermeli - paragraf EKLEME!

ŞIKLAR (Zorlayıcı Çeldirici Stratejisi):
- Doğru cevap: Paragrafın tam ve öz konusu

- Her çeldirici farklı bir "tuzak tipi" kullanmalı:
  1. YAKIN ANLAM: Doğru cevaba çok benzeyen ama ince farkla yanlış
     (örn: "Sporun faydaları" vs "Fiziksel aktivitenin önemi")

  2. DETAY TUZAĞI: Paragrafta geçen önemli bir detay, ama ana konu değil
     (örn: Spor paragrafında geçen "kalp sağlığı" detayı)

  3. ÜST KAVRAM: Konuyu kapsayan ama AYNI ALANDAKİ üst kavram
     (örn: "Spor" için "Fiziksel aktiviteler" - "Yaşam tarzı" DEĞİL!)
     KURAL: Sadece BİR seviye üste çık, iki-üç seviye DEĞİL!

- ZORLUK KURALLARI:
  * En az bir şık, dikkatli okumadan doğru gibi görünmeli
  * Çeldiriciler "aptalca yanlış" olmamalı
  * Şıklar arası uzunluk farkı minimal olmalı
  * Paragrafın ilk veya son cümlesinden doğrudan şık çıkarma

- KAÇINILACAKLAR:
  * Paragrafla hiç ilgisi olmayan şıklar
  * Gramer veya mantık hatası içeren şıklar
  * Doğru cevaptan belirgin derecede kısa/uzun şıklar
""",
    },
    "baslik": {
        "name_tr": "Metinde Başlık",
        "question_templates": ["Bu metnin başlığı aşağıdakilerden hangisi olabilir?"],
        "instruction": """
BAŞLIK SORUSU OLUŞTUR:
- Soru: "Bu metnin başlığı aşağıdakilerden hangisi olabilir?"
- Doğru cevap: Metnin ana temasını yakalayan çekici ve kısa (2-4 kelime) başlık
- Yanlış şıklar:
  * Çok dar kapsamlı başlık
  * Çok geniş kapsamlı başlık
  * İlişkili ama uygun olmayan başlık
- Başlıklar yaratıcı olabilir (metafor kullanılabilir)
""",
    },
    "ana_fikir": {
        "name_tr": "Ana Fikir",
        "question_templates": ["Bu metnin ana fikri aşağıdakilerden hangisidir?"],
        "instruction": """
ANA FİKİR SORUSU OLUŞTUR:
- Soru: "Bu metnin ana fikri aşağıdakilerden hangisidir?"
- ÖNEMLİ: Ana fikir "konu"dan farklıdır!
  * Konu: Metin NE HAKKINDA?
  * Ana fikir: Yazar bu konuda NE SÖYLEMEK İSTİYOR?
- Doğru cevap: Metnin vermek istediği ana mesaj (tam cümle)
- Yanlış şıklar:
  * Metinde geçen ama ana fikir olmayan detay
  * Konuyla ilgili ama desteklenmeyen fikir
  * Kısmen doğru ama eksik yorum
""",
    },
    "yardimci_fikir": {
        "name_tr": "Yardımcı Fikir",
        "question_templates": ["Bu metinde aşağıdakilerden hangisine değinilmemiştir?"],
        "instruction": """
YARDIMCI FİKİR SORUSU OLUŞTUR (NEGATİF):
- Soru: "Bu metinde aşağıdakilerden hangisine değinilmemiştir?"
- Doğru cevap: Konuyla ilgili AMA metinde değinilmemiş bilgi
- Yanlış şıklar: Metinde açıkça veya dolaylı değinilen bilgiler
- Düşündürücü olmalı, çok bariz olmamalı
""",
    },
}
