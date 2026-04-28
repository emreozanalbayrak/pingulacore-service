"""
Geometri gorseli orchestrator chain'i.

Chain 4'un yerine (geometri tipi sorularda) cagirlir. Sirayla:
  1. LLM'den GeometryScene JSON al (chain_generate_geometry_scene)
  2. Auto-snap + yapisal dogrulama
  3. Deterministik SVG + referans PNG render
  4. Referans PNG'yi gorsel modele verip estetik ama geometriyi koruyan final PNG uret
  5. GeneratedImages dondurur

Cikti: main_visual.png (HTML/validator uyumlu), main_visual_base.png,
       main_visual.svg (debug) + geometry_scene.json (debug + retry fingerprint)
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional

from google.genai import types

from pomodoro.chains.chain_generate_geometry_scene import generate_geometry_scene
from pomodoro.geometry_scene import GeometryScene
from pomodoro.geometry_validator import auto_snap_scene, validate_scene
from pomodoro.models import GeneratedImages, GeneratedVisualQuestion
from pomodoro.pipeline_log import pipeline_log
from pomodoro.yaml_loader import ParsedTemplate
from src.render_geometry_scene import render_scene_to_file, render_scene_to_png
from utils.llm import MODEL_REGISTRY, ModelRole, get_image_client


MAX_SCENE_ATTEMPTS = 3
KEEP_GEOMETRY_DEBUG = os.getenv("PINGULA_KEEP_GEOMETRY_DEBUG", "").lower() in {
    "1", "true", "yes", "on"
}


def _save_scene_json(scene: GeometryScene, output_dir: Path) -> None:
    if not KEEP_GEOMETRY_DEBUG:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_path = output_dir / "geometry_scene.json"
    scene_path.write_text(
        json.dumps(scene.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _previous_scene_fingerprint(output_dir: Path) -> str | None:
    """Onceki uretim scene'inin ozetini feedback icin hazirlar.

    Retry'da LLM ayni secimleri tekrar etmesin diye secilmis bg tipi, paleti
    ve polygon layout'u feedback'e enjekte edilir.
    """
    scene_path = output_dir / "geometry_scene.json"
    if not scene_path.exists():
        return None
    try:
        data = json.loads(scene_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    bg = data.get("background") or {}
    polys = data.get("polygons") or []
    poly0 = polys[0] if polys else {}
    verts = poly0.get("vertices") or []
    if verts:
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        bbox = f"({min(xs)},{min(ys)})-({max(xs)},{max(ys)})"
    else:
        bbox = "(yok)"

    parts = [
        "ONCEKI DENEMENIN OZETI — BU SECIMLERDEN EN AZ 2'SINI DEGISTIR:",
        f"- grid_type: {bg.get('type', '?')}",
        f"- paper_color: {bg.get('paper_color', '?')}",
        f"- grid_color: {bg.get('grid_color', '?')}",
        f"- color_theme: {data.get('color_theme', '?')}",
        f"- polygon bbox: {bbox}",
        f"- polygon vertex sayisi: {len(verts)}",
        f"- polygon fill: {poly0.get('fill', '?')}",
        "",
        "BU KEZ: yukaridaki secimlerden en az 2'sini DEGISTIR.",
        "Ornek: farkli grid_type + farkli polygon layout, veya farkli palet.",
        "Amac: ogrenci iki gorseli yan yana koydugunda kolayca ayirt edebilsin.",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Reference-conditioned geometry image generation
# ---------------------------------------------------------------------------

def _format_geometry_questions(question: GeneratedVisualQuestion) -> str:
    lines: list[str] = []
    for q in question.questions[:3]:
        lines.append(f"- {q.question_stem}")
        if q.correct_answer:
            lines.append(f"  Dogru cevap: {q.correct_answer}) {q.options.get(q.correct_answer, '')}")
    return "\n".join(lines) if lines else "(yok)"


def _infer_theme_object(question: GeneratedVisualQuestion, scene: GeometryScene) -> str:
    objects = getattr(question, "used_objects", None) or []
    if objects:
        return str(objects[0])
    if getattr(question, "scenario_target_object", None):
        return str(question.scenario_target_object)
    if scene.scenario_hint:
        return str(scene.scenario_hint)
    return ""


def _object_detail_hint(theme_object: str) -> str:
    obj = theme_object.lower()
    if "keman" in obj:
        return (
            "Tema nesnesi kemansa keman oldugu acikca anlasilmali: govde kivrimi, "
            "ince sap, teller, kopru, f delikleri ve burgular gibi kemana ozgu "
            "ayirt edici parcayi yalnizca bu varyanta yakisiyorsa grid disi/margin alaninda kullan."
        )
    if any(k in obj for k in ("kalem", "kurşun", "kursun")):
        return "Tema nesnesi kalemse ucu, silgisi, govde seritleri ve ahsap ucu gibi ayirt edici parcalar gorunsun."
    if "satran" in obj:
        return "Tema nesnesi satranc tasiyla ilgiliyse tas silueti, taban halkasi ve tepe formu net anlasilsin."
    return (
        f"Tema nesnesi '{theme_object}' ise ve bu varyant tematik dis alan kullanmaya uygunsa "
        "nesne gercekten taninabilir olsun; yalnizca renk cagrisimi yetmez. Nesnenin ayirt "
        "edici parcalarini sade, cocuklara uygun illustratif bicimde kullan."
    )


def _build_restyle_prompt(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    scene: GeometryScene,
    feedback: Optional[str],
) -> str:
    theme_object = _infer_theme_object(question, scene)
    object_hint = _object_detail_hint(theme_object) if theme_object else ""
    return f"""Ekteki PNG bir matematiksel referans iskelettir. Bu iskeleti ayni geometriyle, daha estetik ve cocuklara uygun egitsel bir gorsele donustur.

MUTLAK KORUMA:
- Referanstaki tum matematiksel geometri korunmali: grid/nokta varsa tipi ve araliklari; tum polygon vertex konumlari; segmentler; kenar baglantilari; simetri, aci, alan, cevre, uzunluk, sayim iliskileri ve etiketler.
- Referansta kosegen/yarim birim alan varsa kosegen sade kalmali; kosegenin iki tarafina eslik/tick cizgisi, "1/2" etiketi veya ekstra alan etiketi ekleme.
- Ana geometri alanina yeni sekil, yeni obje, dekoratif ikon, karakter, arka plan sahnesi veya soru metni ekleme.
- Cevabi degistirecek hicbir gorsel yorum yapma; olcu/sayma referans PNG ile ayni kalmali.
- Etiket varsa aynen kalsin; yeni cumle, paragraf, soru kokü veya aciklama yazma.

ESTETIK HEDEF:
- Geometri disi uretimlerdeki gibi temiz, renkli, modern egitim materyali hissi ver.
- Fotogercekci, grid arkasinda fotograf, dramatik isik veya dekoratif sahne yapma.
- Cizgileri, dolgu renklerini, kagit dokusunu ve genel illustratif kaliteyi iyilestir; ama geometriyi yeniden icat etme.
- Cerceve/margin tasarimi OPSIYONELDIR; her gorselde tematik cerceve yapmak zorunda degilsin.
- Soru ve varyanta gore uc yoldan birini sec: (1) cercevesiz temiz kagit/geometri, (2) cok ince modern kagit kenari veya kart zemini, (3) sadece uygun varyantlarda tematik margin/cerceve.
- Tekduzeligi azalt: onceki geometri uretimlerinde hep cerceve varmis gibi davranma; bazi uretimlerde dis alan tamamen sade kalsin.
- Cerceve/margin kullanirsan ana geometri alanina girmemeli, sekli/etiketleri/olcu-sayim iliskisini kapatmamalı ve cevap icin yeni bilgi eklememeli.
- Tema nesnesi varsa bile sadece uygun varyantlarda grid DISINDA/margin alaninda kullan; uygun degilse tema yalnizca renk ve kagit dokusunda hafif kalsin.
{object_hint}

Baglam: sinif {template.sinif_seviyesi}, image_type={template.image_type}, theme_object={theme_object or '(yok)'}, scenario_hint={scene.scenario_hint or '(yok)'}
Soru ozeti:
{_format_geometry_questions(question)}

Geri bildirim:
{feedback or '(yok)'}

Yalnizca tek bir PNG gorseli uret."""


def _generate_restyled_geometry_image(
    *,
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    scene: GeometryScene,
    base_png_path: Path,
    output_path: Path,
    feedback: Optional[str],
) -> str | None:
    """Deterministik referansi image model ile estetik final gorsele donusturur."""
    try:
        client = get_image_client()
        config = MODEL_REGISTRY[ModelRole.IMAGE_GENERATOR]
        prompt = _build_restyle_prompt(template, question, scene, feedback)
        image_part = types.Part.from_bytes(
            data=base_png_path.read_bytes(),
            mime_type="image/png",
        )
        response = client.models.generate_content(
            model=config["model"],
            contents=[image_part, prompt],
            config={"response_modalities": ["TEXT", "IMAGE"]},
        )
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data is not None:
                data = part.inline_data.data
                if isinstance(data, str):
                    import base64
                    data = base64.b64decode(data)
                output_path.write_bytes(data)
                pipeline_log("geometry", f"Hybrid geometri final PNG uretildi: {output_path}")
                return str(output_path)
    except Exception as exc:
        pipeline_log(
            "geometry",
            f"Hybrid geometri gorsel uretimi basarisiz; referans PNG kullanilacak: {type(exc).__name__}: {exc}",
        )
        return None

    pipeline_log("geometry", "Hybrid geometri yaniti gorsel icermiyor; referans PNG kullanilacak.")
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_geometry_image(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    output_dir: str | Path = "output/visual_questions",
    feedback: Optional[str] = None,
) -> GeneratedImages:
    """Referans-kosullu hybrid geometri gorseli.

    Matematik katmani once SVG/PNG olarak uretilir, sonra final gorsel bu
    referansa kosullu image generation ile estetiklestirilir.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Onceki scene varsa fingerprint'i feedback'e ekle
    previous_fp = _previous_scene_fingerprint(output_dir)
    if previous_fp:
        feedback = (feedback + "\n\n" if feedback else "") + previous_fp
        pipeline_log(
            "geometry",
            "Onceki scene fingerprint'i feedback'e eklendi (cesitlilik zorunlulugu)."
        )

    collected_feedback = feedback or ""
    scene: GeometryScene | None = None
    last_issues: list[str] = []

    # 1-2. Scene graph + yapisal dogrulama (max 3 deneme)
    for attempt in range(1, MAX_SCENE_ATTEMPTS + 1):
        pipeline_log(
            "geometry",
            f"Sahne grafi uretimi (deneme {attempt}/{MAX_SCENE_ATTEMPTS})…"
        )
        scene = generate_geometry_scene(template, question, collected_feedback or None)
        scene = auto_snap_scene(scene)

        result = validate_scene(scene)
        if result.ok:
            pipeline_log("geometry", f"Sahne grafi dogrulandi (deneme {attempt}).")
            break

        last_issues = result.issues
        pipeline_log(
            "geometry",
            f"Dogrulama basarisiz (deneme {attempt}): {len(result.issues)} sorun."
        )
        collected_feedback = (
            (feedback + "\n\n" if feedback else "")
            + "YAPISAL DOGRULAMA SORUNLARI (duzelt):\n"
            + result.as_feedback()
        )
    else:
        pipeline_log(
            "geometry",
            f"⚠️ Yapisal dogrulama {MAX_SCENE_ATTEMPTS} denemede gecilmedi. "
            "Son sahne yine de render ediliyor."
        )

    assert scene is not None
    _save_scene_json(scene, output_dir)

    # 3. SVG + referans PNG render
    if KEEP_GEOMETRY_DEBUG:
        svg_path = render_scene_to_file(
            scene, output_dir / "main_visual.svg",
            ambient_image_path=None,
        )
        pipeline_log("geometry", f"SVG yazildi: {svg_path}")

    base_png_path = Path(render_scene_to_png(
        scene, output_dir / "main_visual_base.png",
        ambient_image_path=None,
    ))
    pipeline_log("geometry", f"Referans PNG yazildi: {base_png_path}")

    # 4. Gorsel modele referansla estetik final urettir
    final_png_path = output_dir / "main_visual.png"
    final_path = _generate_restyled_geometry_image(
        template=template,
        question=question,
        scene=scene,
        base_png_path=base_png_path,
        output_path=final_png_path,
        feedback=feedback,
    )
    if final_path is None:
        shutil.copyfile(base_png_path, final_png_path)
        final_path = str(final_png_path)
        pipeline_log("geometry", f"Final PNG referans kopyasi olarak yazildi: {final_png_path}")

    notes = "hybrid geometri render (deterministik referans + image-conditioned final)"
    if last_issues:
        notes += f" — acik sorun: {len(last_issues)}"

    return GeneratedImages(
        main_image_path=final_path,
        option_images=None,
        generation_notes=notes,
    )
