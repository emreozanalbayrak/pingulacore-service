"""
input_dir ve output_dir alarak PDF'lerden soru çıkarma servisi.
chain_extract_question_text chain'ini kullanır.
"""
import json
from pathlib import Path
from typing import Any

import fitz

from core.chains.chain_extract_question_text import (
    extract_questions_from_page_image,
)


def _build_raw_content(q: dict[str, Any]) -> None:
    """Soru sözlüğüne raw_content ekler; [IMAGE] -> <image> dönüşümü yapar."""
    q_num = q.get("question_number", 0)
    stem = q.get("stem", "")
    img_desc = q.get("image_description")

    if img_desc and "[IMAGE]" in stem:
        stem_with_image = stem.replace("[IMAGE]", f"\n\n<image>\n{img_desc}\n</image>\n\n")
    elif img_desc:
        stem_with_image = f"{stem}\n\n<image>\n{img_desc}\n</image>"
    else:
        stem_with_image = stem

    options = q.get("options", {})
    raw_parts = [f"{q_num}. {stem_with_image}"]
    if options:
        raw_parts.append("\n")
        for opt_key in sorted(options.keys()):
            raw_parts.append(f"{opt_key}) {options[opt_key]}")

    q["raw_content"] = "\n".join(raw_parts)
    q["stem"] = stem.replace("[IMAGE]", "").replace("  ", " ").strip()


def _questions_from_page_image(image_path: Path) -> list[dict[str, Any]]:
    """Tek sayfa görüntüsünden chain ile soruları çıkarır (dict listesi)."""
    questions = extract_questions_from_page_image(image_path)
    return [q.model_dump() for q in questions]


def _process_single_pdf(pdf_path: Path, output_dir: Path) -> dict[str, Any]:
    """Tek bir PDF'i işleyip soruları çıkarır; çıktıları output_dir altına yazar."""
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "page_images"
    images_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    all_questions: list[dict[str, Any]] = []

    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            print(f"  Sayfa {page_num + 1}/{len(doc)} işleniyor...")

            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            img_path = images_dir / f"page_{page_num + 1}.png"
            pix.save(str(img_path))

            try:
                questions = _questions_from_page_image(img_path)
                print(f"    {len(questions)} soru bulundu")
                if len(questions) == 0:
                    print(
                        f"    Uyarı: Sayfa {page_num + 1} için 0 soru döndü (sayfa atlanmış olabilir)",
                    )
                for q in questions:
                    q["page"] = page_num + 1
                    all_questions.append(q)
            except json.JSONDecodeError as e:
                print(f"    JSON parse hatası (Sayfa {page_num + 1} atlandı): {e}")
            except Exception as e:
                print(f"    Gemini hatası (Sayfa {page_num + 1} atlandı): {e}")
    finally:
        doc.close()

    all_questions.sort(key=lambda x: x.get("question_number", 0))

    for q in all_questions:
        _build_raw_content(q)

    questions_dir = output_dir / "questions"
    questions_dir.mkdir(parents=True, exist_ok=True)

    for q in all_questions:
        q_num = q.get("question_number", 0)
        (questions_dir / f"question_{q_num}.json").write_text(
            json.dumps(q, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    all_questions_path = output_dir / f"{pdf_path.stem}_questions_gemini.json"
    all_questions_path.write_text(
        json.dumps(
            {
                "source": str(pdf_path),
                "method": "gemini_vision",
                "total_questions": len(all_questions),
                "questions": all_questions,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\n  Toplam {len(all_questions)} soru çıkarıldı")
    print(f"  Sorular: {questions_dir}")
    print(f"  Tüm sorular: {all_questions_path}")
    print(f"  Sayfa görselleri: {images_dir}")

    return {
        "questions": all_questions,
        "questions_dir": str(questions_dir),
        "all_questions_path": str(all_questions_path),
        "images_dir": str(images_dir),
    }


def extract_questions(
    input_dir: str | Path,
    output_dir: str | Path,
    pdf_path: str | Path | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """
    input_dir (ve isteğe bağlı tek PDF) veya sadece pdf_path vererek soruları çıkarır.
    Çıktılar output_dir altına yazılır.

    Kullanım:

    1) Klasör: input_dir içindeki tüm PDF'ler işlenir; her biri için output_dir / pdf_stem.
        results = extract_questions(
            input_dir="pdfs",
            output_dir="out/tyt",
        )

    2) Tek PDF: pdf_path ile dosya, output_dir ile çıktı klasörü.
        out = extract_questions(
            input_dir="pdfs",
            output_dir="out/tyt",
            pdf_path="tyt_fen.pdf",
        )
        # veya pdf_path tam yol: Path("pdfs/tyt_fen.pdf")

    Dönüş:
        - Tek PDF: {"questions", "questions_dir", "all_questions_path", "images_dir"}
        - Klasör (birden fazla PDF): Bu yapıda sözlük listesi.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    if not input_dir.is_dir():
        raise FileNotFoundError(f"Girdi klasörü bulunamadı: {input_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    if pdf_path is not None:
        pdf_path = Path(pdf_path)
        if not pdf_path.is_absolute():
            pdf_path = input_dir / pdf_path
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF bulunamadı: {pdf_path}")
        print(f"\nPDF işleniyor (Gemini Vision): {pdf_path}")
        return _process_single_pdf(pdf_path, output_dir)

    pdf_files = sorted(input_dir.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"PDF dosyası yok: {input_dir}")

    results: list[dict[str, Any]] = []
    for path in pdf_files:
        pdf_out = output_dir / path.stem
        print(f"\nPDF işleniyor (Gemini Vision): {path}")
        results.append(_process_single_pdf(path, pdf_out))
    return results
