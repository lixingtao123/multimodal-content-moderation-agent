import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'

interface Policy {
  id: string
  name: string
  policy_type: string
  description: string
  rule_config: Record<string, any>
  enabled: boolean
  priority: number
  created_by: string
  created_at: string
}

export default function PolicyManager() {
  const [activeTab, setActiveTab] = useState<'keywords' | 'thresholds'>('keywords')
  const [policies, setPolicies] = useState<Policy[]>([])
  const [loading, setLoading] = useState(true)

  const loadPolicies = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getPolicies() as { total: number; policies: Policy[] }
      setPolicies(data.policies || [])
    } catch (e) {
      console.error('Failed to load policies:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadPolicies() }, [loadPolicies])

  const deletePolicy = async (id: string) => {
    if (!confirm('确定删除此策略?')) return
    try {
      await api.deletePolicy(id)
      setPolicies(prev => prev.filter(p => p.id !== id))
    } catch (e: any) {
      alert('删除失败: ' + (e.message || '未知错误'))
    }
  }

  const togglePolicy = async (policy: Policy) => {
    try {
      await api.updatePolicy(policy.id, { enabled: !policy.enabled })
      setPolicies(prev => prev.map(p => p.id === policy.id ? { ...p, enabled: !p.enabled } : p))
    } catch (e: any) {
      alert('操作失败: ' + (e.message || '未知错误'))
    }
  }

  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <h2 className="text-xl font-bold text-slate-800">策略管理</h2>
        <div className="card p-12 text-center">
          <div className="w-10 h-10 border-3 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-sm text-slate-400">加载策略配置...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-800">策略管理</h2>
          <p className="text-sm text-slate-500 mt-1">审核规则、阈值、Agent 配置中心</p>
        </div>
      </div>

      {/* Tab 切换 */}
      <div className="flex gap-1 bg-slate-100 rounded-lg p-1 w-fit">
        {([
          { key: 'keywords', label: '🔤 敏感词库', desc: '关键词增删改查、分级分类' },
          { key: 'thresholds', label: '📏 阈值配置', desc: 'PASS/REVIEW/REJECT 分界值' },
          // Agent 调度已停用 (代码保留在 AgentsTab 组件中)
        ] as const).map(tab => (
          <button
            key={tab.key}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
              activeTab === tab.key ? 'bg-white shadow text-slate-800' : 'text-slate-500 hover:text-slate-700'
            }`}
            onClick={() => setActiveTab(tab.key)}
            title={tab.desc}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'keywords' && <KeywordsTab policies={policies} onDelete={deletePolicy} onToggle={togglePolicy} onRefresh={loadPolicies} />}
      {activeTab === 'thresholds' && <ThresholdsTab policies={policies} onRefresh={loadPolicies} />}
    </div>
  )
}

// ═══════════════════════════════════
// 敏感词库 Tab
// ═══════════════════════════════════

function KeywordsTab({ policies, onDelete, onToggle, onRefresh }: {
  policies: Policy[]
  onDelete: (id: string) => void
  onToggle: (p: Policy) => void
  onRefresh: () => void
}) {
  const keywordPolicies = policies.filter(p => p.policy_type === 'keyword')
  const [showForm, setShowForm] = useState(false)
  const [newName, setNewName] = useState('')
  const [newKeywords, setNewKeywords] = useState('')
  const [newLevel, setNewLevel] = useState('medium')
  const [saving, setSaving] = useState(false)

  // R22·C8: 详情弹窗（getPolicy 读取单条完整配置）
  const [detail, setDetail] = useState<Policy | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const showDetail = async (id: string) => {
    setDetailLoading(true)
    setDetail(null)
    try {
      setDetail(await api.getPolicy(id) as Policy)
    } catch (e: any) {
      alert('加载详情失败: ' + (e.message || '未知错误'))
    } finally {
      setDetailLoading(false)
    }
  }

  const saveKeyword = async () => {
    if (!newName.trim() || !newKeywords.trim()) return
    setSaving(true)
    try {
      await api.createPolicy({
        name: newName.trim(),
        policy_type: 'keyword',
        description: `${newLevel}级敏感词: ${newName}`,
        rule_config: { keywords: newKeywords.split(/[,，\n]/).map(s => s.trim()).filter(Boolean), level: newLevel },
        enabled: true,
        priority: 10,
        created_by: 'admin',
      })
      setShowForm(false)
      setNewName('')
      setNewKeywords('')
      onRefresh()
    } catch (e: any) {
      alert('保存失败: ' + (e.message || '未知错误'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          共 <strong>{keywordPolicies.length}</strong> 条敏感词策略
        </p>
        <button className="btn btn-primary text-sm" onClick={() => setShowForm(true)}>+ 新建敏感词库</button>
      </div>

      {/* 新建表单 */}
      {showForm && (
        <div className="card p-5 border-indigo-200 bg-indigo-50/30">
          <h4 className="text-sm font-bold text-slate-700 mb-3">新建敏感词策略</h4>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-3">
            <input className="input text-sm" placeholder="策略名称 (如: 竞品广告词)" value={newName} onChange={e => setNewName(e.target.value)} />
            <select className="input text-sm" value={newLevel} onChange={e => setNewLevel(e.target.value)}>
              <option value="high">高危</option>
              <option value="medium">中危</option>
              <option value="low">低危</option>
            </select>
            <div className="md:col-span-2 flex gap-2">
              <button className="btn btn-primary text-sm" onClick={saveKeyword} disabled={saving}>
                {saving ? '保存中...' : '保存'}
              </button>
              <button className="btn btn-secondary text-sm" onClick={() => setShowForm(false)}>取消</button>
            </div>
          </div>
          <textarea
            className="input w-full text-sm"
            rows={3}
            placeholder="输入敏感词, 逗号/换行分隔&#10;例如: 加微信, 扫码入群, 点击领取"
            value={newKeywords}
            onChange={e => setNewKeywords(e.target.value)}
          />
        </div>
      )}

      {/* 策略列表 */}
      {keywordPolicies.length === 0 ? (
        <div className="card p-12 text-center">
          <div className="text-4xl mb-3 opacity-20">🔤</div>
          <p className="text-sm text-slate-500">暂无敏感词策略</p>
          <p className="text-xs text-slate-400 mt-1">创建第一条敏感词策略开始风控规则配置</p>
        </div>
      ) : (
        <div className="space-y-3">
          {keywordPolicies.map(p => (
            <div key={p.id} className={`card p-4 flex items-center justify-between ${!p.enabled ? 'opacity-50' : ''}`}>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-semibold text-slate-700">{p.name}</span>
                  <span className={`badge text-xs ${p.rule_config?.level === 'high' ? 'badge-reject' : p.rule_config?.level === 'low' ? 'badge-pass' : 'badge-review'}`}>
                    {p.rule_config?.level === 'high' ? '高危' : p.rule_config?.level === 'low' ? '低危' : '中危'}
                  </span>
                  <span className={`badge text-xs ${p.enabled ? 'badge-pass' : 'badge-info'}`}>
                    {p.enabled ? '✅ 启用' : '⏸ 停用'}
                  </span>
                </div>
                <div className="flex flex-wrap gap-1 mt-2">
                  {(p.rule_config?.keywords || []).slice(0, 15).map((kw: string) => (
                    <span key={kw} className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded">{kw}</span>
                  ))}
                  {(p.rule_config?.keywords || []).length > 15 && (
                    <span className="text-xs text-slate-400">+{(p.rule_config.keywords.length - 15)} 个</span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 ml-4 shrink-0">
                <button className="btn btn-secondary text-xs py-1" onClick={() => showDetail(p.id)}>
                  详情
                </button>
                <button className="btn btn-secondary text-xs py-1" onClick={() => onToggle(p)}>
                  {p.enabled ? '停用' : '启用'}
                </button>
                <button className="btn btn-secondary text-xs py-1 text-red-500" onClick={() => onDelete(p.id)}>
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 详情弹窗（getPolicy 单条完整配置） */}
      {detailLoading && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setDetailLoading(false)}>
          <div className="bg-white rounded-lg p-6 max-w-lg w-full">
            <p className="text-sm text-slate-400">加载中...</p>
          </div>
        </div>
      )}
      {detail && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={() => setDetail(null)}>
          <div className="bg-white rounded-lg p-6 max-w-lg w-full shadow-xl">
            <div className="flex items-center justify-between mb-4">
              <h4 className="font-bold text-slate-800">{detail.name}</h4>
              <button className="text-slate-400 hover:text-slate-600 text-xl" onClick={() => setDetail(null)}>×</button>
            </div>
            <div className="text-xs space-y-3">
              <p><span className="text-slate-500">类型:</span> {detail.policy_type}</p>
              <p><span className="text-slate-500">优先级:</span> {detail.priority} <span className="text-slate-500">｜ 启用:</span> {detail.enabled ? '✅' : '⏸'}</p>
              <p><span className="text-slate-500">创建人:</span> {detail.created_by} <span className="text-slate-500">｜ 创建时间:</span> {detail.created_at || '-'}</p>
              <div>
                <span className="text-slate-500">描述:</span>
                <p className="mt-1 text-slate-600">{detail.description || '-'}</p>
              </div>
              <div>
                <span className="text-slate-500">规则配置 (rule_config):</span>
                <pre className="mt-1 bg-slate-50 p-3 rounded text-[11px] overflow-auto max-h-60">
                  {JSON.stringify(detail.rule_config, null, 2)}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════
// 阈值配置 Tab
// ═══════════════════════════════════

function ThresholdsTab({ policies, onRefresh }: { policies: Policy[]; onRefresh: () => void }) {
  const thresholdPolicies = policies.filter(p => p.policy_type === 'threshold')
  const [reviewThreshold, setReviewThreshold] = useState(0.3)
  const [rejectThreshold, setRejectThreshold] = useState(0.7)
  const [kwWeight, setKwWeight] = useState(0.3)
  const [semanticWeight, setSemanticWeight] = useState(0.5)
  const [caseWeight, setCaseWeight] = useState(0.2)
  const [saving, setSaving] = useState(false)

  // Load existing threshold policy
  useEffect(() => {
    const existing = thresholdPolicies[0]
    if (existing?.rule_config) {
      setReviewThreshold(existing.rule_config.review_threshold ?? 0.3)
      setRejectThreshold(existing.rule_config.reject_threshold ?? 0.7)
      setKwWeight(existing.rule_config.keyword_weight ?? 0.3)
      setSemanticWeight(existing.rule_config.semantic_weight ?? 0.5)
      setCaseWeight(existing.rule_config.case_weight ?? 0.2)
    }
  }, [policies])

  const saveThresholds = async () => {
    setSaving(true)
    try {
      const existing = thresholdPolicies[0]
      const data = {
        name: '风险阈值配置',
        policy_type: 'threshold',
        description: 'PASS/REVIEW/REJECT 分界值及权重配置',
        rule_config: {
          review_threshold: reviewThreshold,
          reject_threshold: rejectThreshold,
          keyword_weight: kwWeight,
          semantic_weight: semanticWeight,
          case_weight: caseWeight,
        },
        enabled: true,
        priority: 100,
        created_by: 'admin',
      }
      if (existing) {
        await api.updatePolicy(existing.id, data)
      } else {
        await api.createPolicy(data)
      }
      onRefresh()
      alert('阈值配置已保存')
    } catch (e: any) {
      alert('保存失败: ' + (e.message || '未知错误'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* 决策阈值 */}
      <div className="card p-5">
        <h3 className="text-sm font-bold text-slate-700 mb-4">决策阈值</h3>
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-slate-600">REVIEW (人工复核) 阈值</span>
              <span className="text-sm font-bold text-yellow-600">{(reviewThreshold * 100).toFixed(0)}%</span>
            </div>
            <input type="range" min="0" max="1" step="0.05" value={reviewThreshold}
              onChange={e => setReviewThreshold(Number(e.target.value))}
              className="w-full h-2 rounded bg-slate-200 appearance-none cursor-pointer"
              style={{ accentColor: '#f59e0b' }} />
            <div className="flex justify-between text-xs text-slate-400 mt-1">
              <span>0% — 低于此分: ✅ PASS</span>
              <span>100%</span>
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-slate-600">REJECT (直接拒绝) 阈值</span>
              <span className="text-sm font-bold text-red-600">{(rejectThreshold * 100).toFixed(0)}%</span>
            </div>
            <input type="range" min="0" max="1" step="0.05" value={rejectThreshold}
              onChange={e => setRejectThreshold(Number(e.target.value))}
              className="w-full h-2 rounded bg-slate-200 appearance-none cursor-pointer"
              style={{ accentColor: '#ef4444' }} />
            <div className="flex justify-between text-xs text-slate-400 mt-1">
              <span>REVIEW 阈值 — 中间: ⚠️ REVIEW</span>
              <span>高于此分: ❌ REJECT</span>
            </div>
          </div>
          {/* 决策区间示意 */}
          <div className="h-3 rounded-full overflow-hidden flex">
            <div className="bg-green-400 flex items-center justify-center text-[10px] text-white font-bold" style={{ width: `${reviewThreshold * 100}%` }}>PASS</div>
            <div className="bg-yellow-400 flex items-center justify-center text-[10px] text-white font-bold" style={{ width: `${(rejectThreshold - reviewThreshold) * 100}%` }}>REVIEW</div>
            <div className="bg-red-400 flex items-center justify-center text-[10px] text-white font-bold" style={{ width: `${(1 - rejectThreshold) * 100}%` }}>REJECT</div>
          </div>
        </div>
      </div>

      {/* 权重配置 */}
      <div className="card p-5">
        <h3 className="text-sm font-bold text-slate-700 mb-4">风险分权重系数</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <WeightSlider label="关键词得分" icon="🔤" value={kwWeight} onChange={setKwWeight} color="#6366f1" />
          <WeightSlider label="语义得分" icon="🧠" value={semanticWeight} onChange={setSemanticWeight} color="#10b981" />
          <WeightSlider label="历史案例得分" icon="📚" value={caseWeight} onChange={setCaseWeight} color="#f59e0b" />
        </div>
      </div>

      <button className="btn btn-primary" onClick={saveThresholds} disabled={saving}>
        {saving ? '💾 保存中...' : '💾 保存阈值配置'}
      </button>
    </div>
  )
}

function WeightSlider({ label, icon, value, onChange, color }: {
  label: string; icon: string; value: number; onChange: (v: number) => void; color: string
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <span>{icon}</span>
        <span className="text-sm text-slate-600">{label}</span>
        <span className="text-sm font-bold ml-auto" style={{ color }}>{(value * 100).toFixed(0)}%</span>
      </div>
      <input type="range" min="0" max="1" step="0.05" value={value}
        onChange={e => onChange(Number(e.target.value))}
        className="w-full h-2 rounded bg-slate-200 appearance-none cursor-pointer"
        style={{ accentColor: color }} />
    </div>
  )
}

// ═══════════════════════════════════
// Agent 调度 Tab
// ═══════════════════════════════════

const DEFAULT_AGENTS = [
  { key: 'text_agent', label: 'TextAgent', icon: '📝', desc: '文本内容审核 (DeepSeek LLM)', enabled: true },
  { key: 'image_agent', label: 'ImageAgent', icon: '🖼️', desc: '图片内容审核 (Vision Model)', enabled: true },
  { key: 'audio_agent', label: 'AudioAgent', icon: '🎤', desc: '语音审核 (ASR + LLM)', enabled: true },
  { key: 'video_agent', label: 'VideoAgent', icon: '🎬', desc: '视频审核 (截帧 + VL)', enabled: true },
  { key: 'blackhat', label: '黑产检测', icon: '🕵️', desc: '对抗样本 + 账号风险分析', enabled: true },
  { key: 'rag', label: 'RAG 检索', icon: '🔍', desc: '六层混合检索增强', enabled: true },
  { key: 'debate', label: '辩论面板', icon: '⚖️', desc: '多Agent分歧时启动辩论', enabled: false },
]

function AgentsTab({ policies, onToggle, onRefresh }: {
  policies: Policy[]
  onToggle: (p: Policy) => void
  onRefresh: () => void
}) {
  const agentPolicies = policies.filter(p => p.policy_type === 'agent_switch')
  const [modelPriority, setModelPriority] = useState(['deepseek-v4-flash', 'qwen-2.5', 'local-bge'])
  const [saving, setSaving] = useState(false)

  const saveAgentConfig = async () => {
    setSaving(true)
    try {
      const existing = agentPolicies[0]
      const data = {
        name: 'Agent调度配置',
        policy_type: 'agent_switch',
        description: 'Agent模块开关及模型调用优先级',
        rule_config: { model_priority: modelPriority },
        enabled: true,
        priority: 90,
        created_by: 'admin',
      }
      if (existing) {
        await api.updatePolicy(existing.id, data)
      } else {
        await api.createPolicy(data)
      }
      onRefresh()
      alert('Agent 配置已保存')
    } catch (e: any) {
      alert('保存失败: ' + (e.message || '未知错误'))
    } finally {
      setSaving(false)
    }
  }

  const moveModel = (index: number, direction: -1 | 1) => {
    const newPrio = [...modelPriority]
    const target = index + direction
    if (target < 0 || target >= newPrio.length) return
    ;[newPrio[index], newPrio[target]] = [newPrio[target], newPrio[index]]
    setModelPriority(newPrio)
  }

  return (
    <div className="space-y-6">
      {/* Agent 开关 */}
      <div className="card p-5">
        <h3 className="text-sm font-bold text-slate-700 mb-4">Agent 模块开关</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {DEFAULT_AGENTS.map(agent => (
            <div key={agent.key} className="flex items-center justify-between p-3 rounded-lg bg-slate-50 border border-slate-100">
              <div className="flex items-center gap-3">
                <span className="text-xl">{agent.icon}</span>
                <div>
                  <div className="text-sm font-semibold text-slate-700">{agent.label}</div>
                  <div className="text-xs text-slate-400">{agent.desc}</div>
                </div>
              </div>
              <button
                className={`w-12 h-6 rounded-full transition-colors relative ${agent.enabled ? 'bg-green-500' : 'bg-slate-300'}`}
                title={agent.enabled ? '点击停用' : '点击启用'}
              >
                <div className={`w-5 h-5 rounded-full bg-white shadow absolute top-0.5 transition-transform ${agent.enabled ? 'left-6' : 'left-0.5'}`} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* 模型优先级 */}
      <div className="card p-5">
        <h3 className="text-sm font-bold text-slate-700 mb-4">模型调用优先级</h3>
        <p className="text-xs text-slate-500 mb-4">拖拽调整优先级, 最高优先级模型故障时自动降级到下一个</p>
        <div className="space-y-2 max-w-md">
          {modelPriority.map((model, i) => (
            <div key={model} className="flex items-center justify-between p-3 rounded-lg bg-slate-50 border border-slate-200">
              <div className="flex items-center gap-3">
                <span className="text-xs font-bold text-slate-400 w-6">#{i + 1}</span>
                <span className="text-sm font-medium text-slate-700">{model}</span>
                {i === 0 && <span className="badge badge-pass text-xs">默认</span>}
              </div>
              <div className="flex gap-1">
                <button className="text-xs px-2 py-1 rounded bg-white border border-slate-200 hover:bg-slate-100 disabled:opacity-30" disabled={i === 0} onClick={() => moveModel(i, -1)}>↑</button>
                <button className="text-xs px-2 py-1 rounded bg-white border border-slate-200 hover:bg-slate-100 disabled:opacity-30" disabled={i === modelPriority.length - 1} onClick={() => moveModel(i, 1)}>↓</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      <button className="btn btn-primary" onClick={saveAgentConfig} disabled={saving}>
        {saving ? '💾 保存中...' : '💾 保存 Agent 配置'}
      </button>
    </div>
  )
}
