from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class EntitySpec(BaseModel):
    name: str
    description: str = Field(description="Short description / role of the entity.")
    quantity: int = Field(ge=0)
    children: list["EntitySpec"] = Field(default_factory=list, description="Child entities contained within this entity. Optional. Max depth of nesting should be limited to 2.")


class QuestionSceneSpec(BaseModel):
    """Spec for a question's scene / background / environment."""

    enabled: bool
    description_prompt: str = Field(
        default="",
        description=(
            "Detailed prompt describing the scene to be generated. "
            "The scene should leave enough empty space for foreground entities."
        ),
    )
    color_scheme: str = ""

    @model_validator(mode="after")
    def _validate_scene(self) -> "QuestionSceneSpec":
        if self.enabled and not self.description_prompt.strip():
            raise ValueError("scene.enabled=true iken description_prompt zorunludur")
        return self


class QuestionCharacterSpec(BaseModel):
    name: str
    description: str = Field(description="Short description / role of the character in the scenario.")


class QuestionScenarioSpec(BaseModel):
    entities: list[EntitySpec] = Field(
        default_factory=list,
        description="List of entities involved in the scenario.",
    )
    scenes: list[QuestionSceneSpec] = Field(
        default_factory=list,
        description=(
            "List of scene/background specs. "
            "A question may include one or more scenes."
        ),
    )
    characters: list[QuestionCharacterSpec] = Field(
        default_factory=list,
        description="List of characters involved in the scenario. Optional.",
    )
    story: str = Field(
        default="",
        description="Short story/context for the question.",
    )

    @model_validator(mode="before")
    @classmethod
    def _backward_compatible_scene_field(cls, data):
        if isinstance(data, dict) and "scenes" not in data and "scene" in data:
            scene = data.get("scene")
            data = {**data, "scenes": [scene] if scene else []}
        return data


class QuestionOptionSpec(BaseModel):
    label: str = Field(description="Label of the option, e.g. A, B, C.")
    modality: Literal["text", "visual"]
    is_correct: bool
    content: str | list[EntitySpec] = Field(
        description=(
            "If modality=text, content must be string. "
            "If modality=visual, content must be list[EntitySpec]."
        )
    )

    @model_validator(mode="after")
    def _validate_content(self) -> "QuestionOptionSpec":
        self.label = self.label.strip().upper()
        if self.modality == "text" and not isinstance(self.content, str):
            raise ValueError("modality=text için content string olmalı")
        if self.modality == "visual" and not isinstance(self.content, list):
            raise ValueError("modality=visual için content list[EntitySpec] olmalı")
        return self


class QuestionSpec(BaseModel):
    question_id: str = Field(description="Unique identifier for the question.")
    scenario: QuestionScenarioSpec = Field(description="Spec for scenario.")
    options: list[QuestionOptionSpec] = Field(description="List of options.")
    solution: list[str] = Field(description="Brief solution / explanation.")
    stem: str = Field(description="The actual question")
    grade: Literal[1, 2, 3, 4, 5, 6, 7, 8] = Field(description="Grade level from 1 to 8.")
    difficulty: Literal["easy", "medium", "hard"]
    schema_version: str = "question-spec.v1"

    @model_validator(mode="after")
    def _validate_options(self) -> "QuestionSpec":
        if not self.options:
            raise ValueError("En az bir seçenek olmalı")
        labels = [opt.label for opt in self.options]
        if len(set(labels)) != len(labels):
            raise ValueError("Option label değerleri benzersiz olmalı")
        correct_count = sum(1 for opt in self.options if opt.is_correct)
        if correct_count != 1:
            raise ValueError("Tam olarak bir seçenek is_correct=true olmalı")
        return self
