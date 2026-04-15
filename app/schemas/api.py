from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.domain import HtmlValidationResult, LayoutPlan, QuestionLayoutValidationResult, QuestionSpec, ValidationRule


class RetryConfig(BaseModel):
    question_max_retries: int | None = None
    layout_max_retries: int | None = None
    html_max_retries: int | None = None
    image_max_retries: int | None = None
    rule_eval_parallelism: int | None = None


class FullPipelineRunRequest(BaseModel):
    yaml_filename: str
    retry_config: RetryConfig | None = None


class RuntimeInfoResponse(BaseModel):
    use_stub_agents: bool
    text_model: str
    light_model: str
    image_model: str
    has_google_api_key: bool
    has_anthropic_api_key: bool


class YamlFilesResponse(BaseModel):
    files: list[str] = Field(default_factory=list)


class YamlFileContentResponse(BaseModel):
    filename: str
    data: dict[str, Any]


class SpFilesResponse(BaseModel):
    files: list[str] = Field(default_factory=list)


class SpJsonFileResponse(BaseModel):
    filename: str
    data: dict[str, Any]


class SpHtmlFileResponse(BaseModel):
    filename: str
    html_content: str


class FullPipelineRunResponse(BaseModel):
    pipeline_id: str
    sub_pipeline_ids: dict[str, str]
    question_json: QuestionSpec
    layout_plan_json: LayoutPlan
    question_html: dict[str, Any]
    rendered_image_path: str | None = None


class YamlToQuestionRunRequest(BaseModel):
    yaml_filename: str
    retry_config: RetryConfig | None = None


class YamlToQuestionRunResponse(BaseModel):
    sub_pipeline_id: str
    question_json: QuestionSpec
    rule_evaluation: dict[str, Any]
    attempts: int


class QuestionToLayoutRunRequest(BaseModel):
    question_json: QuestionSpec
    retry_config: RetryConfig | None = None


class QuestionToLayoutRunResponse(BaseModel):
    sub_pipeline_id: str
    layout_plan_json: LayoutPlan
    validation: QuestionLayoutValidationResult
    attempts: int


class LayoutToHtmlRunRequest(BaseModel):
    question_json: QuestionSpec
    layout_plan_json: LayoutPlan
    retry_config: RetryConfig | None = None


class LayoutToHtmlRunResponse(BaseModel):
    sub_pipeline_id: str
    question_html: dict[str, Any]
    validation: HtmlValidationResult
    attempts: int
    generated_assets: dict[str, str] = Field(default_factory=dict)
    rendered_image_path: str | None = None


class StandaloneGenerateQuestionRequest(BaseModel):
    yaml_content: dict[str, Any]
    feedback: str | None = None


class StandaloneGenerateLayoutRequest(BaseModel):
    question_json: QuestionSpec
    feedback: str | None = None


class StandaloneGenerateHtmlRequest(BaseModel):
    question_json: QuestionSpec
    layout_plan_json: LayoutPlan
    feedback: str | None = None
    asset_map: dict[str, str] = Field(default_factory=dict)


class StandaloneExtractRulesRequest(BaseModel):
    yaml_content: dict[str, Any]


class StandaloneEvaluateRuleRequest(BaseModel):
    rule: ValidationRule
    question_json: QuestionSpec


class StandaloneQuestionLayoutValidationRequest(BaseModel):
    question_json: QuestionSpec
    layout_plan_json: LayoutPlan


class StandaloneLayoutHtmlValidationRequest(BaseModel):
    html_content: str
    rendered_image_path: str | None = None
    asset_map: dict[str, str] = Field(default_factory=dict)
    layout_plan_json: LayoutPlan | None = None


class StandaloneGenerateCompositeImageRequest(BaseModel):
    asset: dict[str, Any]


class StandaloneAgentResponse(BaseModel):
    run_id: str
    result: Any


class PipelineGetResponse(BaseModel):
    id: str
    mode: str
    yaml_filename: str
    status: str
    retry_config: Any
    error: str | None = None
    created_at: str
    finished_at: str | None = None


class SubPipelineGetResponse(BaseModel):
    id: str
    pipeline_id: str | None
    mode: str
    kind: str
    status: str
    input_json: Any
    output_json: Any | None
    error: str | None
    created_at: str
    finished_at: str | None


class PipelineAgentLinkResponse(BaseModel):
    id: int
    pipeline_id: str | None
    sub_pipeline_id: str | None
    agent_name: str
    agent_table: str
    agent_run_id: str
    created_at: str


class PipelineLogEntryResponse(BaseModel):
    id: int
    pipeline_id: str | None
    sub_pipeline_id: str | None
    mode: str
    level: str
    component: str
    message: str
    details: Any | None = None
    created_at: str


class AgentRunGetResponse(BaseModel):
    id: str
    mode: str
    pipeline_id: str | None
    sub_pipeline_id: str | None
    attempt_no: int
    status: str
    input_json: Any
    output_json: Any | None
    feedback_text: str | None
    error: str | None
    model_name: str
    question_id: str | None = None
    schema_version: str | None = None
    started_at: str
    finished_at: str | None
