"""
LLM ile üretilen LaTeX kodunu xelatex ile derleyip PDF olarak yazan servis.
Akış: chain_generate_latex_code (soru -> LaTeX) -> compile_latex -> export.
"""
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Union

QuestionLike = Union[Any, dict[str, Any]]


def compile_latex(
    latex_code: str,
    output_dir: Union[str, Path],
    base_name: str = "question",
) -> tuple[bool, str | None]:
    """
    LaTeX kodunu dosyaya yazar ve xelatex ile PDF'e derler.
    Eski .pdf / .aux / .log / .out dosyalarını temizler.

    Returns:
        (success, pdf_path_or_none)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for ext in (".pdf", ".png", ".aux", ".log", ".out"):
        old = output_dir / f"{base_name}{ext}"
        if old.exists():
            try:
                old.unlink()
            except OSError:
                pass
    tex_file = output_dir / f"{base_name}.tex"
    tex_file.write_text(latex_code, encoding="utf-8")

    xelatex = shutil.which("xelatex")
    if not xelatex:
        return False, None
    try:
        result = subprocess.run(
            [xelatex, "-interaction=nonstopmode", f"{base_name}.tex"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(output_dir),
        )
        pdf_file = output_dir / f"{base_name}.pdf"
        if not pdf_file.exists():
            return False, None
        return True, str(pdf_file)
    except Exception:
        return False, None


def export_question_to_pdf_via_llm(
    question: QuestionLike,
    output_dir: Union[str, Path],
    base_name: str = "question",
    output_pdf_path: Union[str, Path, None] = None,
) -> tuple[bool, str | None]:
    """
    Soruyu LLM ile LaTeX koduna çevirir (chain_generate_latex_code), derler (compile_latex)
    ve PDF path'ini döndürür. İstenirse PDF istenen bir dosya yoluna kopyalanır.

    Returns:
        (success, pdf_path_or_none)
    """
    from core.chains.chain_generate_latex_code import generate_latex_code

    latex_code = generate_latex_code(question)
    ok, pdf_path = compile_latex(latex_code, output_dir, base_name)
    if not ok or not pdf_path:
        return False, None
    if output_pdf_path is not None:
        output_pdf_path = Path(output_pdf_path)
        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf_path, output_pdf_path)
        return True, str(output_pdf_path)
    return True, pdf_path


if __name__ == "__main__":
    out = Path("changed_latex_pdf")
    base = "question"
    if len(sys.argv) >= 2:
        out = Path(sys.argv[1])
    if len(sys.argv) >= 3:
        base = sys.argv[2]
    tex_file = out / f"{base}.tex"
    if not tex_file.exists():
        print(f"Hata: {tex_file} bulunamadı.")
        sys.exit(1)
    code = tex_file.read_text(encoding="utf-8")
    ok, path = compile_latex(code, out, base)
    if ok:
        print(f"Çıktı: {path}")
    else:
        sys.exit(1)
