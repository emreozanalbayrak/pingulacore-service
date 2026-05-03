from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.domain import HtmlValidationResult, LayoutPlan, QuestionLayoutValidationResult, QuestionSpec, ValidationRule


class CreateStreamKeyResponse(BaseModel):
    stream_key: str


class RetryConfig(BaseModel):
    question_max_retries: int | None = None
    layout_max_retries: int | None = None
    html_max_retries: int | None = None
    image_max_retries: int | None = None
    rule_eval_parallelism: int | None = None


class FullPipelineRunRequest(BaseModel):
    yaml_instance_id: str
    retry_config: RetryConfig | None = None
    stream_key: str | None = None


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


class SpFileItemResponse(BaseModel):
    filename: str
    is_favorite: bool = False


class SpFilesResponse(BaseModel):
    files: list[str] = Field(default_factory=list)
    items: list[SpFileItemResponse] = Field(default_factory=list)


class SpJsonFileResponse(BaseModel):
    filename: str
    data: dict[str, Any]


class SpHtmlFileResponse(BaseModel):
    filename: str
    html_content: str


class SpFileFavoriteRequest(BaseModel):
    is_favorite: bool


ExplorerRoot = Literal["runs", "sp_files"]


class ExplorerTreeNode(BaseModel):
    name: str
    path: str
    kind: Literal["file", "dir"]
    size: int | None = None
    modified_at: str | None = None
    is_favorite: bool = False
    favoritable: bool = False
    children: list["ExplorerTreeNode"] = Field(default_factory=list)


class ExplorerTreeResponse(BaseModel):
    root: ExplorerRoot
    path: str | None = None
    items: list[ExplorerTreeNode] = Field(default_factory=list)


class ExplorerFileReadResponse(BaseModel):
    root: ExplorerRoot
    path: str
    filename: str
    content_type: Literal["json", "html", "text", "image", "binary"]
    content: Any | None = None
    mime_type: str | None = None
    asset_url: str | None = None


class ExplorerFavoriteRequest(BaseModel):
    root: ExplorerRoot
    path: str
    is_favorite: bool


class ExplorerFavoriteResponse(BaseModel):
    root: ExplorerRoot
    path: str
    is_favorite: bool


class FavoriteCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["question", "layout"]
    data: dict[str, Any]
    source_sub_pipeline_id: str | None = None


class FavoriteResponse(BaseModel):
    id: int
    name: str
    kind: Literal["question", "layout"]
    data: dict[str, Any]
    source_sub_pipeline_id: str | None = None
    created_at: str


class FullPipelineRunResponse(BaseModel):
    pipeline_id: str
    sub_pipeline_ids: dict[str, str]
    question_artifact_id: str
    layout_artifact_id: str
    html_artifact_id: str
    rendered_image_artifact_id: str | None = None
    question_json: QuestionSpec
    layout_plan_json: LayoutPlan
    question_html: dict[str, Any]


class YamlToQuestionRunRequest(BaseModel):
    yaml_instance_id: str
    retry_config: RetryConfig | None = None
    stream_key: str | None = None


class YamlToQuestionRunResponse(BaseModel):
    sub_pipeline_id: str
    question_artifact_id: str
    question_json: QuestionSpec
    rule_evaluation: dict[str, Any]
    attempts: int


class QuestionToLayoutRunRequest(BaseModel):
    question_artifact_id: str
    retry_config: RetryConfig | None = None
    stream_key: str | None = None


class QuestionToLayoutRunResponse(BaseModel):
    sub_pipeline_id: str
    layout_artifact_id: str
    layout_plan_json: LayoutPlan
    validation: QuestionLayoutValidationResult
    attempts: int


class LayoutToHtmlRunRequest(BaseModel):
    question_artifact_id: str
    layout_artifact_id: str
    retry_config: RetryConfig | None = None
    stream_key: str | None = None


class LayoutToHtmlRunResponse(BaseModel):
    sub_pipeline_id: str
    html_artifact_id: str
    rendered_image_artifact_id: str | None = None
    question_html: dict[str, Any]
    validation: HtmlValidationResult
    attempts: int
    generated_assets: dict[str, str] = Field(default_factory=dict)


class StandaloneGenerateQuestionRequest(BaseModel):
    yaml_content: dict[str, Any]
    feedback: str | None = None
    stream_key: str | None = None


class StandaloneGenerateLayoutRequest(BaseModel):
    question_json: QuestionSpec
    feedback: str | None = None
    stream_key: str | None = None


class StandaloneGenerateHtmlRequest(BaseModel):
    question_json: QuestionSpec
    layout_plan_json: LayoutPlan
    feedback: str | None = None
    asset_map: dict[str, str] = Field(default_factory=dict)
    stream_key: str | None = None


class StandaloneExtractRulesRequest(BaseModel):
    yaml_content: dict[str, Any]
    stream_key: str | None = None


class StandaloneEvaluateRuleRequest(BaseModel):
    rule: ValidationRule
    question_json: QuestionSpec
    stream_key: str | None = None


class StandaloneQuestionLayoutValidationRequest(BaseModel):
    question_json: QuestionSpec
    layout_plan_json: LayoutPlan
    stream_key: str | None = None


class StandaloneLayoutHtmlValidationRequest(BaseModel):
    html_content: str
    rendered_image_path: str | None = None
    asset_map: dict[str, str] = Field(default_factory=dict)
    layout_plan_json: LayoutPlan | None = None
    stream_key: str | None = None


class StandaloneGenerateCompositeImageRequest(BaseModel):
    asset: dict[str, Any]
    stream_key: str | None = None


class StandaloneAgentResponse(BaseModel):
    run_id: str
    result: Any
    artifact_id: str | None = None


class PipelineGetResponse(BaseModel):
    id: str
    mode: str
    yaml_instance_id: str | None = None
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


ExplorerTreeNode.model_rebuild()
