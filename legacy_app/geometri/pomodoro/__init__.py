"""
Pomodoro: Goerselli soru uretim pipeline'i.

ortak/ klasorundeki 7 baslikli YAML sablonlarindan
(meta, context, header_template, format, dogru_cevap, distractors, use_shared_strategies)
adim adim coklu LLM chain'lerle soru + gorsel uretir.

Kullanim:
    from legacy_app.geometri.pomodoro.graph import run
    result = run("ortak/kareli_zeminde_baslangic_hedef_rota_secme.yaml")
"""
