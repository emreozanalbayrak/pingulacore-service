import type {
  AgentRunGetResponse,
  ApiErrorShape,
  ArtifactItem,
  CurriculumNodeItem,
  ExplorerFavoritePayload,
  ExplorerFileReadResponse,
  ExplorerRoot,
  ExplorerTreeResponse,
  FavoriteCreatePayload,
  FavoriteItem,
  FullPipelineRunResponse,
  LayoutToHtmlRunResponse,
  PipelineAgentLinkResponse,
  PipelineGetResponse,
  PipelineLogEntryResponse,
  PropertyDefinitionCreatePayload,
  PropertyDefinitionItem,
  PropertyDefinitionUpdatePayload,
  QuestionToLayoutRunResponse,
  RetryConfig,
  RuntimeInfoResponse,
  StoredJsonFileItem,
  StandaloneAgentName,
  StandaloneAgentResponse,
  SubPipelineGetResponse,
  YamlInstanceCreatePayload,
  YamlInstanceItem,
  YamlInstanceUpdatePayload,
  YamlRenderResponse,
  YamlTemplateCreatePayload,
  YamlTemplateItem,
  YamlTemplateUpdatePayload,
  YamlToQuestionRunResponse,
} from '../types'

const JSON_HEADERS = {
  'Content-Type': 'application/json',
}

export class ApiError extends Error implements ApiErrorShape {
  status: number
  detail: unknown

  constructor(status: number, message: string, detail: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

function parseErrorMessage(status: number, body: unknown): string {
  if (typeof body === 'string' && body.trim()) {
    return body
  }

  if (body && typeof body === 'object') {
    const maybeBody = body as Record<string, unknown>
    const detail = maybeBody.detail

    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    if (detail && typeof detail === 'object') {
      const detailObj = detail as Record<string, unknown>
      if (typeof detailObj.message === 'string' && detailObj.message.trim()) {
        return detailObj.message
      }
    }
  }

  return `İstek başarısız oldu (HTTP ${status})`
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  const contentType = response.headers.get('content-type') ?? ''

  let body: unknown = null
  if (contentType.includes('application/json')) {
    body = await response.json()
  } else {
    body = await response.text()
  }

  if (!response.ok) {
    throw new ApiError(response.status, parseErrorMessage(response.status, body), body)
  }

  return body as T
}

function withQuery(path: string, params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `${path}?${query}` : path
}

export const standaloneEndpointMap: Record<StandaloneAgentName, string> = {
  main_generate_question: '/v1/agents/main/generate-question/run',
  main_generate_layout: '/v1/agents/main/generate-layout/run',
  main_generate_html: '/v1/agents/main/generate-html/run',
  validation_extract_rules: '/v1/agents/validation/extract-rules/run',
  validation_evaluate_rule: '/v1/agents/validation/evaluate-rule/run',
  validation_question_layout: '/v1/agents/validation/validate-question-layout/run',
  validation_layout_html: '/v1/agents/validation/validate-layout-html/run',
  helper_generate_composite_image: '/v1/agents/helper/generate-composite-image/run',
}

export const api = {
  getRuntimeInfo: () => apiFetch<RuntimeInfoResponse>('/v1/runtime-info'),

  getCurriculumTree: () => apiFetch<CurriculumNodeItem[]>('/v1/curriculum/tree'),

  createCurriculumNode: (payload: {
    parent_id?: string | null
    name: string
    slug: string
    grade?: string | null
    subject?: string | null
    theme?: string | null
    code?: string | null
    sort_order?: number
  }) =>
    apiFetch<CurriculumNodeItem>('/v1/curriculum/nodes', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ node_type: 'folder', ...payload }),
    }),

  listProperties: (params?: {
    defined_at_curriculum_node_id?: string
    parent_property_id?: string
    active_only?: boolean
  }) =>
    apiFetch<PropertyDefinitionItem[]>(
      withQuery('/v1/properties', {
        defined_at_curriculum_node_id: params?.defined_at_curriculum_node_id,
        parent_property_id: params?.parent_property_id,
        active_only: params?.active_only,
      }),
    ),

  getEffectiveProperties: (curriculumNodeId: string) =>
    apiFetch<PropertyDefinitionItem[]>(`/v1/properties/effective/${curriculumNodeId}`),

  getProperty: (propertyId: string) => apiFetch<PropertyDefinitionItem>(`/v1/properties/${propertyId}`),

  createProperty: (payload: PropertyDefinitionCreatePayload) =>
    apiFetch<PropertyDefinitionItem>('/v1/properties', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  updateProperty: (propertyId: string, payload: PropertyDefinitionUpdatePayload) =>
    apiFetch<PropertyDefinitionItem>(`/v1/properties/${propertyId}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  deleteProperty: (propertyId: string) =>
    apiFetch<unknown>(`/v1/properties/${propertyId}`, {
      method: 'DELETE',
    }),

  listYamlTemplates: (params?: { curriculum_folder_node_id?: string }) =>
    apiFetch<YamlTemplateItem[]>(
      withQuery('/v1/yaml-templates', {
        curriculum_folder_node_id: params?.curriculum_folder_node_id,
      }),
    ),

  getYamlTemplate: (templateId: string) => apiFetch<YamlTemplateItem>(`/v1/yaml-templates/${templateId}`),

  createYamlTemplate: (payload: YamlTemplateCreatePayload) =>
    apiFetch<YamlTemplateItem>('/v1/yaml-templates', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  updateYamlTemplate: (templateId: string, payload: YamlTemplateUpdatePayload) =>
    apiFetch<YamlTemplateItem>(`/v1/yaml-templates/${templateId}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  deleteYamlTemplate: (templateId: string) =>
    apiFetch<unknown>(`/v1/yaml-templates/${templateId}`, {
      method: 'DELETE',
    }),

  listYamlInstances: (params?: { template_id?: string }) =>
    apiFetch<YamlInstanceItem[]>(
      withQuery('/v1/yaml-instances', {
        template_id: params?.template_id,
      }),
    ),

  getYamlInstance: (instanceId: string) => apiFetch<YamlInstanceItem>(`/v1/yaml-instances/${instanceId}`),

  createYamlInstance: (payload: YamlInstanceCreatePayload) =>
    apiFetch<YamlInstanceItem>('/v1/yaml-instances', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  updateYamlInstance: (instanceId: string, payload: YamlInstanceUpdatePayload) =>
    apiFetch<YamlInstanceItem>(`/v1/yaml-instances/${instanceId}`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  deleteYamlInstance: (instanceId: string) =>
    apiFetch<unknown>(`/v1/yaml-instances/${instanceId}`, {
      method: 'DELETE',
    }),

  renderYamlInstance: (instanceId: string) =>
    apiFetch<YamlRenderResponse>(`/v1/yaml-instances/${instanceId}/render`, {
      method: 'POST',
    }),

  listArtifacts: (kind?: string) => {
    const query = kind ? `?kind=${encodeURIComponent(kind)}` : ''
    return apiFetch<ArtifactItem[]>(`/v1/artifacts${query}`)
  },

  getArtifact: (artifactId: string) => apiFetch<ArtifactItem>(`/v1/artifacts/${artifactId}`),

  runFullPipeline: (payload: { yaml_instance_id: string; retry_config?: RetryConfig; stream_key?: string }) =>
    apiFetch<FullPipelineRunResponse>('/v1/pipelines/full/run', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  runSubYamlToQuestion: (payload: { yaml_instance_id: string; retry_config?: RetryConfig; stream_key?: string }) =>
    apiFetch<YamlToQuestionRunResponse>('/v1/pipelines/sub/yaml-to-question/run', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  runSubQuestionToLayout: (payload: { question_artifact_id: string; retry_config?: RetryConfig; stream_key?: string }) =>
    apiFetch<QuestionToLayoutRunResponse>('/v1/pipelines/sub/question-to-layout/run', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  runSubLayoutToHtml: (payload: {
    question_artifact_id: string
    layout_artifact_id: string
    retry_config?: RetryConfig
    stream_key?: string
  }) =>
    apiFetch<LayoutToHtmlRunResponse>('/v1/pipelines/sub/layout-to-html/run', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  getPipeline: (pipelineId: string) => apiFetch<PipelineGetResponse>(`/v1/pipelines/${pipelineId}`),

  getPipelineAgentRuns: (pipelineId: string) =>
    apiFetch<PipelineAgentLinkResponse[]>(`/v1/pipelines/${pipelineId}/agent-runs`),
  getPipelineLogs: (pipelineId: string) => apiFetch<PipelineLogEntryResponse[]>(`/v1/pipelines/${pipelineId}/logs`),

  getSubPipeline: (subPipelineId: string) => apiFetch<SubPipelineGetResponse>(`/v1/sub-pipelines/${subPipelineId}`),

  getSubPipelineAgentRuns: (subPipelineId: string) =>
    apiFetch<PipelineAgentLinkResponse[]>(`/v1/sub-pipelines/${subPipelineId}/agent-runs`),
  getSubPipelineLogs: (subPipelineId: string) =>
    apiFetch<PipelineLogEntryResponse[]>(`/v1/sub-pipelines/${subPipelineId}/logs`),

  getAgentRun: (agentName: string, runId: string) => apiFetch<AgentRunGetResponse>(`/v1/agent-runs/${agentName}/${runId}`),

  runStandaloneAgent: (agent: StandaloneAgentName, payload: Record<string, unknown>) =>
    apiFetch<StandaloneAgentResponse>(standaloneEndpointMap[agent], {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  listStoredQuestionFiles: async (favoritesOnly = false): Promise<StoredJsonFileItem[]> => {
    const suffix = favoritesOnly ? '?favorites_only=true' : ''
    const response = await apiFetch<{ files: string[]; items?: StoredJsonFileItem[] }>(`/v1/sp-files/q_json${suffix}`)
    if (Array.isArray(response.items)) return response.items
    return response.files.map((filename) => ({ filename, is_favorite: false }))
  },

  listStoredLayoutFiles: async (favoritesOnly = false): Promise<StoredJsonFileItem[]> => {
    const suffix = favoritesOnly ? '?favorites_only=true' : ''
    const response = await apiFetch<{ files: string[]; items?: StoredJsonFileItem[] }>(`/v1/sp-files/layout${suffix}`)
    if (Array.isArray(response.items)) return response.items
    return response.files.map((filename) => ({ filename, is_favorite: false }))
  },

  getStoredQuestionFile: async (filename: string): Promise<Record<string, unknown>> => {
    const response = await apiFetch<{ filename: string; data: Record<string, unknown> }>(
      `/v1/sp-files/q_json/${encodeURIComponent(filename)}`,
    )
    return response.data
  },

  getStoredLayoutFile: async (filename: string): Promise<Record<string, unknown>> => {
    const response = await apiFetch<{ filename: string; data: Record<string, unknown> }>(
      `/v1/sp-files/layout/${encodeURIComponent(filename)}`,
    )
    return response.data
  },

  setStoredQuestionFileFavorite: (filename: string, isFavorite: boolean) =>
    apiFetch<StoredJsonFileItem>(`/v1/sp-files/q_json/${encodeURIComponent(filename)}/favorite`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      body: JSON.stringify({ is_favorite: isFavorite }),
    }),

  setStoredLayoutFileFavorite: (filename: string, isFavorite: boolean) =>
    apiFetch<StoredJsonFileItem>(`/v1/sp-files/layout/${encodeURIComponent(filename)}/favorite`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      body: JSON.stringify({ is_favorite: isFavorite }),
    }),

  createFavorite: (payload: FavoriteCreatePayload) =>
    apiFetch<FavoriteItem>('/v1/favorites', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  listFavorites: (kind?: 'question' | 'layout') => {
    const suffix = kind ? `?kind=${encodeURIComponent(kind)}` : ''
    return apiFetch<FavoriteItem[]>(`/v1/favorites${suffix}`)
  },

  getFavorite: (favoriteId: number) => apiFetch<FavoriteItem>(`/v1/favorites/${favoriteId}`),

  deleteFavorite: (favoriteId: number) =>
    apiFetch<unknown>(`/v1/favorites/${favoriteId}`, {
      method: 'DELETE',
    }),

  getExplorerTree: async (root: ExplorerRoot, path?: string) => {
    const query = path
      ? `?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`
      : `?root=${encodeURIComponent(root)}`
    return apiFetch<ExplorerTreeResponse>(`/v1/explorer/tree${query}`)
  },

  getExplorerFile: (root: ExplorerRoot, path: string) =>
    apiFetch<ExplorerFileReadResponse>(
      `/v1/explorer/file?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`,
    ),

  deleteExplorerFile: (root: ExplorerRoot, path: string) =>
    apiFetch<unknown>(`/v1/explorer/file?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`, {
      method: 'DELETE',
    }),

  setExplorerFavorite: (payload: ExplorerFavoritePayload) =>
    apiFetch<{ root: ExplorerRoot; path: string; is_favorite: boolean }>('/v1/explorer/file/favorite', {
      method: 'PATCH',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),
}
