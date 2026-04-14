from __future__ import annotations

from pydantic import BaseModel


class GeneratedHtml(BaseModel):
    selected_template: str = "default"
    html_content: str
    schema_version: str = "question-html.v1"


class CompositeImageResult(BaseModel):
    asset_slug: str
    image_path: str
    note: str = ""
