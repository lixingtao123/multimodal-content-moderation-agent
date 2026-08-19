import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { HistoryItem, LogEntry, PipelineLog } from '../types'
import { formatShortDateTime, formatTime } from '../utils/time'

const DECISION_COLORS: Record<string, string> = {
  PASS: 'text-green-600',
  REVIEW: 'text-yellow-600',
  REJECT: 'text-red-600',
}

const BADGES: Record<string, string> = {
  PASS: 'badge-pass',
  REVIEW: 'badge-review',
  REJECT: 'badge-reject',
}

type TabKey = 'history' | 'logs'

export default function HistoryList() {
  const navigate = useNavigate()

  // ===== 审核历史状态 =====
  const [items, setItems] = useState<HistoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [decision, setDecision] = useState<string | undefined>()
  const [contentType, setContentType] = useState<string | undefined>()
  const [loading, setLoading] = useState(false)
  const pageSize = 20

  // ===== Pipeline 日志状态 =====
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [logsLoading, setLogsLoading] = useState(false)

  // ===== 搜索 =====
  const [searchId, setSearchId] = useState('')

  // ===== Tab =====
  const [activeTab, setActiveTab] = useState<TabKey>('history')

  // ===== 审核历史加载 =====
  const loadHistory = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.getHistory(page, pageSize, decision, contentType) as { total: number; items: HistoryItem[] }
      setItems(data.items)
      setTotal(data.total)
    } catch (e) {
      console.error('Failed to load history:', e)
    } finally {
      setLoading(false)
    }
  }, [page, decision, contentType])

  useEffect(() => {
    if (activeTab === 'history') loadHistory()
  }, [loadHistory, activeTab])

  useEffect(() => {
    if (activeTab !== 'history' || page !== 1) return
    const timer = setInterval(loadHistory, 5000)
    return () => clearInterval(timer)
  }, [loadHistory, activeTab, page])

  // ===== Pipeline 日志加载 =====
  const loadLogs = useCallback(async () => {
    setLogsLoading(true)
    try {
      const data = await api.getRecentLogs(50) as { items: LogEntry[]; total: number }
      setLogs(data.items || [])
    } catch (e) {
      console.error('Failed to load logs:', e)
    } finally {
      setLogsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'logs') loadLogs()
  }, [loadLogs, activeTab])

  // 自动刷新日志 (5s)
  useEffect(() => {
    if (activeTab !== 'logs') return
    const timer = setInterval(loadLogs, 5000)
    return () => clearInterval(timer)
  }, [loadLogs, activeTab])

  // ===== 搜索 & 详情导航 =====
  const handleSearch = async () => {
    if (!searchId.trim()) return
    navigate(`/history/${searchId.trim()}`)
  }

  const viewDetail = (contentId: string) => {
    navigate(`/history/${contentId}`)
  }

  const totalPages = Math.ceil(total / pageSize)

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-800">审核历史 & 日志</h2>
          <p className="text-sm text-slate-500 mt-1">
            {activeTab === 'history'
              ? `共 ${total} 条审核记录`
              : `${logs.length} 条 Pipeline 日志`}
            {activeTab === 'history' && page === 1 ? ' · 每 5 秒自动刷新' : ''}
          </p>
        </div>
        {/* Quick Search */}
        <div className="flex gap-2">
          <input
            type="text"
            value={searchId}
            onChange={(e) => setSearchId(e.target.value)}
            placeholder="搜索 Content ID..."
            className="input w-56 text-sm"
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          />
          <button onClick={handleSearch} className="btn btn-secondary text-sm py-2">
            搜索
          </button>
        </div>
      </div>

      {/* Tab Switcher */}
      <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1 w-fit">
        <button
          onClick={() => setActiveTab('history')}
          className={`px-4 py-2 text-sm rounded-md font-medium transition-all ${
            activeTab === 'history'
              ? 'bg-white text-slate-800 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          📋 审核记录
        </button>
        <button
          onClick={() => setActiveTab('logs')}
          className={`px-4 py-2 text-sm rounded-md font-medium transition-all ${
            activeTab === 'logs'
              ? 'bg-white text-slate-800 shadow-sm'
              : 'text-slate-500 hover:text-slate-700'
          }`}
        >
          🔍 Pipeline 日志
        </button>
      </div>

      {/* ===== Tab: 审核历史 ===== */}
      {activeTab === 'history' && (
        <>
          {/* Filters */}
          <div className="card p-4">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500 font-medium">决策:</span>
                <select
                  value={decision || ''}
                  onChange={(e) => { setDecision(e.target.value || undefined); setPage(1) }}
                  className="input w-32 text-sm py-1.5"
                >
                  <option value="">全部</option>
                  <option value="PASS">通过</option>
                  <option value="REVIEW">人工复核</option>
                  <option value="REJECT">拒绝</option>
                </select>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500 font-medium">类型:</span>
                <select
                  value={contentType || ''}
                  onChange={(e) => { setContentType(e.target.value || undefined); setPage(1) }}
                  className="input w-32 text-sm py-1.5"
                >
                  <option value="">全部</option>
                  <option value="text">文本</option>
                  <option value="image">图片</option>
                  <option value="audio">语音</option>
                  <option value="video">视频</option>
                  <option value="multi_modal">多模态</option>
                </select>
              </div>
              <button onClick={loadHistory} className="btn btn-secondary text-sm py-1.5 ml-auto">
                🔄 刷新
              </button>
            </div>
          </div>

          {/* Table */}
          <div className="card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-slate-50 border-b border-slate-100">
                  <tr>
                    <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">Content ID</th>
                    <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">内容摘要</th>
                    <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">类型</th>
                    <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">决策</th>
                    <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">风险分</th>
                    <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">耗时</th>
                    <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">时间</th>
                    <th className="text-center px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {loading ? (
                    <tr><td colSpan={8} className="text-center py-16 text-slate-400">
                      <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                      加载中...
                    </td></tr>
                  ) : items.length === 0 ? (
                    <tr><td colSpan={8} className="text-center py-16 text-slate-400">暂无审核记录</td></tr>
                  ) : (
                    items.map((item) => (
                      <tr key={item.content_id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-5 py-3.5 text-sm font-mono text-slate-600">{item.content_id}</td>
                        <td className="px-5 py-3.5">
                          <div
                            className="max-w-64 truncate text-sm text-slate-600"
                            title={item.content_preview || '无内容摘要'}
                          >
                            {item.content_preview?.replace(/\s+/g, ' ').trim() || '无内容摘要'}
                          </div>
                        </td>
                        <td className="px-5 py-3.5">
                          <span className="badge badge-info">{item.content_type}</span>
                        </td>
                        <td className={`px-5 py-3.5 text-sm font-semibold ${DECISION_COLORS[item.final_decision] || ''}`}>
                          <span className={`badge ${BADGES[item.final_decision] || 'badge-info'}`}>
                            {item.final_decision === 'PASS' ? '通过' :
                             item.final_decision === 'REVIEW' ? '复核' :
                             item.final_decision === 'REJECT' ? '拒绝' : item.final_decision}
                          </span>
                        </td>
                        <td className="px-5 py-3.5">
                          <div className="flex items-center gap-2">
                            <div className="w-16 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full transition-all ${
                                  item.risk_score > 0.7 ? 'bg-red-500' : item.risk_score > 0.35 ? 'bg-yellow-500' : 'bg-green-500'
                                }`}
                                style={{ width: `${item.risk_score * 100}%` }}
                              />
                            </div>
                            <span className="text-sm text-slate-600 font-mono">{item.risk_score.toFixed(3)}</span>
                          </div>
                        </td>
                        <td className="px-5 py-3.5 text-sm text-slate-500">{item.processing_time_ms.toFixed(0)}ms</td>
                        <td className="px-5 py-3.5 text-sm text-slate-400">
                          {formatShortDateTime(item.created_at)}
                        </td>
                        <td className="px-5 py-3.5 text-center">
                          <button
                            onClick={() => viewDetail(item.content_id)}
                            className="text-xs text-indigo-600 hover:text-indigo-800 font-medium hover:underline"
                          >
                            详情
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-5 py-3 border-t border-slate-100">
                <span className="text-xs text-slate-400">共 {total} 条</span>
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setPage(1)}
                    disabled={page === 1}
                    className="px-2.5 py-1.5 text-xs border rounded-md hover:bg-slate-50 disabled:opacity-30"
                  >首页</button>
                  <button
                    onClick={() => setPage(Math.max(1, page - 1))}
                    disabled={page === 1}
                    className="px-2.5 py-1.5 text-xs border rounded-md hover:bg-slate-50 disabled:opacity-30"
                  >上一页</button>
                  <span className="text-xs text-slate-600 px-2 font-medium">{page} / {totalPages}</span>
                  <button
                    onClick={() => setPage(Math.min(totalPages, page + 1))}
                    disabled={page === totalPages}
                    className="px-2.5 py-1.5 text-xs border rounded-md hover:bg-slate-50 disabled:opacity-30"
                  >下一页</button>
                  <button
                    onClick={() => setPage(totalPages)}
                    disabled={page === totalPages}
                    className="px-2.5 py-1.5 text-xs border rounded-md hover:bg-slate-50 disabled:opacity-30"
                  >末页</button>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* ===== Tab: Pipeline 日志 ===== */}
      {activeTab === 'logs' && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-slate-50 border-b border-slate-100">
                <tr>
                  <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">Content ID</th>
                  <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">类型</th>
                  <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">步骤数</th>
                  <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">总耗时</th>
                  <th className="text-left px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">时间</th>
                  <th className="text-center px-5 py-3.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {logsLoading ? (
                  <tr><td colSpan={6} className="text-center py-16 text-slate-400">
                    <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                    加载中...
                  </td></tr>
                ) : logs.length === 0 ? (
                  <tr><td colSpan={6} className="text-center py-16 text-slate-400">暂无 Pipeline 日志</td></tr>
                ) : (
                  logs.map((log) => (
                    <tr
                      key={log.content_id}
                      onClick={() => viewDetail(log.content_id)}
                      className="hover:bg-indigo-50/30 transition-colors cursor-pointer"
                    >
                      <td className="px-5 py-3.5 text-sm font-mono text-slate-600">{log.content_id}</td>
                      <td className="px-5 py-3.5">
                        <span className="badge badge-info">{log.content_type}</span>
                      </td>
                      <td className="px-5 py-3.5 text-sm text-slate-600">{log.step_count} 步</td>
                      <td className="px-5 py-3.5 text-sm text-slate-500 font-mono">{log.total_duration_ms.toFixed(0)}ms</td>
                      <td className="px-5 py-3.5 text-sm text-slate-400">{formatTime(log.start_time)}</td>
                      <td className="px-5 py-3.5 text-center">
                        <button
                          onClick={(e) => { e.stopPropagation(); viewDetail(log.content_id) }}
                          className="text-xs text-indigo-600 hover:text-indigo-800 font-medium hover:underline"
                        >
                          查看详情
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
