import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'
import type { PendingReviewEnhanced, ModerationResponse, AnnotationResult } from '../types'

const TYPE_LABELS: Record<string, string> = {
  text: '文本', image: '图片', audio: '语音', video: '视频',
}
const DECISION_BADGE: Record<string, string> = {
  PASS: 'bg-green-100 text-green-700',
  REJECT: 'bg-red-100 text-red-700',
  REVIEW: 'bg-yellow-100 text-yellow-700',
  PENDING_HUMAN_REVIEW: 'bg-purple-100 text-purple-700',
}
const VIOLATION_OPTIONS = [
  'none', 'politics', 'porn', 'violence', 'false_info', 'harassment', 'advertisement',
]
const VIOLATION_LABELS: Record<string, string> = {
  none: '无违规', politics: '政治敏感', porn: '色情低俗', violence: '暴力恐怖',
  false_info: '虚假信息', harassment: '辱骂骚扰', advertisement: '广告引流',
}

export default function HumanReviewPanel() {
  const [reviews, setReviews] = useState<PendingReviewEnhanced[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedCid, setSelectedCid] = useState<string | null>(null)
  const [detail, setDetail] = useState<ModerationResponse | null>(null)
  const [textPreview, setTextPreview] = useState('') // fallback: 从列表项带来的文本预览
  const [detailLoading, setDetailLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [annotationResult, setAnnotationResult] = useState<AnnotationResult | null>(null)
  const [resultMsg, setResultMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)

  // R22·C10: 标注人从 localStorage 持久化，不再硬编码 annotator_001
  const [reviewerId, setReviewerId] = useState(() => localStorage.getItem('reviewer_id') || '')

  const handleReviewerChange = (v: string) => {
    setReviewerId(v)
    localStorage.setItem('reviewer_id', v)
  }

  // R22·C8: 标注统计（getHumanAnnotationStats + getAnnotationStats）
  const [annotationStats, setAnnotationStats] = useState<{
    human: { total: number; errors_found: number; false_positives: number; false_negatives: number; wrong_types: number; correct: number; avg_weight: number } | null
    auto: { total: number; errors_found: number } | null
  } | null>(null)
  const [autoStats, setAutoStats] = useState<Record<string, number | string> | null>(null)

  const loadStats = useCallback(async () => {
    try {
      const [hs, as] = await Promise.all([
        api.getHumanAnnotationStats().catch(() => null),
        api.getAnnotationStats().catch(() => null),
      ])
      setAnnotationStats(hs as never)
      setAutoStats(as as Record<string, number | string> | null)
    } catch {
      // 统计失败不阻塞页面
    }
  }, [])

  useEffect(() => { loadStats() }, [loadStats])

  // 标注表单
  const [form, setForm] = useState({
    decision: '' as string,
    violation_type: 'none',
    confidence: 85, // 0-100
    reason: '',
    tags: [] as string[],
    is_adversarial: false,
    tagInput: '',
  })

  const loadReviews = useCallback(async () => {
    try {
      const data = await api.getPendingReviews() as { total: number; items: PendingReviewEnhanced[] }
      setReviews(data.items || [])
    } catch (e) {
      console.error('Failed to load pending reviews:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadReviews()
    const timer = setInterval(loadReviews, 10000)
    return () => clearInterval(timer)
  }, [loadReviews])

  // ===== 进入详情标注视图 =====
  const openDetail = async (item: PendingReviewEnhanced) => {
    setSelectedCid(item.content_id)
    setDetailLoading(true)
    setDetail(null)
    setAnnotationResult(null)
    setResultMsg(null)
    setTextPreview(item.text_preview || '')  // v3.2: 保存列表中的文本预览作 fallback
    setForm({
      decision: '',
      violation_type: 'none',
      confidence: 85,
      reason: '',
      tags: [],
      is_adversarial: false,
      tagInput: '',
    })
    try {
      const [rec, ann] = await Promise.all([
        api.getResult(item.content_id) as Promise<ModerationResponse>,
        api.getAnnotationResult(item.content_id).catch(() => null) as Promise<AnnotationResult | null>,
      ])
      setDetail(rec)
      setAnnotationResult(ann)
      // 预填表单: 根据 AI 判定
      if (rec) {
        const aiVt = rec.violation_types?.[0] || 'none'
        setForm(f => ({
          ...f,
          violation_type: aiVt,
          reason: rec.final_decision === 'PASS' ? '' : `AI判定: ${aiVt}, 请修正`,
        }))
      }
    } catch (e) {
      console.error('Failed to load detail:', e)
    } finally {
      setDetailLoading(false)
    }
  }

  // ===== 提交人工标注 =====
  const submitAnnotation = async () => {
    if (!selectedCid || !form.decision) return
    if (!reviewerId.trim()) {
      setResultMsg({ type: 'err', text: '❌ 请先在列表页填写标注人姓名' })
      return
    }
    setSubmitting(true)
    setResultMsg(null)
    try {
      const data = {
        reviewer_id: reviewerId.trim(),
        violation_type: form.violation_type,
        confidence: form.confidence / 100,
        reason: form.reason || '人工标注',
        tags: form.tags,
        is_adversarial: form.is_adversarial,
        decision: form.decision,
      }
      const resp = await api.submitHumanAnnotation(selectedCid, data) as {
        saved: boolean; is_error: boolean; error_type: string; human_corrected: Record<string, unknown>
      }
      if (resp.saved) {
        // R22·C8: 同时恢复被中断的工作流（submitReview），让人工判定真正生效
        try {
          await api.submitReview(selectedCid, form.decision, form.reason || '人工标注', form.violation_type)
        } catch (e) {
          console.warn('恢复工作流失败（标注已保存）:', e)
        }
        setResultMsg({
          type: 'ok',
          text: `✅ 标注完成: 判定=${form.decision}, 类型=${VIOLATION_LABELS[form.violation_type] || form.violation_type}` +
            (resp.is_error ? ` (AI判定有误, ${resp.error_type})` : ' (AI判定正确)') +
            ' — 1秒后返回列表',
        })
        // 从列表移除
        setReviews(prev => prev.filter(r => r.content_id !== selectedCid))
        // v3.2: 标注完成后自动返回待标注列表
        setTimeout(() => {
          setSelectedCid(null)
          setDetail(null)
          setAnnotationResult(null)
          setResultMsg(null)
        }, 1200)
      }
    } catch (e) {
      setResultMsg({ type: 'err', text: `❌ 提交失败: ${e instanceof Error ? e.message : '未知错误'}` })
    } finally {
      setSubmitting(false)
    }
  }

  const addTag = () => {
    const t = form.tagInput.trim()
    if (t && !form.tags.includes(t)) {
      setForm(f => ({ ...f, tags: [...f.tags, t], tagInput: '' }))
    }
  }
  const removeTag = (t: string) => {
    setForm(f => ({ ...f, tags: f.tags.filter(x => x !== t) }))
  }

  // ===== 列表视图 =====
  if (!selectedCid) {
    if (loading) {
      return (
        <div className="space-y-6 animate-fade-in">
          <h2 className="text-xl font-bold text-slate-800">人工审核</h2>
          <div className="card p-12 text-center text-slate-400">加载中...</div>
        </div>
      )
    }

    return (
      <div className="space-y-6 animate-fade-in">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-slate-800">人工审核</h2>
            <p className="text-sm text-slate-500 mt-1">
              模糊边界 / 低置信度 / Agent分歧 — 需标注人员修正AI的JSON输出
            </p>
          </div>
          <div className="flex items-center gap-3">
            <input
              value={reviewerId}
              onChange={e => handleReviewerChange(e.target.value)}
              placeholder="标注人姓名（提交标注必需）"
              className="input text-sm py-2 w-52"
            />
            <span className={`badge ${reviews.length > 0 ? 'badge-review' : 'bg-slate-100 text-slate-600'}`}>
              {reviews.length} 条待审
            </span>
            <button onClick={loadReviews} className="btn btn-secondary text-sm py-2">🔄 刷新</button>
          </div>
        </div>

        {/* R22·C8: 标注统计区（真实后端数据） */}
        {(annotationStats || autoStats) && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="card p-4">
              <h3 className="text-xs font-semibold text-slate-500 uppercase mb-2">🤖 自动标注统计（auto）</h3>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <div className="text-xl font-bold text-slate-800">{autoStats?.total_processed ?? annotationStats?.auto?.total ?? 0}</div>
                  <div className="text-xs text-slate-400">已处理</div>
                </div>
                <div>
                  <div className="text-xl font-bold text-amber-600">{autoStats?.total_errors ?? annotationStats?.auto?.errors_found ?? 0}</div>
                  <div className="text-xs text-slate-400">发现错误</div>
                </div>
                <div>
                  <div className="text-xl font-bold text-green-600">{autoStats?.correct ?? 0}</div>
                  <div className="text-xs text-slate-400">判定正确</div>
                </div>
              </div>
            </div>
            <div className="card p-4">
              <h3 className="text-xs font-semibold text-slate-500 uppercase mb-2">👤 人工标注统计（human）</h3>
              <div className="grid grid-cols-4 gap-2 text-center">
                <div>
                  <div className="text-xl font-bold text-slate-800">{annotationStats?.human?.total ?? 0}</div>
                  <div className="text-xs text-slate-400">标注总数</div>
                </div>
                <div>
                  <div className="text-xl font-bold text-red-600">{annotationStats?.human?.errors_found ?? 0}</div>
                  <div className="text-xs text-slate-400">纠错</div>
                </div>
                <div>
                  <div className="text-xl font-bold text-slate-600">
                    {(annotationStats?.human?.false_positives ?? 0) + (annotationStats?.human?.false_negatives ?? 0)}
                  </div>
                  <div className="text-xs text-slate-400">误报/漏报</div>
                </div>
                <div>
                  <div className="text-xl font-bold text-slate-600">{annotationStats?.human?.avg_weight ?? 0}</div>
                  <div className="text-xs text-slate-400">平均权重</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {reviews.length === 0 ? (
          <div className="card p-12 text-center">
            <div className="text-4xl mb-3">✅</div>
            <p className="text-slate-500 text-sm">暂无待审核内容</p>
            <p className="text-slate-400 text-xs mt-1">
              当AI判定置信度低或Agent间严重分歧时, 内容会自动进入此队列
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {reviews.map(item => {
              const aiReasoning = item.agent_reasoning
              // 提取 AI 判定摘要
              let aiSummary = ''
              if (aiReasoning && Object.keys(aiReasoning).length > 0) {
                const firstAgent = Object.values(aiReasoning)[0]
                aiSummary = `${firstAgent.violation_type} (${((firstAgent.confidence || 0) * 100).toFixed(0)}%)`
              }
              return (
                <div key={item.content_id} className="card p-5 hover:shadow-md transition-shadow cursor-pointer"
                  onClick={() => openDetail(item)}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2 flex-wrap">
                        <span className="badge badge-info">{TYPE_LABELS[item.content_type] || item.content_type}</span>
                        <span className="text-xs font-mono text-slate-400">{item.content_id}</span>
                        {item.annotation_status === 'reviewed' ? (
                          <span className="badge bg-green-100 text-green-700">已标注</span>
                        ) : (
                          <span className="badge badge-review">待审核</span>
                        )}
                      </div>
                      <p className="text-sm text-slate-700 line-clamp-2 mb-2">
                        {item.text_preview || '(无文本内容)'}
                      </p>
                      <div className="flex items-center gap-3 text-xs text-slate-500 flex-wrap">
                        <span>风险分: <strong className="text-amber-600">{item.risk_score.toFixed(3)}</strong></span>
                        {item.violation_types && item.violation_types.length > 0 && (
                          <span>AI违规: {item.violation_types.join(', ')}</span>
                        )}
                        {aiSummary && (
                          <span className="text-purple-600">AI摘要: {aiSummary}</span>
                        )}
                        <span className="text-slate-400">{item.reason}</span>
                      </div>
                    </div>
                    <button className="btn btn-primary text-sm py-2 px-4 flex-shrink-0">
                      开始标注
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  // ===== 标注详情视图 =====
  if (detailLoading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <button onClick={() => setSelectedCid(null)} className="text-sm text-blue-600 hover:underline">← 返回列表</button>
        <div className="card p-12 text-center text-slate-400">加载详情中...</div>
      </div>
    )
  }

  const agentReasoning = detail?.agent_reasoning

  return (
    <div className="space-y-6 animate-fade-in">
      {/* 顶部导航 */}
      <div className="flex items-center justify-between">
        <button onClick={() => setSelectedCid(null)} className="text-sm text-blue-600 hover:underline font-medium">
          ← 返回待审核列表
        </button>
        <span className="text-xs font-mono text-slate-400">{selectedCid}</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ===== 左栏: AI 审核结果 (只读, 供参考) ===== */}
        <div className="space-y-4">
          <div className="card p-5">
            <h3 className="text-sm font-semibold text-slate-700 mb-3">📋 原始内容</h3>
            <div className="bg-slate-50 rounded-lg p-4 text-sm text-slate-700 max-h-48 overflow-y-auto whitespace-pre-wrap">
              {detail?.content_preview
                ? detail.content_preview
                : textPreview
                  ? textPreview
                  : '(未能获取原始内容)'}
            </div>
          </div>

          {/* AI 判定摘要 */}
          {detail && (
            <div className="card p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">🤖 AI 审核结果</h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-500">最终决策:</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-semibold ${DECISION_BADGE[detail.final_decision] || 'bg-slate-100'}`}>
                    {detail.final_decision}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">风险分数:</span>
                  <span className="font-mono font-semibold">{(detail.risk_score * 100).toFixed(1)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">违规类型:</span>
                  <span>{detail.violation_types?.join(', ') || '无'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">处理耗时:</span>
                  <span className="font-mono">{detail.processing_time_ms.toFixed(0)}ms</span>
                </div>
                {detail.debate_info && (
                  <div className="mt-2 pt-2 border-t border-slate-200">
                    <span className="text-amber-600 text-xs font-semibold">
                      ⚖️ 触发辩论: {String((detail.debate_info as Record<string, unknown>).debate_mode || '')}
                      {', '}{String((detail.debate_info as Record<string, unknown>).opinion_count || '')}个意见
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* AI 推理详情 */}
          {agentReasoning && Object.keys(agentReasoning).length > 0 && (
            <div className="card p-5">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">🔍 AI 推理过程</h3>
              {Object.entries(agentReasoning).map(([agent, reasoning]) => (
                <div key={agent} className="mb-4 last:mb-0">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-bold text-slate-600 uppercase">{agent}</span>
                    <span className={`text-xs px-2 py-0.5 rounded ${
                      reasoning.violation_type !== 'none' ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'
                    }`}>
                      {reasoning.violation_type} ({(reasoning.confidence * 100).toFixed(0)}%)
                    </span>
                  </div>
                  {/* 推理文本 */}
                  {reasoning.reasoning && (
                    <p className="text-xs text-slate-600 bg-slate-50 p-3 rounded mb-2 max-h-48 overflow-y-auto">
                      {reasoning.reasoning}
                    </p>
                  )}
                  {/* 推理链步骤 */}
                  {reasoning.reasoning_chain && reasoning.reasoning_chain.length > 0 && (
                    <div className="space-y-1">
                      <span className="text-xs text-slate-400">推理链:</span>
                      {reasoning.reasoning_chain.map((step, i) => (
                        <div key={i} className="text-xs font-mono bg-slate-100 px-2 py-1 rounded">
                          {step}
                        </div>
                      ))}
                    </div>
                  )}
                  {/* 关键词匹配 */}
                  {reasoning.keyword_matches && reasoning.keyword_matches.length > 0 && (
                    <div className="flex gap-1 flex-wrap mt-2">
                      {reasoning.keyword_matches.map((kw, i) => (
                        <span key={i} className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded">{kw}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* 已有标注结果 (如果已被标注) */}
          {annotationResult && (
            <div className="card p-5 border-2 border-green-200">
              <h3 className="text-sm font-semibold text-green-700 mb-3">✅ 已有标注记录</h3>
              <div className="space-y-1 text-xs text-slate-600">
                <p>标注判定: <strong>{annotationResult.annotated_violation_types?.join(', ') || '无'}</strong></p>
                <p>是否正确: {annotationResult.is_error ? `❌ ${annotationResult.error_type}` : '✅ 正确'}</p>
                <p>详情: {annotationResult.error_detail}</p>
                <p className="text-slate-400">标注时间: {annotationResult.annotated_at || '未知'}</p>
              </div>
            </div>
          )}
        </div>

        {/* ===== 右栏: 标注操作区 (可编辑) ===== */}
        <div className="space-y-4">
          <div className="card p-5 border-2 border-blue-200">
            <h3 className="text-sm font-semibold text-blue-700 mb-4">✏️ 人工标注 — 修正 AI 输出</h3>

            {/* 最终决策 */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-2">最终判定 *</label>
              <div className="flex gap-3">
                {[
                  { key: 'PASS', label: '✅ 通过', color: 'border-green-500 text-green-700 bg-green-50' },
                  { key: 'REJECT', label: '🚫 拒绝', color: 'border-red-500 text-red-700 bg-red-50' },
                  { key: 'REVIEW', label: '🔍 复核', color: 'border-yellow-500 text-yellow-700 bg-yellow-50' },
                ].map(opt => (
                  <button key={opt.key}
                    onClick={() => setForm(f => ({ ...f, decision: opt.key }))}
                    className={`flex-1 py-2.5 rounded-lg border-2 text-sm font-semibold transition-all ${
                      form.decision === opt.key
                        ? `${opt.color} ring-2 ring-offset-1`
                        : 'border-slate-200 text-slate-500 hover:border-slate-300'
                    }`}>
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 违规类型 */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-2">违规类型</label>
              <select value={form.violation_type}
                onChange={e => setForm(f => ({ ...f, violation_type: e.target.value }))}
                className="input w-full text-sm">
                {VIOLATION_OPTIONS.map(vt => (
                  <option key={vt} value={vt}>{VIOLATION_LABELS[vt] || vt}</option>
                ))}
              </select>
            </div>

            {/* 置信度滑块 */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-2">
                标注置信度: {form.confidence}%
              </label>
              <input type="range" min="0" max="100" value={form.confidence}
                onChange={e => setForm(f => ({ ...f, confidence: Number(e.target.value) }))}
                className="w-full" />
              <div className="flex justify-between text-xs text-slate-400">
                <span>0%</span><span>50%</span><span>100%</span>
              </div>
            </div>

            {/* 判定理由 */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-2">
                判定理由 <span className="text-slate-400 font-normal">(标注依据)</span>
              </label>
              <textarea value={form.reason}
                onChange={e => setForm(f => ({ ...f, reason: e.target.value }))}
                placeholder="描述标注判定依据..."
                rows={3} className="input resize-none w-full text-sm" />
            </div>

            {/* 标签 */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-slate-500 uppercase mb-2">标签</label>
              <div className="flex gap-1 flex-wrap mb-2">
                {form.tags.map(t => (
                  <span key={t} className="text-xs bg-blue-100 text-blue-700 px-2 py-1 rounded flex items-center gap-1">
                    {t}
                    <button onClick={() => removeTag(t)} className="text-blue-400 hover:text-red-500">×</button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                <input value={form.tagInput}
                  onChange={e => setForm(f => ({ ...f, tagInput: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addTag())}
                  placeholder="输入标签后按回车"
                  className="input flex-1 text-sm" />
                <button onClick={addTag} className="btn btn-secondary text-sm py-2">添加</button>
              </div>
            </div>

            {/* 对抗样本 */}
            <div className="mb-4">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={form.is_adversarial}
                  onChange={e => setForm(f => ({ ...f, is_adversarial: e.target.checked }))}
                  className="w-4 h-4" />
                <span>标记为对抗样本</span>
              </label>
            </div>

            {/* 结果消息 */}
            {resultMsg && (
              <div className={`p-3 rounded-lg text-sm mb-4 ${
                resultMsg.type === 'ok' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
              }`}>
                {resultMsg.text}
              </div>
            )}

            {/* 提交按钮 */}
            <div className="flex gap-3">
              <button onClick={() => setSelectedCid(null)}
                className="btn btn-secondary text-sm py-2 flex-1">取消</button>
              <button onClick={submitAnnotation}
                disabled={!form.decision || submitting}
                className="btn btn-primary text-sm py-2 flex-1">
                {submitting ? '提交中...' : '✅ 提交标注'}
              </button>
            </div>
          </div>

          {/* AI vs 人工对比提示 */}
          {detail && form.decision && (
            <div className="card p-4 bg-slate-50">
              <h4 className="text-xs font-semibold text-slate-500 uppercase mb-2">AI vs 人工 对比</h4>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between">
                  <span>决策:</span>
                  <span>
                    <span className={DECISION_BADGE[detail.final_decision] + ' px-1 py-0.5 rounded'}>{detail.final_decision}</span>
                    {' → '}
                    <span className={DECISION_BADGE[form.decision] + ' px-1 py-0.5 rounded'}>{form.decision}</span>
                    {detail.final_decision !== form.decision
                      ? <span className="text-red-500 ml-1">⚠️ 不一致</span>
                      : <span className="text-green-500 ml-1">✅ 一致</span>}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span>违规类型:</span>
                  <span>
                    {(detail.violation_types?.[0] || 'none')} → {form.violation_type}
                    {(detail.violation_types?.[0] || 'none') !== form.violation_type
                      ? <span className="text-red-500 ml-1">⚠️ 不一致</span>
                      : <span className="text-green-500 ml-1">✅ 一致</span>}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
