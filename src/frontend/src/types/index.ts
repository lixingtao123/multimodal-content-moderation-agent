export interface ModerationResponse {
  content_id: string
  content_type: string
  content_preview?: string
  final_decision: 'PASS' | 'REVIEW' | 'REJECT' | 'UNKNOWN'
  risk_score: number
  violation_types: string[]
  violation_details: Record<string, unknown>
  suggestions: Array<{ action: string; reason: string; priority: string }>
  processing_time_ms: number
  cached?: boolean
  human_review_required?: boolean
  debate_info?: {
    had_debate: boolean
    debate_mode: string
    opinion_count: number
    final_confidence: number
    is_consensus: boolean
    needs_human_review: boolean
    agent_opinions: Array<{ agent: string; decision: string; confidence: number }>
  } | null
  agent_reasoning?: Record<string, {
    violation_type: string
    confidence: number
    reason: string
    reasoning: string
    reasoning_chain: string[]
    keyword_matches: string[]
  }> | null
}

export interface HistoryItem {
  content_id: string
  content_type: string
  content_preview?: string
  final_decision: string
  risk_score: number
  processing_time_ms: number
  created_at: string
}

export interface HistoryResponse {
  total: number
  page: number
  page_size: number
  items: HistoryItem[]
}

export interface AdminStats {
  total_moderated: number
  by_decision: Record<string, number>
  by_type: Record<string, number>
  avg_risk_score: number
  avg_processing_time_ms: number
}

// v4.0: 数据看板概览 — 7天趋势 + 违规分布
export interface StatsOverview {
  daily_trend: DailyTrend[]
  violation_distribution: ViolationCount[]
  overview: {
    total: number
    active_days: number
    avg_risk: number
    avg_time_ms: number
    pass_rate: number
  }
  token_estimate: {
    llm_calls: number
    estimated_tokens: number
    estimated_cost_usd: number
  }
}

export interface DailyTrend {
  day: string
  total: number
  pass_count: number
  review_count: number
  reject_count: number
  avg_risk: number
  avg_time_ms: number
}

export interface ViolationCount {
  violation_type: string
  cnt: number
}

export interface HealthStatus {
  status: string
  dependencies: Record<string, boolean>
}

export interface LogEntry {
  content_id: string
  content_type: string
  total_duration_ms: number
  step_count: number
  start_time: string
}

export interface PipelineStep {
  seq: number
  timestamp: string
  node: string
  action: string
  level: string
  duration_ms: number
  elapsed_ms: number
  input?: Record<string, unknown>
  output?: Record<string, unknown>
}

export interface PipelineLog {
  content_id: string
  content_type: string
  start_time: string
  total_duration_ms: number
  step_count: number
  steps: PipelineStep[]
}

export interface PendingReview {
  content_id: string
  content_type: string
  text_preview: string
  risk_score: number
  violation_types: string[]
  reason: string
  created_at: string
}

export interface FeedbackStats {
  buffer_size: number
  threshold: number
  ready_to_optimize: boolean
  last_optimization: number
  stats?: { buffer_size: number; threshold: number }
  reason?: string
  // v2: 标注统计字段
  total_processed?: number
  total_errors?: number
  false_positives?: number
  false_negatives?: number
  wrong_types?: number
  correct?: number
  last_annotation_time?: string
  queue_size?: number
}

export interface AnnotationResult {
  content_id: string
  is_error: boolean
  error_type: string  // false_positive | false_negative | wrong_violation_type | correct
  error_detail: string
  rule_verdict: string
  rule_detail: string
  llm_verdict: string
  llm_reason: string
  contradiction_flag: boolean
  annotated_violation_types: string[]
  annotated_confidence: number
  processing_time_ms: number
  annotated_at?: string  // 标注时间 (ISO 8601 UTC)
  // v3.2: 标注来源追踪
  source?: string        // "auto" | "human"
  weight?: number        // auto=1.0, human=3.0
  reviewer_id?: string   // 标注人员ID (human时填写)
  // 模型原始判定信息
  content_type?: string
  annotation_input?: string
  model_decision?: string
  model_confidence?: number
  model_violation_types?: string[]
  model_reason?: string
  model_risk_score?: number
  // 规则引擎详细信息
  rule_matched_keywords?: string[]
  rule_matched_rules?: string[]
  rule_whitelist_hit?: boolean
  rule_adversarial_hit?: boolean
  llm_called?: boolean
}

export interface OptimizationReport {
  report_id: string
  timestamp: string
  trigger: string  // auto | manual
  total_samples: number
  error_distribution: Record<string, number>
  pattern_analysis: string
  optimization_actions: Array<{
    action_type: string
    target: string
    description: string
    reason: string
  }>
  estimated_impact: string
  before?: {
    prompts: Record<string, { version: string; snippet: string }>
    keywords_stats: Record<string, number>
    thresholds: Record<string, number>
  }
  after?: {
    prompts: Record<string, { version: string; snippet: string }>
    keywords_stats: Record<string, number>
    thresholds: Record<string, number>
  }
}

export interface AnnotationAllResult {
  total: number
  items: AnnotationResult[]
}

export interface PromptVersion {
  name: string
  version: string
  model: string
  optimizer: string
  metrics: Record<string, unknown>
  system_prompt_snippet: string
  created_at: string
}

export interface PromptInfo {
  name: string
  active_version: string | null
  total_versions: number
}

export interface Capabilities {
  agents: Record<string, string>
  rag: Record<string, string>
  optimization: Record<string, string>
  protocols: Record<string, unknown>
  memory: Record<string, string>
  human_in_loop: Record<string, string>
  telemetry: Record<string, string>
  models: Record<string, string>
  ports?: {
    backend: number
    frontend: number
    pg: number
    redis: number
    chroma: number
    funasr: number
  }
  no_rlhf: string
}

// ===== v3.2: 人工标注相关类型 =====

/** 人工标注请求 — 标注人员修改 AI 的 JSON 输出 */
export interface HumanAnnotationRequest {
  content_id: string
  reviewer_id: string
  violation_type: string
  confidence: number
  reason: string
  tags: string[]
  is_adversarial: boolean
  decision: string
}

/** 人工标注响应 */
export interface HumanAnnotationResponse {
  saved: boolean
  content_id: string
  source: string
  weight: number
  is_error: boolean
  error_type: string
  human_corrected: Record<string, unknown>
}

/** 人工标注统计 */
export interface HumanAnnotationStats {
  human: {
    total: number
    errors_found: number
    false_positives: number
    false_negatives: number
    wrong_types: number
    correct: number
    avg_weight: number
  }
  auto: {
    total: number
    errors_found: number
  }
}

// ===== v3.3: 异步审核任务相关类型 =====

export type TaskStatus = 'QUEUED' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | 'AWAITING_HUMAN' | 'CANCELLED'

export interface AsyncTaskInfo {
  task_id: string
  status: TaskStatus
  progress: number           // 0.0 ~ 1.0
  current_step: string
  content_type: string
  content_preview: string
  created_at: string
  // 完成时填充
  final_decision?: string
  risk_score?: number
  violation_types?: string[]
  processing_time_ms?: number
  agent_reasoning?: Record<string, unknown>
  debate_info?: Record<string, unknown>
  suggestions?: Array<{ action: string; reason: string; priority: string }>
  error_message?: string
}

export interface AsyncTaskListResponse {
  total: number
  items: AsyncTaskInfo[]
}

export interface AsyncSubmitResponse {
  task_id: string
  status: string
  content_type: string
  created_at: string
  message: string
}

/** 待审核队列项 (增强版 — 含AI推理) */
export interface PendingReviewEnhanced extends PendingReview {
  agent_reasoning?: Record<string, {
    violation_type: string
    confidence: number
    reason: string
    reasoning: string
    reasoning_chain: string[]
    keyword_matches: string[]
  }>
  debate_info?: Record<string, unknown>
  ai_violation_types?: string[]
  annotation_status?: string
  annotation_source?: string
  trigger_reason?: string
}
