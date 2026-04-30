export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

export interface AuthUser {
  id: number
  email: string
  display_name: string | null
  is_admin: boolean
  created_at: string
}

export interface AuthTokenResponse {
  token: string
  expires_at: string | null
  user: AuthUser
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  display_name?: string
}

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
  question_json: Record<string, unknown>
  layout_plan_json: Record<string, unknown>
  question_html: Record<string, unknown>
  rendered_image_path?: string | null
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
  question_json: Record<string, unknown>
  rule_evaluation: Record<string, unknown>
  attempts: number
}

export interface QuestionToLayoutRunResponse {
  sub_pipeline_id: string
  layout_plan_json: Record<string, unknown>
  validation: Record<string, unknown>
  attempts: number
}

export interface LayoutToHtmlRunResponse {
  sub_pipeline_id: string
  question_html: Record<string, unknown>
  validation: Record<string, unknown>
  attempts: number
  generated_assets: Record<string, string>
  rendered_image_path?: string | null
}

export interface PipelineGetResponse {
  id: string
  mode: string
  yaml_filename: string
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

export type LegacyPipelineKind = 'geometry' | 'turkce'

export interface LegacyPipelineDescriptor {
  kind: LegacyPipelineKind
  label: string
  enabled: boolean
  yaml_root: string
  default_params: Record<string, unknown>
}

export interface LegacyPipelinesResponse {
  pipelines: LegacyPipelineDescriptor[]
}

export interface LegacyYamlFilesResponse {
  kind: LegacyPipelineKind
  files: string[]
}

export interface LegacyYamlUploadResponse {
  kind: LegacyPipelineKind
  yaml_path: string
}

export interface LegacyYamlInfoResponse {
  kind: LegacyPipelineKind
  yaml_path: string
  has_variants: boolean
  variant_count: number
  variant_names: string[]
}

export interface LegacyYamlContentResponse {
  kind: LegacyPipelineKind
  yaml_path: string
  content: string
  is_repo_yaml: boolean
}

export interface LegacyYamlContentUpdateRequest {
  yaml_path: string
  content: string
}

export interface LegacyBatchItem {
  yaml_path: string
  params?: Record<string, string | number | boolean>
  variants?: string[]
}

export interface LegacyBatchRunRequest {
  items: LegacyBatchItem[]
  parallelism?: number
  stream_key?: string
}

export interface LegacyBatchRunResponse {
  batch_id: string
  run_ids: string[]
  status: string
  stream_key?: string | null
}

export interface LegacyOutputNode {
  name: string
  type: 'dir' | 'file'
  url?: string | null
  size?: number | null
  rel_path: string
  children?: LegacyOutputNode[]
}

export interface LegacyRunDetail {
  run_id: string
  kind: LegacyPipelineKind
  yaml_path: string
  variant_name?: string | null
  status: string
  error?: string | null
  started_at: string
  finished_at?: string | null
  outputs: LegacyOutputNode[]
}

export type LegacyRunDetailResponse = LegacyRunDetail

export interface LegacyBatchDetailResponse {
  batch_id: string
  kind: LegacyPipelineKind
  runs: LegacyRunDetail[]
}
