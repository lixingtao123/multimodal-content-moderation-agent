import { useState, useRef, useCallback, useEffect } from 'react'
import { api } from '../api/client'
import type { AsyncTaskInfo } from '../types'

// 复用现有审核结果展示的配置
const DECISION_CONFIG: Record<string, { label: string; className: string; icon: string }> = {
  PASS: { label: '通过', className: 'badge-pass', icon: '✓' },
  REVIEW: { label: '人工复核', className: 'badge-review', icon: '⚠' },
  REJECT: { label: '拒绝', className: 'badge-reject', icon: '✕' },
  UNKNOWN: { label: '未知', className: 'badge-info', icon: '?' },
  PENDING_HUMAN_REVIEW: { label: '待人工', className: 'badge-review', icon: '⏳' },
}

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  QUEUED: { label: '排队中', color: 'bg-slate-100 text-slate-600', icon: '⏳' },
  PROCESSING: { label: '审核中', color: 'bg-blue-100 text-blue-700', icon: '⚙️' },
  COMPLETED: { label: '已完成', color: 'bg-green-100 text-green-700', icon: '✓' },
  FAILED: { label: '失败', color: 'bg-red-100 text-red-700', icon: '✕' },
  AWAITING_HUMAN: { label: '待人工', color: 'bg-yellow-100 text-yellow-700', icon: '👤' },
  CANCELLED: { label: '已取消', color: 'bg-gray-100 text-gray-500', icon: '⊘' },
}

const POLL_INTERVAL = 3000  // 3s 轮询

export default function AsyncModeration() {
  // 输入状态
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [dragOver, setDragOver] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitMsg, setSubmitMsg] = useState<string | null>(null)

  // 任务列表状态
  const [tasks, setTasks] = useState<AsyncTaskInfo[]>([])
  const [selectedTask, setSelectedTask] = useState<AsyncTaskInfo | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // ===== 挂载时恢复历史任务（C7·R22）=====
  const toTask = (raw: Record<string, unknown>): AsyncTaskInfo => ({
    task_id: (raw.task_id as string) || '',
    status: (raw.status as AsyncTaskInfo['status']) || 'QUEUED',
    progress: (raw.progress as number) ?? 0,
    current_step: (raw.current_step as string) || '',
    content_type: (raw.content_type as string) || 'text',
    content_preview: (raw.content_preview as string) || '',
    created_at: (raw.created_at as string) || new Date().toISOString(),
    final_decision: raw.final_decision as string,
    risk_score: raw.risk_score as number,
    violation_types: raw.violation_types as string[],
    processing_time_ms: raw.processing_time_ms as number,
    agent_reasoning: raw.agent_reasoning as Record<string, unknown>,
    debate_info: raw.debate_info as Record<string, unknown>,
    suggestions: raw.suggestions as Array<{ action: string; reason: string; priority: string }>,
    error_message: raw.error_message as string,
  })

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await api.getTaskList(50, 'all')
        const items = (res.items || []).filter(i => i.task_id)
        if (!cancelled && items.length > 0) {
          setTasks(prev => {
            const merged = new Map<string, AsyncTaskInfo>()
            for (const t of prev) merged.set(t.task_id, t)
            for (const raw of items) {
              const t = toTask(raw)
              if (t.task_id && !merged.has(t.task_id)) merged.set(t.task_id, t)
            }
            return [...merged.values()].sort((a, b) =>
              new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
          })
        }
      } catch (e) {
        console.error('加载历史任务失败:', e)
      }
    })()
    return () => { cancelled = true }
  }, [])

  // ===== 取消任务 =====
  const handleCancelTask = async (task: AsyncTaskInfo) => {
    if (!confirm(`确认取消任务 ${task.task_id.slice(0, 16)}... ?`)) return
    try {
      await api.cancelTask(task.task_id)
      setTasks(prev => prev.map(t =>
        t.task_id === task.task_id ? { ...t, status: 'CANCELLED', current_step: '已由用户取消' } : t))
    } catch (e) {
      alert(`取消失败: ${e instanceof Error ? e.message : '未知错误'}`)
    }
  }

  // ===== 提交任务 =====
  const handleSubmit = async () => {
    if (!text.trim() && files.length === 0) return
    setSubmitting(true)
    setSubmitMsg(null)
    try {
      const res = await api.submitAsyncTask(text, files)
      const newTask: AsyncTaskInfo = {
        task_id: res.task_id,
        status: 'QUEUED',
        progress: 0,
        current_step: '',
        content_type: res.content_type || 'text',
        content_preview: text.slice(0, 100) || `[${files.length} 个文件]`,
        created_at: new Date().toISOString(),
      }
      setTasks(prev => [newTask, ...prev])
      setSubmitMsg(`任务已提交: ${res.task_id.slice(0, 20)}...`)
      // 清空输入
      setText('')
      setFiles([])
    } catch (e: unknown) {
      setSubmitMsg(`提交失败: ${e instanceof Error ? e.message : '未知错误'}`)
    } finally {
      setSubmitting(false)
    }
  }

  // ===== 轮询 PROCESSING/QUEUED 任务 =====
  useEffect(() => {
    const activeTasks = tasks.filter(
      t => t.status === 'PROCESSING' || t.status === 'QUEUED'
    )
    if (activeTasks.length === 0) return

    const interval = setInterval(async () => {
      const updated = { ...tasks.reduce((acc, t) => ({ ...acc, [t.task_id]: t }), {} as Record<string, AsyncTaskInfo>) }
      let changed = false

      for (const task of activeTasks) {
        try {
          const raw = await api.getTaskStatus(task.task_id) as Record<string, unknown>
          if (raw && raw.status !== task.status) {
            updated[task.task_id] = {
              ...task,
              task_id: raw.task_id as string || task.task_id,
              status: raw.status as AsyncTaskInfo['status'] || task.status,
              progress: raw.progress as number ?? task.progress,
              current_step: raw.current_step as string || '',
              final_decision: raw.final_decision as string,
              risk_score: raw.risk_score as number,
              violation_types: raw.violation_types as string[],
              processing_time_ms: raw.processing_time_ms as number,
              agent_reasoning: raw.agent_reasoning as Record<string, unknown>,
              debate_info: raw.debate_info as Record<string, unknown>,
              suggestions: raw.suggestions as Array<{ action: string; reason: string; priority: string }>,
              error_message: raw.error_message as string,
            }
            changed = true
          }
        } catch {
          // 忽略轮询错误
        }
      }

      if (changed) {
        setTasks(Object.values(updated).sort((a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        ))
      }
    }, POLL_INTERVAL)

    return () => clearInterval(interval)
  }, [tasks])

  // ===== 文件处理 =====
  const handleFileDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const dropped = Array.from(e.dataTransfer.files)
    setFiles(prev => [...prev, ...dropped])
  }, [])

  const removeFile = (idx: number) => {
    setFiles(prev => prev.filter((_, i) => i !== idx))
  }

  const getFileIcon = (name: string) => {
    const ext = name.split('.').pop()?.toLowerCase() || ''
    const map: Record<string, string> = {
      pdf: '📕', docx: '📘', doc: '📘', txt: '📄', md: '📝',
      csv: '📊', json: '📋', xml: '📋', html: '🌐',
      jpg: '🖼️', jpeg: '🖼️', png: '🖼️', gif: '🖼️', webp: '🖼️',
      mp3: '🎵', wav: '🎤', flac: '🎤', m4a: '🎤',
      mp4: '🎬', avi: '🎬', mov: '🎬',
      py: '🐍', js: '💛', ts: '💙', java: '☕', go: '🔵',
    }
    return map[ext] || '📎'
  }

  // ===== UI 辅助 =====
  const formatTime = (iso: string) => {
    if (!iso) return '-'
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  }

  const statusBadge = (status: string) => {
    const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.QUEUED
    return (
      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${cfg.color}`}>
        {cfg.icon} {cfg.label}
      </span>
    )
  }

  return (
    <div className="p-6 space-y-6 max-w-screen-2xl mx-auto">
      <h1 className="text-xl font-bold text-slate-800">⚡ 异步审核</h1>
      <p className="text-sm text-slate-500 -mt-4">提交任务后无需等待，后台异步处理。刷新页面可查看实时进度。</p>

      {/* ===== 提交区域 ===== */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* 输入区 */}
        <div className="card">
          <h2 className="text-base font-semibold text-slate-700 mb-3">📤 提交审核任务</h2>

          {/* 文本输入 */}
          <textarea
            className="input w-full mb-3 min-h-[120px]"
            placeholder="输入审核文本（可选）..."
            value={text}
            onChange={e => setText(e.target.value)}
          />
          <div className="text-xs text-slate-400 mb-3">{text.length} 字符</div>

          {/* 文件上传 */}
          <div
            className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors
              ${dragOver ? 'border-indigo-400 bg-indigo-50' : 'border-slate-300 hover:border-slate-400'}`}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleFileDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <div className="text-3xl mb-2">📁</div>
            <p className="text-sm text-slate-500">拖拽文件到此处，或点击选择</p>
            <p className="text-xs text-slate-400 mt-1">支持 PDF/Word/TXT/图片/音频/代码文件</p>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={e => {
                const selected = Array.from(e.target.files || [])
                setFiles(prev => [...prev, ...selected])
              }}
            />
          </div>

          {/* 文件列表 */}
          {files.length > 0 && (
            <div className="mt-3 space-y-1">
              {files.map((f, i) => (
                <div key={i} className="flex items-center justify-between text-sm bg-slate-50 rounded px-3 py-1.5">
                  <span>{getFileIcon(f.name)} {f.name} <span className="text-slate-400 text-xs">({(f.size / 1024).toFixed(1)} KB)</span></span>
                  <button onClick={() => removeFile(i)} className="text-red-400 hover:text-red-600 text-xs">移除</button>
                </div>
              ))}
            </div>
          )}

          {/* 提交按钮 */}
          <button
            className="btn-primary mt-4 w-full"
            disabled={submitting || (!text.trim() && files.length === 0)}
            onClick={handleSubmit}
          >
            {submitting ? '提交中...' : '🚀 异步提交任务'}
          </button>
          {submitMsg && (
            <div className={`mt-2 text-xs px-3 py-1.5 rounded ${
              submitMsg.includes('失败') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'
            }`}>
              {submitMsg}
            </div>
          )}
        </div>

        {/* 任务列表 */}
        <div className="card">
          <h2 className="text-base font-semibold text-slate-700 mb-3">📋 任务列表</h2>

          {tasks.length === 0 ? (
            <div className="text-center py-12 text-slate-400">
              <div className="text-4xl mb-3">📭</div>
              <p>暂无任务</p>
              <p className="text-xs mt-1">提交审核任务后将在此显示</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[500px] overflow-y-auto">
              {tasks.map(task => (
                <div
                  key={task.task_id}
                  className={`border rounded-lg p-3 cursor-pointer transition-colors hover:border-indigo-300 ${
                    selectedTask?.task_id === task.task_id ? 'border-indigo-400 bg-indigo-50' : 'border-slate-200'
                  }`}
                  onClick={() => setSelectedTask(task)}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-mono text-slate-400">{task.task_id.slice(0, 20)}...</span>
                    <div className="flex items-center gap-2">
                      {(task.status === 'QUEUED' || task.status === 'PROCESSING') && (
                        <button
                          className="text-xs text-red-500 hover:text-red-700"
                          onClick={e => { e.stopPropagation(); handleCancelTask(task) }}
                        >
                          ✕ 取消
                        </button>
                      )}
                      {statusBadge(task.status)}
                    </div>
                  </div>
                  <div className="text-sm text-slate-700 truncate">
                    {task.content_preview || '(无预览)'}
                  </div>
                  <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-400">
                    <span>{task.content_type}</span>
                    <span>{formatTime(task.created_at)}</span>
                    {task.processing_time_ms != null && (
                      <span>{(task.processing_time_ms / 1000).toFixed(1)}s</span>
                    )}
                  </div>
                  {/* 进度条 (PROCESSING) */}
                  {task.status === 'PROCESSING' && (
                    <div className="mt-2">
                      <div className="w-full bg-slate-200 rounded-full h-1.5">
                        <div
                          className="bg-indigo-500 h-1.5 rounded-full transition-all duration-500"
                          style={{ width: `${Math.round((task.progress || 0) * 100)}%` }}
                        />
                      </div>
                      <div className="text-xs text-slate-400 mt-0.5">
                        {task.current_step || '处理中...'} ({Math.round((task.progress || 0) * 100)}%)
                      </div>
                    </div>
                  )}
                  {/* 错误信息 (FAILED) */}
                  {task.status === 'FAILED' && task.error_message && (
                    <div className="mt-1 text-xs text-red-500 truncate">{task.error_message}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ===== 结果详情 (选中已完成任务) ===== */}
      {selectedTask && selectedTask.status === 'COMPLETED' && (
        <div className="card" id="async-result-detail">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold text-slate-700">
              📊 审核结果: {selectedTask.task_id.slice(0, 20)}...
            </h2>
            <button
              className="text-xs text-slate-400 hover:text-slate-600"
              onClick={() => setSelectedTask(null)}
            >
              关闭
            </button>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
            {/* 风险分数 */}
            <div className="flex flex-col items-center p-4 bg-slate-50 rounded-lg">
              <div className="relative w-24 h-24">
                <svg className="w-24 h-24 transform -rotate-90" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="42" fill="none" stroke="#e2e8f0" strokeWidth="8" />
                  <circle cx="50" cy="50" r="42" fill="none"
                    stroke={((selectedTask.risk_score || 0) > 0.7 ? '#ef4444' : (selectedTask.risk_score || 0) > 0.35 ? '#f59e0b' : '#22c55e')}
                    strokeWidth="8" strokeLinecap="round"
                    strokeDasharray={`${(selectedTask.risk_score || 0) * 264} 264`}
                  />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-2xl font-bold text-slate-700">{((selectedTask.risk_score || 0) * 100).toFixed(0)}</span>
                </div>
              </div>
              <span className="text-xs text-slate-500 mt-2">风险分数</span>
            </div>

            {/* 判定结果 */}
            <div className="flex flex-col items-center justify-center p-4 bg-slate-50 rounded-lg">
              {(() => {
                const dc = DECISION_CONFIG[selectedTask.final_decision || ''] || DECISION_CONFIG.UNKNOWN
                return (
                  <>
                    <span className={`inline-block px-4 py-1.5 rounded-full text-sm font-bold ${dc.className}`}>
                      {dc.icon} {dc.label}
                    </span>
                    <span className="text-xs text-slate-500 mt-2">最终判定</span>
                  </>
                )
              })()}
            </div>

            {/* 处理时间 */}
            <div className="flex flex-col items-center justify-center p-4 bg-slate-50 rounded-lg">
              <span className="text-2xl font-bold text-slate-700">
                {selectedTask.processing_time_ms != null ? `${(selectedTask.processing_time_ms / 1000).toFixed(1)}s` : '-'}
              </span>
              <span className="text-xs text-slate-500 mt-2">处理耗时</span>
            </div>
          </div>

          {/* 违规类型 */}
          {selectedTask.violation_types && selectedTask.violation_types.length > 0 && (
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-slate-600 mb-2">违规类型</h3>
              <div className="flex flex-wrap gap-2">
                {selectedTask.violation_types.map((vt, i) => (
                  <span key={i} className="px-2.5 py-1 bg-red-50 text-red-600 rounded-full text-xs font-medium">
                    {vt}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Agent 推理 */}
          {selectedTask.agent_reasoning && (
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-slate-600 mb-2">AI 推理过程</h3>
              <div className="space-y-2">
                {Object.entries(selectedTask.agent_reasoning as Record<string, Record<string, unknown>>).map(([agent, data]) => (
                  <details key={agent} className="border border-slate-200 rounded-lg">
                    <summary className="px-3 py-2 cursor-pointer text-sm font-medium text-slate-700 bg-slate-50 hover:bg-slate-100">
                      {agent}: {data.violation_type as string || 'none'} (置信度: {String(data.confidence || 0)})
                    </summary>
                    <div className="px-3 py-2 text-xs text-slate-600 space-y-1">
                      <p><span className="font-medium">原因:</span> {String(data.reason || '-')}</p>
                      {Boolean(data.reasoning) && <p><span className="font-medium">推理:</span> {String(data.reasoning)}</p>}
                      {Boolean(data.reasoning_chain) && (
                        <div>
                          <span className="font-medium">推理链:</span>
                          <ul className="list-disc list-inside mt-1">
                            {(data.reasoning_chain as string[]).map((step, i) => (
                              <li key={i}>{String(step)}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {Boolean(data.keyword_matches) && (data.keyword_matches as string[]).length > 0 && (
                        <p><span className="font-medium">关键词:</span> {(data.keyword_matches as string[]).join(', ')}</p>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            </div>
          )}

          {/* 处理建议 */}
          {selectedTask.suggestions && selectedTask.suggestions.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold text-slate-600 mb-2">处理建议</h3>
              <div className="space-y-1.5">
                {selectedTask.suggestions.map((s, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm px-3 py-2 bg-slate-50 rounded">
                    <span className={`w-1.5 h-1.5 rounded-full ${
                      s.priority === 'HIGH' ? 'bg-red-400' : s.priority === 'MEDIUM' ? 'bg-yellow-400' : 'bg-blue-400'
                    }`} />
                    <span className="font-medium text-slate-700">{s.action}</span>
                    <span className="text-slate-500">— {s.reason}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 等待人工审核 */}
      {selectedTask && selectedTask.status === 'AWAITING_HUMAN' && (
        <div className="card border-yellow-300 bg-yellow-50">
          <h2 className="text-base font-semibold text-yellow-700 mb-2">👤 等待人工审核</h2>
          <p className="text-sm text-yellow-600">
            该内容已被标记为需要人工审核。请前往 <a href="/review" className="underline">人工审核页面</a> 处理。
          </p>
        </div>
      )}
    </div>
  )
}
