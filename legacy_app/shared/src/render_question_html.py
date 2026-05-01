from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


def _get_capture_selector() -> str:
    return ".question-container"


def render_question_html(
    html_path: str | Path,
    output_dir: str | Path | None = None,
    answer_text: str | None = None,
) -> tuple[str, str]:
    """Render a local question HTML file into standard and detailed PNGs."""
    html_path = Path(html_path).resolve()
    if output_dir is None:
        output_dir = html_path.parent
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    question_png = output_dir / "question.png"
    detailed_png = output_dir / "question_detailed.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            standard_page = browser.new_page(
                viewport={"width": 900, "height": 1200},
                device_scale_factor=1.5,
            )
            try:
                standard_page.goto(html_path.as_uri(), wait_until="load")
                standard_target = standard_page.locator(_get_capture_selector())
                if standard_target.count() == 0:
                    standard_target = standard_page.locator("body")
                standard_target.screenshot(path=str(question_png))
            finally:
                standard_page.close()

            detailed_page = browser.new_page(
                viewport={"width": 1400, "height": 2200},
                device_scale_factor=2,
            )
            try:
                detailed_page.goto(html_path.as_uri(), wait_until="load")
                if answer_text:
                    detailed_page.evaluate(
                        """
                        ([selector, answerText]) => {
                          const root = document.querySelector(selector) || document.body;
                          const card = document.createElement('div');
                          card.className = 'detailed-answer-box';
                          card.innerHTML = `<strong>Cevap:</strong> ${answerText}`;
                          card.style.marginTop = '20px';
                          card.style.padding = '14px 18px';
                          card.style.borderRadius = '12px';
                          card.style.background = '#ecfdf5';
                          card.style.border = '2px solid #10b981';
                          card.style.color = '#065f46';
                          card.style.fontSize = '28px';
                          card.style.fontWeight = '600';
                          root.appendChild(card);
                        }
                        """,
                        [_get_capture_selector(), answer_text],
                    )
                detailed_target = detailed_page.locator(_get_capture_selector())
                if detailed_target.count() == 0:
                    detailed_target = detailed_page.locator("body")
                detailed_target.screenshot(path=str(detailed_png))
            finally:
                detailed_page.close()
        finally:
            browser.close()

    return str(question_png), str(detailed_png)
