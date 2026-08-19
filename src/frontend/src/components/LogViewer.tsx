import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'
import type { LogEntry, PipelineLog } from '../types'
import { formatTime, formatDateTime } from '../utils/time'

const LEVEL_COLORS: Record<string, string> = {
  ERROR: '#ef4444',
  WARN: '#f59e0b',
  INFO: '#10b981',
}

export default function LogViewer() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [selectedLog, setSelectedLog] = useState<PipelineLog | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchId, setSearchId] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)

  const loadLogs = useCallback(async () => {
    try {
      const data = await api.getRecentLogs(50) as { items: LogEntry[], total: number }
      setLogs(data.items || [])
    } catch (e) {
      console.error('Failed to load logs:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadLogs()
    if (!autoRefresh) return
    const timer = setInterval(loadLogs, 5000)
    return () => clearInterval(timer)
  }, [loadLogs, autoRefresh])

  const viewLogDetail = async (contentId: string) => {
    try {
      const detail = await api.getPipelineLog(contentId) as PipelineLog
      setSelectedLog(detail)
    } catch {
      alert('加载日志详情失败')
    }
  }

  const handleSearch = async () => {
    if (!searchId.trim()) return
    await viewLogDetail(searchId.trim())
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-800">日志追踪</h2>
          <p className="text-sm text-slate-500 mt-1">全链路审核流水线日志</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-slate-500 cursor-pointer">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="w-4 h-4 rounded text-indigo-500 focus:ring-indigo-500"
            />
            自动刷新 (5s)
          </label>
          <button onClick={loadLogs} className="btn btn-secondary text-sm py-2">
            🔄 刷新
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Log List */}
        <div className="lg:col-span-1 card overflow-hidden">
          <div className="p-4 border-b border-slate-100">
            <div className="flex gap-2">
              <input
                type="text"
                value={searchId}
                onChange={(e) => setSearchId(e.target.value)}
                placeholder="搜索 Content ID..."
                className="input text-sm flex-1"
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              />
              <button onClick={handleSearch} className="btn btn-secondary text-sm py-2 px-3">
                查看
              </button>
            </div>
          </div>
          <div className="divide-y divide-slate-50 max-h-[70vh] overflow-y-auto">
            {loading ? (
              <div className="text-center py-12 text-slate-400">
                <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
                加载中...
              </div>
            ) : logs.length === 0 ? (
              <div className="text-center py-12 text-slate-400 text-sm">暂无日志</div>
            ) : (
              logs.map((log) => (
                <div
                  key={log.content_id}
                  onClick={() => viewLogDetail(log.content_id)}
                  className={`px-4 py-3 cursor-pointer hover:bg-slate-50 transition-colors ${
                    selectedLog?.content_id === log.content_id ? 'bg-indigo-50 border-l-2 border-indigo-500' : ''
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-mono text-slate-600 truncate">{log.content_id}</span>
                    <span className="badge badge-info text-xs">{log.content_type}</span>
                  </div>
                  <div className="flex items-center justify-between mt-1.5">
                    <span className="text-xs text-slate-400">{log.step_count} 步骤</span>
                    <span className="text-xs text-slate-500">{log.total_duration_ms.toFixed(0)}ms</span>
                  </div>
                  <div className="text-xs text-slate-400 mt-0.5">
                    {formatTime(log.start_time)}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Log Detail */}
        <div className="lg:col-span-2 card overflow-hidden">
          {selectedLog ? (
            <div>
              <div className="p-5 border-b border-slate-100 bg-slate-50">
                <h3 className="text-sm font-bold text-slate-800 font-mono">
                  🔍 {selectedLog.content_id}
                </h3>
                <div className="flex items-center gap-5 mt-2 text-xs text-slate-500">
                  <span>📦 {selectedLog.content_type}</span>
                  <span>📊 {selectedLog.step_count} 步骤</span>
                  <span>⏱ {selectedLog.total_duration_ms.toFixed(0)}ms</span>
                  <span>🕐 {formatDateTime(selectedLog.start_time)}</span>
                </div>
              </div>
              <div className="overflow-x-auto max-h-[60vh] overflow-y-auto">
                <table className="w-full">
                  <thead className="bg-slate-100 sticky top-0">
                    <tr>
                      <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-600 w-10">#</th>
                      <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-600">节点</th>
                      <th className="text-left px-4 py-2.5 text-xs font-semibold text-slate-600">操作</th>
                      <th className="text-right px-4 py-2.5 text-xs font-semibold text-slate-600 w-20">耗时</th>
                      <th className="text-right px-4 py-2.5 text-xs font-semibold text-slate-600 w-20">累计</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {selectedLog.steps.map((step) => (
                      <tr key={step.seq} className="hover:bg-slate-50 transition-colors">
                        <td className="px-4 py-2.5 text-xs text-slate-400">{step.seq}</td>
                        <td className="px-4 py-2.5">
                          <span className="text-sm font-semibold" style={{ color: LEVEL_COLORS[step.level] || '#64748b' }}>
                            {step.node}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-sm text-slate-600">{step.action}</td>
                        <td className="px-4 py-2.5 text-xs text-slate-500 text-right font-mono">
                          {step.duration_ms > 0 ? `${step.duration_ms.toFixed(0)}ms` : '-'}
                        </td>
                        <td className="px-4 py-2.5 text-xs text-slate-500 text-right font-mono">
                          +{step.elapsed_ms.toFixed(0)}ms
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="text-center py-20">
              <div className="text-5xl mb-4 opacity-20">📋</div>
              <p className="text-sm text-slate-400">选择左侧日志查看详细流水线</p>
              <p className="text-xs text-slate-300 mt-1">包含每一步的节点、操作和耗时信息</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
