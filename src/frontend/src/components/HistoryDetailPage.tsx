import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { ModerationResponse, PipelineLog, AnnotationResult, PipelineStep } from '../types'
import { formatDateTime, formatTime } from '../utils/time'
import PipelineFlowChart from './PipelineFlowChart'

const DECISION_CONFIG: Record<string, { label: string; className: string; icon: string }> = {
  PASS: { label: '通过', className: 'badge-pass', icon: '✓' },
  REVIEW: { label: '人工复核', className: 'badge-review', icon: '⚠' },
  REJECT: { label: '拒绝', className: 'badge-reject', icon: '✕' },
  UNKNOWN: { label: '未知', className: 'badge-info', icon: '?' },
}

const ERROR_LABELS: Record<string, string> = {
  false_positive: '误判',
  false_negative: '漏判',
  wrong_violation_type: '类型错误',
  correct: '正确',
}

const ERROR_COLORS: Record<string, string> = {
  false_positive: '#ef4444',
  false_negative: '#f59e0b',
  wrong_violation_type: '#8b5cf6',
  correct: '#10b981',
}

const LEVEL_COLORS: Record<string, string> = {
  ERROR: '#ef4444',
  WARN: '#f59e0b',
  INFO: '#10b981',
}

export default function HistoryDetailPage() {
  const { contentId } = useParams<{ contentId: string }>()
  const navigate = useNavigate()
  const [record, setRecord] = useState<ModerationResponse | null>(null)
  const [pipeline, setPipeline] = useState<PipelineLog | null>(null)
  const [annotation, setAnnotation] = useState<AnnotationResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadDetail = useCallback(async () => {
    if (!contentId) return
    setLoading(true)
    setError(null)
    try {
      const [rec, pip, ann] = await Promise.all([
        api.getResult(contentId).catch(() => null) as Promise<ModerationResponse | null>,
        api.getPipelineLog(contentId).catch(() => null) as Promise<PipelineLog | null>,
        api.getAnnotationResult(contentId).catch(() => null) as Promise<AnnotationResult | null>,
      ])
      setRecord(rec)
      setPipeline(pip)
      setAnnotation(ann)
      if (!rec && !pip) setError('未找到该审核记录')
    } catch (e) {
      setError('加载详情失败: ' + (e instanceof Error ? e.message : '未知错误'))
    } finally {
      setLoading(false)
    }
  }, [contentId])

  useEffect(() => { loadDetail() }, [loadDetail])

  // ── Loading ──
  if (loading) {
    return (
      <div className="animate-fade-in">
        <div className="flex items-center gap-4 mb-6">
          <button onClick={() => navigate('/history')} className="text-slate-500 hover:text-slate-700 transition-colors">← 返回列表</button>
          <h2 className="text-xl font-bold text-slate-800">审核详情</h2>
        </div>
        <div className="card p-12 text-center">
          <div className="w-10 h-10 border-3 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-sm text-slate-400">加载审核详情...</p>
        </div>
      </div>
    )
  }

  // ── Error / Not Found ──
  if (error || !record) {
    return (
      <div className="animate-fade-in">
        <div className="flex items-center gap-4 mb-6">
          <button onClick={() => navigate('/history')} className="text-slate-500 hover:text-slate-700 transition-colors">← 返回列表</button>
          <h2 className="text-xl font-bold text-slate-800">审核详情</h2>
        </div>
        <div className="card p-12 text-center">
          <div className="text-4xl mb-3 opacity-30">🔍</div>
          <p className="text-sm text-slate-500">{error || '未找到该审核记录'}</p>
          {contentId && <p className="text-xs text-slate-400 mt-1 font-mono">Content ID: {contentId}</p>}
          <button onClick={loadDetail} className="btn btn-secondary text-sm mt-4">🔄 重试</button>
        </div>
      </div>
    )
  }

  const decisionCfg = DECISION_CONFIG[record.final_decision] || DECISION_CONFIG.UNKNOWN
  const hasPipeline = pipeline && pipeline.steps && pipeline.steps.length > 0
  const hasAnnotation = annotation !== null
  const hasReasoning = record.agent_reasoning && Object.keys(record.agent_reasoning).length > 0
  const hasDebate = record.debate_info?.had_debate

  return (
    <div className="space-y-6 animate-fade-in pb-10">
      {/* ── Header ── */}
      <div className="flex items-center gap-4 flex-wrap">
        <button onClick={() => navigate('/history')} className="btn btn-secondary text-sm py-2">← 返回列表</button>
        <div className="flex-1 min-w-0">
          <h2 className="text-xl font-bold text-slate-800">审核详情</h2>
          <p className="text-xs text-slate-400 font-mono mt-0.5 truncate">{record.content_id}</p>
        </div>
        <button onClick={loadDetail} className="btn btn-secondary text-sm py-2">🔄 刷新</button>
      </div>

      <div className="card p-5 border-l-4 border-sky-500">
        <div className="flex items-center justify-between gap-3 mb-3">
          <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
            📝 原始审核内容
          </h3>
          <span className="badge badge-info text-xs">{record.content_type}</span>
        </div>
        {record.content_preview?.trim() ? (
          <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap break-words max-h-72 overflow-y-auto">
            {record.content_preview}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-sm text-slate-400">
            该历史记录没有可用的内容摘要
          </div>
        )}
        {record.content_type !== 'text' && (
          <p className="text-xs text-amber-600 mt-3">
            当前历史记录只保存文件名、大小和文本摘要，不保存上传文件的原始二进制内容。
          </p>
        )}
      </div>

      {/* ═══════════════════════════════════════════
          Section A: 数据概览 — 汇总所有数据源
          ═══════════════════════════════════════════ */}
      <div className="card p-5 border-t-4 border-indigo-500">
        <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
          📊 数据概览
          <span className="text-xs text-slate-400 font-normal">
            (数据来源: {[
              'moderation', pipeline && 'pipeline', annotation && 'annotation'
            ].filter(Boolean).join(' + ')})
          </span>
        </h3>

        {/* Row 1: 核心指标 */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-4">
          <MiniStat label="内容类型" value={record.content_type || '-'} icon="📦" />
          <MiniStat label="最终决策" value={
            <span className={`badge ${decisionCfg.className} text-xs`}>{decisionCfg.icon} {decisionCfg.label}</span>
          } icon="⚖️" />
          <MiniStat label="风险分数" value={`${((record.risk_score ?? 0) * 100).toFixed(1)}%`}
            icon={(record.risk_score ?? 0) > 0.7 ? '🔴' : (record.risk_score ?? 0) > 0.35 ? '🟡' : '🟢'} />
          <MiniStat label="处理耗时" value={`${(record.processing_time_ms ?? 0).toFixed(0)}ms`} icon="⏱" />
          <MiniStat label="审核时间" value={formatDateTime((record as any).created_at)} icon="🕐" />
        </div>

        {/* Row 2: 违规类型 + 状态 */}
        <div className="flex flex-wrap items-center gap-3">
          {(record.violation_types || []).length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-500">违规类型:</span>
              {(record.violation_types || []).map(t => (
                <span key={t} className="badge badge-reject text-xs">{t}</span>
              ))}
            </div>
          )}
          {record.cached && <span className="badge badge-info text-xs">⚡ 缓存命中</span>}
          {hasDebate && <span className="badge badge-review text-xs">⚖️ 已辩论</span>}
          {record.human_review_required && <span className="badge badge-review text-xs">⏳ 待人工审核</span>}
          {hasPipeline && <span className="badge badge-pass text-xs">📋 Pipeline: {pipeline!.step_count}步</span>}
          {hasAnnotation && (
            <span className="badge text-xs text-white" style={{ background: ERROR_COLORS[annotation!.error_type] || '#94a3b8' }}>
              🏷️ 标注: {ERROR_LABELS[annotation!.error_type] || annotation!.error_type}
            </span>
          )}
        </div>
      </div>

      {/* ═══════════════════════════════════════════
          Section B: Pipeline 流程拓扑图 + 详细日志
          ═══════════════════════════════════════════ */}
      {hasPipeline ? (
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-800 mb-1 flex items-center gap-2">
            🔄 审核流程拓扑 · Multi-Agent 执行链路
          </h3>
          <p className="text-xs text-slate-400 mb-4">
            {pipeline!.step_count} 个节点 · 总耗时 {pipeline!.total_duration_ms.toFixed(0)}ms · {formatDateTime(pipeline!.start_time)}
          </p>

          {/* v4.0: 流程拓扑图 — 可视化 Multi-Agent 执行流程 */}
          <PipelineFlowChart pipeline={pipeline!} />

          {/* 原始步骤表格 (可折叠, 供调试用) */}
          <details className="mt-4">
            <summary className="text-xs text-slate-400 cursor-pointer hover:text-slate-600 select-none">
              📋 查看原始步骤日志 ({pipeline!.steps.length} 条)
            </summary>
            <div className="overflow-x-auto rounded-lg border border-slate-200 mt-3">
              <table className="w-full">
                <thead className="bg-slate-100">
                  <tr>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-600 w-10">#</th>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-600">节点</th>
                    <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-600">操作</th>
                    <th className="text-right px-4 py-2.5 text-xs font-semibold text-slate-600 w-24">耗时</th>
                    <th className="text-right px-4 py-2.5 text-xs font-semibold text-slate-600 w-24">累计</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {pipeline!.steps.map((step) => (
                    <tr key={step.seq} className="hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3 text-xs text-slate-400">{step.seq}</td>
                      <td className="px-4 py-3">
                        <span className="text-sm font-semibold" style={{ color: LEVEL_COLORS[step.level] || '#64748b' }}>
                          {step.node}
                        </span>
                        {step.input && Object.keys(step.input).length > 0 && (
                          <div className="text-xs text-slate-400 mt-0.5 font-mono truncate max-w-[200px]" title={JSON.stringify(step.input)}>
                            in: {JSON.stringify(step.input).substring(0, 60)}...
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600">{step.action}</td>
                      <td className="px-4 py-3 text-xs text-slate-500 text-right font-mono">
                        {step.duration_ms > 0 ? `${step.duration_ms.toFixed(0)}ms` : '-'}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 text-right font-mono">
                        +{step.elapsed_ms.toFixed(0)}ms
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
      ) : (
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-800 mb-1 flex items-center gap-2">🔄 审核数据链路</h3>
          <div className="text-center py-8">
            <div className="text-3xl mb-2 opacity-20">📋</div>
            <p className="text-sm text-slate-400">该审核记录暂无 Pipeline 日志</p>
            <p className="text-xs text-slate-300 mt-1">日志可能在 Redis 中已过期 (TTL=1h)，或审核使用了快速路径</p>
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════
          Section C: 模型审核结果 + AI 推理过程
          ═══════════════════════════════════════════ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 模型审核结果 */}
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
            🤖 模型审核结果
          </h3>
          <dl className="space-y-3">
            <DetailRow label="最终决策" value={
              <span className={`badge ${decisionCfg.className}`}>{decisionCfg.icon} {decisionCfg.label}</span>
            } />
            <DetailRow label="风险分数" value={`${((record.risk_score ?? 0) * 100).toFixed(1)}%`} />
            <DetailRow label="违规类型" value={
              (record.violation_types || []).length > 0
                ? (record.violation_types || []).map(t => <span key={t} className="badge badge-reject text-xs mr-1">{t}</span>)
                : <span className="text-slate-400 text-sm">无</span>
            } />
            <DetailRow label="处理耗时" value={`${(record.processing_time_ms ?? 0).toFixed(0)}ms`} />
            {record.violation_details && Object.keys(record.violation_details).length > 0 && (
              <div>
                <dt className="text-xs text-slate-500 mb-1">违规详情</dt>
                <dd className="bg-slate-50 rounded-lg p-3 text-xs text-slate-600 font-mono leading-relaxed max-h-32 overflow-y-auto">
                  {JSON.stringify(record.violation_details, null, 2)}
                </dd>
              </div>
            )}
          </dl>

          {/* 辩论信息 (内嵌) */}
          {hasDebate && (
            <div className="mt-4 pt-4 border-t border-slate-100">
              <h4 className="text-xs font-semibold text-slate-600 mb-2">⚖️ 辩论详情</h4>
              <div className="flex flex-wrap gap-3 text-sm">
                <span className="text-slate-500">模式: <strong>{record.debate_info!.debate_mode}</strong></span>
                <span className="text-slate-500">参与方: <strong>{record.debate_info!.opinion_count}</strong></span>
                <span className="text-slate-500">共识: <strong>{record.debate_info!.is_consensus ? '✅ 是' : '❌ 否'}</strong></span>
                <span className="text-slate-500">人工审核: <strong>{record.debate_info!.needs_human_review ? '⏳ 需要' : '不需要'}</strong></span>
              </div>
              {record.debate_info!.agent_opinions?.length > 0 && (
                <div className="mt-2 space-y-1">
                  {record.debate_info!.agent_opinions.map(op => (
                    <div key={op.agent} className="flex items-center gap-3 text-xs text-slate-600 bg-slate-50 rounded px-2 py-1">
                      <span className="font-medium">{op.agent}</span>
                      <span className="text-slate-400">→</span>
                      <span className={op.decision === 'REJECT' ? 'text-red-500' : op.decision === 'REVIEW' ? 'text-yellow-500' : 'text-green-500'}>
                        {op.decision}
                      </span>
                      <span className="text-slate-400">({(op.confidence * 100).toFixed(0)}%)</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* AI 推理过程 */}
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
            🧠 AI 推理过程
          </h3>
          {hasReasoning ? (
            <div className="space-y-4">
              {Object.entries(record.agent_reasoning!).map(([agent, reasoning]) => (
                <div key={agent} className="bg-slate-50 rounded-lg p-4 border border-slate-100">
                  <div className="flex items-center gap-3 mb-2 flex-wrap">
                    <span className="text-sm font-semibold text-slate-700">{agent}</span>
                    <span className={`badge text-xs ${reasoning.violation_type !== 'none' ? 'badge-reject' : 'badge-pass'}`}>
                      {reasoning.violation_type !== 'none' ? reasoning.violation_type : '正常'}
                    </span>
                    <span className="text-xs text-slate-400">{(reasoning.confidence * 100).toFixed(0)}%</span>
                  </div>
                  {reasoning.reasoning && (
                    <p className="text-sm text-slate-600 mb-2 leading-relaxed">{reasoning.reasoning}</p>
                  )}
                  {reasoning.reason && !reasoning.reasoning && (
                    <p className="text-sm text-slate-500 mb-2">{reasoning.reason}</p>
                  )}
                  {reasoning.reasoning_chain && reasoning.reasoning_chain.length > 0 && (
                    <div className="space-y-1 mt-2 pt-2 border-t border-slate-200">
                      <div className="text-xs text-slate-400 mb-1">推理链:</div>
                      {reasoning.reasoning_chain.map((step, i) => (
                        <p key={i} className="text-xs text-slate-500 font-mono">{step}</p>
                      ))}
                    </div>
                  )}
                  {reasoning.keyword_matches && reasoning.keyword_matches.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-2">
                      {reasoning.keyword_matches.map(kw => (
                        <span key={kw} className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded">{kw}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-12">
              <div className="text-3xl mb-2 opacity-20">🧠</div>
              <p className="text-sm text-slate-400">暂无 AI 推理过程数据</p>
              <p className="text-xs text-slate-300 mt-1">
                推理过程仅在审核当时生成，历史记录可能不含此数据
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ═══════════════════════════════════════════
          Section D: 标注结果
          ═══════════════════════════════════════════ */}
      <div className="card p-5">
        <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
          🏷️ 标注结果
          <span className="text-xs text-slate-400 font-normal">
            (AnnotationAgent 独立校验)
          </span>
        </h3>
        {hasAnnotation ? (
          <div className="space-y-5">
            {/* 标注判定 Banner */}
            <div className="flex items-center gap-4 p-4 rounded-xl" style={{
              background: (ERROR_COLORS[annotation!.error_type] || '#94a3b8') + '12',
              border: `1px solid ${(ERROR_COLORS[annotation!.error_type] || '#94a3b8') + '30'}`
            }}>
              <span className="text-3xl">{annotation!.is_error ? '❌' : '✅'}</span>
              <div>
                <div className="text-sm font-bold text-slate-800">
                  {annotation!.is_error ? '模型判定存在错误' : '模型判定正确'}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="inline-block px-3 py-0.5 rounded-full text-xs font-semibold text-white"
                    style={{ background: ERROR_COLORS[annotation!.error_type] || '#94a3b8' }}>
                    {ERROR_LABELS[annotation!.error_type] || annotation!.error_type}
                  </span>
                  <span className="text-xs text-slate-400">标注耗时: {annotation!.processing_time_ms.toFixed(0)}ms</span>
                </div>
              </div>
            </div>

            {/* 三视角详情 */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* 规则引擎 */}
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                <div className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
                  <span>📏</span> 规则引擎复核
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">判定</span>
                    <span className={`text-xs font-semibold ${
                      annotation!.rule_verdict === 'violation' ? 'text-red-600' :
                      annotation!.rule_verdict === 'normal' ? 'text-green-600' : 'text-slate-500'
                    }`}>
                      {annotation!.rule_verdict === 'violation' ? '🔴 违规' :
                       annotation!.rule_verdict === 'normal' ? '🟢 正常' : '⚪ 不确定'}
                    </span>
                  </div>
                  <div>
                    <span className="text-xs text-slate-500 block mb-1">详情</span>
                    <p className="text-xs text-slate-600 leading-relaxed">{annotation!.rule_detail || '-'}</p>
                  </div>
                  {(annotation as any).rule_matched_keywords?.length > 0 && (
                    <div>
                      <span className="text-xs text-slate-500 block mb-1">命中关键词</span>
                      <div className="flex flex-wrap gap-1">
                        {(annotation as any).rule_matched_keywords.map((kw: string) => (
                          <span key={kw} className="text-[10px] bg-red-100 text-red-600 px-1.5 py-0.5 rounded">{kw}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* LLM 独立审核 */}
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                <div className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
                  <span>🤖</span> LLM 独立审核
                </div>
                {annotation!.llm_verdict ? (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">判定</span>
                      <span className={`text-xs font-semibold ${
                        annotation!.llm_verdict === 'violation' ? 'text-red-600' :
                        annotation!.llm_verdict === 'normal' ? 'text-green-600' : 'text-slate-500'
                      }`}>
                        {annotation!.llm_verdict === 'violation' ? '🔴 违规' :
                         annotation!.llm_verdict === 'normal' ? '🟢 正常' : '⚪ 不确定'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">置信度</span>
                      <span className="text-xs text-slate-700 font-semibold">
                        {((annotation!.annotated_confidence || 0) * 100).toFixed(1)}%
                      </span>
                    </div>
                    {annotation!.llm_reason && (
                      <div>
                        <span className="text-xs text-slate-500 block mb-1">判定理由</span>
                        <p className="text-xs text-slate-600 leading-relaxed bg-white rounded p-2 border border-slate-100">
                          {annotation!.llm_reason}
                        </p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-center py-3">
                    <div className="text-xl opacity-30">⚡</div>
                    <p className="text-xs text-slate-400">规则引擎明确一致，跳过 LLM 调用</p>
                  </div>
                )}
              </div>

              {/* 语义矛盾检测 */}
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                <div className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
                  <span>🔍</span> 语义矛盾检测
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">检测结果</span>
                    <span className={`text-xs font-semibold ${annotation!.contradiction_flag ? 'text-red-600' : 'text-green-600'}`}>
                      {annotation!.contradiction_flag ? '⚠️ 检测到矛盾' : '✅ 无矛盾'}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    对比 violation_type 与 reason 的语义自洽性
                  </p>
                  {annotation!.contradiction_flag && (
                    <div className="bg-red-50 rounded-lg p-2 border border-red-100">
                      <p className="text-xs text-red-600">
                        {annotation!.error_detail?.split('矛盾检测: ')?.[1]?.split(';')?.[0] || '语义矛盾'}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* 详细说明 */}
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-100">
              <div className="text-xs text-slate-500 mb-2">📝 综合裁决说明</div>
              <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{annotation!.error_detail}</p>
            </div>

            {/* 标注违规类型 */}
            {annotation!.annotated_violation_types?.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500">标注违规类型:</span>
                {annotation!.annotated_violation_types.map(t => (
                  <span key={t} className="badge badge-reject text-xs">{t}</span>
                ))}
              </div>
            )}

            {/* 标注时间 */}
            {(annotation as any).annotated_at && (
              <div className="text-xs text-slate-400">
                标注时间: {formatDateTime((annotation as any).annotated_at)}
              </div>
            )}
          </div>
        ) : (
          <div className="text-center py-12">
            <div className="text-3xl mb-2 opacity-20">🏷️</div>
            <p className="text-sm text-slate-400">暂无标注结果</p>
            <p className="text-xs text-slate-300 mt-1">标注在审核完成后异步进行，请稍后刷新</p>
          </div>
        )}
      </div>

      {/* ═══════════════════════════════════════════
          Section E: 处理建议
          ═══════════════════════════════════════════ */}
      {record.suggestions?.length > 0 && (
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
            💡 处理建议
          </h3>
          <div className="space-y-2">
            {record.suggestions.map((s, i) => (
              <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-slate-50">
                <span className={`w-2.5 h-2.5 rounded-full mt-1.5 shrink-0 ${
                  s.priority === 'HIGH' ? 'bg-red-500' :
                  s.priority === 'MEDIUM' ? 'bg-yellow-500' : 'bg-blue-500'
                }`} />
                <div>
                  <p className="text-sm font-medium text-slate-700">{s.action}</p>
                  <p className="text-xs text-slate-500 mt-0.5">{s.reason}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 空数据提示 ── */}
      {!hasPipeline && !hasAnnotation && !hasReasoning && !hasDebate && (
        <div className="card p-8 text-center border-2 border-dashed border-slate-200">
          <div className="text-4xl mb-3 opacity-20">📭</div>
          <p className="text-sm text-slate-500">该记录仅包含基础审核数据</p>
          <p className="text-xs text-slate-400 mt-1">
            Pipeline 日志 (Redis TTL=1h) 和标注结果可能已过期。提交新审核内容可获得完整数据。
          </p>
        </div>
      )}
    </div>
  )
}

// ── Helper Components ──

function MiniStat({ label, value, icon }: { label: string; value: React.ReactNode; icon: string }) {
  return (
    <div className="bg-slate-50 rounded-lg p-3 text-center">
      <div className="text-lg mb-1">{icon}</div>
      <div className="text-xs text-slate-500 mb-0.5">{label}</div>
      <div className="text-sm font-semibold text-slate-700">{value}</div>
    </div>
  )
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="text-sm text-slate-700">{value}</dd>
    </div>
  )
}
