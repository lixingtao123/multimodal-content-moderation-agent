import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'

interface SkillMeta {
  name: string
  description: string
  version: string
  invocation_mode: string
  scope: string
  mcp_tools: string[]
  triggers: any[]
  tags: string[]
  source_path: string
  token_estimate: number
  activations: number
}

interface SkillRoutingLog {
  id: number
  content_id: string
  agent: string
  query: string
  content_type: string
  filtered_skills: string[]
  ranked_skills: string[]
  selected_skills: string[]
  timestamp: string
}

interface SuggestionWithVote {
  id: number
  skill_name: string
  suggestion_type: string
  current_value: string
  suggested_value: string
  reason: string
  confidence: number
  supporting_examples: string[]
  analysis_detail?: string
  impact?: string
  approved: boolean
  votes: Array<{ voter: string; vote: boolean; comment: string; timestamp: number }>
  applied: boolean
  applied_at?: number
}

interface EnhancedOptimizationReport {
  generated_at: number
  analysis_summary: string
  suggestions: SuggestionWithVote[]
  voting_required: boolean
  approved: boolean
  votes: Array<{ voter: string; vote: boolean; comment: string; timestamp: number }>
  applied_at?: number
  applied_suggestions: number[]
  report_path: string
}

interface SkillDetail {
  meta: {
    name: string
    description: string
    version: string
    invocation_mode: string
    mcp_tools: string[]
    triggers: any[]
    tags: string[]
  }
  instructions: string
  references: string[]
  scripts: string[]
  activation_count: number
  related_logs: Array<{
    id: number
    query: string
    agent: string
    was_selected: boolean
    was_ranked: boolean
    was_filtered: boolean
    selected_skills: string[]
    timestamp: string
  }>
}

export default function SkillManager() {
  const [skills, setSkills] = useState<SkillMeta[]>([])
  const [routingLogs, setRoutingLogs] = useState<SkillRoutingLog[]>([])
  const [skillStats, setSkillStats] = useState<Record<string, number>>({})
  const [optimizationReports, setOptimizationReports] = useState<EnhancedOptimizationReport[]>([])
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)
  const [skillDetail, setSkillDetail] = useState<SkillDetail | null>(null)
  const [showDetail, setShowDetail] = useState(false)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [activeTab, setActiveTab] = useState<'skills' | 'logs' | 'optimization'>('skills')
  const [expandedSuggestion, setExpandedSuggestion] = useState<number | null>(null)
  const [selectedSuggestions, setSelectedSuggestions] = useState<Set<number>>(new Set())
  const [previewState, setPreviewState] = useState<{ reportPath: string; suggestionId: number } | null>(null)
  const [previewData, setPreviewData] = useState<any>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)

  const loadData = useCallback(async () => {
    try {
      setLoading(true)

      // 并行加载数据
      const [skillsRes, logsRes, reportsRes] = await Promise.allSettled([
        api.getSkills(),
        api.getSkillRoutingLogs(100),
        api.getOptimizationReports(20),
      ])

      if (skillsRes.status === 'fulfilled') {
        setSkills((skillsRes.value as { skills?: SkillMeta[] }).skills || [])
      }

      if (logsRes.status === 'fulfilled') {
        const logsValue = logsRes.value as { logs?: SkillRoutingLog[]; skill_stats?: Record<string, number> }
        setRoutingLogs(logsValue.logs || [])
        setSkillStats(logsValue.skill_stats || {})
      }

      if (reportsRes.status === 'fulfilled') {
        setOptimizationReports((reportsRes.value as { reports?: EnhancedOptimizationReport[] }).reports || [])
      }
    } catch (e) {
      console.error('Skill manager load error:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleAnalyzeSkills = async () => {
    setAnalyzing(true)
    try {
      const result = await api.analyzeSkillRouting(1)
      if (result.status === 'success' && result.report) {
        await loadData()
      }
      alert(result.status === 'success' ? '分析完成！' : `分析跳过：${result.reason}`)
    } catch (e) {
      console.error('Skill analysis error:', e)
      alert('分析失败，请查看控制台')
    } finally {
      setAnalyzing(false)
    }
  }

  const handleVoteSingle = async (reportPath: string, suggestionId: number, vote: boolean) => {
    try {
      await api.voteSingleSuggestion(reportPath, suggestionId, 'user', vote, '')
      await loadData()
    } catch (e) {
      console.error('Single vote error:', e)
      alert('投票失败')
    }
  }

  const handleApplySelected = async (reportPath: string) => {
    const selectedIds = Array.from(selectedSuggestions)
    if (selectedIds.length === 0) {
      alert('请至少选择一个建议')
      return
    }

    if (!confirm(`确定要应用选中的 ${selectedIds.length} 个建议吗？`)) {
      return
    }

    try {
      await api.applySelectedSuggestions(reportPath, selectedIds)
      setSelectedSuggestions(new Set())
      await loadData()
      alert('优化已应用！')
    } catch (e) {
      console.error('Apply selected error:', e)
      alert('应用优化失败')
    }
  }

  const handleApplySingle = async (reportPath: string, suggestionId: number, suggestionDesc: string) => {
    if (!confirm(`确定要应用此优化建议吗？\n\n${suggestionDesc}`)) {
      return
    }

    try {
      await api.applySelectedSuggestions(reportPath, [suggestionId])
      setSelectedSuggestions(new Set())
      await loadData()
      alert('优化已应用！')
    } catch (e) {
      console.error('Apply single error:', e)
      alert('应用优化失败')
    }
  }

  const handleShowPreview = async (reportPath: string, suggestionId: number) => {
    setPreviewState({ reportPath, suggestionId })
    setLoadingPreview(true)
    try {
      const preview = await api.getSuggestionPreview(reportPath, suggestionId)
      setPreviewData(preview)
    } catch (e) {
      console.error('Preview load error:', e)
      alert('加载预览失败')
    } finally {
      setLoadingPreview(false)
    }
  }

  const handleViewSkill = async (name: string) => {
    setSelectedSkill(name)
    setShowDetail(true)
    setLoadingDetail(true)

    try {
      // 调用 API 获取 Skill 详情
      const response = await fetch(`/api/v1/tech/skills/${encodeURIComponent(name)}`)
      if (response.ok) {
        const data = await response.json()
        setSkillDetail(data)
      } else {
        console.error('Failed to load skill detail')
      }
    } catch (e) {
      console.error('Skill detail load error:', e)
    } finally {
      setLoadingDetail(false)
    }
  }

  const toggleSuggestionSelection = (suggestionId: number, approved: boolean) => {
    if (!approved) {
      alert('请先批准该建议后再选择')
      return
    }
    const newSelection = new Set(selectedSuggestions)
    if (newSelection.has(suggestionId)) {
      newSelection.delete(suggestionId)
    } else {
      newSelection.add(suggestionId)
    }
    setSelectedSuggestions(newSelection)
  }

  const selectAllSuggestions = (suggestions: SuggestionWithVote[]) => {
    const approvedIds = suggestions.filter(s => s.approved && !s.applied).map(s => s.id)
    setSelectedSuggestions(new Set(approvedIds))
  }

  const deselectAllSuggestions = () => {
    setSelectedSuggestions(new Set())
  }

  const formatTime = (timestamp: number | string) => {
    const ts = typeof timestamp === 'number' ? timestamp * 1000 : timestamp
    return new Date(ts).toLocaleString('zh-CN')
  }

  const getSuggestionTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      'description_update': '📝 描述优化',
      'trigger_add': '➕ 添加触发词',
      'trigger_remove': '➖ 移除触发词',
      'tag_add': '🏷️ 添加标签',
      'tag_remove': '🏷️ 移除标签',
      'new_skill': '🆕 新建 Skill',
    }
    return labels[type] || type
  }

  const getImpactColor = (impact: string) => {
    if (!impact) return 'bg-slate-100 text-slate-600'
    if (impact.includes('高')) return 'bg-red-100 text-red-700'
    if (impact.includes('中')) return 'bg-yellow-100 text-yellow-700'
    return 'bg-green-100 text-green-700'
  }

  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <h2 className="text-xl font-bold text-slate-800">Skill 管理</h2>
        <div className="card p-12 text-center text-slate-400">加载中...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-800">Skill 管理</h2>
          <p className="text-slate-500 text-sm mt-1">动态路由管理与 Skill 自优化</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadData}
            className="px-3 py-2 text-sm bg-slate-100 text-slate-700 rounded-lg hover:bg-slate-200"
          >
            🔄 刷新
          </button>
          <button
            onClick={handleAnalyzeSkills}
            disabled={analyzing}
            className="px-4 py-2 bg-gradient-to-r from-indigo-600 to-purple-600 text-white rounded-lg font-medium hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {analyzing ? <span className="animate-spin">⚙️</span> : '🧪'}
            {analyzing ? '分析中...' : '分析并优化'}
          </button>
        </div>
      </div>

      <div className="flex gap-2 border-b border-slate-200">
        {[
          { id: 'skills', label: 'Skills 列表', icon: '📚' },
          { id: 'logs', label: '路由日志', icon: '📝' },
          { id: 'optimization', label: '优化建议', icon: '🎯' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-4 py-2 font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            {tab.icon} {tab.label}
            {tab.id === 'logs' && <span className="ml-1 text-xs">({routingLogs.length})</span>}
            {tab.id === 'optimization' && <span className="ml-1 text-xs">({optimizationReports.length})</span>}
          </button>
        ))}
      </div>

      {activeTab === 'skills' && (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-bold text-slate-700">Skills 列表</h3>
            <span className="text-xs text-slate-400">{skills.length} 个 Skill</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider py-3">Skill 名称</th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider py-3">描述</th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider py-3">标签</th>
                  <th className="text-left text-xs font-medium text-slate-500 uppercase tracking-wider py-3">使用次数</th>
                  <th className="text-right text-xs font-medium text-slate-500 uppercase tracking-wider py-3">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {skills.map((skill) => (
                  <tr key={skill.name} className="hover:bg-slate-50">
                    <td className="py-3">
                      <div className="font-medium text-slate-800">{skill.name}</div>
                      <div className="text-xs text-slate-400">v{skill.version}</div>
                    </td>
                    <td className="py-3 text-sm text-slate-600 max-w-md truncate">
                      {skill.description}
                    </td>
                    <td className="py-3">
                      <div className="flex flex-wrap gap-1">
                        {skill.tags.map((tag) => (
                          <span
                            key={tag}
                            className="px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded-full"
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="py-3 text-sm">
                      <span className={skillStats[skill.name] ? 'text-green-600 font-medium' : 'text-slate-400'}>
                        {skillStats[skill.name] ?? 0}
                      </span>
                    </td>
                    <td className="py-3 text-right">
                      <button
                        onClick={() => handleViewSkill(skill.name)}
                        className="text-indigo-600 hover:text-indigo-700 text-sm font-medium"
                      >
                        查看详情
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {activeTab === 'logs' && (
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-bold text-slate-700">Skill 路由日志</h3>
            <div className="text-xs text-slate-400">
              显示最近 {routingLogs.length} 条记录
            </div>
          </div>

          {routingLogs.length === 0 ? (
            <div className="text-center text-slate-400 py-8">
              暂无路由日志，开始审核后会记录路由情况
            </div>
          ) : (
            <div className="space-y-3 max-h-[70vh] overflow-y-auto">
              {routingLogs.map((log) => (
                <div key={log.id} className="p-4 bg-slate-50 rounded-lg border border-slate-100">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded font-medium">
                        {log.agent}
                      </span>
                      <span className="px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded">
                        {log.content_type}
                      </span>
                      <span className="text-xs text-slate-400">
                        ID: {log.content_id}
                      </span>
                    </div>
                    <div className="text-xs text-slate-400">{formatTime(log.timestamp)}</div>
                  </div>
                  <div className="text-sm text-slate-700 mb-3 bg-white p-2 rounded border border-slate-200">
                    {log.query || '(无查询)'}
                  </div>

                  <div className="grid grid-cols-3 gap-3 text-xs">
                    <div>
                      <div className="text-slate-500 mb-1 font-medium">Filter 阶段</div>
                      <div className="flex flex-wrap gap-1">
                        {log.filtered_skills.map((skill) => (
                          <span
                            key={skill}
                            className="px-1.5 py-0.5 bg-slate-200 text-slate-600 rounded"
                          >
                            {skill}
                          </span>
                        ))}
                        {log.filtered_skills.length === 0 && (
                          <span className="text-slate-400">无</span>
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="text-slate-500 mb-1 font-medium">Rank 阶段</div>
                      <div className="flex flex-wrap gap-1">
                        {log.ranked_skills.map((skill) => (
                          <span
                            key={skill}
                            className="px-1.5 py-0.5 bg-blue-100 text-blue-600 rounded"
                          >
                            {skill}
                          </span>
                        ))}
                        {log.ranked_skills.length === 0 && (
                          <span className="text-slate-400">无</span>
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="text-slate-500 mb-1 font-medium">Select 阶段</div>
                      <div className="flex flex-wrap gap-1">
                        {log.selected_skills.map((skill) => (
                          <span
                            key={skill}
                            className="px-1.5 py-0.5 bg-green-100 text-green-700 rounded font-medium"
                          >
                            {skill}
                          </span>
                        ))}
                        {log.selected_skills.length === 0 && (
                          <span className="text-slate-400">无</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'optimization' && (
        <div className="space-y-6">
          {optimizationReports.length === 0 ? (
            <div className="card text-center text-slate-400 py-12">
              <div className="text-4xl mb-4">🎯</div>
              <p>暂无优化建议</p>
              <p className="text-sm mt-2">点击"分析并优化"按钮开始分析路由日志</p>
            </div>
          ) : (
            optimizationReports.map((report, reportIdx) => {
              // 区分待处理建议和已应用建议
              const pendingSuggestions = report.suggestions.filter(s => !s.applied)
              const appliedSuggestions = report.suggestions.filter(s => s.applied)

              return (
                <div key={reportIdx} className="card">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-bold text-slate-800">
                          {appliedSuggestions.length === report.suggestions.length ?
                           '✅ 已完成' : '📋 优化建议'}
                        </h3>
                        <span className="text-sm px-2 py-0.5 bg-slate-100 text-slate-600 rounded">
                          {pendingSuggestions.length} 条待处理
                        </span>
                        {appliedSuggestions.length > 0 && (
                          <span className="text-sm px-2 py-0.5 bg-green-100 text-green-700 rounded">
                            {appliedSuggestions.length} 条已应用
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-slate-600 mt-1">{report.analysis_summary}</p>
                      <p className="text-xs text-slate-400 mt-1">{formatTime(report.generated_at)}</p>
                    </div>
                  </div>

                  {/* 待处理建议区 */}
                  {pendingSuggestions.length > 0 && (
                    <>
                      {/* 批量操作区 - 可选的高级功能 */}
                      {pendingSuggestions.filter(s => s.approved && !s.applied).length > 1 && (
                        <div className="mb-4 p-3 bg-slate-50 rounded-lg border border-slate-200">
                          <div className="text-xs text-slate-500 mb-2">💡 批量操作（可选）：</div>
                          <div className="flex items-center justify-between flex-wrap gap-2">
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => selectAllSuggestions(pendingSuggestions)}
                                className="px-3 py-1.5 text-sm bg-slate-200 text-slate-700 rounded hover:bg-slate-300"
                              >
                                全选已批准
                              </button>
                              <button
                                onClick={deselectAllSuggestions}
                                className="px-3 py-1.5 text-sm bg-slate-200 text-slate-700 rounded hover:bg-slate-300"
                              >
                                取消全选
                              </button>
                              <span className="text-sm text-slate-600">
                                已选择: {selectedSuggestions.size} / {pendingSuggestions.filter(s => s.approved).length}
                              </span>
                            </div>
                            <button
                              onClick={() => handleApplySelected(report.report_path)}
                              disabled={selectedSuggestions.size === 0}
                              className="px-4 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              🚀 批量应用选中
                            </button>
                          </div>
                        </div>
                      )}

                      <div className="space-y-4 mb-4">
                        {pendingSuggestions.map((suggestion, sIdx) => (
                          <div key={sIdx} className={`p-4 rounded-lg border ${
                            suggestion.approved ? 'bg-blue-50 border-blue-200' : 'bg-slate-50 border-slate-200'
                          }`}>
                            <div className="flex items-start gap-3">
                              {/* 选择框 */}
                              {!report.applied_at && (
                                <div className="pt-1">
                                  <input
                                    type="checkbox"
                                    checked={selectedSuggestions.has(suggestion.id)}
                                    onChange={() => toggleSuggestionSelection(suggestion.id, suggestion.approved)}
                                    disabled={!suggestion.approved || suggestion.applied}
                                    className="w-4 h-4 text-indigo-600 rounded border-slate-300 focus:ring-indigo-500 disabled:opacity-50"
                                  />
                                </div>
                              )}

                              <div className="flex-1">
                                <div className="flex items-center gap-2 flex-wrap mb-2">
                                  <span className="font-medium text-slate-800">{suggestion.skill_name}</span>
                                  <span className="px-2 py-1 text-xs rounded-full bg-indigo-100 text-indigo-700">
                                    {getSuggestionTypeLabel(suggestion.suggestion_type)}
                                  </span>
                                  <span className={`px-2 py-1 text-xs rounded-full ${
                                    suggestion.confidence >= 0.8 ? 'bg-green-100 text-green-700' :
                                    suggestion.confidence >= 0.6 ? 'bg-yellow-100 text-yellow-700' :
                                    'bg-slate-100 text-slate-600'
                                  }`}>
                                    置信度: {(suggestion.confidence * 100).toFixed(0)}%
                                  </span>
                                  {suggestion.impact && (
                                    <span className={`px-2 py-1 text-xs rounded-full ${getImpactColor(suggestion.impact)}`}>
                                      {suggestion.impact}
                                    </span>
                                  )}
                                  {/* 状态标签 */}
                                  {suggestion.applied ? (
                                    <span className="px-2 py-1 text-xs rounded-full bg-green-200 text-green-800 font-medium">
                                      ✅ 已应用
                                    </span>
                                  ) : suggestion.approved ? (
                                    <span className="px-2 py-1 text-xs rounded-full bg-blue-200 text-blue-800 font-medium">
                                      ✅ 已批准
                                    </span>
                                  ) : (
                                    <span className="px-2 py-1 text-xs rounded-full bg-yellow-100 text-yellow-800 font-medium">
                                      ⏳ 待审批
                                    </span>
                                  )}
                                </div>

                                <p className="text-slate-700 text-sm mb-3">{suggestion.reason}</p>

                                {/* 优化前后对比 */}
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-3">
                                  <div className="bg-white p-3 rounded border border-slate-200">
                                    <div className="text-xs font-medium text-slate-500 mb-1">📊 当前值</div>
                                    <div className="text-sm text-slate-700 break-all">
                                      {suggestion.current_value || '(空)'}
                                    </div>
                                  </div>
                                  <div className="bg-white p-3 rounded border border-green-200 bg-green-50">
                                    <div className="flex items-center justify-between mb-1">
                                      <div className="text-xs font-medium text-green-700">✅ 建议值</div>
                                      {/* 单个应用按钮 */}
                                      {!suggestion.applied && suggestion.approved && (
                                        <button
                                          onClick={() => handleApplySingle(report.report_path, suggestion.id, `${suggestion.skill_name} - ${suggestion.suggestion_type}`)}
                                          className="px-2 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700 flex items-center gap-1"
                                        >
                                          🚀 应用此建议
                                        </button>
                                      )}
                                    </div>
                                    <div className="text-sm text-green-800 break-all">
                                      {suggestion.suggested_value}
                                    </div>
                                  </div>
                                </div>

                                {/* 详情展开 */}
                                <div>
                                  <button
                                    onClick={() => setExpandedSuggestion(expandedSuggestion === sIdx ? null : sIdx)}
                                    className="text-sm text-indigo-600 hover:text-indigo-700 flex items-center gap-1"
                                  >
                                    {expandedSuggestion === sIdx ? '收起详情 ▲' : '查看详情 ▼'}
                                  </button>

                                  {expandedSuggestion === sIdx && (
                                    <div className="mt-3 space-y-3 border-t border-slate-200 pt-3">
                                      {suggestion.analysis_detail && (
                                        <div>
                                          <div className="text-xs font-medium text-indigo-600 mb-1">📊 详细分析</div>
                                          <div className="text-sm text-slate-700 bg-white p-3 rounded border border-slate-200 whitespace-pre-line">
                                            {suggestion.analysis_detail}
                                          </div>
                                        </div>
                                      )}
                                      {suggestion.supporting_examples && suggestion.supporting_examples.length > 0 && (
                                        <div>
                                          <div className="text-xs font-medium text-slate-500 mb-1">📌 相关示例</div>
                                          <div className="space-y-1">
                                            {suggestion.supporting_examples.map((example, eIdx) => (
                                              <div key={eIdx} className="text-sm text-slate-600 bg-slate-100 p-2 rounded">
                                                • {example}
                                              </div>
                                            ))}
                                          </div>
                                        </div>
                                      )}
                                      {suggestion.votes.length > 0 && (
                                        <div>
                                          <div className="text-xs font-medium text-slate-500 mb-1">🗳️ 投票情况</div>
                                          <div className="flex flex-wrap gap-1">
                                            {suggestion.votes.map((vote, vIdx) => (
                                              <span
                                                key={vIdx}
                                                className={`px-2 py-1 text-xs rounded ${
                                                  vote.vote ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                                                }`}
                                              >
                                                {vote.voter}: {vote.vote ? '通过' : '拒绝'}
                                                {vote.comment && ` - ${vote.comment}`}
                                              </span>
                                            ))}
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>

                                {/* 操作按钮 - 只要建议未应用就显示 */}
                                {!suggestion.applied && (
                                  <div className="flex gap-2 mt-3 pt-3 border-t border-slate-200">
                                    {suggestion.approved ? (
                                      <>
                                        {/* 已批准状态：可以取消批准 */}
                                        <button
                                          onClick={() => handleVoteSingle(report.report_path, suggestion.id, false)}
                                          className="px-3 py-1.5 bg-yellow-100 text-yellow-700 text-sm rounded hover:bg-yellow-200"
                                        >
                                          ↩️ 取消批准
                                        </button>
                                      </>
                                    ) : (
                                      <>
                                        {/* 未批准状态：可以批准或拒绝 */}
                                        <button
                                          onClick={() => handleVoteSingle(report.report_path, suggestion.id, false)}
                                          className="px-3 py-1.5 bg-slate-200 text-slate-700 text-sm rounded hover:bg-slate-300"
                                        >
                                          👎 拒绝
                                        </button>
                                        <button
                                          onClick={() => handleVoteSingle(report.report_path, suggestion.id, true)}
                                          className="px-3 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700"
                                        >
                                          👍 批准
                                        </button>
                                      </>
                                    )}
                                    <button
                                      onClick={() => handleShowPreview(report.report_path, suggestion.id)}
                                      className="px-3 py-1.5 bg-indigo-100 text-indigo-700 text-sm rounded hover:bg-indigo-200"
                                    >
                                      👁️ 预览效果
                                    </button>
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}
                  </div>
                  </>
                )}

                {/* 已应用建议归档区 */}
                {appliedSuggestions.length > 0 && (
                  <div className="mt-6 border-t border-slate-200 pt-4">
                    <div className="flex items-center gap-2 mb-4">
                      <h4 className="font-medium text-slate-700">📦 已应用建议归档</h4>
                      <span className="text-xs text-slate-400">({appliedSuggestions.length} 条)</span>
                    </div>
                    <div className="space-y-3">
                      {appliedSuggestions.map((suggestion, sIdx) => (
                        <div key={sIdx} className="p-3 bg-slate-50 rounded border border-slate-200 opacity-75">
                          <div className="flex items-center gap-2 flex-wrap mb-2">
                            <span className="text-sm text-slate-600 line-through">{suggestion.skill_name}</span>
                            <span className="px-2 py-0.5 text-xs rounded-full bg-slate-200 text-slate-600">
                              {getSuggestionTypeLabel(suggestion.suggestion_type)}
                            </span>
                            <span className="px-2 py-0.5 text-xs rounded-full bg-green-200 text-green-800 font-medium">
                              ✅ 已应用
                            </span>
                          </div>
                          <p className="text-sm text-slate-500 line-through mb-1">{suggestion.reason}</p>
                          <div className="flex gap-4 text-xs text-slate-400">
                            <span>当前值: {suggestion.current_value || '(空)'}</span>
                            <span>→</span>
                            <span>已优化为: {suggestion.suggested_value}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
              )
            })
          )}
        </div>
      )}

      {/* 预览弹窗 */}
      {previewState && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-4xl w-full max-h-[85vh] overflow-hidden flex flex-col">
            <div className="p-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
              <h3 className="text-lg font-bold text-slate-800">
                👁️ 优化效果预览
              </h3>
              <button
                onClick={() => { setPreviewState(null); setPreviewData(null); }}
                className="text-slate-400 hover:text-slate-600 p-2 hover:bg-slate-200 rounded"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {loadingPreview ? (
                <div className="text-center py-12 text-slate-400">加载中...</div>
              ) : previewData ? (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="bg-white p-4 rounded border border-slate-200">
                      <h4 className="text-sm font-medium text-slate-700 mb-2">📄 原文件内容</h4>
                      <pre className="text-xs text-slate-700 bg-slate-50 p-3 rounded whitespace-pre-wrap overflow-x-auto max-h-80">
                        {previewData.original}
                      </pre>
                    </div>
                    <div className="bg-white p-4 rounded border border-green-200 bg-green-50">
                      <h4 className="text-sm font-medium text-green-800 mb-2">✅ 优化后内容</h4>
                      <pre className="text-xs text-green-900 bg-white p-3 rounded border border-green-200 whitespace-pre-wrap overflow-x-auto max-h-80">
                        {previewData.optimized}
                      </pre>
                    </div>
                  </div>
                  {previewData.diff && previewData.diff.length > 0 && (
                    <div className="bg-white p-4 rounded border border-slate-200">
                      <h4 className="text-sm font-medium text-slate-700 mb-2">📊 差异对比</h4>
                      <pre className="text-xs text-slate-700 bg-slate-50 p-3 rounded whitespace-pre overflow-x-auto max-h-40">
                        {previewData.diff.join('\n')}
                      </pre>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center py-12 text-slate-400">预览加载失败</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Skill 详情弹窗 */}
      {showDetail && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-4xl w-full max-h-[85vh] overflow-hidden flex flex-col">
            <div className="p-4 border-b border-slate-200 flex items-center justify-between bg-slate-50">
              <div>
                <h3 className="text-lg font-bold text-slate-800">
                  📚 {selectedSkill}
                </h3>
                {skillDetail && (
                  <p className="text-sm text-slate-500 mt-1">
                    版本 v{skillDetail.meta.version} · {skillDetail.meta.invocation_mode}
                    · {skillDetail.activation_count} 次激活
                  </p>
                )}
              </div>
              <button
                onClick={() => setShowDetail(false)}
                className="text-slate-400 hover:text-slate-600 p-2 hover:bg-slate-200 rounded"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto">
              {loadingDetail ? (
                <div className="p-8 text-center text-slate-400">加载中...</div>
              ) : skillDetail ? (
                <div className="p-4 space-y-4">
                  {/* 基本信息 */}
                  <div className="bg-slate-50 p-4 rounded-lg">
                    <h4 className="font-medium text-slate-800 mb-3">📋 基本信息</h4>
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <span className="text-slate-500">描述:</span>
                        <p className="text-slate-700 mt-1">{skillDetail.meta.description}</p>
                      </div>
                      <div>
                        <span className="text-slate-500">触发词:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {skillDetail.meta.triggers.map((t, i) => (
                            <span key={i} className="px-2 py-0.5 bg-yellow-100 text-yellow-700 text-xs rounded-full">
                              {typeof t === 'string' ? t : JSON.stringify(t)}
                            </span>
                          ))}
                          {skillDetail.meta.triggers.length === 0 && <span className="text-slate-400">无</span>}
                        </div>
                      </div>
                      <div>
                        <span className="text-slate-500">标签:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {skillDetail.meta.tags.map((tag, i) => (
                            <span key={i} className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full">
                              {tag}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div>
                        <span className="text-slate-500">MCP 工具:</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {skillDetail.meta.mcp_tools.map((tool, i) => (
                            <span key={i} className="px-2 py-0.5 bg-purple-100 text-purple-700 text-xs rounded-full">
                              {tool}
                            </span>
                          ))}
                          {skillDetail.meta.mcp_tools.length === 0 && <span className="text-slate-400">无</span>}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Skill 指令 */}
                  <div className="bg-slate-50 p-4 rounded-lg">
                    <h4 className="font-medium text-slate-800 mb-3">📝 Skill 指令</h4>
                    <pre className="text-sm text-slate-700 bg-white p-3 rounded border border-slate-200 whitespace-pre-wrap overflow-x-auto max-h-60">
                      {skillDetail.instructions}
                    </pre>
                  </div>

                  {/* 相关日志 */}
                  <div className="bg-slate-50 p-4 rounded-lg">
                    <h4 className="font-medium text-slate-800 mb-3">📊 相关路由日志 ({skillDetail.related_logs.length})</h4>
                    {skillDetail.related_logs.length === 0 ? (
                      <p className="text-sm text-slate-400">暂无相关日志</p>
                    ) : (
                      <div className="space-y-2 max-h-60 overflow-y-auto">
                        {skillDetail.related_logs.map((log) => (
                          <div key={log.id} className="bg-white p-3 rounded border border-slate-200 text-sm">
                            <div className="flex items-center justify-between mb-2">
                              <div className="flex items-center gap-2">
                                <span className="text-slate-500 text-xs">{log.agent}</span>
                                {log.was_selected && (
                                  <span className="px-1.5 py-0.5 bg-green-100 text-green-700 text-xs rounded-full">
                                    已选中
                                  </span>
                                )}
                                {!log.was_selected && log.was_ranked && (
                                  <span className="px-1.5 py-0.5 bg-yellow-100 text-yellow-700 text-xs rounded-full">
                                    仅排名
                                  </span>
                                )}
                                {!log.was_selected && !log.was_ranked && log.was_filtered && (
                                  <span className="px-1.5 py-0.5 bg-slate-200 text-slate-600 text-xs rounded-full">
                                    仅过滤
                                  </span>
                                )}
                              </div>
                              <span className="text-xs text-slate-400">{formatTime(log.timestamp)}</span>
                            </div>
                            <p className="text-slate-700 truncate">{log.query}</p>
                            {log.was_selected && (
                              <div className="mt-2 text-xs text-slate-500">
                                同时选中: {log.selected_skills.join(', ')}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                <div className="p-8 text-center text-slate-400">加载失败</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
