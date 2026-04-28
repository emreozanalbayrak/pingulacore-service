"""
HTML rendering tool for agentic question generator.

This module provides:
1. HTML_TEMPLATE - A styled HTML template for rendering questions
2. render_question_html() - Fills template with question content
3. render_to_png() - Converts HTML to PNG using Playwright

The template is designed to match "Arı Paragraf" textbook styling:
- 300px column width
- Times New Roman font
- Exam-style layout (paragraph → question → options A-D)
"""

import logging
import re
from pathlib import Path

__all__ = [
    "render_question_html",
    "render_detailed_html",
    "render_to_png",
    "render_context_group_html",
    "render_detailed_context_group_html",
]

logger = logging.getLogger(__name__)


# ============================================================================
# HTML TEMPLATE
# ============================================================================
# This template renders a question in classic Turkish exam format:
# - Justified paragraph with text indent
# - Bold question
# - Vertical options A) B) C) D)
#
# The <meta name="correct-answer"> tag stores the answer for validation.
# Validators can extract this to check if solvers got the right answer.

# CSS wrapper — provides <html><head><style>...</style></head><body>...</body></html>
# The {body_content} placeholder is filled with either the default body template
# or a custom html_body_template from the YAML template.
CSS_WRAPPER = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="correct-answer" content="{correct_answer}">
    <style>
        body {{
            font-family: 'Times New Roman', serif;
            font-size: 12px;
            line-height: 1.4;
            padding: 12px 16px;
            max-width: 300px;  /* Matches Arı Paragraf single column width */
            background: #fff;
            color: #000;
            margin: 0;
        }}
        .paragraph {{
            text-align: justify;
            hyphens: manual;
            -webkit-hyphens: manual;

            margin-bottom: 16px;
            text-indent: 1.5em;  /* First-line indent like textbooks */
        }}
        .paragraph.titles-list {{
            text-indent: 0;  /* No indent for title lists */
        }}
        .paragraph.titles-list ol {{
            margin: 0;
            padding-left: 1.5em;
            list-style-type: decimal;
        }}
        .paragraph.titles-list ol li {{
            margin-bottom: 2px;
        }}
        .paragraph.table-content {{
            text-indent: 0;
            text-align: left;
        }}
        .paragraph table {{
            width: 100%;
            border-collapse: collapse;
            margin: 4px 0;
            font-size: 11px;
        }}
        .paragraph table th,
        .paragraph table td {{
            border: 1px solid #333;
            padding: 3px 6px;
            text-align: center;
        }}
        .paragraph table th {{
            background: #f0f0f0;
            font-weight: bold;
        }}
        .paragraph.chart-content {{
            text-indent: 0;
            text-align: left;
        }}
        .paragraph .chart {{
            display: grid;
            grid-template-columns: auto 1fr auto;
            align-items: center;
            column-gap: 6px;
            row-gap: 4px;
            margin: 6px 0;
            font-size: 10px;
        }}
        .paragraph .chart-row {{
            display: contents;
        }}
        .paragraph .chart-label {{
            text-align: right;
            font-size: 10px;
            white-space: nowrap;
        }}
        .paragraph .chart-bar {{
            height: 14px;
            background: linear-gradient(90deg, #4a90d9, #357abd);
            border-radius: 2px;
            min-width: 2px;
        }}
        .paragraph .chart-val {{
            font-size: 9px;
            font-weight: bold;
            white-space: nowrap;
        }}
        /* ── Infografik: Bilgi kartlari / siniflandirma / surec akisi ── */
        .paragraph.infographic-content {{
            text-indent: 0;
            text-align: left;
        }}
        .paragraph .info-title {{
            font-weight: bold;
            font-size: 12px;
            text-align: center;
            margin-bottom: 8px;
            padding-bottom: 4px;
            border-bottom: 2px solid #4a90d9;
        }}
        .paragraph .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 6px;
            margin: 6px 0;
        }}
        .paragraph .info-card {{
            background: #f0f7ff;
            border: 1px solid #b8d4f0;
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 10px;
        }}
        .paragraph .info-card-title {{
            font-weight: bold;
            font-size: 10px;
            color: #2c5282;
            margin-bottom: 4px;
            padding-bottom: 3px;
            border-bottom: 1px solid #b8d4f0;
        }}
        .paragraph .info-card-body {{
            font-size: 9px;
            line-height: 1.3;
            color: #333;
        }}
        .paragraph .info-card-body ul {{
            margin: 2px 0;
            padding-left: 12px;
        }}
        .paragraph .info-card-body li {{
            margin-bottom: 1px;
        }}
        .paragraph .process-flow {{
            display: flex;
            align-items: stretch;
            gap: 2px;
            margin: 6px 0;
            flex-wrap: wrap;
        }}
        .paragraph .process-step {{
            flex: 1;
            min-width: 55px;
            background: #e8f4e8;
            border: 1px solid #90c090;
            border-radius: 4px;
            padding: 5px 6px;
            font-size: 9px;
            text-align: center;
        }}
        .paragraph .process-step-title {{
            font-weight: bold;
            font-size: 9px;
            color: #2d6a2d;
            margin-bottom: 2px;
        }}
        .paragraph .process-step-desc {{
            font-size: 8px;
            color: #444;
        }}
        .paragraph .process-arrow {{
            display: flex;
            align-items: center;
            font-size: 14px;
            color: #666;
            padding: 0 1px;
        }}
        .question {{
            font-weight: normal;  /* Topic normal, sadece <b> tagları bold */
            margin-bottom: 12px;
            word-wrap: break-word;
            overflow-wrap: break-word;
        }}
        .question b {{
            font-weight: bold;
        }}
        .question u {{
            text-decoration: underline;
        }}
        .options {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        .options.two-column {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 4px 20px;
        }}
        .options.image-options {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px 20px;
        }}
        .options.image-options-3 {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 12px;
        }}
        .options.image-options-3 .option {{
            flex-direction: column;
            gap: 2px;
            align-items: flex-start;
        }}
        .option {{
            display: flex;
            gap: 6px;
            align-items: flex-start;
        }}
        .options.image-options .option {{
            flex-direction: column;
            gap: 2px;
            align-items: flex-start;
        }}
        .option-letter {{
            font-weight: normal;
            flex-shrink: 0;
            min-width: 18px;
        }}
        .option-image {{
            width: 100%;
            height: auto;
            display: block;
        }}
        .diagram {{
            display: block;
            max-width: 100%;
            margin: 12px auto;
        }}
    </style>
</head>
<body>
    {body_content}
</body>
</html>"""

# Default body template — standard paragraph + question + options layout
DEFAULT_BODY_TEMPLATE = """<div class="paragraph">{paragraph}</div>
    {image_html}
    <div class="question">{question}</div>
    <div class="options">
        <div class="option"><span class="option-letter">A)</span> {option_a}</div>
        <div class="option"><span class="option-letter">B)</span> {option_b}</div>
        <div class="option"><span class="option-letter">C)</span> {option_c}</div>
        <div class="option"><span class="option-letter">D)</span> {option_d}</div>
    </div>"""


def _build_default_body(options: dict) -> str:
    """Build default body template dynamically based on option count.

    Supports 3, 4, or 5 options (A-C, A-D, A-E).
    """
    labels = sorted(options.keys())

    option_divs = "\n        ".join(
        f'<div class="option"><span class="option-letter">{l})</span> {{option_{l.lower()}}}</div>'
        for l in labels
    )
    return (
        '<div class="paragraph">{paragraph}</div>\n'
        '    {image_html}\n'
        '    <div class="question">{question}</div>\n'
        f'    <div class="options">\n        {option_divs}\n    </div>'
    )


# ============================================================================
# TURKISH HYPHENATION
# ============================================================================

_Path = Path

# Soft hyphen character — invisible but tells the browser where it CAN break
_SOFT_HYPHEN = "\u00AD"

# Lazy-loaded pyphen dictionary (loaded once on first use)
_tr_dic = None
import os as _os
_TR_DIC_PATH = _Path(
    _os.environ.get("LEGACY_TURKCE_DATA_DIR")
    or (_Path(__file__).parent.parent / "data")
) / "hyph_tr_TR.dic"

# Pre-compiled regex to split text on HTML tags (used by _hyphenate_turkish)
_HTML_TAG_SPLIT_RE = re.compile(r"(<[^>]+>)")


def _get_tr_dic():
    """Get or create the Turkish hyphenation dictionary (lazy singleton)."""
    global _tr_dic
    if _tr_dic is None:
        try:
            import pyphen
            _tr_dic = pyphen.Pyphen(filename=str(_TR_DIC_PATH))
        except Exception:
            _tr_dic = False  # Mark as unavailable, don't retry
    return _tr_dic if _tr_dic else None


def _hyphenate_turkish(text: str) -> str:
    """
    Insert soft hyphens into Turkish text for better justified rendering.

    Preserves HTML tags (<b>, <u>, etc.) — only hyphenates plain text parts.
    Skips short words (≤5 chars) and ensures at least 3 chars remain
    after each hyphen break to avoid ugly single-char orphans like "r".
    """
    if not text:
        return text

    dic = _get_tr_dic()
    if not dic:
        return text  # pyphen not available, return unchanged

    def _hyphenate_word(word: str) -> str:
        # Hunspell dictionary already enforces LEFTHYPHENMIN 2 / RIGHTHYPHENMIN 3
        # Soft hyphens are invisible — browser only breaks at them when needed
        return dic.inserted(word, hyphen=_SOFT_HYPHEN)

    # Split on HTML tags — hyphenate only text parts
    parts = _HTML_TAG_SPLIT_RE.split(text)
    result = []
    for part in parts:
        if part.startswith("<"):
            result.append(part)
        else:
            words = part.split(" ")
            hyphenated = " ".join(_hyphenate_word(w) for w in words)
            result.append(hyphenated)
    return "".join(result)


# ============================================================================
# TEXT NORMALIZATION FOR RENDER
# ============================================================================

# Pre-compiled regex for efficiency
_MULTI_SPACE_RE = re.compile(r" {2,}")


def _normalize_for_render(text: str) -> str:
    """
    Final cleanup before HTML render.

    This is a safety net to catch any formatting issues that might have
    slipped through earlier validation. It's intentionally conservative.

    Operations:
    1. Strip leading/trailing whitespace
    2. Collapse multiple spaces to single space
    3. Convert tabs to spaces
    4. Remove leftover placeholder brackets [X] → X

    Args:
        text: Raw text to normalize

    Returns:
        Normalized text safe for rendering
    """
    if not text:
        return ""
    # Strip leading/trailing whitespace
    result = text.strip()
    # Convert tabs to spaces
    result = result.replace("\t", " ")
    # Collapse multiple spaces to single space
    result = _MULTI_SPACE_RE.sub(" ", result)
    # Remove leftover placeholder brackets (e.g., [söz öbeği] → söz öbeği)
    result = re.sub(r"\[([^\]]+)\]", r"\1", result)
    # Bolum 6: ensure bare ---- placeholder is consistently wrapped in quotes
    # (already-quoted "----" left alone). Matches 3+ dashes.
    result = re.sub(r'(?<!["\'“”‘’])(-{3,})(?!["\'“”‘’])', r'"----"', result)
    return result


# ============================================================================
# STEM BOLD ENFORCEMENT
# ============================================================================

def _ensure_bold_stem(question: str) -> str:
    """Wrap question stem in <b> tags if not already bold.

    LLMs sometimes drop the <b> tag even when instructed to keep it.
    This ensures every rendered question stem is bold.
    """
    stripped = question.strip()
    if not stripped:
        return question
    if stripped.startswith("<b>"):
        return question
    return f"<b>{question}</b>"


# ============================================================================
# HTML ESCAPING
# ============================================================================

def _escape_html(text: str, preserve_formatting: bool = True) -> str:
    """
    Escape HTML special characters while optionally preserving formatting tags.

    This is crucial - user-provided content (topics, paragraphs) could
    contain characters like < > & that would break HTML or create XSS.

    However, for question stems, we want to preserve <u> and <b> tags
    that the LLM uses to emphasize negative phrases like "yer almaz".

    Args:
        text: Raw text string
        preserve_formatting: If True, preserves <u>, </u>, <b>, </b> tags

    Returns:
        HTML-safe string with special chars escaped (formatting tags preserved)
    """
    if not text:
        return ""

    if preserve_formatting:
        # Pre-process: convert <strong>→<b>, <em>→<u> (LLM sometimes uses these)
        text = re.sub(r'<strong\b[^>]*>', '<b>', text, flags=re.IGNORECASE)
        text = re.sub(r'</strong>', '</b>', text, flags=re.IGNORECASE)
        text = re.sub(r'<em\b[^>]*>', '<u>', text, flags=re.IGNORECASE)
        text = re.sub(r'</em>', '</u>', text, flags=re.IGNORECASE)

        # Two-pass approach: protect allowed tags → escape → restore
        protected = []

        def protect_tag(match):
            protected.append(match.group(0))
            return f"\x00[{len(protected)-1}]\x00"

        # Protect <u>, </u>, <b>, </b>, <br>, table tags, and chart div/span tags (case-insensitive)
        result = re.sub(
            r'</?[ub]>|<br\s*/?>|</?(?:table|thead|tbody|tr|th|td)(?:\s[^>]*)?>|<(?:div|span)(?:\s[^>]*)?>|</(?:div|span)>',
            protect_tag, text, flags=re.IGNORECASE
        )

        # Escape remaining HTML special characters
        result = (
            result
            .replace("&", "&amp;")   # Must be first (& is in other escapes)
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

        # Restore protected tags
        for i, tag in enumerate(protected):
            result = result.replace(f"\x00[{i}]\x00", tag)

        return result
    else:
        # Original behavior - escape everything
        return (
            text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )


# ============================================================================
# MULTI-TEXT PARAGRAPH SPLITTING
# ============================================================================

# Regex to detect "1. Metin:" and "2. Metin:" labels in paragraph text.
# Captures the split point between two texts.
_MULTI_TEXT_RE = re.compile(
    r'(\d+)\.\s*[Mm]etin\s*:\s*',
)


def _split_multi_text_paragraph(paragraph: str) -> str:
    """
    Split multi-text paragraphs into separate HTML divs.

    Detects patterns like "1. Metin: text1... 2. Metin: text2..." and
    renders them as two separate paragraph divs with vertical spacing,
    removing the "N. Metin:" labels.

    Returns the paragraph unchanged if no multi-text pattern is found.
    """
    if not paragraph:
        return paragraph

    # Find all "N. Metin:" occurrences
    matches = list(_MULTI_TEXT_RE.finditer(paragraph))
    if len(matches) < 2:
        return paragraph

    # Extract texts between labels
    texts = []
    for i, m in enumerate(matches):
        start = m.end()  # After "N. Metin: "
        end = matches[i + 1].start() if i + 1 < len(matches) else len(paragraph)
        text = paragraph[start:end].strip()
        if text:
            texts.append(text)

    if len(texts) < 2:
        return paragraph

    # Build separate paragraph divs with spacing
    # Keep "N. Metin" labels as bold headers
    # The caller wraps result in <div class="paragraph">...</div>
    # so we return the inner content with </div><div> to create separation
    parts = []
    for i, text in enumerate(texts):
        label = f"<b>{i+1}. Metin:</b> "
        parts.append(label + text)

    # Join with closing + reopening div to create visual separation
    return '</div>\n<div class="paragraph" style="margin-top: 10px;">'.join(parts)


# ============================================================================
# MAIN FUNCTIONS
# ============================================================================

def _convert_titles_to_list(paragraph: str) -> tuple[str, bool]:
    """
    Detect if paragraph contains numbered titles and convert to <ol> list.

    Detects pattern like: "1. Title A<br>2. Title B<br>3. Title C"

    Returns:
        tuple of (converted_html, is_titles_list)
    """
    if not paragraph:
        return paragraph, False

    if re.match(r'^\s*1\.', paragraph) and '<br>' in paragraph.lower():
        # Split by <br> and extract items
        items = re.split(r'<br\s*/?>', paragraph, flags=re.IGNORECASE)

        # Remove the number prefix from each item and build list
        list_items = []
        for item in items:
            # Remove leading "1. ", "2. ", "3. " etc.
            cleaned = re.sub(r'^\s*\d+\.\s*', '', item.strip())
            if cleaned:
                list_items.append(f'<li>{cleaned}</li>')

        if len(list_items) >= 2:  # At least 2 items to be a list
            return f'<ol>{"".join(list_items)}</ol>', True

    return paragraph, False


def render_question_html(
    paragraph: str,
    question: str,
    options: dict,
    correct_answer: str,
    key_word: str = "",
    image_base64: str | None = None,
    options_layout: str | None = None,
    html_body_template: str | None = None,
    option_images: dict[str, str] | None = None,
    background_color: str | None = None,
) -> str:
    """
    Render a question as HTML in classic exam format.

    Args:
        paragraph: The educational paragraph (reading content)
        question: The question text (stem)
        options: Dict with keys A, B, C, D mapping to option text
        correct_answer: The correct option letter (A, B, C, or D)
        key_word: Optional key word (not currently used in template)
        image_base64: Optional base64-encoded PNG image (diagram)
        options_layout: Optional layout hint ("two_column" for 2x2 grid)
        html_body_template: Optional body template from YAML. When provided,
            used instead of DEFAULT_BODY_TEMPLATE. Supports {paragraph},
            {question}, {option_a}-{option_d}, {image_html}, {titles_paragraph}.

    Returns:
        Complete HTML string ready for rendering

    Example:
        html = render_question_html(
            paragraph="Güneş sisteminde 8 gezegen bulunur...",
            question="Buna göre, aşağıdakilerden hangisi doğrudur?",
            options={"A": "Mars en büyük gezegendir", "B": "...", ...},
            correct_answer="B",
            image_base64="iVBORw0KGgo...",  # Optional diagram
        )
    """
    # Order: normalize → hyphenate (on raw text) → escape (for HTML safety)
    escaped_paragraph = _escape_html(_hyphenate_turkish(_normalize_for_render(paragraph)))
    question = _ensure_bold_stem(question)
    escaped_question = _escape_html(_hyphenate_turkish(_normalize_for_render(question)))

    # Split multi-text paragraphs (e.g., "1. Metin: ... 2. Metin: ...")
    # into separate divs with spacing, removing labels
    escaped_paragraph = _split_multi_text_paragraph(escaped_paragraph)

    # Check if paragraph is a titles list (for baslik_inverse format)
    escaped_paragraph, is_titles_list = _convert_titles_to_list(escaped_paragraph)

    # Build image HTML if provided
    image_html = ""
    if image_base64:
        image_html = f'<img src="data:image/png;base64,{image_base64}" alt="Diyagram" class="diagram"/>'

    # Prepare field values for template substitution
    field_values = {
        "paragraph": escaped_paragraph,
        "titles_paragraph": escaped_paragraph,  # alias for inverse title format
        "question": escaped_question,
        "image_html": image_html,
    }
    # Add option fields dynamically
    for label in sorted(options.keys()):
        if option_images and label in option_images:
            # Render as image for gorsel_siklar templates
            field_values[f"option_{label.lower()}"] = (
                f'<img src="data:image/png;base64,{option_images[label]}" '
                f'alt="Secenek {label}" class="option-image" />'
            )
        else:
            field_values[f"option_{label.lower()}"] = _escape_html(
                _normalize_for_render(options.get(label, ""))
            )

    # Use custom body template from YAML, or build default dynamically
    if html_body_template:
        body_template = html_body_template
        template_source = "YAML html_body_template"
    else:
        body_template = _build_default_body(options)
        template_source = "dynamic DEFAULT_BODY"

    options_log = "\n".join(
        f"  {l}) {options.get(l, '')}" for l in sorted(options.keys())
    )
    logger.debug(
        f"[RENDER HTML]\n{'='*60}\n"
        f"Template source: {template_source}\n"
        f"Correct answer: {correct_answer}\n"
        f"Has image: {bool(image_base64)}\n"
        f"Options layout: {options_layout or 'default'}\n"
        f"Is titles list: {is_titles_list}\n"
        f"Paragraph ({len(paragraph)} chars):\n{paragraph}\n"
        f"Question:\n{question}\n"
        f"Options:\n{options_log}\n"
        f"Body template:\n{body_template}\n"
        f"{'='*60}"
    )

    # Fill the body template
    body_content = body_template.format(**field_values)

    # Wrap body in CSS wrapper
    html = CSS_WRAPPER.format(
        correct_answer=correct_answer,
        body_content=body_content,
    )

    # Add colored background to paragraph if template specifies it
    # NOTE: Bu işlem titles-list ve diğer class eklemelerinden ÖNCE yapılmalı,
    # çünkü sonraki replacements `class="paragraph"` ifadesini parçalıyor.
    if background_color:
        _bg_style = (
            f"background: {background_color}; border-radius: 6px; "
            f"padding: 12px; border: 1px solid {background_color}88;"
        )
        html = html.replace(
            'class="paragraph"',
            f'class="paragraph" style="{_bg_style}"',
        )

    # Add titles-list class if paragraph is a numbered list
    if is_titles_list:
        paragraph_class = "paragraph titles-list"
        html = html.replace('class="paragraph"', f'class="{paragraph_class}"')

    # Add table-content, chart-content, or infographic-content class based on paragraph content
    if '<table' in escaped_paragraph.lower():
        html = html.replace('class="paragraph"', 'class="paragraph table-content"')
    elif 'class="chart"' in escaped_paragraph.lower() or "class='chart'" in escaped_paragraph.lower():
        html = html.replace('class="paragraph"', 'class="paragraph chart-content"')
    elif 'class="info-grid"' in escaped_paragraph.lower() or "class='info-grid'" in escaped_paragraph.lower() or 'class="process-flow"' in escaped_paragraph.lower() or "class='process-flow'" in escaped_paragraph.lower():
        html = html.replace('class="paragraph"', 'class="paragraph infographic-content"')

    # Apply layout for options
    if option_images:
        n_img = len(option_images)
        if n_img == 3:
            html = html.replace('class="options"', 'class="options image-options-3"')
        else:
            html = html.replace('class="options"', 'class="options image-options"')
    elif options_layout == "two_column":
        html = html.replace('class="options"', 'class="options two-column"')

    return html


async def render_to_png(
    html_content: str,
    output_path: Path,
    width: int = 340,
    height: int = 600,
    scale: float = 3.0,
) -> Path:
    """
    Render HTML to PNG using Playwright's headless Chromium.

    This function:
    1. Launches a headless browser
    2. Sets viewport to specified dimensions
    3. Loads the HTML content
    4. Screenshots the <body> element (avoiding whitespace)

    Args:
        html_content: The HTML string to render
        output_path: Where to save the PNG file
        width: Viewport width (340px = 300px content + 40px padding)
        height: Initial viewport height (adjusted by content)
        scale: Device scale factor for high-DPI (3.0 = 3x resolution)

    Returns:
        Path to the created PNG file

    Raises:
        PlaywrightError: If browser launch or rendering fails

    Note:
        Requires Playwright and Chromium to be installed:
        pip install playwright
        playwright install chromium
    """
    # Import here to avoid requiring Playwright if not rendering
    from playwright.async_api import async_playwright

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        # Launch headless Chromium
        browser = await p.chromium.launch()

        # Create page with specified viewport
        page = await browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=scale,  # 3x for crisp text
        )

        # Load HTML content
        await page.set_content(html_content)

        # Wait for any async content (fonts, etc.)
        await page.wait_for_load_state("networkidle")

        # Screenshot just the body to avoid extra whitespace
        body = await page.query_selector("body")
        if body:
            await body.screenshot(path=str(output_path))
        else:
            # Fallback to full page if body not found
            await page.screenshot(path=str(output_path), full_page=True)

        await browser.close()

    return output_path


# ============================================================================
# DETAILED HTML TEMPLATE (with metadata)
# ============================================================================
# This template shows the question PLUS:
# - Option reasoning (why each distractor was chosen)
# - Validation checks (pass/fail status)
# - Curriculum grounding (MEB source)
#
# Used for review/debugging purposes.

HTML_DETAILED_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="correct-answer" content="{correct_answer}">
    <style>
        body {{
            font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            font-size: 11px;
            line-height: 1.4;
            padding: 16px;
            max-width: 700px;
            background: #fff;
            color: #1a1a1a;
            margin: 0;
        }}
        .question-section {{
            background: #fafafa;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            padding: 14px;
            margin-bottom: 14px;
        }}
        .section-title {{
            font-size: 10px;
            font-weight: 600;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 10px;
            padding-bottom: 6px;
            border-bottom: 1px solid #eee;
        }}
        .paragraph {{
            text-align: justify;
            hyphens: manual;
            -webkit-hyphens: manual;

            margin-bottom: 12px;
            text-indent: 1.5em;
            font-family: 'Times New Roman', serif;
            font-size: 12px;
        }}
        .paragraph.titles-list {{
            text-indent: 0;
        }}
        .paragraph.titles-list ol {{
            margin: 0;
            padding-left: 1.5em;
            list-style-type: decimal;
        }}
        .paragraph.titles-list ol li {{
            margin-bottom: 2px;
        }}
        .paragraph.table-content {{
            text-indent: 0;
            text-align: left;
        }}
        .paragraph table {{
            width: 100%;
            border-collapse: collapse;
            margin: 4px 0;
            font-size: 11px;
        }}
        .paragraph table th,
        .paragraph table td {{
            border: 1px solid #333;
            padding: 3px 6px;
            text-align: center;
        }}
        .paragraph table th {{
            background: #f0f0f0;
            font-weight: bold;
        }}
        .paragraph.chart-content {{
            text-indent: 0;
            text-align: left;
        }}
        .paragraph .chart {{
            display: grid;
            grid-template-columns: auto 1fr auto;
            align-items: center;
            column-gap: 6px;
            row-gap: 4px;
            margin: 6px 0;
            font-size: 10px;
        }}
        .paragraph .chart-row {{
            display: contents;
        }}
        .paragraph .chart-label {{
            text-align: right;
            font-size: 10px;
            white-space: nowrap;
        }}
        .paragraph .chart-bar {{
            height: 14px;
            background: linear-gradient(90deg, #4a90d9, #357abd);
            border-radius: 2px;
            min-width: 2px;
        }}
        .paragraph .chart-val {{
            font-size: 9px;
            font-weight: bold;
            white-space: nowrap;
        }}
        /* ── Infografik: Bilgi kartlari / siniflandirma / surec akisi ── */
        .paragraph.infographic-content {{
            text-indent: 0;
            text-align: left;
        }}
        .paragraph .info-title {{
            font-weight: bold;
            font-size: 12px;
            text-align: center;
            margin-bottom: 8px;
            padding-bottom: 4px;
            border-bottom: 2px solid #4a90d9;
        }}
        .paragraph .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 6px;
            margin: 6px 0;
        }}
        .paragraph .info-card {{
            background: #f0f7ff;
            border: 1px solid #b8d4f0;
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 10px;
        }}
        .paragraph .info-card-title {{
            font-weight: bold;
            font-size: 10px;
            color: #2c5282;
            margin-bottom: 4px;
            padding-bottom: 3px;
            border-bottom: 1px solid #b8d4f0;
        }}
        .paragraph .info-card-body {{
            font-size: 9px;
            line-height: 1.3;
            color: #333;
        }}
        .paragraph .info-card-body ul {{
            margin: 2px 0;
            padding-left: 12px;
        }}
        .paragraph .info-card-body li {{
            margin-bottom: 1px;
        }}
        .paragraph .process-flow {{
            display: flex;
            align-items: stretch;
            gap: 2px;
            margin: 6px 0;
            flex-wrap: wrap;
        }}
        .paragraph .process-step {{
            flex: 1;
            min-width: 55px;
            background: #e8f4e8;
            border: 1px solid #90c090;
            border-radius: 4px;
            padding: 5px 6px;
            font-size: 9px;
            text-align: center;
        }}
        .paragraph .process-step-title {{
            font-weight: bold;
            font-size: 9px;
            color: #2d6a2d;
            margin-bottom: 2px;
        }}
        .paragraph .process-step-desc {{
            font-size: 8px;
            color: #444;
        }}
        .paragraph .process-arrow {{
            display: flex;
            align-items: center;
            font-size: 14px;
            color: #666;
            padding: 0 1px;
        }}
        .question {{
            font-weight: normal;  /* Topic normal, sadece <b> tagları bold */
            margin-bottom: 10px;
            font-family: 'Times New Roman', serif;
            font-size: 12px;
        }}
        .question b {{
            font-weight: bold;
        }}
        .options {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            font-family: 'Times New Roman', serif;
            font-size: 12px;
        }}
        .options.two-column {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 4px 20px;
        }}
        .option {{
            display: flex;
            gap: 6px;
            align-items: flex-start;
        }}
        .option-letter {{
            font-weight: normal;
            flex-shrink: 0;
            min-width: 18px;
        }}
        .correct {{
            color: #0a7c42;
            font-weight: 600;
        }}
        .diagram {{
            display: block;
            max-width: 100%;
            margin: 10px auto;
        }}
        .metadata-section {{
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 12px;
        }}
        .reasoning-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }}
        .reasoning-item {{
            background: #fff;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 8px;
            font-size: 10px;
        }}
        .reasoning-item.correct-answer {{
            border-color: #28a745;
            background: #f0fff4;
        }}
        .reasoning-option {{
            font-weight: 600;
            color: #495057;
            margin-bottom: 4px;
        }}
        .reasoning-strategy {{
            color: #6c757d;
            font-style: italic;
            margin-bottom: 2px;
        }}
        .reasoning-text {{
            color: #212529;
        }}
        .validation-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 6px;
        }}
        .check-item {{
            background: #fff;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 10px;
        }}
        .check-item.pass {{
            border-left: 3px solid #28a745;
        }}
        .check-item.fail {{
            border-left: 3px solid #dc3545;
        }}
        .check-name {{
            font-weight: 500;
            color: #495057;
        }}
        .check-status {{
            font-size: 9px;
            padding: 1px 4px;
            border-radius: 2px;
            margin-left: 4px;
        }}
        .check-status.pass {{
            background: #d4edda;
            color: #155724;
        }}
        .check-status.fail {{
            background: #f8d7da;
            color: #721c24;
        }}
        .check-feedback {{
            color: #6c757d;
            font-size: 9px;
            margin-top: 3px;
        }}
        .curriculum-box {{
            background: #fff3cd;
            border: 1px solid #ffc107;
            border-radius: 4px;
            padding: 10px;
            font-size: 10px;
        }}
        .curriculum-source {{
            font-weight: 600;
            color: #856404;
            margin-bottom: 4px;
        }}
        .curriculum-reasoning {{
            color: #664d03;
        }}
        .score-badge {{
            display: inline-block;
            background: #6c757d;
            color: #fff;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            font-weight: 500;
            margin-left: 8px;
        }}
        .score-badge.high {{
            background: #28a745;
        }}
        .score-badge.medium {{
            background: #ffc107;
            color: #212529;
        }}
        .score-badge.low {{
            background: #dc3545;
        }}
    </style>
</head>
<body>
    <div class="question-section">
        <div class="section-title">Soru</div>
        <div class="paragraph">{paragraph}</div>
        {image_html}
        <div class="question">{question}</div>
        <div class="options">
            {options_html}
        </div>
    </div>

    {option_reasoning_html}
    {validation_html}
    {curriculum_html}
</body>
</html>"""


def render_detailed_html(
    paragraph: str,
    question: str,
    options: dict,
    correct_answer: str,
    option_reasoning: dict | None = None,
    validation: dict | None = None,
    curriculum_source: str | None = None,
    curriculum_reasoning: str | None = None,
    image_base64: str | None = None,
    options_layout: str | None = None,
    option_images: dict[str, str] | None = None,
) -> str:
    """
    Render a detailed question view with metadata.

    This includes the question plus:
    - Option reasoning (why each option/distractor was designed)
    - Validation checks (pass/fail with feedback)
    - Curriculum grounding (MEB source reference)

    Args:
        paragraph: The educational paragraph
        question: The question text (stem)
        options: Dict with keys A, B, C, D mapping to option text
        correct_answer: The correct option letter
        option_reasoning: Dict with A, B, C, D keys, each containing
                         {strategy: str, reasoning: str}
        validation: Dict with 'checks' list and 'overall_score'
        curriculum_source: Source from MEB curriculum
        curriculum_reasoning: Why this matches curriculum

    Returns:
        Complete HTML string ready for rendering
    """
    # Order: normalize → hyphenate (on raw text) → escape (for HTML safety)
    escaped_paragraph = _escape_html(_hyphenate_turkish(_normalize_for_render(paragraph)))
    escaped_question = _escape_html(_hyphenate_turkish(_normalize_for_render(question)))

    # Split multi-text paragraphs (e.g., "1. Metin: ... 2. Metin: ...")
    # into separate divs with spacing, removing labels
    escaped_paragraph = _split_multi_text_paragraph(escaped_paragraph)

    # Check if paragraph is a titles list (for baslik_inverse format)
    escaped_paragraph, is_titles_list = _convert_titles_to_list(escaped_paragraph)

    # Build image HTML if provided
    image_html = ""
    if image_base64:
        image_html = f'<img src="data:image/png;base64,{image_base64}" alt="Diyagram" class="diagram"/>'

    # Build options HTML dynamically
    option_labels = sorted(options.keys())
    options_html_parts = []
    for label in option_labels:
        css_class = "correct" if label == correct_answer else ""
        if option_images and label in option_images:
            opt_content = (
                f'<img src="data:image/png;base64,{option_images[label]}" '
                f'alt="Secenek {label}" class="option-image" />'
            )
        else:
            opt_content = _escape_html(_normalize_for_render(options.get(label, "")))
        options_html_parts.append(
            f'<div class="option {css_class}"><span class="option-letter">{label})</span> {opt_content}</div>'
        )
    options_html = "\n            ".join(options_html_parts)

    # Build option reasoning HTML
    option_reasoning_html = ""
    if option_reasoning:
        items = []
        for opt in option_labels:
            reasoning_data = option_reasoning.get(opt, {})
            # Handle both single string and list of strategies
            strategy_raw = reasoning_data.get("strategy", "")
            if isinstance(strategy_raw, list):
                strategy = _escape_html(" + ".join(strategy_raw))
            else:
                strategy = _escape_html(str(strategy_raw) if strategy_raw else "")
            # Normalize strategy names to Turkish
            if strategy.upper() in ("CORRECT_ANSWER", "DOGRU_CEVAP", "DOĞRU_CEVAP"):
                strategy = "DOĞRU CEVAP"
            elif strategy.upper() in ("KONU_UYGUN", "KONUYA_UYGUN"):
                strategy = "KONUYA UYGUN"
            reasoning = _escape_html(reasoning_data.get("reasoning", ""))
            is_correct = "correct-answer" if opt == correct_answer else ""

            items.append(f"""
            <div class="reasoning-item {is_correct}">
                <div class="reasoning-option">{opt}) {_escape_html(options.get(opt, ''))}</div>
                <div class="reasoning-strategy">{strategy}</div>
                <div class="reasoning-text">{reasoning}</div>
            </div>
            """)

        option_reasoning_html = f"""
        <div class="metadata-section">
            <div class="section-title">Secenek Mantigi</div>
            <div class="reasoning-grid">
                {''.join(items)}
            </div>
        </div>
        """

    # Build validation HTML
    validation_html = ""
    if validation and validation.get("checks"):
        score = validation.get("overall_score", 0)
        # Score comes from batch_validator as 0-100 range
        score_class = "high" if score >= 80 else ("medium" if score >= 50 else "low")

        check_items = []
        for check in validation.get("checks", []):
            status = check.get("status", "PASS")
            status_class = "pass" if status == "PASS" else "fail"
            name = _escape_html(check.get("name", check.get("type", "")))
            feedback = _escape_html(check.get("feedback", ""))

            check_items.append(f"""
            <div class="check-item {status_class}">
                <span class="check-name">{name}</span>
                <span class="check-status {status_class}">{status}</span>
                <div class="check-feedback">{feedback}</div>
            </div>
            """)

        validation_html = f"""
        <div class="metadata-section">
            <div class="section-title">Dogrulama Kontrolleri
                <span class="score-badge {score_class}">{score:.0f}%</span>
            </div>
            <div class="validation-grid">
                {''.join(check_items)}
            </div>
        </div>
        """

    # Build curriculum HTML
    curriculum_html = ""
    if curriculum_source or curriculum_reasoning:
        source_html = (
            f'<div class="curriculum-source">'
            f'{_escape_html(curriculum_source or "")}</div>'
            if curriculum_source else ""
        )
        reasoning_html = (
            f'<div class="curriculum-reasoning">'
            f'{_escape_html(curriculum_reasoning or "")}</div>'
            if curriculum_reasoning else ""
        )

        curriculum_html = f"""
        <div class="metadata-section">
            <div class="section-title">Mufredat Eslesmesi</div>
            <div class="curriculum-box">
                {source_html}
                {reasoning_html}
            </div>
        </div>
        """

    # Add titles-list class if paragraph is a numbered list
    paragraph_class = "paragraph titles-list" if is_titles_list else "paragraph"

    html = HTML_DETAILED_TEMPLATE.format(
        paragraph=escaped_paragraph,
        question=escaped_question,
        options_html=options_html,
        correct_answer=correct_answer,
        image_html=image_html,
        option_reasoning_html=option_reasoning_html,
        validation_html=validation_html,
        curriculum_html=curriculum_html,
    )

    # Replace paragraph class if it's a titles list
    if is_titles_list:
        html = html.replace('class="paragraph"', f'class="{paragraph_class}"')

    # Add table-content, chart-content, or infographic-content class based on paragraph content
    if '<table' in escaped_paragraph.lower():
        html = html.replace('class="paragraph"', 'class="paragraph table-content"')
    elif 'class="chart"' in escaped_paragraph.lower() or "class='chart'" in escaped_paragraph.lower():
        html = html.replace('class="paragraph"', 'class="paragraph chart-content"')
    elif 'class="info-grid"' in escaped_paragraph.lower() or "class='info-grid'" in escaped_paragraph.lower() or 'class="process-flow"' in escaped_paragraph.lower() or "class='process-flow'" in escaped_paragraph.lower():
        html = html.replace('class="paragraph"', 'class="paragraph infographic-content"')

    # Apply layout for options
    if option_images:
        n_img = len(option_images)
        if n_img == 3:
            html = html.replace('class="options"', 'class="options image-options-3"')
        else:
            html = html.replace('class="options"', 'class="options image-options"')
    elif options_layout == "two_column":
        html = html.replace('class="options"', 'class="options two-column"')

    return html


# ============================================================================
# CONTEXT GROUP RENDERING
# ============================================================================

CONTEXT_GROUP_CSS = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="correct-answers" content="{correct_answers}">
    <style>
        body {{
            font-family: 'Times New Roman', serif;
            font-size: 12px;
            line-height: 1.4;
            padding: 12px 16px;
            max-width: 340px;
            background: #fff;
            color: #000;
            margin: 0;
        }}
        .group-header {{
            font-weight: bold;
            font-size: 12px;
            margin-bottom: 10px;
            text-align: center;
        }}
        .context-block {{
            text-align: justify;
            hyphens: manual;
            -webkit-hyphens: manual;
            margin-bottom: 14px;
            text-indent: 1.5em;
            padding-bottom: 10px;
            border-bottom: 1px solid #ccc;
        }}
        .context-block table {{
            width: 100%;
            border-collapse: collapse;
            margin: 8px 0;
            font-size: 11px;
            text-indent: 0;
            table-layout: fixed;
            word-wrap: break-word;
        }}
        .context-block table th,
        .context-block table td {{
            border: 1px solid #999;
            padding: 3px 6px;
            text-align: center;
            word-break: break-word;
            overflow-wrap: break-word;
            vertical-align: middle;
        }}
        .context-block table th {{
            background: #f0f0f0;
            font-weight: bold;
        }}
        .context-block .chart {{
            display: grid;
            grid-template-columns: auto 1fr auto;
            align-items: center;
            column-gap: 4px;
            row-gap: 4px;
            margin: 6px 0;
            text-indent: 0;
            font-size: 10px;
        }}
        .context-block .context-image {{
            display: block;
            width: 100%;
            max-width: 310px;
            height: auto;
            margin: 8px auto;
            text-indent: 0;
        }}
        .context-block .chart-row {{
            display: contents;
        }}
        .context-block .chart-label {{
            text-align: right;
            font-size: 10px;
            white-space: nowrap;
        }}
        .context-block .chart-bar {{
            height: 14px;
            background: linear-gradient(90deg, #4a90d9, #357abd);
            border-radius: 2px;
            min-width: 2px;
        }}
        .context-block .chart-val {{
            font-size: 9px;
            font-weight: bold;
            white-space: nowrap;
        }}
        .context-block .pie-chart {{
            text-indent: 0;
            text-align: center;
            margin: 8px 0;
        }}
        .context-block .pie-chart .pie {{
            width: 140px;
            height: 140px;
            border-radius: 50%;
            margin: 0 auto 8px auto;
        }}
        .context-block .pie-chart .pie-legend {{
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 4px 10px;
            font-size: 9px;
            text-indent: 0;
        }}
        .context-block .pie-chart .pie-legend-item {{
            display: flex;
            align-items: center;
            gap: 3px;
        }}
        .context-block .pie-chart .pie-legend-color {{
            width: 10px;
            height: 10px;
            border-radius: 2px;
            flex-shrink: 0;
        }}
        .question-card {{
            margin-bottom: 12px;
            padding-bottom: 8px;
        }}
        .question-card:not(:last-child) {{
            border-bottom: 1px dashed #ddd;
        }}
        .question {{
            font-weight: normal;
            margin-bottom: 8px;
            word-wrap: break-word;
        }}
        .question-number {{
            font-weight: bold;
            display: inline;
            margin-right: 2px;
        }}
        .question b {{
            font-weight: bold;
        }}
        .question u {{
            text-decoration: underline;
        }}
        .options {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .option {{
            display: flex;
            gap: 6px;
            align-items: flex-start;
        }}
        .option-letter {{
            font-weight: normal;
            flex-shrink: 0;
            min-width: 18px;
        }}
        /* ── Extra context block styles ── */
        .context-block.chart-content {{
            text-indent: 0;
            text-align: left;
        }}
        /* ── Infografik styles for context groups ── */
        .context-block.infographic-content {{
            text-indent: 0;
            text-align: left;
        }}
        /* ═══ FORMAT: Özellik Tablosu (X işaretli) ═══ */
        .context-block .dialogue {{ margin: 8px 0; font-size: 11px; }}
        .context-block .dialogue p {{ margin: 3px 0; text-indent: 0; text-align: left; }}
        .context-block .dialogue .speaker {{ font-weight: bold; }}
        .context-block .feature-note {{ font-size: 10px; font-style: italic; margin: 6px 0 4px 0; text-indent: 0; }}
        .context-block table.feature-table {{
            width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 10px; text-indent: 0;
        }}
        .context-block table.feature-table th,
        .context-block table.feature-table td {{
            border: 1px solid #999; padding: 4px 5px; text-align: center; vertical-align: middle;
        }}
        .context-block table.feature-table th {{
            background: #e8e8e8; font-weight: bold; font-size: 10px;
        }}
        .context-block table.feature-table td:first-child {{
            text-align: left; font-weight: bold;
        }}
        .context-block table.feature-table .check {{
            color: #2d6a2d; font-weight: bold; font-size: 13px;
        }}
        /* ═══ FORMAT: Basit Veri Tablosu (renkli başlık) ═══ */
        .context-block table.data-table {{
            width: 100%; margin: 10px 0; border-collapse: collapse; font-size: 11px; text-indent: 0;
            table-layout: auto;
        }}
        .context-block table.data-table th,
        .context-block table.data-table td {{
            white-space: nowrap;
            padding: 5px 10px;
        }}
        .context-block table.data-table td:last-child,
        .context-block table.data-table th:last-child {{
            white-space: normal; word-break: break-word;
        }}
        .context-block table.data-table th {{
            background: #4a90d9; color: #fff; font-weight: bold; padding: 6px 16px; border: 1px solid #3a7bc8; text-align: center;
        }}
        .context-block table.data-table td {{
            padding: 5px 16px; border: 1px solid #ccc; text-align: center;
        }}
        .context-block table.data-table tr:nth-child(even) td {{
            background: #f5f8fc;
        }}
        /* ═══ FORMAT: Sütun Grafiği (Tekli — dikey bar chart) ═══ */
        .context-block .bar-chart-container {{ margin: 10px 0; text-indent: 0; }}
        .context-block .y-axis-title {{ font-size: 10px; font-weight: bold; text-align: center; margin-bottom: 2px; }}
        .context-block .bar-chart {{
            display: flex; align-items: flex-end; justify-content: center; gap: 20px;
            height: 160px; border-left: 2px solid #333; border-bottom: 2px solid #333;
            padding: 0 15px 0 30px; position: relative; margin-bottom: 4px;
        }}
        .context-block .bar-chart .y-axis {{
            position: absolute; left: -28px; top: 0; bottom: 0;
            display: flex; flex-direction: column-reverse; justify-content: space-between;
            font-size: 9px; color: #555;
        }}
        .context-block .bar-chart .y-axis span {{ display: block; }}
        .context-block .bar-column {{ display: flex; flex-direction: column; align-items: center; gap: 2px; }}
        .context-block .bar-column .bar {{
            width: 42px; background: #4a90d9; border-radius: 2px 2px 0 0; position: relative;
        }}
        .context-block .bar-column .bar-value {{
            font-size: 10px; font-weight: bold; color: #fff;
            position: absolute; top: 4px; left: 0; right: 0; text-align: center;
        }}
        .context-block .bar-column .bar-label {{
            font-size: 9px; text-align: center; max-width: 70px; line-height: 1.2; margin-top: 4px;
        }}
        /* ═══ FORMAT: Gruplu Sütun Grafiği (çift renk + legend) ═══ */
        .context-block .grouped-chart-container {{ margin: 8px 0; text-indent: 0; }}
        .context-block .grouped-chart-title {{ font-weight: bold; font-size: 11px; text-align: center; margin-bottom: 4px; }}
        .context-block .grouped-chart-subtitle {{ font-size: 10px; text-align: center; margin-bottom: 8px; color: #555; }}
        .context-block .grouped-bar-chart {{
            display: flex; align-items: flex-end; justify-content: center; gap: 24px;
            height: 160px; border-left: 2px solid #333; border-bottom: 2px solid #333;
            padding: 0 10px 0 30px; position: relative;
        }}
        .context-block .grouped-bar-chart .y-axis {{
            position: absolute; left: -28px; top: 0; bottom: 0;
            display: flex; flex-direction: column-reverse; justify-content: space-between;
            font-size: 9px; color: #555;
        }}
        .context-block .bar-group {{ display: flex; flex-direction: column; align-items: center; gap: 2px; }}
        .context-block .bar-pair {{ display: flex; align-items: flex-end; gap: 2px; }}
        .context-block .bar-pair .bar {{ width: 24px; border-radius: 2px 2px 0 0; position: relative; }}
        .context-block .bar-pair .bar .bar-value {{
            font-size: 8px; font-weight: bold; color: #fff;
            position: absolute; top: 2px; left: 0; right: 0; text-align: center;
        }}
        .context-block .bar-pair .bar.color-a {{ background: #2c5282; }}
        .context-block .bar-pair .bar.color-b {{ background: #dd6b20; }}
        .context-block .bar-group .bar-label {{ font-size: 9px; text-align: center; margin-top: 4px; }}
        .context-block .chart-legend {{ display: flex; justify-content: center; gap: 16px; margin-top: 8px; font-size: 10px; }}
        .context-block .legend-item {{ display: flex; align-items: center; gap: 4px; }}
        .context-block .legend-color {{ width: 12px; height: 12px; border-radius: 2px; }}
        .context-block .legend-color.color-a {{ background: #2c5282; }}
        .context-block .legend-color.color-b {{ background: #dd6b20; }}
        /* ═══ FORMAT: Gazete Haberi ═══ */
        .context-block .newspaper {{
            border: 2px solid #666; border-radius: 4px; padding: 12px 14px;
            background: linear-gradient(135deg, #fafafa 0%, #f0f0f0 100%);
            box-shadow: 2px 2px 6px rgba(0,0,0,0.1); margin: 6px 0;
        }}
        .context-block .newspaper-top {{
            display: flex; justify-content: space-between; align-items: center;
            font-size: 9px; color: #666; margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid #ccc;
        }}
        .context-block .newspaper-badge {{
            background: #333; color: #fff; padding: 1px 6px; border-radius: 2px;
            font-size: 8px; font-weight: bold; letter-spacing: 0.5px;
        }}
        .context-block .newspaper-title {{
            font-family: Georgia, 'Times New Roman', serif; font-size: 20px; font-weight: bold;
            text-align: center; margin: 8px 0; line-height: 1.2; color: #1a1a1a;
        }}
        .context-block .newspaper-subtitle {{ font-weight: bold; font-size: 11px; margin-bottom: 6px; color: #333; }}
        .context-block .newspaper-body {{ font-size: 11px; text-align: justify; line-height: 1.5; color: #222; }}
        /* ═══ FORMAT: Bilgi Kartları (iki sütunlu, renkli) ═══ */
        .context-block .info-cards-container {{
            display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; text-indent: 0;
        }}
        .context-block .info-card-block {{
            background: #e8f4f8; border-radius: 6px; padding: 10px; border: 1px solid #b8d8e8;
        }}
        .context-block .info-card-block.color-b {{ background: #fce8e8; border-color: #e8b8b8; }}
        .context-block .info-card-block.color-c {{ background: #e8f8e8; border-color: #b8e8b8; }}
        .context-block .info-card-block.color-d {{ background: #f8f0e0; border-color: #e8d8b0; }}
        .context-block .info-card-block .card-title {{
            font-weight: bold; font-size: 12px; text-align: center; margin-bottom: 6px; color: #1a1a1a;
        }}
        .context-block .info-card-block .card-body {{
            font-size: 11px; text-align: left; line-height: 1.4; color: #222;
        }}
        .context-block .info-title {{
            font-weight: bold;
            font-size: 12px;
            text-align: center;
            margin-bottom: 8px;
            padding-bottom: 4px;
            border-bottom: 2px solid #4a90d9;
        }}
        .context-block .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 6px;
            margin: 6px 0;
        }}
        .context-block .info-card {{
            background: #f0f7ff;
            border: 1px solid #b8d4f0;
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 10px;
        }}
        .context-block .info-card-title {{
            font-weight: bold;
            font-size: 10px;
            color: #2c5282;
            margin-bottom: 4px;
            padding-bottom: 3px;
            border-bottom: 1px solid #b8d4f0;
        }}
        .context-block .info-card-body {{
            font-size: 9px;
            line-height: 1.3;
            color: #333;
        }}
        .context-block .info-card-body ul {{
            margin: 2px 0;
            padding-left: 12px;
        }}
        .context-block .info-card-body li {{
            margin-bottom: 1px;
        }}
        .context-block .process-flow {{
            display: flex;
            align-items: stretch;
            gap: 2px;
            margin: 6px 0;
            flex-wrap: wrap;
        }}
        .context-block .process-step {{
            flex: 1;
            min-width: 55px;
            background: #e8f4e8;
            border: 1px solid #90c090;
            border-radius: 4px;
            padding: 5px 6px;
            font-size: 9px;
            text-align: center;
        }}
        .context-block .process-step-title {{
            font-weight: bold;
            font-size: 9px;
            color: #2d6a2d;
            margin-bottom: 2px;
        }}
        .context-block .process-step-desc {{
            font-size: 8px;
            color: #444;
        }}
        .context-block .process-arrow {{
            display: flex;
            align-items: center;
            font-size: 14px;
            color: #666;
            padding: 0 1px;
        }}
    </style>
</head>
<body>
    {body_content}
</body>
</html>"""


def _fix_table_html(text: str) -> str:
    """Fix common LLM table HTML issues: missing cells, unclosed tags, inconsistent columns."""
    if "<table" not in text.lower():
        return text

    import re as _re

    # Fix unclosed table tags
    for tag in ["table", "tr", "th", "td", "thead", "tbody"]:
        open_count = len(_re.findall(rf"<{tag}[\s>]", text, _re.IGNORECASE))
        close_count = len(_re.findall(rf"</{tag}>", text, _re.IGNORECASE))
        if open_count > close_count:
            for _ in range(open_count - close_count):
                # Find last occurrence of opening tag and add closing before </table> or at end
                text = _re.sub(
                    rf"(.*<{tag}\b[^>]*>(?:(?!</{tag}>).)*?)(\s*</(tr|table)>)",
                    rf"\1</{tag}>\2",
                    text,
                    count=1,
                    flags=_re.IGNORECASE | _re.DOTALL,
                )

    # Normalize column counts: find max columns and pad short rows
    table_match = _re.search(r"<table\b[^>]*>(.*?)</table>", text, _re.IGNORECASE | _re.DOTALL)
    if table_match:
        table_content = table_match.group(1)
        rows = _re.findall(r"<tr\b[^>]*>(.*?)</tr>", table_content, _re.IGNORECASE | _re.DOTALL)
        if rows:
            col_counts = []
            for row in rows:
                cells = _re.findall(r"<(?:th|td)\b[^>]*>", row, _re.IGNORECASE)
                col_counts.append(len(cells))
            max_cols = max(col_counts) if col_counts else 0

            if max_cols > 0:
                new_table_content = table_content
                for row in rows:
                    cells = _re.findall(r"<(?:th|td)\b[^>]*>", row, _re.IGNORECASE)
                    n = len(cells)
                    if 0 < n < max_cols:
                        # Determine cell type from first cell in row
                        cell_tag = "th" if "<th" in row.lower() else "td"
                        padding = f"<{cell_tag}>&ndash;</{cell_tag}>" * (max_cols - n)
                        padded_row = row.rstrip()
                        # Insert before </tr> equivalent (end of row content)
                        padded_row = _re.sub(
                            rf"(.*)((</{cell_tag}>)\s*)$",
                            rf"\1\2{padding}",
                            padded_row,
                            flags=_re.IGNORECASE | _re.DOTALL,
                        )
                        new_table_content = new_table_content.replace(row, padded_row)
                text = text[:table_match.start(1)] + new_table_content + text[table_match.end(1):]

    return text


def _escape_html_preserve_tables(text: str) -> str:
    """Escape HTML but preserve table-related tags and br/b/u tags.

    Also decodes common HTML entities that LLMs may produce (&rarr;, &quot;, etc.)
    back to their unicode characters before escaping.
    """
    if not text:
        return ""

    import html as _html

    # Step 0: Decode any HTML entities the LLM may have generated
    # e.g. &rarr; → →, &quot; → ", &amp; → &
    text = _html.unescape(text)

    # Step 0.5: Fix broken table HTML (missing cells, unclosed tags)
    text = _fix_table_html(text)

    # Step 0.6: Convert <strong>→<b>, <em>→<u> (LLM sometimes uses these)
    text = re.sub(r'<strong\b[^>]*>', '<b>', text, flags=re.IGNORECASE)
    text = re.sub(r'</strong>', '</b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<em\b[^>]*>', '<u>', text, flags=re.IGNORECASE)
    text = re.sub(r'</em>', '</u>', text, flags=re.IGNORECASE)

    protected: list[str] = []

    def protect_tag(match):
        protected.append(match.group(0))
        return f"\x00[{len(protected)-1}]\x00"

    # Protect table tags + formatting tags + chart div/span tags
    result = re.sub(
        r'</?(?:table|tr|th|td|thead|tbody|br|b|u|div|span)\b[^>]*>',
        protect_tag,
        text,
        flags=re.IGNORECASE,
    )

    # Escape only dangerous chars (not quotes — they're fine in text content)
    result = (
        result
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    # Restore protected tags
    for i, tag in enumerate(protected):
        result = result.replace(f"\x00[{i}]\x00", tag)

    return result


def render_context_group_html(
    header_text: str,
    context_text: str,
    questions: list[dict],
    correct_answers: list[str] | None = None,
    image_base64: str | None = None,
    background_color: str | None = None,
) -> str:
    """Render a context-based question group as HTML.

    Args:
        header_text: Group header (e.g., "(1-4). soruları ... cevaplayınız.")
        context_text: Shared context text (may contain HTML tables)
        questions: List of question dicts with keys:
            question, options (dict A/B/C/D)
        correct_answers: Optional list of correct answer letters (for meta tag)
        image_base64: Optional base64-encoded PNG image to embed between context and questions

    Returns:
        Complete HTML string for the group.
    """
    # Build header
    escaped_header = _escape_html(header_text, preserve_formatting=True)

    # Escape context but preserve table tags
    escaped_context = _escape_html_preserve_tables(
        _hyphenate_turkish(_normalize_for_render(context_text))
    )

    # Build question cards
    question_cards = []
    for i, q_data in enumerate(questions, 1):
        raw_q = _ensure_bold_stem(q_data.get("question", ""))
        q_text = _escape_html(
            _hyphenate_turkish(_normalize_for_render(raw_q)),
            preserve_formatting=True,
        )
        options = q_data.get("options", {})
        option_images = q_data.get("option_images") or {}

        opts_html = []
        # Only render labels that exist in the options dict (supports 3-option templates)
        _present_labels = [l for l in ["A", "B", "C", "D", "E"] if l in options]
        if not _present_labels:
            _present_labels = sorted(options.keys())
        for letter in _present_labels:
            if option_images and letter in option_images:
                opts_html.append(
                    f'<div class="option"><span class="option-letter">{letter})</span> '
                    f'<img src="data:image/png;base64,{option_images[letter]}" '
                    f'alt="Secenek {letter}" class="option-image" /></div>'
                )
            else:
                opt_text = _escape_html(_normalize_for_render(options.get(letter, "")))
                opts_html.append(
                    f'<div class="option"><span class="option-letter">{letter})</span> {opt_text}</div>'
                )

        card = f"""<div class="question-card">
        <div class="question"><span class="question-number">{i}.</span> {q_text}</div>
        <div class="options">
            {''.join(opts_html)}
        </div>
    </div>"""
        question_cards.append(card)

    # Determine context-block CSS class based on content
    context_class = "context-block"
    lower_ctx = escaped_context.lower()
    # New visual formats need text-indent:0
    needs_no_indent = any(cls in lower_ctx for cls in [
        'class="bar-chart"', 'class="grouped-bar-chart"', 'class="bar-chart-container"',
        'class="grouped-chart-container"', 'class="newspaper"',
        'class="feature-table"', 'class="data-table"',
        'class="dialogue"',
        'class="info-cards-container"', 'class="info-card-block"',
    ])
    if needs_no_indent or '<table' in lower_ctx:
        pass  # styles scoped under .context-block — text-indent handled per element
    elif 'class="chart"' in lower_ctx or "class='chart'" in lower_ctx:
        context_class = "context-block chart-content"
    elif any(cls in lower_ctx for cls in ['class="info-grid"', "class='info-grid'", 'class="process-flow"', "class='process-flow'"]):
        context_class = "context-block infographic-content"

    # Build optional image HTML (between context and questions)
    image_html = ""
    if image_base64:
        image_html = f'<img src="data:image/png;base64,{image_base64}" alt="Gorsel" class="context-image"/>'
        # When infographic image exists, remove HTML tables from rendered
        # context to avoid showing the same data twice (table + image overlap).
        # The table data is already represented in the infographic image.
        escaped_context = re.sub(r'<table[\s\S]*?</table>', '', escaped_context)
        # Remove orphaned bold title at the end (was the table's heading)
        escaped_context = re.sub(r'(<br\s*/?>[\s]*)*<b>[^<]*</b>[\s]*(<br\s*/?>[\s]*)*$', '', escaped_context)
        # Clean up trailing br tags
        escaped_context = re.sub(r'(<br\s*/?>[\s]*)+$', '', escaped_context)

    # Apply background color to context block if specified
    bg_style_attr = ""
    if background_color:
        bg_style_attr = (
            f' style="background: {background_color}; border-radius: 6px; '
            f'padding: 12px; border: 1px solid {background_color}88;"'
        )

    body = f"""<div class="group-header">{escaped_header}</div>
    <div class="{context_class}"{bg_style_attr}>{escaped_context}{image_html}</div>
    {''.join(question_cards)}"""

    # Build correct answer meta (comma-separated)
    ca_str = ",".join(correct_answers) if correct_answers else ""

    return CONTEXT_GROUP_CSS.format(
        correct_answers=ca_str,
        body_content=body,
    )


_DETAILED_CONTEXT_GROUP_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="correct-answers" content="{correct_answers}">
    <style>
        body {{
            font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
            font-size: 11px;
            line-height: 1.4;
            padding: 16px;
            max-width: 700px;
            background: #fff;
            color: #1a1a1a;
            margin: 0;
        }}
        .question-section {{
            background: #fafafa;
            border: 1px solid #e0e0e0;
            border-radius: 6px;
            padding: 14px;
            margin-bottom: 14px;
        }}
        .section-title {{
            font-size: 10px;
            font-weight: 600;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 10px;
            padding-bottom: 6px;
            border-bottom: 1px solid #eee;
        }}
        .question-card {{
            margin-bottom: 12px;
            padding-bottom: 8px;
        }}
        .question-card:not(:last-child) {{
            border-bottom: 1px dashed #ddd;
        }}
        .question {{
            font-weight: normal;
            margin-bottom: 8px;
            font-family: 'Times New Roman', serif;
            font-size: 12px;
            word-wrap: break-word;
        }}
        .question b {{ font-weight: bold; }}
        .question u {{ text-decoration: underline; }}
        .question-number {{
            font-weight: bold;
            display: inline;
            margin-right: 2px;
        }}
        .options {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            font-family: 'Times New Roman', serif;
            font-size: 12px;
        }}
        .option {{
            display: flex;
            gap: 6px;
            align-items: flex-start;
        }}
        .option-letter {{
            font-weight: normal;
            flex-shrink: 0;
            min-width: 18px;
        }}
        .correct {{
            color: #0a7c42;
            font-weight: 600;
        }}
        /* ── Context block styles ── */
        .context-block table {{
            width: 100%;
            border-collapse: collapse;
            margin: 8px 0;
            font-size: 11px;
            table-layout: fixed;
            word-wrap: break-word;
        }}
        .context-block table th,
        .context-block table td {{
            border: 1px solid #999;
            padding: 3px 6px;
            text-align: center;
            word-break: break-word;
            vertical-align: middle;
        }}
        .context-block table th {{
            background: #f0f0f0;
            font-weight: bold;
        }}
        .context-block.chart-content {{ text-indent: 0; text-align: left; }}
        .context-block .chart {{ margin: 6px 0; }}
        .context-block .chart-row {{ display: flex; align-items: center; margin-bottom: 4px; font-size: 10px; }}
        .context-block .chart-label {{ width: 80px; flex-shrink: 0; text-align: right; padding-right: 6px; font-size: 10px; }}
        .context-block .chart-bar {{ height: 14px; background: linear-gradient(90deg, #4a90d9, #357abd); border-radius: 2px; min-width: 2px; }}
        .context-block .chart-val {{ padding-left: 4px; font-size: 9px; font-weight: bold; white-space: nowrap; }}
        .context-block.infographic-content {{ text-indent: 0; text-align: left; }}
        .context-block .info-title {{ font-weight: bold; font-size: 12px; text-align: center; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 2px solid #4a90d9; }}
        .context-block .info-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 6px; margin: 6px 0; }}
        .context-block .info-card {{ background: #f0f7ff; border: 1px solid #b8d4f0; border-radius: 4px; padding: 6px 8px; font-size: 10px; }}
        .context-block .info-card-title {{ font-weight: bold; font-size: 10px; color: #2c5282; margin-bottom: 4px; padding-bottom: 3px; border-bottom: 1px solid #b8d4f0; }}
        .context-block .info-card-body {{ font-size: 9px; line-height: 1.3; color: #333; }}
        .context-block .info-card-body ul {{ margin: 2px 0; padding-left: 12px; }}
        .context-block .info-card-body li {{ margin-bottom: 1px; }}
        .context-block .process-flow {{ display: flex; align-items: stretch; gap: 2px; margin: 6px 0; flex-wrap: wrap; }}
        .context-block .process-step {{ flex: 1; min-width: 55px; background: #e8f4e8; border: 1px solid #90c090; border-radius: 4px; padding: 5px 6px; font-size: 9px; text-align: center; }}
        .context-block .process-step-title {{ font-weight: bold; font-size: 9px; color: #2d6a2d; margin-bottom: 2px; }}
        .context-block .process-step-desc {{ font-size: 8px; color: #444; }}
        .context-block .process-arrow {{ display: flex; align-items: center; font-size: 14px; color: #666; padding: 0 1px; }}
        /* ═══ Yeni görsel formatlar (detailed) ═══ */
        .context-block .dialogue {{ margin: 8px 0; font-size: 11px; }}
        .context-block .dialogue p {{ margin: 3px 0; text-indent: 0; text-align: left; }}
        .context-block .dialogue .speaker {{ font-weight: bold; }}
        .context-block .feature-note {{ font-size: 10px; font-style: italic; margin: 6px 0 4px 0; text-indent: 0; }}
        .context-block table.feature-table {{ width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 10px; text-indent: 0; }}
        .context-block table.feature-table th, .context-block table.feature-table td {{ border: 1px solid #999; padding: 4px 5px; text-align: center; vertical-align: middle; }}
        .context-block table.feature-table th {{ background: #e8e8e8; font-weight: bold; font-size: 10px; }}
        .context-block table.feature-table td:first-child {{ text-align: left; font-weight: bold; }}
        .context-block table.feature-table .check {{ color: #2d6a2d; font-weight: bold; font-size: 13px; }}
        .context-block table.data-table {{ width: 100%; margin: 10px 0; border-collapse: collapse; font-size: 11px; text-indent: 0; word-break: keep-all; white-space: nowrap; }}
        .context-block table.data-table th {{ background: #4a90d9; color: #fff; font-weight: bold; padding: 6px 16px; border: 1px solid #3a7bc8; text-align: center; }}
        .context-block table.data-table td {{ padding: 5px 16px; border: 1px solid #ccc; text-align: center; }}
        .context-block table.data-table tr:nth-child(even) td {{ background: #f5f8fc; }}
        .context-block .bar-chart-container {{ margin: 10px 0; text-indent: 0; }}
        .context-block .y-axis-title {{ font-size: 10px; font-weight: bold; text-align: center; margin-bottom: 2px; }}
        .context-block .bar-chart {{ display: flex; align-items: flex-end; justify-content: center; gap: 20px; height: 160px; border-left: 2px solid #333; border-bottom: 2px solid #333; padding: 0 15px 0 30px; position: relative; margin-bottom: 4px; }}
        .context-block .bar-chart .y-axis {{ position: absolute; left: -28px; top: 0; bottom: 0; display: flex; flex-direction: column-reverse; justify-content: space-between; font-size: 9px; color: #555; }}
        .context-block .bar-chart .y-axis span {{ display: block; }}
        .context-block .bar-column {{ display: flex; flex-direction: column; align-items: center; gap: 2px; }}
        .context-block .bar-column .bar {{ width: 42px; background: #4a90d9; border-radius: 2px 2px 0 0; position: relative; }}
        .context-block .bar-column .bar-value {{ font-size: 10px; font-weight: bold; color: #fff; position: absolute; top: 4px; left: 0; right: 0; text-align: center; }}
        .context-block .bar-column .bar-label {{ font-size: 9px; text-align: center; max-width: 70px; line-height: 1.2; margin-top: 4px; }}
        .context-block .grouped-chart-container {{ margin: 8px 0; text-indent: 0; }}
        .context-block .grouped-chart-title {{ font-weight: bold; font-size: 11px; text-align: center; margin-bottom: 4px; }}
        .context-block .grouped-bar-chart {{ display: flex; align-items: flex-end; justify-content: center; gap: 24px; height: 160px; border-left: 2px solid #333; border-bottom: 2px solid #333; padding: 0 10px 0 30px; position: relative; }}
        .context-block .grouped-bar-chart .y-axis {{ position: absolute; left: -28px; top: 0; bottom: 0; display: flex; flex-direction: column-reverse; justify-content: space-between; font-size: 9px; color: #555; }}
        .context-block .bar-group {{ display: flex; flex-direction: column; align-items: center; gap: 2px; }}
        .context-block .bar-pair {{ display: flex; align-items: flex-end; gap: 2px; }}
        .context-block .bar-pair .bar {{ width: 24px; border-radius: 2px 2px 0 0; position: relative; }}
        .context-block .bar-pair .bar .bar-value {{ font-size: 8px; font-weight: bold; color: #fff; position: absolute; top: 2px; left: 0; right: 0; text-align: center; }}
        .context-block .bar-pair .bar.color-a {{ background: #2c5282; }}
        .context-block .bar-pair .bar.color-b {{ background: #dd6b20; }}
        .context-block .bar-group .bar-label {{ font-size: 9px; text-align: center; margin-top: 4px; }}
        .context-block .chart-legend {{ display: flex; justify-content: center; gap: 16px; margin-top: 8px; font-size: 10px; }}
        .context-block .legend-item {{ display: flex; align-items: center; gap: 4px; }}
        .context-block .legend-color {{ width: 12px; height: 12px; border-radius: 2px; }}
        .context-block .legend-color.color-a {{ background: #2c5282; }}
        .context-block .legend-color.color-b {{ background: #dd6b20; }}
        .context-block .newspaper {{ border: 2px solid #666; border-radius: 4px; padding: 12px 14px; background: linear-gradient(135deg, #fafafa 0%, #f0f0f0 100%); box-shadow: 2px 2px 6px rgba(0,0,0,0.1); margin: 6px 0; }}
        .context-block .newspaper-top {{ display: flex; justify-content: space-between; align-items: center; font-size: 9px; color: #666; margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px solid #ccc; }}
        .context-block .newspaper-badge {{ background: #333; color: #fff; padding: 1px 6px; border-radius: 2px; font-size: 8px; font-weight: bold; letter-spacing: 0.5px; }}
        .context-block .newspaper-title {{ font-family: Georgia, 'Times New Roman', serif; font-size: 20px; font-weight: bold; text-align: center; margin: 8px 0; line-height: 1.2; color: #1a1a1a; }}
        .context-block .newspaper-subtitle {{ font-weight: bold; font-size: 11px; margin-bottom: 6px; color: #333; }}
        .context-block .newspaper-body {{ font-size: 11px; text-align: justify; line-height: 1.5; color: #222; }}
        /* ═══ FORMAT: Bilgi Kartları (iki sütunlu, renkli) ═══ */
        .context-block .info-cards-container {{
            display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; text-indent: 0;
        }}
        .context-block .info-card-block {{
            background: #e8f4f8; border-radius: 6px; padding: 10px; border: 1px solid #b8d8e8;
        }}
        .context-block .info-card-block.color-b {{ background: #fce8e8; border-color: #e8b8b8; }}
        .context-block .info-card-block.color-c {{ background: #e8f8e8; border-color: #b8e8b8; }}
        .context-block .info-card-block.color-d {{ background: #f8f0e0; border-color: #e8d8b0; }}
        .context-block .info-card-block .card-title {{
            font-weight: bold; font-size: 12px; text-align: center; margin-bottom: 6px; color: #1a1a1a;
        }}
        .context-block .info-card-block .card-body {{
            font-size: 11px; text-align: left; line-height: 1.4; color: #222;
        }}
        /* ── Metadata section styles ── */
        .metadata-section {{
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 12px;
        }}
        .reasoning-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
        }}
        .reasoning-item {{
            background: #fff;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 8px;
            font-size: 10px;
        }}
        .reasoning-item.correct-answer {{
            border-color: #28a745;
            background: #f0fff4;
        }}
        .reasoning-option {{ font-weight: 600; color: #495057; margin-bottom: 4px; }}
        .reasoning-strategy {{ color: #6c757d; font-style: italic; margin-bottom: 2px; }}
        .reasoning-text {{ color: #212529; }}
        .validation-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 6px;
        }}
        .check-item {{
            background: #fff;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 10px;
        }}
        .check-item.pass {{ border-left: 3px solid #28a745; }}
        .check-item.fail {{ border-left: 3px solid #dc3545; }}
        .check-name {{ font-weight: 500; color: #495057; }}
        .check-status {{ font-size: 9px; padding: 1px 4px; border-radius: 2px; margin-left: 4px; }}
        .check-status.pass {{ background: #d4edda; color: #155724; }}
        .check-status.fail {{ background: #f8d7da; color: #721c24; }}
        .check-feedback {{ color: #6c757d; font-size: 9px; margin-top: 3px; }}
        .curriculum-box {{
            background: #fff3cd;
            border: 1px solid #ffc107;
            border-radius: 4px;
            padding: 10px;
            font-size: 10px;
        }}
        .curriculum-source {{ font-weight: 600; color: #856404; margin-bottom: 4px; }}
        .curriculum-reasoning {{ color: #664d03; }}
        .score-badge {{
            display: inline-block;
            background: #6c757d;
            color: #fff;
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            font-weight: 500;
            margin-left: 8px;
        }}
        .score-badge.high {{ background: #28a745; }}
        .score-badge.medium {{ background: #ffc107; color: #212529; }}
        .score-badge.low {{ background: #dc3545; }}
    </style>
</head>
<body>
    {body_content}
</body>
</html>"""


def render_detailed_context_group_html(
    header_text: str,
    context_text: str,
    questions: list[dict],
    correct_answers: list[str],
    option_reasonings: list[dict | None] | None = None,
    validations: list[dict | None] | None = None,
    cross_validation: dict | None = None,
    curriculum_source: str | None = None,
    curriculum_reasoning: str | None = None,
    image_base64: str | None = None,
) -> str:
    """Render a detailed context group view with metadata for each sub-question.

    Includes correct answers highlighted, option reasoning, validation checks,
    cross-validation results, and curriculum grounding.

    Args:
        header_text: Group header
        context_text: Shared context text (may contain HTML)
        questions: List of question dicts (question, options)
        correct_answers: List of correct answer letters per question
        option_reasonings: List of option_reasoning dicts per question
        validations: List of validation dicts per question
        cross_validation: Cross-validation result dict
        curriculum_source: MEB source reference
        curriculum_reasoning: Why this matches curriculum
    """
    escaped_header = _escape_html(header_text, preserve_formatting=True)
    escaped_context = _escape_html_preserve_tables(
        _hyphenate_turkish(_normalize_for_render(context_text))
    )

    # Determine context CSS class
    context_class = "context-block"
    lower_ctx = escaped_context.lower()
    needs_no_indent = any(cls in lower_ctx for cls in [
        'class="bar-chart"', 'class="grouped-bar-chart"', 'class="bar-chart-container"',
        'class="grouped-chart-container"', 'class="newspaper"',
        'class="feature-table"', 'class="data-table"',
        'class="dialogue"',
        'class="info-cards-container"', 'class="info-card-block"',
    ])
    if needs_no_indent:
        pass  # styles scoped under .context-block
    elif 'class="chart"' in lower_ctx or "class='chart'" in lower_ctx:
        context_class = "context-block chart-content"
    elif any(cls in lower_ctx for cls in ['class="info-grid"', "class='info-grid'", 'class="process-flow"', "class='process-flow'"]):
        context_class = "context-block infographic-content"

    # Build question cards with correct answer highlighting
    question_cards = []
    for i, q_data in enumerate(questions):
        raw_q = _ensure_bold_stem(q_data.get("question", ""))
        q_text = _escape_html(
            _hyphenate_turkish(_normalize_for_render(raw_q)),
            preserve_formatting=True,
        )
        options = q_data.get("options", {})
        correct = correct_answers[i] if i < len(correct_answers) else ""

        opts_html = []
        for letter in ["A", "B", "C", "D"]:
            opt_text = _escape_html(_normalize_for_render(options.get(letter, "")))
            css_class = "correct" if letter == correct else ""
            opts_html.append(
                f'<div class="option {css_class}"><span class="option-letter">{letter})</span> {opt_text}</div>'
            )

        card = f"""<div class="question-card">
        <div class="question"><span class="question-number">{i + 1}.</span> {q_text}</div>
        <div class="options">
            {''.join(opts_html)}
        </div>
    </div>"""
        question_cards.append(card)

    # Build per-question metadata sections
    metadata_sections = []
    for i, q_data in enumerate(questions):
        options = q_data.get("options", {})
        correct = correct_answers[i] if i < len(correct_answers) else ""
        option_labels = sorted(options.keys())

        # Option reasoning
        reasoning_html = ""
        if option_reasonings and i < len(option_reasonings) and option_reasonings[i]:
            items = []
            for opt in option_labels:
                reasoning_data = option_reasonings[i].get(opt, {})
                strategy_raw = reasoning_data.get("strategy", "")
                if isinstance(strategy_raw, list):
                    strategy = _escape_html(" + ".join(strategy_raw))
                else:
                    strategy = _escape_html(str(strategy_raw) if strategy_raw else "")
                if strategy.upper() in ("CORRECT_ANSWER", "DOGRU_CEVAP", "DOĞRU_CEVAP"):
                    strategy = "DOĞRU CEVAP"
                reasoning = _escape_html(reasoning_data.get("reasoning", ""))
                is_correct = "correct-answer" if opt == correct else ""
                items.append(f"""
                <div class="reasoning-item {is_correct}">
                    <div class="reasoning-option">{opt}) {_escape_html(options.get(opt, ''))}</div>
                    <div class="reasoning-strategy">{strategy}</div>
                    <div class="reasoning-text">{reasoning}</div>
                </div>""")
            reasoning_html = f"""
            <div class="reasoning-grid">
                {''.join(items)}
            </div>"""

        # Validation checks
        validation_html = ""
        if validations and i < len(validations) and validations[i]:
            val = validations[i]
            score = val.get("overall_score", 0)
            score_class = "high" if score >= 80 else ("medium" if score >= 50 else "low")
            check_items = []
            for check in val.get("checks", []):
                status = check.get("status", "PASS")
                status_class = "pass" if status == "PASS" else "fail"
                name = _escape_html(check.get("name", check.get("type", "")))
                feedback = _escape_html(check.get("feedback", ""))
                check_items.append(f"""
                <div class="check-item {status_class}">
                    <span class="check-name">{name}</span>
                    <span class="check-status {status_class}">{status}</span>
                    <div class="check-feedback">{feedback}</div>
                </div>""")
            validation_html = f"""
            <div class="validation-grid">
                {''.join(check_items)}
            </div>
            <div style="margin-top:4px;font-size:9px;color:#666;">Puan: <span class="score-badge {score_class}">{score:.0f}%</span></div>"""

        if reasoning_html or validation_html:
            metadata_sections.append(f"""
    <div class="metadata-section">
        <div class="section-title">Soru {i + 1} Detay</div>
        {reasoning_html}
        {validation_html}
    </div>""")

    # Cross-validation section
    cross_val_html = ""
    if cross_validation:
        passed = cross_validation.get("passed", True)
        issues = cross_validation.get("issues", [])
        dup_answers = cross_validation.get("duplicate_answers", [])
        overlap_dist = cross_validation.get("overlapping_distractors", [])

        status_text = "GECTI" if passed else "BASARISIZ"
        status_class = "pass" if passed else "fail"

        details = []
        if dup_answers:
            details.append(f"Tekrar eden cevaplar: {', '.join(dup_answers)}")
        if overlap_dist:
            details.append(f"Cakisan celdiriciler: {', '.join(overlap_dist)}")
        if issues:
            details.extend(issues)

        details_html = "".join(
            f'<div class="check-feedback">{_escape_html(d)}</div>' for d in details
        )

        cross_val_html = f"""
    <div class="metadata-section">
        <div class="section-title">Capraz Dogrulama
            <span class="check-status {status_class}">{status_text}</span>
        </div>
        {details_html}
    </div>"""

    # Curriculum section
    curriculum_html = ""
    if curriculum_source or curriculum_reasoning:
        source_html = f'<div class="curriculum-source">{_escape_html(curriculum_source or "")}</div>' if curriculum_source else ""
        reasoning_html_c = f'<div class="curriculum-reasoning">{_escape_html(curriculum_reasoning or "")}</div>' if curriculum_reasoning else ""
        curriculum_html = f"""
    <div class="metadata-section">
        <div class="section-title">Mufredat Eslesmesi</div>
        <div class="curriculum-box">
            {source_html}
            {reasoning_html_c}
        </div>
    </div>"""

    # Build optional image HTML for detailed view
    detail_image_html = ""
    if image_base64:
        detail_image_html = f'<img src="data:image/png;base64,{image_base64}" alt="Gorsel" style="display:block;width:100%;max-width:500px;height:auto;margin:8px auto;"/>'
        # Remove HTML tables from context when image exists (same data shown as image)
        escaped_context = re.sub(r'<table[\s\S]*?</table>', '', escaped_context)
        escaped_context = re.sub(r'(<br\s*/?>[\s]*)*<b>[^<]*</b>[\s]*(<br\s*/?>[\s]*)*$', '', escaped_context)
        escaped_context = re.sub(r'(?:<br\s*/?>[\s]*)+$', '', escaped_context).strip()

    # Assemble body content
    body_content = f"""
    <div class="question-section">
        <div class="section-title">Baglam Sorusu Grubu</div>
        <div class="group-header" style="font-size:11px;margin-bottom:8px;text-align:center;">{escaped_header}</div>
        <div class="{context_class}" style="font-family:'Times New Roman',serif;font-size:12px;text-align:justify;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid #ccc;">{escaped_context}</div>
        {detail_image_html}
        {''.join(question_cards)}
    </div>
    {''.join(metadata_sections)}
    {cross_val_html}
    {curriculum_html}"""

    ca_str = ",".join(correct_answers)

    return _DETAILED_CONTEXT_GROUP_TEMPLATE.format(
        correct_answers=ca_str,
        body_content=body_content,
    )


# ============================================================================
# MULTI-QUESTION HTML RENDER
# ============================================================================


def render_multi_question_html(
    paragraph: str,
    questions: list[dict],
    image_base64: str | None = None,
) -> str:
    """
    Render multiple questions sharing a single paragraph.

    Each question dict should have: question, options, correct_answer.

    Args:
        paragraph: Shared paragraph text
        questions: List of question dicts with question/options/correct_answer
        image_base64: Optional diagram image

    Returns:
        Complete HTML string with one paragraph and N question blocks
    """
    escaped_paragraph = _escape_html(_hyphenate_turkish(_normalize_for_render(paragraph)))

    image_html = ""
    if image_base64:
        image_html = f'<img src="data:image/png;base64,{image_base64}" alt="Diyagram" class="diagram"/>'

    question_blocks = []
    for i, q in enumerate(questions, 1):
        raw_q = _ensure_bold_stem(q.get("question", ""))
        escaped_q = _escape_html(_hyphenate_turkish(_normalize_for_render(raw_q)))
        opts = q.get("options", {})
        correct = q.get("correct_answer", "")

        option_divs = []
        for label in sorted(opts.keys()):
            css_class = "correct" if label == correct else ""
            escaped_opt = _escape_html(_normalize_for_render(opts.get(label, "")))
            option_divs.append(
                f'<div class="option {css_class}">'
                f'<span class="option-letter">{label})</span> {escaped_opt}</div>'
            )

        question_blocks.append(
            f'<div class="question-block">\n'
            f'    <div class="question-number">SORU {i}:</div>\n'
            f'    <div class="question">{escaped_q}</div>\n'
            f'    <div class="options">\n        '
            + "\n        ".join(option_divs)
            + "\n    </div>\n</div>"
        )

    # Determine paragraph CSS class
    paragraph_class = "paragraph"
    if '<table' in escaped_paragraph.lower():
        paragraph_class = "paragraph table-content"
    elif 'class="chart"' in escaped_paragraph.lower() or "class='chart'" in escaped_paragraph.lower():
        paragraph_class = "paragraph chart-content"
    elif 'class="info-grid"' in escaped_paragraph.lower() or "class='info-grid'" in escaped_paragraph.lower() or 'class="process-flow"' in escaped_paragraph.lower() or "class='process-flow'" in escaped_paragraph.lower():
        paragraph_class = "paragraph infographic-content"

    body_content = (
        f'<div class="{paragraph_class}">{escaped_paragraph}</div>\n'
        f"    {image_html}\n"
        + "\n    ".join(question_blocks)
    )

    return CSS_WRAPPER.format(
        correct_answer="multi",
        body_content=body_content,
    )
