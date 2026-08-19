import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'
import type { FeedbackStats, PromptInfo, PromptVersion, AnnotationResult, OptimizationReport, AnnotationAllResult } from '../types'
import { formatTime, formatUnixTimestamp, formatDateTime } from '../utils/time'

const ERROR_COLORS: Record<string, string> = {
  false_positive: '#ef4444',
  false_negative: '#f59e0b',
  wrong_violation_type: '#8b5cf6',
  correct: '#10b981',
}

const ERROR_LABELS: Record<string, string> = {
  false_positive: '误判',
  false_negative: '漏判',
  wrong_violation_type: '类型错误',
  correct: '正确',
}

export default function OptimizationMonitor() {
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null)
  const [prompts, setPrompts] = useState<PromptInfo[]>([])
  const [selectedPrompt, setSelectedPrompt] = useState<string>('')
  const [versions, setVersions] = useState<PromptVersion[]>([])
  const [activeVersion, setActiveVersion] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [optimizing, setOptimizing] = useState(false)
  const [optResult, setOptResult] = useState<{ optimized: boolean; reason?: string; new_version?: string; report?: OptimizationReport } | null>(null)
  const [auditLog, setAuditLog] = useState<string[]>([])
  // v2: 标注相关状态
  const [annotationBuffer, setAnnotationBuffer] = useState<AnnotationResult[]>([])
  const [allAnnotations, setAllAnnotations] = useState<AnnotationResult[]>([])
  const [annotationFilter, setAnnotationFilter] = useState<string>('')
  const [showReport, setShowReport] = useState<OptimizationReport | null>(null)

  // v3: 优化历史
  const [optimizationHistory, setOptimizationHistory] = useState<OptimizationReport[]>([])
  const [selectedHistory, setSelectedHistory] = useState<OptimizationReport | null>(null)

  // v4: 标注详情弹窗
  const [selectedAnnotation, setSelectedAnnotation] = useState<AnnotationResult | null>(null)
  const [annotationDetailLoading, setAnnotationDetailLoading] = useState(false)

  const loadData = useCallback(async () => {
    try {
      const [stats, promptsData, bufferData, allAnnotationData, historyData] = await Promise.all([
        api.getFeedbackStats() as Promise<FeedbackStats>,
        api.listAllPrompts() as Promise<{ prompts: PromptInfo[] }>,
        api.getAnnotationBuffer(8, 0).catch(() => ({ items: [] })) as Promise<{ items: AnnotationResult[] }>,
        api.getAllAnnotations(50, 0).catch(() => ({ items: [] })) as Promise<{ items: AnnotationResult[] }>,
        api.getOptimizationReports(20).catch(() => ({ reports: [] })) as Promise<{ reports: OptimizationReport[] }>,
      ])
      setFeedbackStats(stats)
      setPrompts(promptsData.prompts || [])
      setAnnotationBuffer(bufferData.items || [])
      setAllAnnotations(allAnnotationData.items || [])
      setOptimizationHistory(historyData.reports || [])
      if (promptsData.prompts?.length > 0 && !selectedPrompt) {
        setSelectedPrompt(promptsData.prompts[0].name)
      }
    } catch (e) {
      console.error('Optimization monitor load error:', e)
    } finally {
      setLoading(false)
    }
  }, [selectedPrompt])

  useEffect(() => {
    loadData()
    const timer = setInterval(loadData, 10000)
    return () => clearInterval(timer)
  }, [loadData])

  // Load versions when prompt selected
  useEffect(() => {
    if (!selectedPrompt) return
    api.getPromptVersions(selectedPrompt).then((data: unknown) => {
      const d = data as { versions: PromptVersion[]; active_version: string | null }
      setVersions(d.versions || [])
      setActiveVersion(d.active_version || null)
    }).catch(() => {})
  }, [selectedPrompt])

  const handleTriggerOptimization = async () => {
    setOptimizing(true)
    setOptResult(null)
    try {
      const result = await api.triggerOptimization() as { optimized: boolean; reason?: string; report?: OptimizationReport }
      setOptResult(result)
      const timestamp = formatTime(new Date().toISOString())
      if (result.optimized) {
        setAuditLog(prev => [`${timestamp} ✅ 优化成功 → ${result.report?.optimization_actions?.length || 0} 个动作`, ...prev.slice(0, 19)])
        if (result.report) setShowReport(result.report)
        loadData()
      } else {
        setAuditLog(prev => [`${timestamp} ⚠️ 优化未触发: ${result.reason || ''}`, ...prev.slice(0, 19)])
      }
    } catch (e) {
      setOptResult({ optimized: false, reason: e instanceof Error ? e.message : '请求失败' })
    } finally {
      setOptimizing(false)
    }
  }

  const openAnnotationDetail = async (item: AnnotationResult) => {
    // 先用列表数据显示
    setSelectedAnnotation(item)
    // 异步获取最完整数据
    setAnnotationDetailLoading(true)
    try {
      const full = await api.getAnnotationResult(item.content_id) as AnnotationResult | null
      if (full) {
        setSelectedAnnotation(full)
      }
    } catch {
      // 列表数据已足够, 忽略获取失败
    } finally {
      setAnnotationDetailLoading(false)
    }
  }

  const closeAnnotationDetail = () => {
    setSelectedAnnotation(null)
  }

  const bufferPercent = feedbackStats
    ? Math.min(100, Math.round(((feedbackStats.buffer_size || 0) / (feedbackStats.threshold || 100)) * 100))
    : 0

  const errorTypes = [
    { key: 'false_positives', label: '误判', color: ERROR_COLORS.false_positive, icon: '🔴' },
    { key: 'false_negatives', label: '漏判', color: ERROR_COLORS.false_negative, icon: '🟡' },
    { key: 'wrong_types', label: '类型错误', color: ERROR_COLORS.wrong_violation_type, icon: '🟣' },
    { key: 'correct', label: '正确', color: ERROR_COLORS.correct, icon: '🟢' },
  ]

  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <h2 className="text-xl font-bold text-slate-800">优化监控</h2>
        <div className="card p-12 text-center text-slate-400">加载中...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-800">优化监控</h2>
          <p className="text-sm text-slate-500 mt-1">
            AnnotationAgent 标注校验 + FeedbackLoop 积累 (&ge;100) → OptimizationAgent 智能优化
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={loadData} className="btn btn-secondary text-sm py-2">
            🔄 刷新
          </button>
        </div>
      </div>

      {/* v2: 标注统计卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatMiniCard
          label="已处理" value={feedbackStats?.total_processed || 0}
          icon="📊" color="slate"
        />
        <StatMiniCard
          label="正确" value={feedbackStats?.correct || 0}
          icon="✅" color="green"
        />
        <StatMiniCard
          label="误判" value={feedbackStats?.false_positives || 0}
          icon="🔴" color="red"
        />
        <StatMiniCard
          label="漏判" value={feedbackStats?.false_negatives || 0}
          icon="🟡" color="yellow"
        />
      </div>

      {/* Buffer Progress + Trigger */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card p-5 md:col-span-2">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">
            📊 错误案例积累 (仅模型判断错误的数据)
          </h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-500">已积累错误案例</span>
              <span className="font-bold text-slate-700">
                {feedbackStats?.buffer_size || 0} / {feedbackStats?.threshold || 100}
              </span>
            </div>
            {/* Progress Bar */}
            <div className="w-full bg-slate-100 rounded-full h-4 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-700 ${
                  bufferPercent >= 100
                    ? 'bg-gradient-to-r from-green-400 to-emerald-500 animate-pulse'
                    : bufferPercent >= 60
                    ? 'bg-gradient-to-r from-amber-400 to-orange-500'
                    : 'bg-gradient-to-r from-indigo-400 to-blue-500'
                }`}
                style={{ width: `${bufferPercent}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{bufferPercent}%</span>
              <span>{feedbackStats?.ready_to_optimize ? '✅ 已达到优化阈值 (≥100)' : '⏳ 累积中...'}</span>
            </div>
            {feedbackStats?.last_annotation_time ? (
              <p className="text-xs text-slate-400">
                上次标注: {formatUnixTimestamp(feedbackStats.last_annotation_time)}
              </p>
            ) : (
              <p className="text-xs text-slate-400">尚未有标注数据</p>
            )}
          </div>

          {/* v2: 错误分类分布 */}
          {feedbackStats && (feedbackStats.false_positives || feedbackStats.false_negatives || feedbackStats.wrong_types) ? (
            <div className="mt-4 pt-4 border-t border-slate-100">
              <div className="flex gap-4">
                {errorTypes.map(et => {
                  const count = (feedbackStats as unknown as Record<string, number>)[et.key] || 0
                  const total = (feedbackStats.total_errors || 1) + (feedbackStats.correct || 0)
                  const pct = total > 0 ? Math.round((count / total) * 100) : 0
                  return (
                    <div key={et.key} className="flex-1 text-center">
                      <div className="text-lg">{et.icon}</div>
                      <div className="text-xs text-slate-500 mt-1">{et.label}</div>
                      <div className="text-sm font-bold" style={{ color: et.color }}>{count}</div>
                      <div className="text-[10px] text-slate-400">{pct}%</div>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}
        </div>

        {/* Trigger Button Card */}
        <div className="card p-5 flex flex-col items-center justify-center gap-4">
          <div className="text-4xl">🚀</div>
          <p className="text-sm text-slate-600 text-center">
            手动触发智能优化<br />
            <span className="text-xs text-slate-400">(手动不受阈值限制, ≥5条即可)</span>
          </p>
          <button
            onClick={handleTriggerOptimization}
            disabled={optimizing}
            className={`btn text-sm py-2 px-6 w-full ${
              feedbackStats?.ready_to_optimize
                ? 'btn-primary animate-pulse-glow'
                : 'btn-secondary'
            }`}
          >
            {optimizing ? '优化中...' : '触发优化'}
          </button>
          {optResult && (
            <div className={`text-xs text-center p-2 rounded-lg w-full ${
              optResult.optimized
                ? 'bg-green-50 text-green-700'
                : 'bg-amber-50 text-amber-700'
            }`}>
              {optResult.optimized
                ? `✅ 完成: ${optResult.report?.optimization_actions?.length || 0} 个优化动作`
                : `⚠️ ${optResult.reason || '条件不满足'}`
              }
            </div>
          )}
          {!feedbackStats?.ready_to_optimize && (
            <p className="text-xs text-slate-400 text-center">
              错误案例达到 {feedbackStats?.threshold || 100} 条后自动触发
            </p>
          )}
          {/* v2: 查看最近报告 */}
          {showReport && (
            <button
              onClick={() => { setSelectedHistory(null); setTimeout(() => document.getElementById('opt-report-detail')?.scrollIntoView({ behavior: 'smooth' }), 100) }}
              className="text-xs text-indigo-600 hover:underline"
            >
              📄 查看最新报告
            </button>
          )}
        </div>
      </div>

      {/* v3: 标注详情 — 全部标注结果 (正确+错误) */}
      <div className="card overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex items-center justify-between flex-wrap gap-2">
          <h3 className="text-sm font-semibold text-slate-700">📋 标注详情 ({allAnnotations.length} 条)</h3>
          <div className="flex items-center gap-2">
            {['', 'correct', 'false_positive', 'false_negative', 'wrong_violation_type'].map(f => (
              <button
                key={f}
                onClick={() => setAnnotationFilter(f)}
                className={`text-xs px-2 py-1 rounded-full transition-colors ${
                  annotationFilter === f ? 'bg-indigo-100 text-indigo-700 font-medium' : 'text-slate-500 hover:bg-slate-100'
                }`}
              >
                {f === '' ? '全部' : ERROR_LABELS[f] || f}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <table className="w-full">
            <thead className="bg-slate-50 sticky top-0">
              <tr>
                <th className="text-left px-4 py-2 text-[11px] font-semibold text-slate-500 uppercase">时间</th>
                <th className="text-left px-4 py-2 text-[11px] font-semibold text-slate-500 uppercase">Content ID</th>
                <th className="text-left px-4 py-2 text-[11px] font-semibold text-slate-500 uppercase">来源</th>
                <th className="text-left px-4 py-2 text-[11px] font-semibold text-slate-500 uppercase">标注判定</th>
                <th className="text-left px-4 py-2 text-[11px] font-semibold text-slate-500 uppercase">规则引擎</th>
                <th className="text-left px-4 py-2 text-[11px] font-semibold text-slate-500 uppercase">LLM审核</th>
                <th className="text-left px-4 py-2 text-[11px] font-semibold text-slate-500 uppercase">矛盾检测</th>
                <th className="text-center px-4 py-2 text-[11px] font-semibold text-slate-500 uppercase w-20">详情</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {allAnnotations.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-6 text-slate-400 text-sm">
                    暂无标注数据，提交审核后自动标注
                  </td>
                </tr>
              ) : (
                (annotationFilter
                  ? allAnnotations.filter(a => a.error_type === annotationFilter)
                  : allAnnotations
                ).slice(0, 20).map(item => (
                  <tr
                    key={item.content_id}
                    onClick={() => openAnnotationDetail(item)}
                    className="hover:bg-indigo-50/40 transition-colors cursor-pointer"
                  >
                    <td className="px-4 py-2.5 text-xs text-slate-500 whitespace-nowrap">
                      {item.annotated_at ? formatDateTime(item.annotated_at) : '-'}
                    </td>
                    <td className="px-4 py-2.5 text-xs font-mono text-slate-600 max-w-[140px] truncate" title={item.content_id}>
                      {item.content_id?.substring(0, 16)}...
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                        item.source === 'human'
                          ? 'bg-purple-100 text-purple-700'
                          : 'bg-slate-100 text-slate-500'
                      }`}>
                        {item.source === 'human' ? '👤 人工' : '🤖 自动'}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold text-white"
                        style={{ background: ERROR_COLORS[item.error_type] || '#94a3b8' }}
                      >
                        {ERROR_LABELS[item.error_type] || item.error_type}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs ${
                        item.rule_verdict === 'violation' ? 'text-red-500 font-medium' :
                        item.rule_verdict === 'normal' ? 'text-green-500' : 'text-slate-400'
                      }`}>
                        {item.rule_verdict === 'violation' ? '🔴 违规' :
                         item.rule_verdict === 'normal' ? '🟢 正常' : '⚪ 不确定'}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`text-xs ${item.llm_verdict === 'violation' ? 'text-red-500' : item.llm_verdict === 'normal' ? 'text-green-500' : 'text-slate-400'}`}>
                        {item.llm_verdict ? (
                          item.llm_verdict === 'violation' ? '违规' :
                          item.llm_verdict === 'normal' ? '正常' : '不确定'
                        ) : (item.llm_called === false ? '⚡ 跳过' : '-')}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs">
                      {item.contradiction_flag ? '⚠️ 是' : '✅ 否'}
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <button
                        onClick={(e) => { e.stopPropagation(); openAnnotationDetail(item) }}
                        className="text-xs text-indigo-600 hover:text-indigo-800 hover:bg-indigo-50 px-2 py-1 rounded transition-colors font-medium"
                      >
                        📄 查看
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Prompt Registry */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="card p-0 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100 bg-slate-50">
            <h3 className="text-sm font-semibold text-slate-700">📝 Prompt 注册表</h3>
          </div>
          <div className="divide-y divide-slate-50">
            {prompts.map(p => (
              <button
                key={p.name}
                onClick={() => setSelectedPrompt(p.name)}
                className={`w-full text-left px-5 py-3 text-sm transition-colors hover:bg-slate-50 ${
                  selectedPrompt === p.name ? 'bg-indigo-50 border-l-2 border-indigo-500' : ''
                }`}
              >
                <div className="font-medium text-slate-700">{p.name}</div>
                <div className="text-xs text-slate-400 mt-0.5">
                  v{p.active_version || '?'} · {p.total_versions} 个版本
                </div>
              </button>
            ))}
            {prompts.length === 0 && (
              <div className="px-5 py-4 text-sm text-slate-400">暂无 Prompt</div>
            )}
          </div>
        </div>

        {/* Version History */}
        <div className="lg:col-span-3 card p-0 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700">
              📋 {selectedPrompt || 'Prompt'} · 版本历史
            </h3>
            {activeVersion && (
              <span className="badge badge-pass">活跃: v{activeVersion}</span>
            )}
          </div>
          <div className="divide-y divide-slate-50">
            {versions.map(v => (
              <div key={v.version} className={`px-5 py-3 ${
                v.version === activeVersion ? 'bg-green-50/30' : ''
              }`}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-semibold text-slate-700">v{v.version}</span>
                  {v.version === activeVersion && (
                    <span className="badge badge-pass text-[10px]">当前</span>
                  )}
                  <span className="badge badge-info text-[10px]">{v.optimizer}</span>
                  <span className="text-xs text-slate-400">{v.model}</span>
                </div>
                <p className="text-xs text-slate-500 line-clamp-2 mb-1">
                  {v.system_prompt_snippet}
                </p>
                {v.metrics && Object.keys(v.metrics).length > 0 && (
                  <div className="text-xs text-slate-400">
                    指标: {JSON.stringify(v.metrics)}
                  </div>
                )}
              </div>
            ))}
            {versions.length === 0 && (
              <div className="px-5 py-8 text-center text-sm text-slate-400">
                选择左侧 Prompt 查看版本历史
              </div>
            )}
          </div>
        </div>
      </div>

      {/* v3: 优化历史 + 详情 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 优化历史时间线 */}
        <div className="card p-0 overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-100 bg-slate-50">
            <h3 className="text-sm font-semibold text-slate-700">📜 优化历史</h3>
          </div>
          <div className="divide-y divide-slate-50 max-h-96 overflow-y-auto">
            {optimizationHistory.length === 0 ? (
              <div className="px-5 py-8 text-center text-sm text-slate-400">
                暂无优化记录，buffer满100条后自动触发
              </div>
            ) : (
              optimizationHistory.map((report) => (
                <div
                  key={report.report_id || report.timestamp}
                  onClick={() => setSelectedHistory(report)}
                  className={`px-4 py-3 cursor-pointer hover:bg-slate-50 transition-colors ${
                    selectedHistory?.report_id === report.report_id || selectedHistory?.timestamp === report.timestamp
                      ? 'bg-indigo-50 border-l-2 border-indigo-500' : ''
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className={`badge text-[10px] ${report.trigger === 'auto' ? 'badge-info' : 'badge-pass'}`}>
                      {report.trigger === 'auto' ? '自动' : '手动'}
                    </span>
                    <span className="text-xs text-slate-400">{report.timestamp?.substring(0, 16) || ''}</span>
                  </div>
                  <div className="flex items-center justify-between mt-1.5">
                    <span className="text-xs text-slate-600">{report.total_samples} 样本</span>
                    <span className="text-xs text-slate-500">{report.optimization_actions?.length || 0} 动作</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* 优化详情 */}
        <div className="lg:col-span-2" id="opt-report-detail">
          {selectedHistory ? (
            <div className="card p-5 border-2 border-indigo-200 bg-white">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                  📄 优化详情
                  <span className="text-xs text-slate-400 font-mono">{selectedHistory.report_id}</span>
                </h3>
                <button onClick={() => setSelectedHistory(null)} className="text-slate-400 hover:text-slate-600">✕</button>
              </div>
              <div className="space-y-4">
                {/* Before/After 对比 */}
                {selectedHistory.before && selectedHistory.after && (
                  <div className="grid grid-cols-2 gap-4">
                    <div className="bg-red-50/30 rounded-lg p-3 border border-red-100">
                      <div className="text-xs text-red-500 font-medium mb-2">🔴 优化前</div>
                      {Object.entries(selectedHistory.before.prompts || {}).map(([name, p]) => (
                        <div key={name} className="text-xs text-slate-600 mb-1">
                          <span className="font-medium">{name}:</span> v{p.version}
                        </div>
                      ))}
                      <div className="text-xs text-slate-500 mt-2">
                        {Object.entries(selectedHistory.before.keywords_stats || {}).map(([k, v]) => (
                          <span key={k} className="mr-2">{k}: {v}</span>
                        ))}
                      </div>
                    </div>
                    <div className="bg-green-50/30 rounded-lg p-3 border border-green-100">
                      <div className="text-xs text-green-500 font-medium mb-2">🟢 优化后</div>
                      {Object.entries(selectedHistory.after.prompts || {}).map(([name, p]) => (
                        <div key={name} className="text-xs text-slate-600 mb-1">
                          <span className="font-medium">{name}:</span> v{p.version}
                        </div>
                      ))}
                      <div className="text-xs text-slate-500 mt-2">
                        {Object.entries(selectedHistory.after.keywords_stats || {}).map(([k, v]) => (
                          <span key={k} className="mr-2">{k}: {v}</span>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* 错误分布 */}
                <div className="flex gap-2 text-sm">
                  {Object.entries(selectedHistory.error_distribution || {}).map(([k, v]) => (
                    <span key={k} className="px-3 py-1 rounded-full text-xs font-semibold" style={{
                      background: (ERROR_COLORS[k] || '#94a3b8') + '20',
                      color: ERROR_COLORS[k] || '#94a3b8',
                    }}>
                      {ERROR_LABELS[k] || k}: {v}
                    </span>
                  ))}
                </div>

                {/* 模式分析 */}
                {selectedHistory.pattern_analysis && (
                  <div className="bg-slate-50 rounded-lg p-4">
                    <div className="text-xs text-slate-500 mb-1">📊 模式分析</div>
                    <p className="text-sm text-slate-700">{selectedHistory.pattern_analysis}</p>
                  </div>
                )}

                {/* 优化动作 */}
                {selectedHistory.optimization_actions?.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-xs text-slate-500">🔧 优化动作 ({selectedHistory.optimization_actions.length})</div>
                    {selectedHistory.optimization_actions.map((action, i) => (
                      <div key={i} className="bg-slate-50 rounded-lg p-3 border border-slate-100">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="badge badge-info text-[10px]">{action.action_type}</span>
                          <span className="text-sm font-medium text-slate-700">{action.target}</span>
                        </div>
                        <p className="text-xs text-slate-600 mb-1">{action.description}</p>
                        <p className="text-xs text-slate-400">依据: {action.reason}</p>
                      </div>
                    ))}
                  </div>
                )}

                {/* 预期提升 */}
                {selectedHistory.estimated_impact && (
                  <div className="bg-green-50 rounded-lg p-4 border border-green-100">
                    <div className="text-xs text-green-600 mb-1">📈 预期提升</div>
                    <p className="text-sm text-green-800">{selectedHistory.estimated_impact}</p>
                  </div>
                )}

                <div className="text-xs text-slate-400 pt-2 border-t border-slate-100">
                  {selectedHistory.total_samples} 条样本 · {formatDateTime(selectedHistory.timestamp)}
                </div>
              </div>
            </div>
          ) : showReport ? (
            /* 最新优化结果 (简化版) */
            <div className="card p-5 border-2 border-indigo-200 bg-indigo-50/30">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold text-slate-800">📄 最近优化完成</h3>
                <button onClick={() => setShowReport(null)} className="text-slate-400 hover:text-slate-600">✕</button>
              </div>
              <div className="space-y-3">
                <p className="text-sm text-slate-600">{showReport.optimization_actions?.length || 0} 个优化动作已执行</p>
                <div className="flex gap-2">
                  {Object.entries(showReport.error_distribution).map(([k, v]) => (
                    <span key={k} className="px-3 py-1 rounded-full text-xs font-semibold" style={{
                      background: (ERROR_COLORS[k] || '#94a3b8') + '20', color: ERROR_COLORS[k] || '#94a3b8',
                    }}>
                      {ERROR_LABELS[k] || k}: {v}
                    </span>
                  ))}
                </div>
                {showReport.estimated_impact && (
                  <p className="text-xs text-green-600">📈 {showReport.estimated_impact}</p>
                )}
              </div>
            </div>
          ) : (
            <div className="card p-5 text-center py-16">
              <div className="text-5xl mb-4 opacity-20">📜</div>
              <p className="text-sm text-slate-400">选择左侧优化记录查看详情</p>
              <p className="text-xs text-slate-300 mt-1">或点击"触发优化"执行新优化</p>
            </div>
          )}
        </div>
      </div>

      {/* Optimization Audit Log */}
      <div className="card p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
          📜 优化操作日志
        </h3>
        <div className="bg-slate-900 rounded-lg p-4 font-mono text-xs max-h-40 overflow-y-auto space-y-0.5">
          {auditLog.length > 0 ? (
            auditLog.map((line, i) => (
              <div key={i}>
                <span className="text-slate-500">{line.substring(0, 9)}</span>
                <span className="text-green-300">{line.substring(9)}</span>
              </div>
            ))
          ) : (
            <div className="text-slate-500">等待优化事件...</div>
          )}
        </div>
      </div>

      {/* v4: 标注详情弹窗 */}
      {selectedAnnotation && (
        <AnnotationDetailModal
          annotation={selectedAnnotation}
          loading={annotationDetailLoading}
          onClose={closeAnnotationDetail}
        />
      )}
    </div>
  )
}

function StatMiniCard({ label, value, icon, color }: {
  label: string; value: number; icon: string; color: string
}) {
  const bgMap: Record<string, string> = {
    slate: 'from-slate-500 to-gray-500',
    green: 'from-emerald-500 to-teal-500',
    red: 'from-red-500 to-rose-500',
    yellow: 'from-amber-500 to-orange-500',
    purple: 'from-violet-500 to-purple-500',
  }
  return (
    <div className="card p-4 hover:shadow-md transition-all">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xl">{icon}</span>
        <div className={`w-5 h-5 rounded bg-gradient-to-br ${bgMap[color] || bgMap.slate} opacity-15`} />
      </div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-xl font-bold text-slate-800">{value.toLocaleString()}</p>
    </div>
  )
}

// ============================================================
// v4: 标注详情弹窗 — 完整展示审核结果 + 标注全过程
// ============================================================

const DECISION_LABELS: Record<string, { label: string; color: string; icon: string }> = {
  PASS: { label: '通过', color: '#10b981', icon: '✓' },
  REVIEW: { label: '人工复核', color: '#f59e0b', icon: '⚠' },
  REJECT: { label: '拒绝', color: '#ef4444', icon: '✕' },
  UNKNOWN: { label: '未知', color: '#94a3b8', icon: '?' },
}

function AnnotationDetailModal({
  annotation,
  loading,
  onClose,
}: {
  annotation: AnnotationResult
  loading: boolean
  onClose: () => void
}) {
  const errorCfg = {
    color: ERROR_COLORS[annotation.error_type] || '#94a3b8',
    label: ERROR_LABELS[annotation.error_type] || annotation.error_type,
  }
  const modelDecisionCfg = DECISION_LABELS[annotation.model_decision || ''] || DECISION_LABELS.UNKNOWN

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-8 pb-8 overflow-y-auto" style={{ background: 'rgba(0,0,0,0.5)' }} onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl mx-4 animate-fade-in" onClick={e => e.stopPropagation()}>
        {/* Modal Header */}
        <div className="sticky top-0 bg-white rounded-t-2xl border-b border-slate-200 px-6 py-4 flex items-center justify-between z-10">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold text-slate-800">📋 标注详情</h2>
            <span
              className="inline-block px-3 py-1 rounded-full text-xs font-semibold text-white"
              style={{ background: errorCfg.color }}
            >
              {errorCfg.label}
            </span>
            <span className={`inline-block px-3 py-1 rounded-full text-xs font-semibold ${
              annotation.source === 'human'
                ? 'bg-purple-100 text-purple-700 border border-purple-300'
                : 'bg-slate-100 text-slate-500 border border-slate-300'
            }`}>
              {annotation.source === 'human' ? '👤 人工标注' : '🤖 自动标注'}
            </span>
            {annotation.source === 'human' && annotation.reviewer_id && (
              <span className="text-xs text-slate-400 font-mono">
                标注人: {annotation.reviewer_id}
              </span>
            )}
            {loading && (
              <span className="text-xs text-slate-400">加载完整数据中...</span>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 w-8 h-8 rounded-full flex items-center justify-center text-lg transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Modal Body */}
        <div className="px-6 py-5 space-y-6 overflow-y-auto" style={{ maxHeight: 'calc(100vh - 200px)' }}>

          {/* 基本信息栏 */}
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-slate-400">Content ID:</span>
              <code className="text-xs bg-slate-100 px-2 py-1 rounded text-slate-700 font-mono">{annotation.content_id}</code>
            </div>
            {annotation.annotated_at && (
              <div className="flex items-center gap-2">
                <span className="text-slate-400">标注时间:</span>
                <span className="text-slate-700 font-medium">{formatDateTime(annotation.annotated_at)}</span>
              </div>
            )}
            {annotation.content_type && (
              <div className="flex items-center gap-2">
                <span className="text-slate-400">内容类型:</span>
                <span className="badge badge-info text-xs">{annotation.content_type}</span>
              </div>
            )}
            <div className="flex items-center gap-2">
              <span className="text-slate-400">处理耗时:</span>
              <span className="text-slate-700 font-medium">{annotation.processing_time_ms?.toFixed(0)}ms</span>
            </div>
          </div>

          {/* Section 1: 原始审核内容 */}
          {annotation.annotation_input && (
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-100">
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                📝 原始审核内容
              </h3>
              <div className="bg-white rounded-lg p-4 border border-slate-200 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto">
                {annotation.annotation_input}
              </div>
            </div>
          )}

          {/* Section 2: 模型审核结果 vs 标注判定 — 并排对比 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* 模型审核结果 */}
            <div className="bg-blue-50/30 rounded-xl p-4 border border-blue-100">
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                🤖 模型原始判定
              </h3>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">决策</span>
                  <span className="text-sm font-semibold" style={{ color: modelDecisionCfg.color }}>
                    {modelDecisionCfg.icon} {modelDecisionCfg.label}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">风险分数</span>
                  <span className="text-sm font-semibold text-slate-700">
                    {((annotation.model_risk_score || 0) * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">置信度</span>
                  <span className="text-sm font-semibold text-slate-700">
                    {((annotation.model_confidence || 0) * 100).toFixed(1)}%
                  </span>
                </div>
                {annotation.model_violation_types && annotation.model_violation_types.length > 0 && (
                  <div>
                    <span className="text-xs text-slate-500 block mb-1">违规类型</span>
                    <div className="flex flex-wrap gap-1">
                      {annotation.model_violation_types.map(t => (
                        <span key={t} className="badge badge-reject text-[10px]">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
                {annotation.model_reason && (
                  <div>
                    <span className="text-xs text-slate-500 block mb-1">判定理由</span>
                    <p className="text-xs text-slate-600 bg-white rounded p-2 border border-slate-100">{annotation.model_reason}</p>
                  </div>
                )}
              </div>
            </div>

            {/* 标注判定结果 */}
            <div className="rounded-xl p-4 border" style={{ background: errorCfg.color + '08', borderColor: errorCfg.color + '30' }}>
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                🏷️ 标注判定
              </h3>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">判定结果</span>
                  <span className="text-sm font-bold" style={{ color: errorCfg.color }}>
                    {annotation.is_error ? '❌ 模型错误' : '✅ 模型正确'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">错误类型</span>
                  <span
                    className="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold text-white"
                    style={{ background: errorCfg.color }}
                  >
                    {errorCfg.label}
                  </span>
                </div>
                {/* v3.2: 标注来源与权重 */}
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">标注来源</span>
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                    annotation.source === 'human' ? 'bg-purple-100 text-purple-700' : 'bg-slate-100 text-slate-500'
                  }`}>
                    {annotation.source === 'human' ? '👤 人工标注' : '🤖 自动标注'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">标注权重</span>
                  <span className={`text-xs font-semibold ${(annotation.weight || 1.0) >= 3.0 ? 'text-purple-600' : 'text-slate-500'}`}>
                    {annotation.weight || 1.0}x
                  </span>
                </div>
                {annotation.annotated_violation_types && annotation.annotated_violation_types.length > 0 && (
                  <div>
                    <span className="text-xs text-slate-500 block mb-1">标注违规类型</span>
                    <div className="flex flex-wrap gap-1">
                      {annotation.annotated_violation_types.map(t => (
                        <span key={t} className="badge badge-reject text-[10px]">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-500">标注置信度</span>
                  <span className="text-sm font-semibold text-slate-700">
                    {((annotation.annotated_confidence || 0) * 100).toFixed(1)}%
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Section 3: 标注全过程 — 三视角分析 */}
          <div>
            <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              🔍 标注全过程 — 三视角交叉验证
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* 视角1: 规则引擎 */}
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                <div className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
                  <span className="text-base">📏</span> 规则引擎复核
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">判定</span>
                    <span className={`text-xs font-semibold ${
                      annotation.rule_verdict === 'violation' ? 'text-red-600' :
                      annotation.rule_verdict === 'normal' ? 'text-green-600' : 'text-slate-500'
                    }`}>
                      {annotation.rule_verdict === 'violation' ? '🔴 违规' :
                       annotation.rule_verdict === 'normal' ? '🟢 正常' : '⚪ 不确定'}
                    </span>
                  </div>
                  <div>
                    <span className="text-xs text-slate-500 block mb-1">详情</span>
                    <p className="text-xs text-slate-600 leading-relaxed">{annotation.rule_detail || '-'}</p>
                  </div>
                  {annotation.rule_matched_keywords && annotation.rule_matched_keywords.length > 0 && (
                    <div>
                      <span className="text-xs text-slate-500 block mb-1">命中关键词</span>
                      <div className="flex flex-wrap gap-1">
                        {annotation.rule_matched_keywords.map(kw => (
                          <span key={kw} className="text-[10px] bg-red-100 text-red-600 px-1.5 py-0.5 rounded">{kw}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  {annotation.rule_matched_rules && annotation.rule_matched_rules.length > 0 && (
                    <div>
                      <span className="text-xs text-slate-500 block mb-1">命中规则</span>
                      <div className="flex flex-wrap gap-1">
                        {annotation.rule_matched_rules.map(r => (
                          <span key={r} className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded">{r}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="flex gap-3 text-[10px] text-slate-400 pt-1">
                    <span>白名单: {annotation.rule_whitelist_hit ? '✅ 命中' : '❌ 未命中'}</span>
                    <span>对抗特征: {annotation.rule_adversarial_hit ? '⚠️ 检测到' : '✅ 未检测到'}</span>
                  </div>
                </div>
              </div>

              {/* 视角2: LLM 独立审核 */}
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                <div className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
                  <span className="text-base">🤖</span> LLM 独立审核
                </div>
                {annotation.llm_verdict ? (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">判定</span>
                      <span className={`text-xs font-semibold ${
                        annotation.llm_verdict === 'violation' ? 'text-red-600' :
                        annotation.llm_verdict === 'normal' ? 'text-green-600' : 'text-slate-500'
                      }`}>
                        {annotation.llm_verdict === 'violation' ? '🔴 违规' :
                         annotation.llm_verdict === 'normal' ? '🟢 正常' : '⚪ 不确定'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-slate-500">置信度</span>
                      <span className="text-xs text-slate-700 font-semibold">
                        {((annotation.annotated_confidence || 0) * 100).toFixed(1)}%
                      </span>
                    </div>
                    {annotation.llm_reason && (
                      <div>
                        <span className="text-xs text-slate-500 block mb-1">判定理由</span>
                        <p className="text-xs text-slate-600 leading-relaxed bg-white rounded p-2 border border-slate-100">{annotation.llm_reason}</p>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-center py-4">
                    <div className="text-2xl mb-1 opacity-30">⚡</div>
                    <p className="text-xs text-slate-400">
                      {annotation.llm_called === false
                        ? '规则引擎明确一致，跳过 LLM 调用'
                        : '未调用（规则一致）'}
                    </p>
                  </div>
                )}
              </div>

              {/* 视角3: 语义矛盾检测 */}
              <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                <div className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-1.5">
                  <span className="text-base">🔍</span> 语义矛盾检测
                </div>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-slate-500">检测结果</span>
                    <span className={`text-xs font-semibold ${annotation.contradiction_flag ? 'text-red-600' : 'text-green-600'}`}>
                      {annotation.contradiction_flag ? '⚠️ 检测到矛盾' : '✅ 无矛盾'}
                    </span>
                  </div>
                  <div>
                    <span className="text-xs text-slate-500 block mb-1">检查逻辑</span>
                    <p className="text-xs text-slate-500 leading-relaxed">
                      对比 violation_type 与 reason 的语义自洽性:
                      若违规类型与理由描述内容不一致（如判为暴力但理由描述广告），
                      则标记为矛盾。
                    </p>
                  </div>
                  {annotation.contradiction_flag && (
                    <div className="bg-red-50 rounded-lg p-2 border border-red-100">
                      <p className="text-xs text-red-600">{annotation.error_detail?.split('矛盾检测: ')?.[1]?.split(';')?.[0] || '语义矛盾'}</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Section 4: 详细说明 */}
          <div className="bg-slate-50 rounded-xl p-4 border border-slate-100">
            <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              📝 综合裁决说明
            </h3>
            <div className="bg-white rounded-lg p-4 border border-slate-200">
              <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">{annotation.error_detail}</p>
            </div>
          </div>

          {/* Section 5: 裁决投票机制说明 */}
          <div className="bg-indigo-50/30 rounded-xl p-4 border border-indigo-100">
            <h3 className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-2">
              ⚖️ 三方投票裁决机制
            </h3>
            <p className="text-xs text-slate-600 leading-relaxed">
              规则: <strong>2-of-3 投票</strong>。规则引擎 + LLM独立审核 + 语义矛盾检测 三者中 ≥2 个认为模型出错 →
              标注为错误。<br />
              快速跳过: 规则引擎结果与模型判定明确一致时，跳过 LLM 调用以节省 Token。
            </p>
            <div className="mt-3 grid grid-cols-3 gap-3 text-center">
              <div className="bg-white rounded-lg p-2 border border-slate-200">
                <div className="text-[10px] text-slate-400 mb-0.5">规则引擎</div>
                <div className="text-xs font-semibold text-slate-700">{annotation.rule_verdict}</div>
              </div>
              <div className="bg-white rounded-lg p-2 border border-slate-200">
                <div className="text-[10px] text-slate-400 mb-0.5">LLM 审核</div>
                <div className="text-xs font-semibold text-slate-700">{annotation.llm_verdict || 'skipped'}</div>
              </div>
              <div className="bg-white rounded-lg p-2 border border-slate-200">
                <div className="text-[10px] text-slate-400 mb-0.5">矛盾检测</div>
                <div className="text-xs font-semibold text-slate-700">{annotation.contradiction_flag ? 'conflict' : 'clean'}</div>
              </div>
            </div>
          </div>

        </div>

        {/* Modal Footer */}
        <div className="border-t border-slate-200 px-6 py-4 flex items-center justify-between rounded-b-2xl bg-slate-50/50">
          <span className="text-xs text-slate-400">
            {annotation.is_error
              ? `错误类型: ${errorCfg.label} · 规则: ${annotation.rule_verdict} · LLM: ${annotation.llm_verdict || 'skipped'} · 矛盾: ${annotation.contradiction_flag ? '是' : '否'}`
              : '模型判定与标注验证一致，三方投票结果为正确'}
          </span>
          <button onClick={onClose} className="btn btn-secondary text-sm py-2 px-6">
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}
