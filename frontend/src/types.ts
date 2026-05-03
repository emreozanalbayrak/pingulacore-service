export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

export interface RetryConfig {
  question_max_retries?: number
  layout_max_retries?: number
  html_max_retries?: number
  image_max_retries?: number
  rule_eval_parallelism?: number
}

export interface FullPipelineRunResponse {
  pipeline_id: string
  sub_pipeline_ids: Record<string, string>
  question_artifact_id: string
  layout_artifact_id: string
  html_artifact_id: string
  rendered_image_artifact_id?: string | null
  question_json: Record<string, unknown>
  layout_plan_json: Record<string, unknown>
  question_html: Record<string, unknown>
}

export interface RuntimeInfoResponse {
  use_stub_agents: boolean
  text_model: string
  light_model: string
  image_model: string
  has_google_api_key: boolean
  has_anthropic_api_key: boolean
}

export interface FavoriteItem {
  id: number
  name: string
  kind: 'question' | 'layout'
  data: Record<string, unknown>
  source_sub_pipeline_id?: string | null
  created_at: string
}

export interface FavoriteCreatePayload {
  name: string
  kind: 'question' | 'layout'
  data: Record<string, unknown>
  source_sub_pipeline_id?: string | null
}

export type CurriculumNodeScope = 'constant' | 'folder'

export interface CurriculumNodeItem {
  id: string
  parent_id?: string | null
  node_type: string
  scope: CurriculumNodeScope
  name: string
  slug: string
  code?: string | null
  grade?: string | null
  subject?: string | null
  theme?: string | null
  sort_order: number
  depth: number
  path: string
  is_active: boolean
  children: CurriculumNodeItem[]
}

export type PropertyDataType = 'text' | 'bool' | 'number' | 'json' | 'array' | 'enum' | 'object'

export interface PropertyDefinitionItem {
  id: string
  defined_at_curriculum_node_id: string
  parent_property_id?: string | null
  label: string
  description?: string | null
  property_key: string
  canonical_path: string
  data_type: PropertyDataType
  default_value?: string | null
  constraints?: unknown
  is_required: boolean
  is_active: boolean
}

export interface PropertyDefinitionCreatePayload {
  defined_at_curriculum_node_id: string
  parent_property_id?: string | null
  label: string
  description?: string | null
  property_key: string
  canonical_path: string
  data_type: PropertyDataType
  default_value?: string | null
  constraints?: unknown
  is_required?: boolean
}

export interface PropertyDefinitionUpdatePayload {
  label?: string
  description?: string | null
  property_key?: string
  canonical_path?: string
  data_type?: PropertyDataType
  default_value?: string | null
  constraints?: unknown
  is_required?: boolean
  is_active?: boolean
}

export interface YamlTemplateItem {
  id: string
  curriculum_folder_node_id: string
  template_code: string
  title: string
  description?: string | null
  field_schema: Record<string, unknown>
  schema_version: string
  status: 'active' | 'archived' | string
  created_by?: string | null
}

export interface YamlTemplateCreatePayload {
  curriculum_folder_node_id: string
  template_code: string
  title: string
  description?: string | null
  field_schema: Record<string, unknown>
  schema_version?: string
  created_by?: string | null
}

export interface YamlTemplateUpdatePayload {
  template_code?: string
  title?: string
  description?: string | null
  field_schema?: Record<string, unknown>
  schema_version?: string
  status?: 'active' | 'archived'
}

export interface YamlInstanceItem {
  id: string
  template_id: string
  instance_name: string
  status: string
  values: Record<string, unknown>
  rendered_yaml_text?: string | null
  created_by?: string | null
}

export interface YamlInstanceCreatePayload {
  template_id: string
  instance_name: string
  values: Record<string, unknown>
  status?: 'draft' | 'final' | 'archived'
  created_by?: string | null
}

export interface YamlInstanceUpdatePayload {
  instance_name?: string
  values?: Record<string, unknown>
  status?: 'draft' | 'final' | 'archived'
}

export interface YamlRenderResponse {
  instance_id: string
  artifact_id: string
  yaml_content: Record<string, unknown>
  rendered_yaml_text: string
}

export interface ArtifactItem {
  id: string
  kind: string
  content_json?: unknown
  content_text?: string | null
  object_bucket?: string | null
  object_key?: string | null
  mime_type?: string | null
  is_favorite: boolean
  source_pipeline_id?: string | null
  source_sub_pipeline_id?: string | null
  source_agent_name?: string | null
  source_agent_run_id?: string | null
  created_at: string
  updated_at?: string | null
}

export interface StoredJsonFileItem {
  filename: string
  is_favorite: boolean
}

export type ExplorerRoot = 'runs' | 'sp_files'

export interface ExplorerTreeNode {
  name: string
  path: string
  kind: 'file' | 'dir'
  size?: number | null
  modified_at?: string | null
  is_favorite: boolean
  favoritable: boolean
  children?: ExplorerTreeNode[]
}

export interface ExplorerTreeResponse {
  root: ExplorerRoot
  path?: string | null
  items: ExplorerTreeNode[]
}

export interface ExplorerFileReadResponse {
  root: ExplorerRoot
  path: string
  filename: string
  content_type: 'json' | 'html' | 'text' | 'image' | 'binary'
  content?: unknown
  mime_type?: string | null
  asset_url?: string | null
}

export interface ExplorerFavoritePayload {
  root: ExplorerRoot
  path: string
  is_favorite: boolean
}

export interface YamlToQuestionRunResponse {
  sub_pipeline_id: string
  question_artifact_id: string
  question_json: Record<string, unknown>
  rule_evaluation: Record<string, unknown>
  attempts: number
}

export interface QuestionToLayoutRunResponse {
  sub_pipeline_id: string
  layout_artifact_id: string
  layout_plan_json: Record<string, unknown>
  validation: Record<string, unknown>
  attempts: number
}

export interface LayoutToHtmlRunResponse {
  sub_pipeline_id: string
  html_artifact_id: string
  rendered_image_artifact_id?: string | null
  question_html: Record<string, unknown>
  validation: Record<string, unknown>
  attempts: number
  generated_assets: Record<string, string>
}

export interface PipelineGetResponse {
  id: string
  mode: string
  yaml_instance_id?: string | null
  status: string
  retry_config: Record<string, unknown>
  error?: string | null
  created_at: string
  finished_at?: string | null
}

export interface SubPipelineGetResponse {
  id: string
  pipeline_id?: string | null
  mode: string
  kind: string
  status: string
  input_json: Record<string, unknown>
  output_json?: Record<string, unknown> | null
  error?: string | null
  created_at: string
  finished_at?: string | null
}

export interface PipelineAgentLinkResponse {
  id: number
  pipeline_id?: string | null
  sub_pipeline_id?: string | null
  agent_name: string
  agent_table: string
  agent_run_id: string
  created_at: string
}

export interface PipelineLogEntryResponse {
  id: number
  pipeline_id?: string | null
  sub_pipeline_id?: string | null
  mode: string
  level: string
  component: string
  message: string
  details?: Record<string, unknown> | string | number | boolean | null
  created_at: string
}

export interface AgentRunGetResponse {
  id: string
  mode: string
  pipeline_id?: string | null
  sub_pipeline_id?: string | null
  attempt_no: number
  status: string
  input_json: Record<string, unknown>
  output_json?: Record<string, unknown> | null
  feedback_text?: string | null
  error?: string | null
  model_name: string
  question_id?: string | null
  schema_version?: string | null
  started_at: string
  finished_at?: string | null
}

export interface StandaloneAgentResponse {
  run_id: string
  result: Record<string, unknown>
}

export type StandaloneAgentName =
  | 'main_generate_question'
  | 'main_generate_layout'
  | 'main_generate_html'
  | 'validation_extract_rules'
  | 'validation_evaluate_rule'
  | 'validation_question_layout'
  | 'validation_layout_html'
  | 'helper_generate_composite_image'

export interface ApiErrorShape {
  status: number
  message: string
  detail: unknown
}
