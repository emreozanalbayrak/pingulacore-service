import type {
  AgentRunGetResponse,
  ApiErrorShape,
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
  QuestionToLayoutRunResponse,
  RetryConfig,
  RuntimeInfoResponse,
  StoredJsonFileItem,
  StandaloneAgentName,
  StandaloneAgentResponse,
  SubPipelineGetResponse,
  YamlToQuestionRunResponse,
  LegacyPipelineKind,
  LegacyPipelinesResponse,
  LegacyYamlFilesResponse,
  LegacyYamlUploadResponse,
  LegacyYamlInfoResponse,
  LegacyYamlContentResponse,
  LegacyYamlContentUpdateRequest,
  LegacyBatchRunRequest,
  LegacyBatchRunResponse,
  LegacyBatchDetailResponse,
  LegacyRunDetailResponse,
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

  listYamlFiles: async (): Promise<string[]> => {
    const response = await apiFetch<{ files: string[] }>('/v1/yaml-files')
    return response.files
  },

  getYamlFileContent: async (filename: string): Promise<Record<string, unknown>> => {
    const response = await apiFetch<{ filename: string; data: Record<string, unknown> }>(
      `/v1/yaml-files/${encodeURIComponent(filename)}`,
    )
    return response.data
  },

  runFullPipeline: (payload: { yaml_filename: string; retry_config?: RetryConfig; stream_key?: string }) =>
    apiFetch<FullPipelineRunResponse>('/v1/pipelines/full/run', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  runSubYamlToQuestion: (payload: { yaml_filename: string; retry_config?: RetryConfig; stream_key?: string }) =>
    apiFetch<YamlToQuestionRunResponse>('/v1/pipelines/sub/yaml-to-question/run', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  runSubQuestionToLayout: (payload: { question_json: Record<string, unknown>; retry_config?: RetryConfig; stream_key?: string }) =>
    apiFetch<QuestionToLayoutRunResponse>('/v1/pipelines/sub/question-to-layout/run', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
    }),

  runSubLayoutToHtml: (payload: {
    question_json: Record<string, unknown>
    layout_plan_json: Record<string, unknown>
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

  listLegacyPipelines: () => apiFetch<LegacyPipelinesResponse>('/v1/legacy/pipelines'),

  listLegacyYamlFiles: (kind: LegacyPipelineKind) =>
    apiFetch<LegacyYamlFilesResponse>(`/v1/legacy/pipelines/${encodeURIComponent(kind)}/yaml-files`),

  uploadLegacyYaml: (kind: LegacyPipelineKind, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiFetch<LegacyYamlUploadResponse>(
      `/v1/legacy/pipelines/${encodeURIComponent(kind)}/yaml-upload`,
      { method: 'POST', body: formData },
    )
  },

  getLegacyYamlInfo: (kind: LegacyPipelineKind, yamlPath: string) =>
    apiFetch<LegacyYamlInfoResponse>(
      `/v1/legacy/pipelines/${encodeURIComponent(kind)}/yaml-info?yaml_path=${encodeURIComponent(yamlPath)}`,
    ),

  getLegacyYamlContent: (kind: LegacyPipelineKind, yamlPath: string) =>
    apiFetch<LegacyYamlContentResponse>(
      `/v1/legacy/pipelines/${encodeURIComponent(kind)}/yaml-content?yaml_path=${encodeURIComponent(yamlPath)}`,
    ),

  updateLegacyYamlContent: (kind: LegacyPipelineKind, payload: LegacyYamlContentUpdateRequest) =>
    apiFetch<LegacyYamlContentResponse>(
      `/v1/legacy/pipelines/${encodeURIComponent(kind)}/yaml-content`,
      {
        method: 'PUT',
        headers: JSON_HEADERS,
        body: JSON.stringify(payload),
      },
    ),

  runLegacyBatch: (kind: LegacyPipelineKind, payload: LegacyBatchRunRequest) =>
    apiFetch<LegacyBatchRunResponse>(
      `/v1/legacy/pipelines/${encodeURIComponent(kind)}/batch-run`,
      {
        method: 'POST',
        headers: JSON_HEADERS,
        body: JSON.stringify(payload),
      },
    ),

  getLegacyRun: (runId: string) =>
    apiFetch<LegacyRunDetailResponse>(`/v1/legacy/runs/${encodeURIComponent(runId)}`),

  getLegacyBatch: (batchId: string) =>
    apiFetch<LegacyBatchDetailResponse>(`/v1/legacy/runs/${encodeURIComponent(batchId)}/batch`),

  getLegacyRunDownloadUrl: (runId: string, subdir?: string) => {
    const base = `/v1/legacy/runs/${encodeURIComponent(runId)}/download`
    return subdir ? `${base}?subdir=${encodeURIComponent(subdir)}` : base
  },

  getLegacyRunLogs: (runId: string) =>
    apiFetch<PipelineLogEntryResponse[]>(`/v1/legacy/runs/${encodeURIComponent(runId)}/logs`),
}
