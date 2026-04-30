"""
Visual format post-processor for context HTML.

Transforms LLM-generated content into styled visual formats:
- feature_table: X-mark comparison table with dialogue
- data_table: Clean 2-3 column table with blue header
- bar_chart: Vertical bar chart (single color)
- grouped_bar_chart: Grouped bar chart (two colors + legend)
- newspaper: Newspaper article layout

The LLM generates standard HTML (tables, text). This module adds CSS classes
and transforms table data into chart HTML when needed.
"""

import logging
import re

logger = logging.getLogger(__name__)


def apply_visual_format(html: str, visual_format: str | None) -> str:
    """Apply visual format post-processing to context HTML.

    Args:
        html: Raw HTML from LLM (context paragraph).
        visual_format: Format type or None for default.

    Returns:
        Transformed HTML with proper CSS classes.
    """
    if not visual_format:
        return html

    fmt = visual_format.lower().strip()
    if fmt == "feature_table":
        return _apply_feature_table(html)
    elif fmt == "data_table":
        return _apply_data_table(html)
    elif fmt == "bar_chart":
        return _apply_bar_chart(html)
    elif fmt == "grouped_bar_chart":
        return _apply_grouped_bar_chart(html)
    elif fmt == "newspaper":
        return _apply_newspaper(html)
    elif fmt == "info_cards":
        return _apply_info_cards(html)
    else:
        logger.warning(f"[VISUAL_FORMAT] Unknown format: {fmt}, returning as-is")
        return html


# ═══════════════════════════════════════════════════════════════
# TABLE FORMATS — Add CSS classes to existing <table> tags
# ═══════════════════════════════════════════════════════════════

def _apply_feature_table(html: str) -> str:
    """Add feature-table class and convert empty cells to X marks if needed."""
    # Add class to table
    html = re.sub(
        r'<table(?:\s+class="[^"]*")?',
        '<table class="feature-table"',
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    logger.info("[VISUAL_FORMAT] Applied feature_table class")
    return html


def _apply_data_table(html: str) -> str:
    """Add data-table class for blue-header styling."""
    html = re.sub(
        r'<table(?:\s+class="[^"]*")?',
        '<table class="data-table"',
        html,
        count=1,
        flags=re.IGNORECASE,
    )
    logger.info("[VISUAL_FORMAT] Applied data_table class")
    return html


# ═══════════════════════════════════════════════════════════════
# CHART FORMATS — Extract table data → build chart HTML
# ═══════════════════════════════════════════════════════════════

def _extract_table_data(html: str) -> tuple[str, list[list[str]]]:
    """Extract table data from HTML and return (html_without_table, rows).

    Returns:
        Tuple of (html with table removed, list of rows where each row is list of cell texts)
    """
    table_match = re.search(r'<table\b[^>]*>.*?</table>', html, re.DOTALL | re.IGNORECASE)
    if not table_match:
        return html, []

    table_html = table_match.group(0)
    html_without = html[:table_match.start()] + html[table_match.end():]
    # Clean trailing <br>
    html_without = re.sub(r'(?:<br\s*/?>[\s]*)+$', '', html_without).strip()

    rows = []
    for tr_match in re.finditer(r'<tr\b[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE):
        cells = []
        for cell_match in re.finditer(r'<t[hd]\b[^>]*>(.*?)</t[hd]>', tr_match.group(1), re.DOTALL | re.IGNORECASE):
            cell_text = re.sub(r'<[^>]+>', '', cell_match.group(1)).strip()
            cells.append(cell_text)
        if cells:
            rows.append(cells)

    return html_without, rows


def _parse_numeric(text: str) -> float | None:
    """Try to extract a number from text like '600 birim' or '%34'."""
    m = re.search(r'[%]?\s*(\d+(?:[.,]\d+)?)', text.replace(',', '.'))
    if m:
        return float(m.group(1))
    return None


def _apply_bar_chart(html: str) -> str:
    """Convert table data to single-color vertical bar chart."""
    text_part, rows = _extract_table_data(html)
    if len(rows) < 2:
        logger.warning("[VISUAL_FORMAT] bar_chart: Not enough table rows, returning as-is")
        return html

    # First row = headers, rest = data
    headers = rows[0]
    data_rows = rows[1:]

    # Determine which column has the label and which has the value
    # Try: col 0 = label, col 1 = value (most common)
    categories = []
    for row in data_rows:
        if len(row) < 2:
            continue
        label = row[0]
        val = _parse_numeric(row[1]) if len(row) > 1 else None
        if val is None and len(row) > 2:
            val = _parse_numeric(row[2])
        if val is not None:
            categories.append((label, val))

    if not categories:
        logger.warning("[VISUAL_FORMAT] bar_chart: Could not parse numeric data, returning as-is")
        return html

    max_val = max(v for _, v in categories)
    # Y axis title from header
    y_title = headers[1] if len(headers) > 1 else "Değer"

    # Build y-axis labels (0 to nearest round number above max)
    y_max = _nice_max(max_val)
    step = _nice_step(y_max)
    y_labels = list(range(0, int(y_max) + 1, int(step)))

    chart_height = 160  # px
    y_spans = ''.join(f'<span>{v}</span>' for v in y_labels)

    bars_html = ''
    for label, val in categories:
        bar_h = int((val / y_max) * chart_height) if y_max > 0 else 0
        bar_h = max(bar_h, 4)  # minimum visible
        display_val = int(val) if val == int(val) else val
        bars_html += f"""<div class="bar-column">
            <div class="bar" style="height: {bar_h}px;"><span class="bar-value">{display_val}</span></div>
            <div class="bar-label">{label}</div>
        </div>\n"""

    chart_html = f"""<div class="bar-chart-container">
        <div class="y-axis-title">{y_title}</div>
        <div class="bar-chart">
            <div class="y-axis">{y_spans}</div>
            {bars_html}
        </div>
    </div>"""

    result = text_part + '<br>' + chart_html if text_part else chart_html
    logger.info(f"[VISUAL_FORMAT] Converted table to bar_chart ({len(categories)} bars)")
    return result


def _apply_grouped_bar_chart(html: str) -> str:
    """Convert table data to grouped bar chart (two colors + legend)."""
    text_part, rows = _extract_table_data(html)
    if len(rows) < 2:
        logger.warning("[VISUAL_FORMAT] grouped_bar_chart: Not enough rows, returning as-is")
        return html

    headers = rows[0]
    data_rows = rows[1:]

    # Need at least 3 columns: label, group_a, group_b
    if len(headers) < 3:
        logger.warning("[VISUAL_FORMAT] grouped_bar_chart: Need 3+ columns, falling back to bar_chart")
        return _apply_bar_chart(html)

    group_a_name = headers[1]
    group_b_name = headers[2]

    groups = []
    for row in data_rows:
        if len(row) < 3:
            continue
        label = row[0]
        val_a = _parse_numeric(row[1])
        val_b = _parse_numeric(row[2])
        if val_a is not None and val_b is not None:
            groups.append((label, val_a, val_b))

    if not groups:
        logger.warning("[VISUAL_FORMAT] grouped_bar_chart: Could not parse data, returning as-is")
        return html

    all_vals = [v for _, a, b in groups for v in (a, b)]
    max_val = max(all_vals)
    y_max = _nice_max(max_val)
    step = _nice_step(y_max)
    y_labels = list(range(0, int(y_max) + 1, int(step)))

    chart_height = 160
    y_spans = ''.join(f'<span>{v}</span>' for v in y_labels)

    # Determine chart title from context type or headers
    chart_title = f"Grafik: {headers[0]} Karşılaştırması" if headers else "Grafik"

    bars_html = ''
    for label, val_a, val_b in groups:
        h_a = int((val_a / y_max) * chart_height) if y_max > 0 else 0
        h_b = int((val_b / y_max) * chart_height) if y_max > 0 else 0
        h_a = max(h_a, 4)
        h_b = max(h_b, 4)
        d_a = int(val_a) if val_a == int(val_a) else val_a
        d_b = int(val_b) if val_b == int(val_b) else val_b
        bars_html += f"""<div class="bar-group">
            <div class="bar-pair">
                <div class="bar color-a" style="height: {h_a}px;"><span class="bar-value">{d_a}</span></div>
                <div class="bar color-b" style="height: {h_b}px;"><span class="bar-value">{d_b}</span></div>
            </div>
            <div class="bar-label">{label}</div>
        </div>\n"""

    chart_html = f"""<div class="grouped-chart-container">
        <div class="grouped-chart-title">{chart_title}</div>
        <div class="grouped-bar-chart">
            <div class="y-axis">{y_spans}</div>
            {bars_html}
        </div>
        <div class="chart-legend">
            <div class="legend-item"><div class="legend-color color-a"></div> {group_a_name}</div>
            <div class="legend-item"><div class="legend-color color-b"></div> {group_b_name}</div>
        </div>
    </div>"""

    result = text_part + '<br>' + chart_html if text_part else chart_html
    logger.info(f"[VISUAL_FORMAT] Converted table to grouped_bar_chart ({len(groups)} groups)")
    return result


# ═══════════════════════════════════════════════════════════════
# NEWSPAPER FORMAT — Wrap text in newspaper layout
# ═══════════════════════════════════════════════════════════════

def _apply_newspaper(html: str) -> str:
    """Wrap content in newspaper article layout.

    Tries to extract: title (first bold text), subtitle, body.
    Falls back to wrapping everything as newspaper body.
    """
    import random

    # Metinden tarih çıkarmaya çalış
    date_match = re.search(r'(\d{1,2})\s*(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)\s*(\d{4})?', html)
    if date_match:
        day = date_match.group(1)
        month = date_match.group(2)
        year = date_match.group(3) or "2025"
        date_str = f"{day} {month} {year}"
    else:
        date_str = ""

    # Try to extract title from bold text at the beginning
    title = ""
    subtitle = ""
    body = html

    # Look for a bold title pattern
    title_match = re.match(r'^(?:<br\s*/?>)*\s*(?:<b>(.*?)</b>|<strong>(.*?)</strong>)', html, re.IGNORECASE)
    if title_match:
        title = title_match.group(1) or title_match.group(2) or ""
        body = html[title_match.end():]
        # Clean leading <br>
        body = re.sub(r'^(?:<br\s*/?>[\s]*)+', '', body).strip()

    # If no bold title, try first line as title
    if not title:
        # Split by <br> and take first segment as title
        parts = re.split(r'<br\s*/?>', html, maxsplit=1)
        if len(parts) >= 2 and len(parts[0].strip()) < 80:
            title = re.sub(r'<[^>]+>', '', parts[0]).strip()
            body = parts[1].strip()
        else:
            # Just use first sentence as title
            sentences = re.split(r'(?<=[.!?])\s+', re.sub(r'<[^>]+>', '', html), maxsplit=1)
            if len(sentences) >= 2:
                title = sentences[0]
                body = html.replace(sentences[0], '', 1).strip()
                body = re.sub(r'^(?:<br\s*/?>[\s]*)+', '', body).strip()

    # Extract subtitle (first sentence of body)
    body_text = re.sub(r'<[^>]+>', '', body).strip()
    sent_match = re.match(r'^([^.!?]+[.!?])\s*', body_text)
    if sent_match and len(sent_match.group(1)) < 100:
        subtitle = sent_match.group(1)
        # Remove subtitle from body
        body_clean = body_text[len(subtitle):].strip()
    else:
        subtitle = ""
        body_clean = body_text

    # Detect news category
    categories = {
        "çevre": "Çevre", "doğa": "Çevre", "ağaç": "Çevre", "kirlil": "Çevre",
        "okul": "Eğitim", "öğrenci": "Eğitim", "kitap": "Eğitim", "ders": "Eğitim",
        "yardım": "Yerel Haber", "mahalle": "Yerel Haber", "bakkal": "Yerel Haber",
        "spor": "Spor", "yarış": "Spor", "takım": "Spor",
        "sağlık": "Sağlık", "hastane": "Sağlık",
        "kültür": "Kültür-Sanat", "müze": "Kültür-Sanat", "sergi": "Kültür-Sanat",
    }
    category = "Yerel Haber"
    lower_body = body_text.lower()
    for keyword, cat in categories.items():
        if keyword in lower_body:
            category = cat
            break

    newspaper_html = f"""<div class="newspaper">
        <div class="newspaper-top">
            <span>{date_str}</span>
            <span class="newspaper-badge">HABER</span>
            <span>{category}</span>
        </div>
        <div class="newspaper-title">{title or 'Haber'}</div>
        {'<div class="newspaper-subtitle">' + subtitle + '</div>' if subtitle else ''}
        <div class="newspaper-body">{body_clean}</div>
    </div>"""

    logger.info(f"[VISUAL_FORMAT] Applied newspaper format (title: {title[:40]}...)")
    return newspaper_html


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════
# INFO CARDS FORMAT — Split text blocks into colored cards
# ═══════════════════════════════════════════════════════════════

def _apply_info_cards(html: str) -> str:
    """Convert text blocks into two-column colored info cards WITHOUT titles.

    Splits by separator marker or double <br>, puts each block into a colored card.
    No card titles — just the text body.
    """
    # Try splitting by custom separator first
    if '---KART-AYIRICI---' in html:
        # Remove the bold tags around separator
        clean = re.sub(r'<b>\s*---KART-AYIRICI---\s*</b>', '---KART-AYIRICI---', html)
        blocks = clean.split('---KART-AYIRICI---')
    else:
        # AYIRICI yoksa split yapma — tüm metni tek blok olarak al
        blocks = [html]

    # Clean blocks
    cleaned_blocks = []
    for block in blocks:
        b = block.strip()
        b = re.sub(r'^(?:<br\s*/?>[\s]*)+', '', b)
        b = re.sub(r'(?:<br\s*/?>[\s]*)+$', '', b)
        b = re.sub(r'<br\s*/?>', ' ', b).strip()
        # Remove any remaining bold tags that look like titles
        b = re.sub(r'^<b>[IVX\d\.\s:]+(?:Kart|Metin|Bölüm)[^<]*</b>\s*', '', b, flags=re.IGNORECASE)
        if b and len(b) > 20:  # Minimum meaningful block
            cleaned_blocks.append(b)

    if len(cleaned_blocks) < 1:
        logger.warning("[VISUAL_FORMAT] info_cards: No text blocks found, returning as-is")
        return html

    # Tek blok gelirse → rastgele renkli tek kart (1Q sorular için)
    if len(cleaned_blocks) == 1:
        import random
        single_colors = ["", "color-b", "color-c", "color-d"]
        color = random.choice(single_colors)
        cards_html = f"""<div class="info-card-block {color}">
            <div class="card-body">{cleaned_blocks[0]}</div>
        </div>"""
        logger.info(f"[VISUAL_FORMAT] Applied info_cards format (1 card, color={color or 'blue'})")
        return cards_html

    colors = ["", "color-b", "color-c", "color-d"]
    cards = []
    for idx, block in enumerate(cleaned_blocks):
        color_class = colors[idx % len(colors)]
        cards.append(f"""<div class="info-card-block {color_class}">
            <div class="card-body">{block}</div>
        </div>""")

    cards_html = f"""<div class="info-cards-container">
        {''.join(cards)}
    </div>"""

    logger.info(f"[VISUAL_FORMAT] Applied info_cards format ({len(cards)} cards, no titles)")
    return cards_html


# ═══════════════════════════════════════════════════════════════

def _nice_max(val: float) -> float:
    """Round up to a nice axis maximum."""
    if val <= 10:
        return 10
    elif val <= 20:
        return 20
    elif val <= 50:
        return 50
    elif val <= 100:
        return 100
    elif val <= 200:
        return 200
    elif val <= 500:
        return 500
    else:
        return ((val // 100) + 1) * 100


def _nice_step(y_max: float) -> float:
    """Determine nice step size for y-axis labels."""
    if y_max <= 10:
        return 2
    elif y_max <= 20:
        return 5
    elif y_max <= 50:
        return 10
    elif y_max <= 100:
        return 10
    elif y_max <= 200:
        return 20
    elif y_max <= 500:
        return 50
    else:
        return 100
