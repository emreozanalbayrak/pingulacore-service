from __future__ import annotations

import base64
import os.path
from html import escape
from pathlib import Path


def _guess_mime_type(image_path: Path) -> str:
    suffix = image_path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def _to_image_src(
    image_path: str | Path,
    output_dir: Path,
    *,
    inline_images: bool,
) -> str:
    raw_path = str(image_path)
    if raw_path.startswith(("data:", "http://", "https://", "file://")):
        return raw_path

    path = Path(raw_path)
    if path.exists():
        if inline_images:
            mime_type = _guess_mime_type(path)
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"

        relative_path = os.path.relpath(path.resolve(), output_dir.resolve())
        return Path(relative_path).as_posix()

    return raw_path


def _build_single_question_block(
    q: dict,
    option_image_map: dict[str, str],
    q_index: int,
    total_questions: int,
) -> str:
    """Tek bir soru icin HTML blogu olusturur."""
    question_stem = escape(q.get("question_stem", ""))
    options = q.get("options") or {}
    has_visual_options = bool(option_image_map)

    option_items = []
    for label in ["A", "B", "C", "D", "E"]:
        if label not in options:
            continue
        value = escape(str(options[label]))
        if has_visual_options and label in option_image_map:
            option_items.append(
                f"""<li class="option-card">
      <div class="option-label">{escape(label)})</div>
      <img class="option-image" src="{escape(option_image_map[label])}" alt="{escape(label)} şıkkı görseli">
      <div class="option-text">{value}</div>
    </li>"""
            )
        else:
            option_items.append(f"<li>{escape(label)}) {value}</li>")
    options_html = "\n    ".join(option_items)
    options_class = "options options-grid" if has_visual_options else "options"

    # Coklu soru ise baslik ekle
    header = ""
    if total_questions > 1:
        header = f'<div class="question-number">Soru {q_index}</div>'

    return f"""{header}
  <div class="question-stem">{question_stem}</div>
  <ul class="{options_class}">
    {options_html}
  </ul>"""


def build_question_html(
    question_data: dict,
    output_dir: str | Path,
    main_image_path: str | Path | None = None,
    option_images: dict[str, str] | None = None,
    inline_images: bool = True,
) -> str:
    """Build a consistent question HTML using the k10-style layout.

    Coklu soru destegi: questions listesindeki tum sorular ayri bloklar olarak gosterilir.
    Senaryo ve gorsel tum sorular icin ortaktir.
    """
    output_dir = Path(output_dir)
    questions = question_data.get("questions") or []
    scene_description = escape(question_data.get("scene_description", "Soru görseli"))
    scenario_text = escape(question_data.get("scenario_text", ""))

    image_html = ""
    if main_image_path:
        image_ref = _to_image_src(
            main_image_path,
            output_dir,
            inline_images=inline_images,
        )
        image_html = (
            f'<img class="embedded-main-visual" src="{escape(image_ref)}" '
            f'alt="{scene_description}">'
        )

    option_image_map: dict[str, str] = {}
    if option_images:
        for label, path in option_images.items():
            option_image_map[label] = _to_image_src(
                path,
                output_dir,
                inline_images=inline_images,
            )

    # Her soru icin ayri blok olustur
    question_blocks = []
    total = len(questions)
    for i, q in enumerate(questions, 1):
        block = _build_single_question_block(q, option_image_map, i, total)
        question_blocks.append(block)

    questions_html = "\n  <hr class=\"question-divider\">\n  ".join(question_blocks)

    # Coklu soru ise ek CSS
    multi_css = ""
    if total > 1:
        multi_css = """
  .question-number {
    font-size: 15px;
    font-weight: bold;
    color: #fff;
    background: #5b7dba;
    display: inline-block;
    padding: 4px 14px;
    border-radius: 12px;
    margin-bottom: 10px;
    margin-top: 5px;
  }
  .question-divider {
    border: none;
    border-top: 2px dashed #d0d7de;
    margin: 20px 0;
  }"""

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<style>
  body {{
    font-family: 'Comic Sans MS', Arial, sans-serif;
    background-color: #f9f9f9;
    color: #333;
    padding: 20px;
  }}
  .question-container {{
    background-color: #fff;
    border-radius: 10px;
    padding: 20px;
    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    max-width: 760px;
    margin: auto;
  }}
  .scenario {{
    font-size: 16px;
    line-height: 1.5;
    margin-bottom: 15px;
  }}
  .embedded-main-visual {{
    display: block;
    width: 100%;
    max-width: 720px;
    height: auto;
    margin: 16px auto 20px;
    border-radius: 12px;
    box-shadow: 0 3px 10px rgba(0,0,0,0.08);
    background: #fff;
  }}
  .question-stem {{
    font-size: 18px;
    font-weight: bold;
    margin-bottom: 15px;
  }}
  .options {{
    list-style-type: none;
    padding: 0;
    margin: 0;
  }}
  .options-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px;
  }}
  .options li {{
    font-size: 16px;
    margin-bottom: 10px;
    padding: 10px;
    background-color: #eef2f5;
    border-radius: 5px;
    border: 1px solid #d0d7de;
  }}
  .option-card {{
    margin-bottom: 0;
    padding: 12px;
    background: #fffdf7;
    border: 2px solid #ead9b6;
    box-shadow: 0 3px 10px rgba(0,0,0,0.05);
  }}
  .option-label {{
    font-size: 18px;
    font-weight: bold;
    margin-bottom: 8px;
  }}
  .option-image {{
    display: block;
    width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
    border-radius: 10px;
    background: #fff;
    border: 1px solid #e5e7eb;
    margin-bottom: 10px;
  }}
  .option-text {{
    font-size: 15px;
    line-height: 1.4;
  }}{multi_css}
</style>
</head>
<body>
<div class="question-container">
  <div class="scenario">{scenario_text}</div>
  {image_html}
  {questions_html}
</div>
</body>
</html>"""
