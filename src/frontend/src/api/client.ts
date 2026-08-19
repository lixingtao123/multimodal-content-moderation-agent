import type { LogEntry } from '../types'

const API_BASE = '/api/v1'

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  // ===== 审核 =====
  moderateText: (text: string, accountId?: string) =>
    apiFetch('/moderate/text', {
      method: 'POST',
      body: JSON.stringify({ text, account_id: accountId }),
    }),

  moderateImage: async (file: File, accountId?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (accountId) form.append('account_id', accountId)
    const res = await fetch(`${API_BASE}/moderate/image`, { method: 'POST', body: form })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  moderateAudio: async (file: File, accountId?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (accountId) form.append('account_id', accountId)
    const res = await fetch(`${API_BASE}/moderate/audio`, { method: 'POST', body: form })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  moderateVideo: async (file: File, accountId?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (accountId) form.append('account_id', accountId)
    const res = await fetch(`${API_BASE}/moderate/video`, { method: 'POST', body: form })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  moderateMultiModal: async (text: string, files: File[], accountId?: string) => {
    const form = new FormData()
    form.append('text', text)
    if (accountId) form.append('account_id', accountId)
    for (const f of files) {
      form.append('files', f)
    }
    const res = await fetch(`${API_BASE}/moderate/multi-modal`, { method: 'POST', body: form })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  // ===== 查询 =====
  getResult: (contentId: string) => apiFetch(`/moderate/${contentId}`),

  getHistory: (page = 1, pageSize = 20, decision?: string, contentType?: string) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    if (decision) params.set('decision', decision)
    if (contentType) params.set('content_type', contentType)
    return apiFetch(`/history?${params}`)
  },

  // ===== 策略管理 =====
  getPolicies: (type?: string) => {
    const params = type ? `?policy_type=${type}` : ''
    return apiFetch(`/admin/policies${params}`)
  },
  getPolicy: (id: string) => apiFetch(`/admin/policies/${id}`),
  createPolicy: (data: Record<string, unknown>) =>
    apiFetch('/admin/policies', { method: 'POST', body: JSON.stringify(data) }),
  updatePolicy: (id: string, data: Record<string, unknown>) =>
    apiFetch(`/admin/policies/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deletePolicy: (id: string) =>
    apiFetch(`/admin/policies/${id}`, { method: 'DELETE' }),

  // ===== 统计 =====
  getStats: () => apiFetch('/admin/statistics'),
  getStatsOverview: () => apiFetch('/admin/stats/overview'),

  // ===== 技术实验室 =====
  ragDebug: (text: string, topK = 8) =>
    apiFetch('/tech/rag-debug', { method: 'POST', body: JSON.stringify({ text, top_k: topK }) }),

  promptCompare: (text: string, promptA: string, promptB: string) =>
    apiFetch('/tech/prompt-compare', { method: 'POST', body: JSON.stringify({ text, prompt_a: promptA, prompt_b: promptB }) }),

  getPipelineFlow: () => apiFetch('/tech/pipeline-flow'),

  getAgentPrompts: () => apiFetch('/tech/prompts'),

  // ===== v4.1: MCP Tools + Skills =====
  getTools: () => apiFetch<{ tools: Record<string, unknown>[]; total?: number }>('/tech/tools'),
  getSkills: () => apiFetch('/tech/skills'),
  getSkillDetail: (name: string) => apiFetch(`/tech/skills/${name}`),
  getSkillToolMap: () => apiFetch('/tech/skill-tool-map'),

  getHealth: () => fetch('/health').then(r => r.json()),

  // ===== 日志 =====
  getRecentLogs: (limit = 50) =>
    apiFetch<{ items: LogEntry[]; total: number }>(`/logs/recent/all?limit=${limit}`),
  getPipelineLog: (contentId: string) => apiFetch(`/logs/${contentId}`),

  // ===== 人工审核 v3.2 =====
  getPendingReviews: () => apiFetch('/moderate/pending-reviews'),
  submitReview: (contentId: string, decision: string, reason: string, violationType?: string) =>
    apiFetch(`/moderate/${contentId}/review`, {
      method: 'POST',
      body: JSON.stringify({ decision, reason, violation_type: violationType || '' }),
    }),
  // 人工标注 (独立于工作流恢复流程)
  submitHumanAnnotation: (contentId: string, data: Record<string, unknown>) =>
    apiFetch(`/admin/annotation/human?content_id=${contentId}`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getHumanAnnotationStats: () => apiFetch('/admin/annotation/human/stats'),

  // ===== 优化监控 =====
  getFeedbackStats: () => apiFetch('/admin/optimization/feedback-stats'),
  getPromptVersions: (name: string) => apiFetch(`/admin/optimization/prompt-versions/${name}`),
  listAllPrompts: () => apiFetch('/admin/optimization/prompts'),
  triggerOptimization: () => apiFetch('/admin/optimization/trigger', { method: 'POST' }),

  // ===== v2: 标注结果 =====
  getAnnotationStats: () => apiFetch('/admin/optimization/annotation-stats'),
  getAnnotationBuffer: (limit = 50, offset = 0) =>
    apiFetch(`/admin/optimization/annotation-buffer?limit=${limit}&offset=${offset}`),
  getAllAnnotations: (limit = 50, offset = 0, errorType = '') =>
    apiFetch(`/admin/optimization/annotation-all?limit=${limit}&offset=${offset}&error_type=${errorType}`),
  getAnnotationResult: (contentId: string) =>
    apiFetch(`/admin/optimization/annotation-results/${contentId}`),

  // ===== 系统能力 =====
  getCapabilities: () => apiFetch('/eval/capabilities'),

  // ===== v3.3: 异步审核 =====
  submitAsyncTask: async (text: string, files: File[], accountId?: string) => {
    const form = new FormData()
    form.append('text', text)
    if (accountId) form.append('account_id', accountId)
    for (const f of files) {
      form.append('files', f)
    }
    const res = await fetch(`${API_BASE}/moderate/async`, { method: 'POST', body: form })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return res.json()
  },

  getTaskStatus: (taskId: string) =>
    apiFetch<Record<string, unknown>>(`/moderate/task/${taskId}`),

  getTaskList: (limit = 50, status = 'all') => {
    const params = new URLSearchParams({ limit: String(limit), status })
    return apiFetch<{ total: number; items: Record<string, unknown>[] }>(`/moderate/tasks?${params}`)
  },

  cancelTask: (taskId: string) =>
    apiFetch<{ task_id: string; cancelled: boolean }>(`/moderate/task/${taskId}`, { method: 'DELETE' }),

  // ===== R17: Benchmark / Skills / Dataset =====
  getBenchmarkReport: () =>
    apiFetch<{ baseline: Record<string, unknown> | null; latest: Record<string, unknown> | null; tracks: { name: string; status: string; note: string }[] }>('/eval/benchmark'),

  // ===== R22·C5: OutSafe 数据集统计（真实读盘）=====
  getDatasetStats: () =>
    apiFetch<{
      available: boolean
      root_dir: string
      stats: { categories: number; text_zh: number; text_en: number; image: number; video: number; audio: number } | null
      per_category: { category: string; text_zh: number; text_en: number; image: number; video: number; audio: number }[]
      error?: string
    }>('/eval/dataset/stats'),

  // ===== Skill 自优化 API =====
  getSkillRoutingLogs: (limit?: number, offset?: number, agent?: string) =>
    apiFetch<{
      logs: Array<{
        id: number
        content_id: string
        agent: string
        query: string
        content_type: string
        filtered_skills: string[]
        ranked_skills: string[]
        selected_skills: string[]
        timestamp: string
      }>
      total: number
      skill_stats: Record<string, number>
    }>(`/tech/skill-routing-logs?${new URLSearchParams({
      limit: String(limit ?? 100),
      offset: String(offset ?? 0),
      ...(agent ? { agent } : {}),
    })}`),

  analyzeSkillRouting: (minLogs?: number) =>
    apiFetch<{
      status: string
      reason?: string
      report?: {
        generated_at: number
        suggestion_count: number
        analysis_summary: string
        suggestions: Array<{
          skill_name: string
          suggestion_type: string
          current_value: string
          suggested_value: string
          reason: string
          confidence: number
          supporting_examples: string[]
        }>
        voting_required: boolean
        votes: Array<{ voter: string; vote: boolean; comment: string; timestamp: number }>
        approved: boolean
      }
    }>('/tech/skill-optimization/analyze', {
      method: 'POST',
      body: JSON.stringify({ min_logs: minLogs ?? 10 }),
    }),

  getOptimizationSuggestions: () =>
    apiFetch<{
      suggestions: any[]
      total: number
    }>('/tech/skill-optimization/suggestions'),

  voteOptimization: (suggestionId: string, voter: string, vote: boolean, comment?: string) =>
    apiFetch(`/tech/skill-optimization/suggestions/${encodeURIComponent(suggestionId)}/vote`, {
      method: 'POST',
      body: JSON.stringify({ voter, vote, comment: comment ?? '' }),
    }),

  applyOptimization: (suggestionId: string) =>
    apiFetch(`/tech/skill-optimization/apply`, {
      method: 'POST',
      body: JSON.stringify({ suggestion_id: suggestionId }),
    }),

  getOptimizationReports: (limit?: number) =>
    apiFetch<{
      reports: any[]
      total: number
    }>(`/tech/skill-optimization/reports?${new URLSearchParams({ limit: String(limit ?? 20) })}`),

  // ===== 增强版 Skill 优化 API =====
  voteSingleSuggestion: (reportPath: string, suggestionId: number, voter: string, vote: boolean, comment?: string) =>
    apiFetch(`/tech/skill-optimization/suggestions/${encodeURIComponent(reportPath)}/${suggestionId}/vote`, {
      method: 'POST',
      body: JSON.stringify({ voter, vote, comment: comment ?? '' }),
    }),

  applySelectedSuggestions: (reportPath: string, suggestionIds: number[]) =>
    apiFetch('/tech/skill-optimization/apply-selected', {
      method: 'POST',
      body: JSON.stringify({ report_path: reportPath, suggestion_ids: suggestionIds }),
    }),

  getSuggestionPreview: (reportPath: string, suggestionId: number) =>
    apiFetch(`/tech/skill-optimization/suggestions/${encodeURIComponent(reportPath)}/${suggestionId}/preview`),
}
