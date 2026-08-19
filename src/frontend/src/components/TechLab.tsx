import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'

// ── 类型定义 ──

interface PipelineNode {
  id: string
  name: string
  icon: string
  type: 'entry' | 'router' | 'agent' | 'debate' | 'decision' | 'exit' | 'fusion' | 'parallel'
  description: string
  input: string
  output: string
  model?: string
  tools?: string[]
  condition?: string
  thresholds?: string
  parallel_agents?: string[]
}

interface ModalityPipeline {
  name: string
  icon: string
  description: string
  pipeline: PipelineNode[]
}

interface PipelineFlow {
  name: string
  description: string
  modalities: Record<string, ModalityPipeline>
  shared_components: Record<string, any>
}

interface AgentPrompt {
  name: string
  version: string
  model: string
  system_prompt: string
  optimizer: string
  metrics: Record<string, any>
  created_at: string
}

// ── 节点类型颜色映射 ──
const NODE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  entry:    { bg: '#f0fdf4', border: '#22c55e', text: '#166534' },
  router:   { bg: '#fef3c7', border: '#f59e0b', text: '#92400e' },
  agent:    { bg: '#eef2ff', border: '#6366f1', text: '#3730a3' },
  debate:   { bg: '#fdf2f8', border: '#ec4899', text: '#9d174d' },
  decision: { bg: '#fef2f2', border: '#ef4444', text: '#991b1b' },
  exit:     { bg: '#f0f9ff', border: '#0ea5e9', text: '#075985' },
  fusion:   { bg: '#f5f3ff', border: '#8b5cf6', text: '#5b21b6' },
  parallel: { bg: '#ecfeff', border: '#06b6d4', text: '#155e75' },
}

// ── 层颜色映射 (RAG保留) ──
const LAYER_COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']

// ═══════════════════════════════════════════════════════════
// 主组件
// ═══════════════════════════════════════════════════════════

export default function TechLab() {
  const [activeTab, setActiveTab] = useState<'pipeline' | 'prompt' | 'rag' | 'tools' | 'skills'>('pipeline')

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-800">技术实验室</h2>
          <p className="text-sm text-slate-500 mt-1">全流程可视化 · Prompt 调试 · RAG 检索 · MCP 工具 · Skills</p>
        </div>
      </div>

      {/* Tab 切换 */}
      <div className="flex gap-1 bg-slate-100 rounded-lg p-1 w-fit flex-wrap">
        <button
          className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
            activeTab === 'pipeline' ? 'bg-white shadow text-slate-800' : 'text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveTab('pipeline')}
        >
          🔄 案件全流程可视化
        </button>
        <button
          className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
            activeTab === 'prompt' ? 'bg-white shadow text-slate-800' : 'text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveTab('prompt')}
        >
          ✏️ Prompt 调试工坊
        </button>
        <button
          className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
            activeTab === 'rag' ? 'bg-white shadow text-slate-800' : 'text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveTab('rag')}
        >
          🔍 RAG 六层检索
        </button>
        <button
          className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
            activeTab === 'tools' ? 'bg-white shadow text-slate-800' : 'text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveTab('tools')}
        >
          🔧 MCP 工具清单
        </button>
        <button
          className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
            activeTab === 'skills' ? 'bg-white shadow text-slate-800' : 'text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveTab('skills')}
        >
          📚 Skill 知识库
        </button>
      </div>

      {activeTab === 'pipeline' && <PipelineFlowPanel />}
      {activeTab === 'prompt' && <PromptWorkshop />}
      {activeTab === 'rag' && <RAGDebugPanel />}
      {activeTab === 'tools' && <MCPToolsPanel />}
      {activeTab === 'skills' && <SkillsPanel />}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// 全流程可视化面板
// ═══════════════════════════════════════════════════════════

function PipelineFlowPanel() {
  const [data, setData] = useState<PipelineFlow | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeModality, setActiveModality] = useState<string>('text')
  const [expandedNode, setExpandedNode] = useState<string | null>(null)

  useEffect(() => {
    api.getPipelineFlow().then((d: unknown) => setData(d as PipelineFlow)).catch((e: any) => setError(e.message || '加载失败')).finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="card p-12 text-center">
        <div className="w-10 h-10 border-3 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-sm text-slate-400">加载管线拓扑...</p>
      </div>
    )
  }

  if (error || !data) {
    return <div className="card p-4 border-red-200 bg-red-50"><p className="text-sm text-red-600">{error || '数据为空'}</p></div>
  }

  const modalities = Object.entries(data.modalities)
  const current = data.modalities[activeModality]

  return (
    <div className="space-y-6">
      {/* 概览卡片 */}
      <div className="card p-5 bg-gradient-to-r from-indigo-50 to-purple-50 border-indigo-100">
        <h3 className="text-sm font-bold text-slate-700 mb-2">{data.name}</h3>
        <p className="text-xs text-slate-500">{data.description}</p>
        <div className="flex items-center gap-3 mt-3 flex-wrap">
          {Object.entries(data.shared_components).map(([key, comp]: [string, any]) => (
            <span key={key} className="text-xs bg-white rounded-full px-3 py-1 border border-slate-200 shadow-sm">
              {comp.icon} {comp.name}
            </span>
          ))}
        </div>
      </div>

      {/* 模态选择器 */}
      <div className="card p-4">
        <h3 className="text-sm font-bold text-slate-700 mb-3">选择模态查看管线差异</h3>
        <div className="flex gap-2 flex-wrap">
          {modalities.map(([key, mod]: [string, ModalityPipeline]) => (
            <button
              key={key}
              className={`px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                activeModality === key
                  ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-200'
                  : 'bg-slate-50 text-slate-600 hover:bg-slate-100 border border-slate-200'
              }`}
              onClick={() => { setActiveModality(key); setExpandedNode(null) }}
            >
              <span className="mr-1.5">{mod.icon}</span>
              {mod.name}
            </button>
          ))}
        </div>
        {current && (
          <p className="text-xs text-slate-400 mt-3">{current.description}</p>
        )}
      </div>

      {/* 管线流程图 */}
      {current && (
        <div className="card p-5">
          <h3 className="text-sm font-bold text-slate-700 mb-4">
            {current.icon} {current.name} — 审核链路
          </h3>

          {/* 流程节点 */}
          <div className="space-y-0">
            {current.pipeline.map((node, i) => {
              const colors = NODE_COLORS[node.type] || NODE_COLORS.agent
              const isExpanded = expandedNode === node.id
              const isLast = i === current.pipeline.length - 1

              return (
                <div key={node.id}>
                  {/* 节点卡片 */}
                  <div
                    className="relative cursor-pointer transition-all duration-200 hover:shadow-md rounded-lg border-2 mb-[-1px]"
                    style={{
                      background: colors.bg,
                      borderColor: isExpanded ? colors.border : `${colors.border}60`,
                      opacity: isExpanded ? 1 : 0.9,
                    }}
                    onClick={() => setExpandedNode(isExpanded ? null : node.id)}
                  >
                    <div className="p-4">
                      <div className="flex items-start gap-3">
                        {/* 节点序号 */}
                        <div
                          className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 mt-0.5"
                          style={{ background: colors.border, color: '#fff' }}
                        >
                          {i + 1}
                        </div>

                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-lg">{node.icon}</span>
                            <span className="text-sm font-bold" style={{ color: colors.text }}>{node.name}</span>
                            <span
                              className="text-xs px-2 py-0.5 rounded-full font-medium"
                              style={{ background: `${colors.border}20`, color: colors.text }}
                            >
                              {node.type.toUpperCase()}
                            </span>
                            {node.model && (
                              <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 font-mono">
                                {node.model}
                              </span>
                            )}
                          </div>

                          <p className="text-xs text-slate-500 mt-1.5 leading-relaxed">{node.description}</p>

                          {/* 条件标注 */}
                          {node.condition && (
                            <div className="mt-2 text-xs text-amber-600 bg-amber-50 rounded px-2 py-1 inline-block">
                              ⚡ 条件: {node.condition}
                            </div>
                          )}
                          {node.thresholds && (
                            <div className="mt-2 text-xs text-indigo-600 bg-indigo-50 rounded px-2 py-1 inline-block">
                              ⚙️ {node.thresholds}
                            </div>
                          )}

                          {/* 工具列表 */}
                          {node.tools && node.tools.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-2">
                              {node.tools.map(t => (
                                <span key={t} className="text-[10px] bg-white/70 text-slate-500 px-2 py-0.5 rounded border border-slate-200">
                                  🔧 {t}
                                </span>
                              ))}
                            </div>
                          )}

                          {/* 并行标注 */}
                          {node.parallel_agents && (
                            <div className="flex flex-wrap gap-1 mt-2">
                              <span className="text-[10px] text-cyan-600 font-medium">⚡ 并行:</span>
                              {node.parallel_agents.map(a => (
                                <span key={a} className="text-[10px] bg-cyan-50 text-cyan-600 px-2 py-0.5 rounded">{a}</span>
                              ))}
                            </div>
                          )}

                          <div className="text-xs text-slate-400 mt-2">
                            {isExpanded ? '▲ 收起' : '▼ 展开'}输入/输出
                          </div>
                        </div>
                      </div>

                      {/* 展开: 输入/输出 */}
                      {isExpanded && (
                        <div className="mt-3 pt-3 border-t border-slate-200/50 grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div className="bg-white/60 rounded-lg p-3">
                            <div className="text-[10px] font-bold text-slate-400 uppercase mb-1">📥 输入</div>
                            <div className="text-xs text-slate-600 font-mono leading-relaxed">{node.input}</div>
                          </div>
                          <div className="bg-white/60 rounded-lg p-3">
                            <div className="text-[10px] font-bold text-slate-400 uppercase mb-1">📤 输出</div>
                            <div className="text-xs text-slate-600 font-mono leading-relaxed">{node.output}</div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 连接线 */}
                  {!isLast && (
                    <div className="flex justify-center py-1">
                      <div className="w-0.5 h-5 bg-gradient-to-b from-slate-300 to-slate-200 rounded" />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* 模态差异对比 */}
      <div className="card p-5">
        <h3 className="text-sm font-bold text-slate-700 mb-4">📋 模态差异对比</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-slate-200">
                <th className="text-left py-2 px-3 text-slate-500 font-medium">特性</th>
                {modalities.map(([key, mod]: [string, ModalityPipeline]) => (
                  <th key={key} className="text-left py-2 px-3 text-slate-700 font-semibold">{mod.icon} {mod.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-slate-100">
                <td className="py-2 px-3 text-slate-500">分析节点数</td>
                {modalities.map(([key, mod]: [string, ModalityPipeline]) => (
                  <td key={key} className="py-2 px-3 font-mono text-slate-700">{mod.pipeline.length}</td>
                ))}
              </tr>
              <tr className="border-b border-slate-100">
                <td className="py-2 px-3 text-slate-500">Agent 节点</td>
                {modalities.map(([key, mod]: [string, ModalityPipeline]) => (
                  <td key={key} className="py-2 px-3 font-mono text-slate-700">
                    {mod.pipeline.filter(n => n.type === 'agent').length}
                  </td>
                ))}
              </tr>
              <tr className="border-b border-slate-100">
                <td className="py-2 px-3 text-slate-500">是否有辩论</td>
                {modalities.map(([key, mod]: [string, ModalityPipeline]) => (
                  <td key={key} className="py-2 px-3">
                    {mod.pipeline.some(n => n.type === 'debate') ? '✅' : '—'}
                  </td>
                ))}
              </tr>
              <tr className="border-b border-slate-100">
                <td className="py-2 px-3 text-slate-500">是否有融合</td>
                {modalities.map(([key, mod]: [string, ModalityPipeline]) => (
                  <td key={key} className="py-2 px-3">
                    {mod.pipeline.some(n => n.type === 'fusion') ? '✅' : '—'}
                  </td>
                ))}
              </tr>
              <tr>
                <td className="py-2 px-3 text-slate-500">核心模型</td>
                {modalities.map(([key, mod]: [string, ModalityPipeline]) => (
                  <td key={key} className="py-2 px-3 font-mono text-xs text-slate-500">
                    {[...new Set(mod.pipeline.filter(n => n.model).map(n => n.model))].join(', ') || '—'}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// RAG 六层检索可视化面板 (保留)
// ═══════════════════════════════════════════════════════════

interface LayerResult {
  layer: number
  name: string
  icon: string
  description: string
  duration_ms: number
  result_count: number
  top_results: any[]
  error: string | null
}

interface RagDebugResponse {
  query: string
  total_duration_ms: number
  layers: LayerResult[]
}

function RAGDebugPanel() {
  const [query, setQuery] = useState('加我微信赚钱日入过万')
  const [topK, setTopK] = useState(8)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<RagDebugResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [expandedLayer, setExpandedLayer] = useState<number | null>(null)

  const runDebug = async () => {
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await api.ragDebug(query.trim(), topK) as RagDebugResponse
      setResult(data)
    } catch (e: any) {
      setError(e.message || '请求失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* 输入区 */}
      <div className="card p-5">
        <div className="flex items-end gap-4">
          <div className="flex-1">
            <label className="block text-xs font-semibold text-slate-600 mb-2">测试查询文本</label>
            <input
              className="input w-full text-sm"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && runDebug()}
              placeholder="输入待检索的文本..."
            />
          </div>
          <div className="w-32">
            <label className="block text-xs font-semibold text-slate-600 mb-2">Top-K</label>
            <select className="input w-full text-sm" value={topK} onChange={e => setTopK(Number(e.target.value))}>
              {[3, 5, 8, 10, 15].map(k => <option key={k} value={k}>{k}</option>)}
            </select>
          </div>
          <button className="btn btn-primary" onClick={runDebug} disabled={loading}>
            {loading ? '⏳ 检索中...' : '🔍 开始检索'}
          </button>
        </div>
      </div>

      {error && (
        <div className="card p-4 border-red-200 bg-red-50">
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}

      {result && (
        <>
          <div className="card p-4 bg-gradient-to-r from-indigo-50 to-purple-50 border-indigo-100">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-xs text-slate-500">查询: </span>
                <span className="text-sm font-semibold text-slate-700">{result.query}</span>
              </div>
              <div className="flex items-center gap-6 text-sm">
                <span className="text-slate-500">
                  覆盖: <strong className="text-indigo-600">{result.layers.filter(l => l.result_count > 0).length}/{result.layers.length} 层</strong>
                </span>
                <span className="text-slate-500">
                  耗时: <strong className="text-indigo-600">{result.total_duration_ms.toFixed(0)}ms</strong>
                </span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {result.layers.map((layer, i) => (
              <div
                key={layer.layer}
                className="card overflow-hidden cursor-pointer transition-all duration-200 hover:shadow-lg"
                style={{ borderLeft: `3px solid ${LAYER_COLORS[i]}`, opacity: layer.error ? 0.6 : 1 }}
                onClick={() => setExpandedLayer(expandedLayer === layer.layer ? null : layer.layer)}
              >
                <div className="p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{layer.icon}</span>
                      <span className="text-sm font-bold text-slate-700">{layer.name}</span>
                    </div>
                    <span className="text-xs font-mono px-2 py-0.5 rounded" style={{ background: `${LAYER_COLORS[i]}15`, color: LAYER_COLORS[i] }}>
                      {layer.duration_ms > 0 ? `${layer.duration_ms.toFixed(0)}ms` : '<1ms'}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed">{layer.description}</p>
                  <div className="flex items-center gap-3 mt-3">
                    <span className="text-xs text-slate-500">命中: <strong style={{ color: LAYER_COLORS[i] }}>{layer.result_count}</strong> 条</span>
                    {layer.error && <span className="text-xs text-red-400 truncate max-w-[200px]">⚠️ {layer.error.substring(0, 40)}</span>}
                  </div>
                  {layer.result_count > 0 && (
                    <div className="text-xs text-slate-400 mt-2">{expandedLayer === layer.layer ? '▲ 收起' : '▼ 展开'}</div>
                  )}
                </div>
                {expandedLayer === layer.layer && layer.top_results.length > 0 && (
                  <div className="border-t border-slate-100 bg-slate-50 p-4 space-y-2 max-h-64 overflow-y-auto">
                    {layer.top_results.map((r: any, j: number) => {
                      if (r.rewrites) {
                        return (
                          <div key={j} className="text-xs">
                            <div className="font-semibold text-slate-600 mb-1">原始查询: {r.original_query}</div>
                            {Object.entries(r.rewrites as Record<string, any>).map(([k, v]) => (
                              <div key={k} className="ml-2 mb-1">
                                <span className="text-indigo-500 font-mono">{v.strategy}:</span>
                                <span className="text-slate-600 ml-1">{v.rewritten}</span>
                              </div>
                            ))}
                          </div>
                        )
                      }
                      if (r.inferred_types) {
                        return (
                          <div key={j} className="text-xs">
                            <div className="text-slate-600">推测类型: {(r.inferred_types as string[]).join(', ')}</div>
                            {r.related_types?.length > 0 && (
                              <div className="text-slate-500 mt-1">关联: {r.related_types.map((t: any) => `${t.type || t}`).join(', ')}</div>
                            )}
                          </div>
                        )
                      }
                      return (
                        <div key={j} className="flex items-start gap-2 text-xs">
                          <span className="text-slate-400 font-mono shrink-0">#{j + 1}</span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-slate-500 text-[10px]">{r.doc_id?.substring(0, 16)}</span>
                              <span className="font-semibold" style={{ color: LAYER_COLORS[i] }}>
                                {typeof r.score === 'number' ? r.score.toFixed(4) : r.score}
                              </span>
                            </div>
                            <p className="text-slate-600 mt-0.5 truncate">{r.content}</p>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {!result && !loading && !error && (
        <div className="card p-12 text-center">
          <div className="text-5xl mb-4 opacity-20">🔍</div>
          <p className="text-sm text-slate-500">输入查询文本, 点击"开始检索"查看六层 RAG 逐步结果</p>
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// Prompt 调试工坊 (增强版)
// ═══════════════════════════════════════════════════════════

function PromptWorkshop() {
  const [activeView, setActiveView] = useState<'browse' | 'compare'>('browse')
  const [prompts, setPrompts] = useState<AgentPrompt[]>([])
  const [loadingPrompts, setLoadingPrompts] = useState(true)

  // 浏览视图
  const [selectedPrompt, setSelectedPrompt] = useState<AgentPrompt | null>(null)

  // 对比视图
  const [testText, setTestText] = useState('加我微信abc123，日赚千元不是梦')
  const [promptA, setPromptA] = useState('')
  const [promptB, setPromptB] = useState('')
  const [compareLabelA, setCompareLabelA] = useState('版本 A')
  const [compareLabelB, setCompareLabelB] = useState('版本 B')
  const [comparing, setComparing] = useState(false)
  const [compareResult, setCompareResult] = useState<any>(null)
  const [compareError, setCompareError] = useState<string | null>(null)

  // 加载所有提示词
  useEffect(() => {
    api.getAgentPrompts().then((data: any) => {
      setPrompts(data.prompts || [])
    }).catch((e: any) => {
      console.error('Failed to load prompts:', e)
    }).finally(() => setLoadingPrompts(false))
  }, [])

  const selectForCompare = (prompt: AgentPrompt, slot: 'A' | 'B') => {
    if (slot === 'A') {
      setPromptA(prompt.system_prompt)
      setCompareLabelA(`${prompt.name} v${prompt.version}`)
    } else {
      setPromptB(prompt.system_prompt)
      setCompareLabelB(`${prompt.name} v${prompt.version}`)
    }
    setActiveView('compare')
  }

  const runCompare = async () => {
    if (!testText.trim() || !promptA.trim() || !promptB.trim()) return
    setComparing(true)
    setCompareError(null)
    setCompareResult(null)
    try {
      const data = await api.promptCompare(testText.trim(), promptA.trim(), promptB.trim())
      setCompareResult(data)
    } catch (e: any) {
      setCompareError(e.message || '请求失败')
    } finally {
      setComparing(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* 子Tab */}
      <div className="flex gap-1 bg-slate-100 rounded-lg p-1 w-fit">
        <button
          className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
            activeView === 'browse' ? 'bg-white shadow text-slate-800' : 'text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveView('browse')}
        >
          📚 浏览所有提示词
        </button>
        <button
          className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
            activeView === 'compare' ? 'bg-white shadow text-slate-800' : 'text-slate-500 hover:text-slate-700'
          }`}
          onClick={() => setActiveView('compare')}
        >
          ⚖️ 对照实验
        </button>
      </div>

      {/* 浏览视图 */}
      {activeView === 'browse' && (
        <div className="space-y-4">
          {loadingPrompts ? (
            <div className="card p-12 text-center">
              <div className="w-10 h-10 border-3 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
              <p className="text-sm text-slate-400">加载提示词...</p>
            </div>
          ) : prompts.length === 0 ? (
            <div className="card p-12 text-center">
              <div className="text-5xl mb-4 opacity-20">📝</div>
              <p className="text-sm text-slate-500">暂未加载到提示词</p>
              <p className="text-xs text-slate-400 mt-1">提示词将从 PromptRegistry 或 prompts/ 目录自动发现</p>
            </div>
          ) : (
            <>
              <div className="text-sm text-slate-500">共 <strong>{prompts.length}</strong> 个提示词</div>
              <div className="grid grid-cols-1 gap-3">
                {prompts.map(p => (
                  <div key={p.name} className={`card p-4 cursor-pointer transition-all hover:shadow-md ${
                    selectedPrompt?.name === p.name ? 'ring-2 ring-indigo-400' : ''
                  }`}
                    onClick={() => setSelectedPrompt(selectedPrompt?.name === p.name ? null : p)}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="text-lg">📝</span>
                        <div>
                          <div className="text-sm font-bold text-slate-700">{p.name}</div>
                          <div className="text-xs text-slate-400">v{p.version} · {p.model} · {p.optimizer || '手动'}</div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          className="text-xs px-3 py-1 rounded bg-indigo-50 text-indigo-600 hover:bg-indigo-100 transition-colors"
                          onClick={(e) => { e.stopPropagation(); selectForCompare(p, 'A') }}
                        >
                          作为 A
                        </button>
                        <button
                          className="text-xs px-3 py-1 rounded bg-emerald-50 text-emerald-600 hover:bg-emerald-100 transition-colors"
                          onClick={(e) => { e.stopPropagation(); selectForCompare(p, 'B') }}
                        >
                          作为 B
                        </button>
                      </div>
                    </div>

                    {/* 展开的提示词内容 */}
                    {selectedPrompt?.name === p.name && (
                      <div className="mt-4 pt-3 border-t border-slate-100">
                        <div className="flex items-center gap-4 text-xs text-slate-400 mb-3">
                          {p.metrics && Object.keys(p.metrics).length > 0 && (
                            <span>指标: {JSON.stringify(p.metrics)}</span>
                          )}
                          {p.created_at && <span>创建: {p.created_at}</span>}
                        </div>
                        <pre className="text-xs text-slate-600 bg-slate-50 rounded-lg p-4 whitespace-pre-wrap max-h-96 overflow-y-auto font-mono leading-relaxed">
                          {p.system_prompt}
                        </pre>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {/* 对照实验视图 */}
      {activeView === 'compare' && (
        <div className="space-y-6">
          {/* 测试文本 */}
          <div className="card p-5">
            <label className="block text-xs font-semibold text-slate-600 mb-2">测试文本</label>
            <div className="flex gap-3">
              <input
                className="input flex-1 text-sm"
                value={testText}
                onChange={e => setTestText(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && runCompare()}
                placeholder="输入待审核的文本..."
              />
              <button className="btn btn-primary" onClick={runCompare} disabled={comparing}>
                {comparing ? '⏳ 对比中...' : '🔍 运行对比'}
              </button>
            </div>
          </div>

          {/* 快速加载提示词 */}
          {prompts.length > 0 && (
            <div className="flex flex-wrap gap-2">
              <span className="text-xs text-slate-400 self-center mr-2">快速加载:</span>
              {prompts.map(p => (
                <div key={p.name} className="flex gap-1">
                  <button className="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-600 hover:bg-indigo-100" onClick={() => selectForCompare(p, 'A')}>
                    {p.name} → A
                  </button>
                  <button className="text-xs px-2 py-1 rounded bg-emerald-50 text-emerald-600 hover:bg-emerald-100" onClick={() => selectForCompare(p, 'B')}>
                    {p.name} → B
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* 双 Prompt 编辑 */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Prompt A */}
            <div className="card overflow-hidden">
              <div className="px-4 py-3 bg-indigo-50 border-b border-indigo-100 flex items-center justify-between">
                <span className="text-sm font-bold text-indigo-700">📝 {compareLabelA}</span>
                <button className="text-xs text-indigo-500 hover:text-indigo-700" onClick={() => { setPromptA(''); setCompareLabelA('版本 A') }}>
                  清空
                </button>
              </div>
              <textarea
                className="w-full p-4 text-sm font-mono text-slate-700 bg-white resize-none outline-none"
                rows={12}
                value={promptA}
                onChange={e => { setPromptA(e.target.value); setCompareLabelA('自定义 A') }}
                placeholder="输入 System Prompt A，或从上方提示词列表加载..."
              />
            </div>

            {/* Prompt B */}
            <div className="card overflow-hidden">
              <div className="px-4 py-3 bg-emerald-50 border-b border-emerald-100 flex items-center justify-between">
                <span className="text-sm font-bold text-emerald-700">📝 {compareLabelB}</span>
                <button className="text-xs text-emerald-500 hover:text-emerald-700" onClick={() => { setPromptB(''); setCompareLabelB('版本 B') }}>
                  清空
                </button>
              </div>
              <textarea
                className="w-full p-4 text-sm font-mono text-slate-700 bg-white resize-none outline-none"
                rows={12}
                value={promptB}
                onChange={e => { setPromptB(e.target.value); setCompareLabelB('自定义 B') }}
                placeholder="输入 System Prompt B，或从上方提示词列表加载..."
              />
            </div>
          </div>

          {/* 对比结果 */}
          {compareError && (
            <div className="card p-4 border-red-200 bg-red-50">
              <p className="text-sm text-red-600">{compareError}</p>
            </div>
          )}

          {compareResult && (
            <div className="space-y-4">
              <div className={`card p-4 border-2 ${compareResult.diff?.same_decision ? 'border-green-200 bg-green-50' : 'border-yellow-200 bg-yellow-50'}`}>
                <div className="flex items-center gap-4">
                  <span className="text-lg">{compareResult.diff?.same_decision ? '✅' : '⚠️'}</span>
                  <div>
                    <div className="text-sm font-bold text-slate-700">
                      {compareResult.diff?.same_decision ? '两个版本判定一致' : '两个版本判定不一致'}
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">
                      A: <strong>{compareResult.diff?.a_decision}</strong> | B: <strong>{compareResult.diff?.b_decision}</strong>
                      {' | '}置信度差: <strong>{compareResult.diff?.confidence_diff}</strong>
                    </div>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {['version_a', 'version_b'].map((verKey, idx) => {
                  const v = compareResult[verKey]
                  return (
                    <div key={verKey} className="card p-5" style={{ borderTop: `3px solid ${idx === 0 ? '#6366f1' : '#10b981'}` }}>
                      <h4 className="text-sm font-bold mb-3" style={{ color: idx === 0 ? '#6366f1' : '#10b981' }}>
                        版本 {idx === 0 ? 'A' : 'B'}: {v?.label}
                      </h4>
                      {v?.error ? (
                        <div className="p-3 bg-red-50 rounded-lg text-sm text-red-600">{v.error}</div>
                      ) : (
                        <div className="space-y-3">
                          <div className="flex items-center gap-3">
                            <span className={`badge text-sm ${v?.decision === 'REJECT' ? 'badge-reject' : v?.decision === 'REVIEW' ? 'badge-review' : 'badge-pass'}`}>
                              {v?.decision}
                            </span>
                            <span className="text-sm text-slate-500">置信度: <strong>{(v?.confidence * 100).toFixed(0)}%</strong></span>
                          </div>
                          {v?.violation_type && v.violation_type !== 'none' && (
                            <div>
                              <span className="text-xs text-slate-500">违规类型: </span>
                              <span className="badge badge-reject text-xs">{v.violation_type}</span>
                            </div>
                          )}
                          <div className="flex items-center gap-4 text-xs text-slate-400">
                            <span>🪙 Token: {v?.token_cost || 0}</span>
                            <span>⏱ {v?.duration_ms || 0}ms</span>
                          </div>
                          {v?.reasoning && (
                            <div className="bg-slate-50 rounded-lg p-3">
                              <p className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">{v.reasoning}</p>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// MCP 工具清单面板
// ═══════════════════════════════════════════════════════════

interface MCPTool {
  name: string
  description: string
  inputSchema: Record<string, any>
  allowed_agents: string[]
}

function MCPToolsPanel() {
  const [tools, setTools] = useState<MCPTool[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedTool, setExpandedTool] = useState<string | null>(null)

  useEffect(() => {
    api.getTools()
      .then((d: any) => setTools(d.tools || []))
      .catch((e: any) => setError(e.message || '加载失败'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="card p-12 text-center">
        <div className="w-10 h-10 border-3 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-slate-500">Loading MCP tools...</p>
      </div>
    )
  }

  if (error) {
    return <div className="card p-6 text-center text-red-500">⚠️ {error}</div>
  }

  const toolColors: Record<string, string> = {
    keyword_check: '#f59e0b', history_search: '#6366f1', image_hash: '#10b981',
    account_risk_check: '#ef4444', adversarial_detect: '#8b5cf6', url_check: '#06b6d4',
    content_dedup: '#ec4899', regex_rule_check: '#14b8a6',
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="px-3 py-1 bg-indigo-100 text-indigo-700 rounded-full text-xs font-bold">{tools.length} Tools</div>
        <p className="text-sm text-slate-500">MCP 协议注册的工具清单 — 从 Registry API 动态加载</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {tools.map(tool => {
          const color = toolColors[tool.name] || '#64748b'
          const required = tool.inputSchema?.required || []
          const props = tool.inputSchema?.properties || {}
          const isExpanded = expandedTool === tool.name

          return (
            <div key={tool.name} className="card p-4 cursor-pointer hover:shadow-md transition-shadow"
              style={{ borderLeft: `3px solid ${color}` }}
              onClick={() => setExpandedTool(isExpanded ? null : tool.name)}
            >
              <div className="flex items-center justify-between mb-2">
                <h4 className="font-bold text-sm text-slate-800">{tool.name}</h4>
                <span className="text-xs text-slate-400">{tool.allowed_agents?.length || 0} agents</span>
              </div>
              <p className="text-xs text-slate-500 mb-3 line-clamp-2">{tool.description}</p>

              {/* 参数预览 */}
              <div className="flex flex-wrap gap-1 mb-2">
                {Object.entries(props).map(([key, schema]: [string, any]) => (
                  <span key={key} className={`text-xs px-2 py-0.5 rounded-full ${
                    required.includes(key) ? 'bg-amber-50 text-amber-700 border border-amber-200' : 'bg-slate-50 text-slate-500 border border-slate-200'
                  }`}>
                    {key}: <em>{schema.type || 'any'}</em>{required.includes(key) ? ' *' : ''}
                  </span>
                ))}
              </div>

              {/* 展开详情 */}
              {isExpanded && (
                <div className="mt-3 pt-3 border-t border-slate-100 space-y-2">
                  <div>
                    <span className="text-xs font-bold text-slate-500">Authorized Agents:</span>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {tool.allowed_agents?.map(agent => (
                        <span key={agent} className="text-xs px-2 py-0.5 bg-green-50 text-green-700 rounded-full border border-green-200">
                          {agent}
                        </span>
                      ))}
                      {(!tool.allowed_agents || tool.allowed_agents.length === 0) && (
                        <span className="text-xs text-slate-400">无限制</span>
                      )}
                    </div>
                  </div>
                  {Object.entries(props).map(([key, schema]: [string, any]) => (
                    <div key={key} className="text-xs">
                      <span className="font-bold text-slate-600">{key}</span>
                      <span className="text-slate-400"> ({schema.type || 'any'})</span>
                      {required.includes(key) && <span className="text-amber-500 ml-1">*required</span>}
                      {schema.description && <span className="text-slate-400 block">{schema.description}</span>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════════
// Skill 知识库面板
// ═══════════════════════════════════════════════════════════

interface SkillMeta {
  name: string
  description: string
  version: string
  invocation_mode: string
  mcp_tools: string[]
  triggers: Record<string, string>[]
  tags: string[]
  activations: number
}

function SkillsPanel() {
  const [skills, setSkills] = useState<SkillMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedSkill, setExpandedSkill] = useState<string | null>(null)
  const [skillDetail, setSkillDetail] = useState<Record<string, any>>({})
  const [toolMap, setToolMap] = useState<Record<string, string[]>>({})

  useEffect(() => {
    Promise.all([
      api.getSkills().then((d: any) => setSkills(d.skills || [])),
      api.getSkillToolMap().then((d: any) => setToolMap(d.mcp_tool_to_skills || {})),
    ]).catch((e: any) => setError(e.message || '加载失败'))
    .finally(() => setLoading(false))
  }, [])

  const loadDetail = async (name: string) => {
    if (skillDetail[name]) return
    try {
      const detail = await api.getSkillDetail(name)
      setSkillDetail((prev: any) => ({ ...prev, [name]: detail }))
    } catch {}
  }

  if (loading) {
    return (
      <div className="card p-12 text-center">
        <div className="w-10 h-10 border-3 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-slate-500">Loading Skills...</p>
      </div>
    )
  }

  if (error) {
    return <div className="card p-6 text-center text-red-500">⚠️ {error}</div>
  }

  const modeLabels: Record<string, string> = { 'agent-only': '🤖 Agent Only', 'user-only': '👤 User Only', 'both': '👤🤖 Both' }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="px-3 py-1 bg-purple-100 text-purple-700 rounded-full text-xs font-bold">{skills.length} Skills</div>
        <p className="text-sm text-slate-500">Skill 知识库 — 来自 .claude/skills/ 和 /workspace/skills/ 目录</p>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {skills.map(skill => {
          const isExpanded = expandedSkill === skill.name
          const detail = skillDetail[skill.name]

          return (
            <div key={skill.name} className="card p-5 cursor-pointer hover:shadow-md transition-shadow"
              style={{ borderLeft: '3px solid #8b5cf6' }}
              onClick={() => {
                setExpandedSkill(isExpanded ? null : skill.name)
                if (!isExpanded) loadDetail(skill.name)
              }}
            >
              <div className="flex items-start justify-between mb-2">
                <div>
                  <h4 className="font-bold text-sm text-slate-800">{skill.name}</h4>
                  <p className="text-xs text-slate-500 mt-0.5">{skill.description}</p>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-slate-400">v{skill.version}</span>
                  <span className="px-2 py-0.5 bg-slate-100 rounded-full text-slate-600">{modeLabels[skill.invocation_mode] || skill.invocation_mode}</span>
                </div>
              </div>

              {/* 标签行 */}
              <div className="flex flex-wrap gap-1 mb-2">
                {(Array.isArray(skill.mcp_tools) ? skill.mcp_tools : []).map(tool => (
                  <span key={tool} className="text-xs px-2 py-0.5 bg-indigo-50 text-indigo-600 rounded-full border border-indigo-100">
                    🔧 {tool}
                  </span>
                ))}
                {(Array.isArray(skill.tags) ? skill.tags : []).map(tag => (
                  <span key={tag} className="text-xs px-2 py-0.5 bg-slate-50 text-slate-500 rounded-full border border-slate-200">
                    #{tag}
                  </span>
                ))}
              </div>

              {/* 激活统计 */}
              {skill.activations > 0 && (
                <div className="text-xs text-slate-400">🔥 已激活 {skill.activations} 次</div>
              )}

              {/* 展开详情 */}
              {isExpanded && detail && (
                <div className="mt-3 pt-3 border-t border-slate-100 space-y-3">
                  <div>
                    <span className="text-xs font-bold text-slate-500">完整指令 (L2):</span>
                    <pre className="mt-1 p-3 bg-slate-50 rounded-lg text-xs text-slate-600 whitespace-pre-wrap max-h-60 overflow-y-auto">
                      {detail.instructions || '(无指令内容)'}
                    </pre>
                  </div>
                  {detail.references?.length > 0 && (
                    <div>
                      <span className="text-xs font-bold text-slate-500">参考文件 (L3):</span>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {detail.references.map((ref: string) => (
                          <span key={ref} className="text-xs px-2 py-0.5 bg-green-50 text-green-600 rounded-full border border-green-200">
                            📄 {ref}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
