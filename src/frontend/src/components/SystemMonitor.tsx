import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'
import type { AdminStats, HealthStatus, Capabilities } from '../types'
import { formatTime } from '../utils/time'

export default function SystemMonitor() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [loading, setLoading] = useState(true)
  const [backendLog, setBackendLog] = useState<string[]>([])

  const loadData = useCallback(async () => {
    const [h, s, c] = await Promise.all([
      api.getHealth().catch((e) => { console.error('getHealth failed:', e); return null }),
      api.getStats().catch((e) => { console.error('getStats failed:', e); return null }),
      api.getCapabilities().catch(() => null),
    ])
    if (h) setHealth(h as HealthStatus)
    if (s) setStats(s as AdminStats)
    if (c) setCapabilities(c as Capabilities)
    setLoading(false)
  }, [])

  useEffect(() => {
    loadData()
    const timer = setInterval(loadData, 10000)
    return () => clearInterval(timer)
  }, [loadData])

  // 日志轮询 — 随 loadData 一起刷新（R22·C11: 统一走 api 封装，不再裸 fetch）
  useEffect(() => {
    api.getRecentLogs(5)
      .then(d => {
        const items = d.items || []
        setBackendLog(items.slice(0, 5).map(l =>
          `[${formatTime(new Date().toISOString())}] ${l.content_id} ${l.total_duration_ms.toFixed(0)}ms`
        ))
      })
      .catch(() => setBackendLog(['无法获取日志']))
  }, [stats])  // stats 更新时同步刷新日志

  const allHealthy = health?.status === 'ok'

  // 端口优先取后端 capabilities 的权威值，其次 VITE_ 环境变量（vite build 注入），最后回退默认值
  const DEFAULT_PORTS = {
    backend: '18080', frontend: '13000', pg: '15432',
    redis: '16379', chroma: '18001', funasr: '15001',
  }
  const portOf = (key: keyof typeof DEFAULT_PORTS): string =>
    String(capabilities?.ports?.[key] ?? import.meta.env[`VITE_${key.toUpperCase()}_PORT`] ?? DEFAULT_PORTS[key])

  const dependencyNames: Record<string, string> = {
    postgres: 'PostgreSQL',
    redis: 'Redis',
    chromadb: 'ChromaDB',
    funasr: 'FunASR',
  }

  const depDetails: Record<string, { port: string; desc: string; icon: string }> = {
    postgres: { port: portOf('pg'), desc: '审核记录持久化存储', icon: '🗄️' },
    redis: { port: portOf('redis'), desc: '短期记忆 + LLM 缓存 + 任务队列', icon: '⚡' },
    chromadb: { port: portOf('chroma'), desc: '历史案例向量检索 (bge-small-zh-v1.5)', icon: '🧠' },
    funasr: { port: portOf('funasr'), desc: '语音转文本 (SenseVoiceSmall + GPU)', icon: '🎙️' },
  }

  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <h2 className="text-xl font-bold text-slate-800">系统状态</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[1,2,3,4].map(i => (
            <div key={i} className="card p-5 animate-pulse">
              <div className="h-4 bg-slate-200 rounded w-20 mb-3" />
              <div className="h-3 bg-slate-200 rounded w-32" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-800">系统状态</h2>
          <p className="text-sm text-slate-500 mt-1">基础设施 + 依赖服务运行状态</p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-semibold ${
            allHealthy ? 'bg-green-50 text-green-700' : 'bg-yellow-50 text-yellow-700'
          }`}>
            <span className={`w-2.5 h-2.5 rounded-full ${allHealthy ? 'bg-green-400 animate-pulse' : 'bg-yellow-400 animate-pulse'}`} />
            {allHealthy ? '全部正常' : '部分降级'}
          </span>
          <button onClick={loadData} className="btn btn-secondary text-sm py-2">
            🔄 刷新
          </button>
        </div>
      </div>

      {/* Service Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {health && Object.entries(health.dependencies).map(([name, ok]) => (
          <div key={name} className={`card p-5 border-l-4 ${ok ? 'border-l-green-500' : 'border-l-red-500'}`}>
            <div className="flex items-start justify-between mb-3">
              <span className="text-2xl">{depDetails[name]?.icon || '📦'}</span>
              <span className={`badge ${ok ? 'badge-pass' : 'badge-reject'}`}>
                {ok ? '正常' : '异常'}
              </span>
            </div>
            <h3 className="text-sm font-bold text-slate-800">{dependencyNames[name] || name}</h3>
            <p className="text-xs text-slate-500 mt-1">{depDetails[name]?.desc || ''}</p>
            <div className="flex items-center gap-3 mt-3 text-xs text-slate-400">
              <span>端口: {depDetails[name]?.port || '-'}</span>
              <span className={`w-2 h-2 rounded-full ${ok ? 'bg-green-400' : 'bg-red-400'}`} />
            </div>
          </div>
        ))}
      </div>

      {/* System Info + Stats */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Backend Info — from /api/v1/eval/capabilities */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-2">
            🖥️ 后端服务信息
          </h3>
          <div className="space-y-3">
            {capabilities ? (
              <>
                <InfoRow label="文本模型" value={capabilities.models?.text || '-'} />
                <InfoRow label="视觉模型" value={capabilities.models?.vision || '-'} />
                <InfoRow label="嵌入模型" value={capabilities.models?.embedding || '-'} />
                <InfoRow label="Reranker" value={capabilities.models?.reranker || '-'} />
                <InfoRow label="语音识别" value={capabilities.models?.stt || '-'} />
                <InfoRow label="文本 Agent" value={capabilities.agents?.text?.split(' — ')[0] || '-'} />
                <InfoRow label="图片 Agent" value={capabilities.agents?.image?.split(' — ')[0] || '-'} />
                <InfoRow label="API 端口" value={portOf('backend')} />
                <InfoRow
                  label="API 文档"
                  value={<a href={`http://localhost:${portOf('backend')}/docs`} target="_blank" className="text-indigo-600 hover:underline">Swagger UI →</a>}
                />
              </>
            ) : (
              <>
                <InfoRow label="框架" value="FastAPI + Uvicorn" />
                <InfoRow label="Agent 引擎" value="LangGraph StateGraph" />
                <InfoRow label="LLM 供应商" value="DeepSeek (deepseek-chat)" />
                <InfoRow label="多模态 VL" value="Qwen3-VL (阿里云 MaaS)" />
                <InfoRow label="语音识别" value="FunASR SenseVoiceSmall" />
                <InfoRow label="API 端口" value={portOf('backend')} />
                <InfoRow
                  label="API 文档"
                  value={<a href={`http://localhost:${portOf('backend')}/docs`} target="_blank" className="text-indigo-600 hover:underline">Swagger UI →</a>}
                />
              </>
            )}
          </div>
        </div>

        {/* Runtime Stats */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-2">
            📈 运行时统计
          </h3>
          {stats ? (
            <div className="space-y-3">
              <StatRow label="总审核量" value={stats.total_moderated.toLocaleString()} />
              <StatRow label="PASS 数量" value={(stats.by_decision.PASS || 0).toLocaleString()} color="text-green-600" />
              <StatRow label="REVIEW 数量" value={(stats.by_decision.REVIEW || 0).toLocaleString()} color="text-yellow-600" />
              <StatRow label="REJECT 数量" value={(stats.by_decision.REJECT || 0).toLocaleString()} color="text-red-600" />
              <StatRow label="平均风险分" value={stats.avg_risk_score.toFixed(3)} />
              <StatRow label="平均处理时间" value={`${stats.avg_processing_time_ms.toFixed(0)}ms`} />
              <StatRow
                label="通过率"
                value={`${stats.total_moderated > 0 ? ((stats.by_decision.PASS || 0) / stats.total_moderated * 100).toFixed(1) : 0}%`}
              />
            </div>
          ) : (
            <div className="text-center py-8 text-slate-400 text-sm">暂无数据</div>
          )}
        </div>
      </div>

      {/* Recent Backend Activity */}
      <div className="card p-5">
        <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
          📜 最近后端活动
        </h3>
        <div className="bg-slate-900 rounded-lg p-4 font-mono text-xs text-green-400 max-h-40 overflow-y-auto space-y-0.5">
          {backendLog.map((line, i) => (
            <div key={i}>
              <span className="text-slate-500">{line.substring(0, 10)}</span>
              <span className="text-green-300">{line.substring(10)}</span>
            </div>
          ))}
          {backendLog.length === 0 && (
            <div className="text-slate-500">等待后端活动...</div>
          )}
        </div>
      </div>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-700 font-medium">{value}</span>
    </div>
  )
}

function StatRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 text-sm border-b border-slate-50 last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className={`font-semibold font-mono ${color || 'text-slate-700'}`}>{value}</span>
    </div>
  )
}
