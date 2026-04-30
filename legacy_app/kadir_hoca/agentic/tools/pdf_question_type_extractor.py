"""
PDF question stem (type) extractor.

This reads the PDF directly via Gemini (native PDF understanding) and extracts
distinct question stem templates (e.g., "Bu metnin konusu ...?") with examples.

Uses direct google.genai SDK.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ExtractedQuestionStem",
    "QuestionTypeExtractionResult",
    "extract_question_types_from_pdf",
    "normalize_question_stem",
    "dedupe_question_stems",
]


_WS_RE: re.Pattern[str] = re.compile(r"\s+")


def normalize_question_stem(stem: str) -> str:
    """
    Normalize a question stem for stable deduplication.

    Notes:
    - Keeps Turkish characters intact.
    - Collapses whitespace and standardizes trailing '?'.
    - Does NOT attempt semantic paraphrase grouping; only light normalization.
    """
    s: str = stem.strip()
    s = s.strip('"\'"')  # strip common surrounding quotes
    s = _WS_RE.sub(" ", s)
    s = s.replace(" ?","?").replace("  ", " ").strip()
    if s.endswith(" ?"):
        s = s[:-2] + "?"
    return s


def dedupe_question_stems(stems: list[str]) -> list[str]:
    """
    Deduplicate stems using `normalize_question_stem`, preserving first-seen order.
    """
    seen: set[str] = set()
    out: list[str] = []
    for stem in stems:
        normalized: str = normalize_question_stem(stem)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


class ExtractedQuestionStem(BaseModel):
    """
    A single extracted question stem template from a PDF.
    """

    model_config = ConfigDict(extra="forbid")

    category: str = Field(
        ...,
        description=(
            "Short label grouping similar stems (e.g., konu, baslik, ana_fikir, "
            "yardimci_fikir, anlam, cikarim, vb.)."
        ),
    )
    stem: str = Field(..., description="Exact stem text as it appears in the PDF.")
    example_pages: list[int] = Field(
        default_factory=list,
        description="1-based PDF page numbers where this stem appears (a few examples).",
    )
    count_estimate: int | None = Field(
        default=None,
        description="Rough count estimate across the book (optional).",
    )


class _GeminiExtractionResponse(BaseModel):
    """
    Raw extraction response schema for Gemini.
    """

    model_config = ConfigDict(extra="forbid")

    stems: list[ExtractedQuestionStem] = Field(
        default_factory=list,
        description="Unique question stem templates found in the PDF.",
    )
    notes: str = Field(
        default="",
        description="Optional notes about sections or uncertainty.",
    )


class QuestionTypeExtractionResult(BaseModel):
    """
    Post-processed extraction result written to disk.
    """

    model_config = ConfigDict(extra="forbid")

    pdf_path: str
    model: str
    notes: str = ""
    stems: list[ExtractedQuestionStem] = Field(default_factory=list)
    unique_stems_normalized: list[str] = Field(default_factory=list)


def _build_prompt() -> str:
    return (
        "Asagidaki PDF bir Turkce paragraf soru kitabidir.\n\n"
        "GOREV:\n"
        "- Kitaptaki coktan secmeli sorularda gecen TUM farkli soru koku kaliplarini "
        "(question stem template) cikar.\n"
        "- 'Soru koku' = paragraftan sonra gelen ve seceneklerden (A,B,C,D) once gelen "
        "soru cumlesidir.\n"
        "- Paragraf ve siklari KESINLIKLE yazma.\n"
        "- Ayni anlamdaki ama farkli yazilmis kaliplari AYRI ayri listele (biz sonradan "
        "istersek birlestiririz). Yani paraphrase birlestirme.\n"
        "- Her kalip icin:\n"
        "  * category: kisa grup etiketi (orn: konu, baslik, ana_fikir, yardimci_fikir, "
        "anlam, cikarim, vb.)\n"
        "  * stem: PDF'deki haliyle soru cumlesi\n"
        "  * example_pages: bu kalibin gectigi sayfalardan 1-3 ornek (sayfa numarasi)\n"
        "  * count_estimate: kitaptaki yaklasik tekrar sayisi (tahmini olabilir)\n\n"
        "KAPSAM:\n"
        "- Tum kitabi tara. Farkli bolumlerde farkli kaliplar olabilir.\n"
        "- Yalnizca gercekten soru koku olan kaliplari cikar.\n"
    )


async def extract_question_types_from_pdf(
    pdf_path: Path,
    output_json_path: Path,
    model: str = "gemini-2.5-pro",
    max_output_tokens: int = 8000,
) -> QuestionTypeExtractionResult:
    """
    Extract distinct question stem templates from a PDF and write a JSON report.

    Uses direct google.genai SDK with Gemini model for PDF understanding.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_json_path = Path(output_json_path)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)

    # Get API key
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY environment variable required")

    # Create client
    client = genai.Client(api_key=api_key)

    # Upload PDF
    uploaded_file = client.files.upload(file=pdf_path)

    prompt: str = _build_prompt()

    # Generate with structured output
    response = await client.aio.models.generate_content(
        model=model,
        contents=[
            types.Content(
                parts=[
                    types.Part.from_uri(
                        file_uri=uploaded_file.uri,
                        mime_type="application/pdf",
                    ),
                    types.Part(text=prompt),
                ]
            )
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_GeminiExtractionResponse,
        ),
    )

    # Parse response
    raw = _GeminiExtractionResponse.model_validate_json(response.text)

    # Post-process: normalize and dedupe stems across categories if necessary.
    normalized_list: list[str] = dedupe_question_stems([s.stem for s in raw.stems])

    # Keep original objects but normalize stem field in-place for consistency.
    stems: list[ExtractedQuestionStem] = []
    seen_norm: set[str] = set()
    for s in raw.stems:
        norm: str = normalize_question_stem(s.stem)
        if not norm or norm in seen_norm:
            continue
        seen_norm.add(norm)
        stems.append(
            ExtractedQuestionStem(
                category=normalize_question_stem(s.category),
                stem=norm,
                example_pages=sorted(set(int(p) for p in s.example_pages if int(p) > 0))[:5],
                count_estimate=s.count_estimate,
            )
        )

    # Stable sort: category, then stem.
    stems_sorted: list[ExtractedQuestionStem] = sorted(
        stems, key=lambda x: (x.category.lower(), x.stem.lower())
    )

    result = QuestionTypeExtractionResult(
        pdf_path=str(pdf_path),
        model=model,
        notes=raw.notes,
        stems=stems_sorted,
        unique_stems_normalized=normalized_list,
    )

    output_json_path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return result


def extract_question_types_from_pdf_sync(
    pdf_path: Path,
    output_json_path: Path,
    model: str = "gemini-2.5-pro",
    max_output_tokens: int = 8000,
) -> QuestionTypeExtractionResult:
    """
    Synchronous wrapper for scripts/CLI.
    """
    return asyncio.run(
        extract_question_types_from_pdf(
            pdf_path=pdf_path,
            output_json_path=output_json_path,
            model=model,
            max_output_tokens=max_output_tokens,
        )
    )
