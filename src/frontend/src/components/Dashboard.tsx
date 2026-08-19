import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'
import type { AdminStats, LogEntry, HealthStatus, StatsOverview } from '../types'
import { formatTime } from '../utils/time'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
  AreaChart, Area, LineChart, Line,
} from 'recharts'

const DECISION_COLORS: Record<string, string> = {
  PASS: '#10b981',
  REVIEW: '#f59e0b',
  REJECT: '#ef4444',
}

const PIE_COLORS = ['#6366f1', '#ef4444', '#f59e0b', '#10b981', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#14b8a6']

const VIO_LABELS: Record<string, string> = {
  advertisement: '广告',
  harassment: '骚扰',
  violence: '暴力',
  false_info: '虚假信息',
  porn: '色情',
  politics: '政治',
  illegal: '违法',
  phishing: '钓鱼',
  terrorism: '恐怖主义',
  bulk_generation: '批量生成',
  BULK_GENERATION: '批量生成',
  KEYWORD_VARIANT: '关键词变体',
  PHISHING: '钓鱼',
}

export default function Dashboard() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [overview, setOverview] = useState<StatsOverview | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [loading, setLoading] = useState(true)

  const loadAll = useCallback(async () => {
    // 每个 API 独立容错：一个失败不影响其他
    const [s, ov, l, h] = await Promise.all([
      api.getStats().catch((e) => { console.error('getStats failed:', e); return null }),
      api.getStatsOverview().catch((e) => { console.error('getStatsOverview failed:', e); return null }),
      api.getRecentLogs(20).catch((e) => { console.error('getRecentLogs failed:', e); return null }),
      api.getHealth().catch((e) => { console.error('getHealth failed:', e); return null }),
    ])
    if (s) setStats(s as AdminStats)
    if (ov) setOverview(ov as StatsOverview)
    if (l) setLogs((l as { items: LogEntry[] }).items || [])
    if (h) setHealth(h as HealthStatus)
    setLoading(false)
  }, [])

  useEffect(() => {
    loadAll()
    const timer = setInterval(loadAll, 15000)
    return () => clearInterval(timer)
  }, [loadAll])

  if (loading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <h2 className="text-xl font-bold text-slate-800">数据看板</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {[1,2,3,4].map(i => (
            <div key={i} className="card p-5 animate-pulse">
              <div className="h-4 bg-slate-200 rounded w-16 mb-3" />
              <div className="h-8 bg-slate-200 rounded w-24" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  const decisionData = stats ? Object.entries(stats.by_decision).map(([k, v]) => ({
    name: k === 'PASS' ? '通过' : k === 'REVIEW' ? '复核' : k === 'REJECT' ? '拒绝' : k,
    value: v,
    fill: DECISION_COLORS[k] || '#94a3b8',
  })) : []

  const typeData = stats ? Object.entries(stats.by_type).map(([k, v]) => ({
    name: k === 'text' ? '文本' : k === 'image' ? '图片' : k === 'audio' ? '语音' : k === 'video' ? '视频' : k,
    value: v,
  })) : []

  // v4.0: 违规类型分布 (from overview)
  const violationData = overview?.violation_distribution?.map(v => ({
    name: VIO_LABELS[v.violation_type] || v.violation_type,
    value: v.cnt,
  })) || []

  // v4.0: 7天趋势 (from overview)
  const trendData = overview?.daily_trend?.map(d => ({
    day: d.day.slice(5), // MM-DD
    total: d.total,
    pass: d.pass_count,
    review: d.review_count,
    reject: d.reject_count,
    avgRisk: d.avg_risk,
  })) || []

  // v4.0: Token 消耗 (from overview)
  const tokenEst = overview?.token_estimate

  const recentLogsData = logs.slice(0, 12).reverse().map(l => ({
    time: formatTime(l.start_time),
    duration: l.total_duration_ms,
    steps: l.step_count,
  }))

  const passRate = stats && stats.total_moderated > 0
    ? ((stats.by_decision.PASS || 0) / stats.total_moderated * 100).toFixed(1)
    : '0'

  // 动态计算 trend（基于当前数据阈值，未来可对比历史周期）
  const reviewCount = stats?.total_moderated || 0
  const totalTrend = reviewCount >= 100 ? '📈 活跃' : reviewCount >= 10 ? '📊 正常' : '🆕 初始'
  const passRateNum = Number(passRate)
  const passTrend = passRateNum >= 80 ? '✅ 良好' : passRateNum >= 50 ? '⚠️ 一般' : '🔴 偏低'
  const avgRisk = stats?.avg_risk_score || 0
  const riskTrend = avgRisk > 0.5 ? '🔴 高风险' : avgRisk > 0.3 ? '⚠️ 中等' : '✅ 低风险'
  const avgTime = stats?.avg_processing_time_ms || 0
  const timeTrend = avgTime > 5000 ? '🐢 较慢' : avgTime > 2000 ? '⚡ 正常' : '🚀 快速'

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-800">数据看板</h2>
          <p className="text-sm text-slate-500 mt-1">实时监控内容审核系统运行状态</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-2 text-sm text-slate-500">
            <span className={`w-2.5 h-2.5 rounded-full ${health?.status === 'ok' ? 'bg-green-400 animate-pulse' : 'bg-yellow-400 animate-pulse'}`} />
            {health?.status === 'ok' ? '全部健康' : '部分降级'}
          </span>
          <button onClick={loadAll} className="btn btn-secondary text-sm py-2 px-4">
            🔄 刷新
          </button>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="总审核量" value={reviewCount.toLocaleString()}
          icon="📝" trend={totalTrend} trendUp
          color="indigo"
        />
        <StatCard
          title="通过率" value={`${passRate}%`}
          icon="✅" trend={passTrend}
          trendUp={passRateNum >= 70}
          color="green"
        />
        <StatCard
          title="平均风险分" value={avgRisk.toFixed(3)}
          icon="⚠️"
          trend={riskTrend}
          trendUp={avgRisk <= 0.3}
          color={avgRisk > 0.4 ? 'yellow' : 'blue'}
        />
        <StatCard
          title="平均耗时" value={`${avgTime.toFixed(0)}ms`}
          icon="⚡"
          trend={timeTrend}
          trendUp={avgTime <= 3000}
          color="purple"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Decision Distribution */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">决策分布</h3>
          <div className="flex items-center gap-6">
            <div style={{ width: 180, height: 180 }}>
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={decisionData}
                    cx="50%" cy="50%" innerRadius={45} outerRadius={75}
                    paddingAngle={3} dataKey="value"
                  >
                    {decisionData.map((d, i) => (
                      <Cell key={i} fill={d.fill} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="flex-1 space-y-3">
              {decisionData.map(d => (
                <div key={d.name} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="w-3 h-3 rounded-full" style={{ background: d.fill }} />
                    <span className="text-sm text-slate-600">{d.name}</span>
                  </div>
                  <span className="text-sm font-semibold text-slate-800">{d.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Content Type Distribution */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">内容类型分布</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={typeData} barSize={40}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="name" tick={{ fontSize: 12 }} stroke="#94a3b8" />
              <YAxis tick={{ fontSize: 12 }} stroke="#94a3b8" />
              <Tooltip />
              <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                {typeData.map((_, i) => (
                  <Cell key={i} fill={PIE_COLORS[i]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* v4.0: 违规类型分布 + 7天趋势 + Token 消耗 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 违规类型分布 */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">违规类型分布 (7天)</h3>
          {violationData.length > 0 ? (
            <div className="flex items-center gap-4">
              <div style={{ width: 150, height: 150 }}>
                <ResponsiveContainer>
                  <PieChart>
                    <Pie
                      data={violationData}
                      cx="50%" cy="50%" innerRadius={35} outerRadius={60}
                      paddingAngle={2} dataKey="value"
                    >
                      {violationData.map((_, i) => (
                        <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="flex-1 space-y-1.5 max-h-[150px] overflow-y-auto">
                {violationData.slice(0, 8).map((d, i) => (
                  <div key={d.name} className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                      <span className="text-slate-600 truncate max-w-[80px]">{d.name}</span>
                    </div>
                    <span className="text-slate-800 font-semibold">{d.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="text-center py-8 text-slate-400 text-sm">暂无违规数据</div>
          )}
        </div>

        {/* 7天审核趋势 */}
        <div className="lg:col-span-2 card p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">7天审核趋势</h3>
          {trendData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} stroke="#94a3b8" />
                <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" />
                <Tooltip />
                <Line type="monotone" dataKey="total" stroke="#6366f1" strokeWidth={2} dot={{ r: 3 }} name="总量" />
                <Line type="monotone" dataKey="review" stroke="#f59e0b" strokeWidth={1.5} dot={{ r: 2 }} name="复核" />
                <Line type="monotone" dataKey="reject" stroke="#ef4444" strokeWidth={1.5} dot={{ r: 2 }} name="拒绝" />
                <Line type="monotone" dataKey="pass" stroke="#10b981" strokeWidth={1.5} dot={{ r: 2 }} name="通过" />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-center py-12 text-slate-400 text-sm">暂无趋势数据</div>
          )}
        </div>
      </div>


      {/* Recent Activity + Health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Processing Time Trend */}
        <div className="lg:col-span-2 card p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">最近审核耗时趋势 (ms)</h3>
          {recentLogsData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={recentLogsData}>
                <defs>
                  <linearGradient id="colorDur" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="time" tick={{ fontSize: 11 }} stroke="#94a3b8" />
                <YAxis tick={{ fontSize: 11 }} stroke="#94a3b8" />
                <Tooltip />
                <Area type="monotone" dataKey="duration" stroke="#6366f1" fill="url(#colorDur)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="text-center py-12 text-slate-400 text-sm">暂无数据，提交审核后显示</div>
          )}
        </div>

        {/* Health Status */}
        <div className="card p-5">
          <h3 className="text-sm font-semibold text-slate-700 mb-4">服务健康状态</h3>
          {health ? (
            <div className="space-y-3">
              {Object.entries(health.dependencies).map(([name, ok]) => (
                <div key={name} className="flex items-center justify-between py-2 px-3 rounded-lg bg-slate-50">
                  <span className="text-sm text-slate-600">
                    {name === 'postgres' ? 'PostgreSQL' :
                     name === 'redis' ? 'Redis' :
                     name === 'chromadb' ? 'ChromaDB' :
                     name === 'funasr' ? 'FunASR' : name}
                  </span>
                  <span className={`badge ${ok ? 'badge-pass' : 'badge-reject'}`}>
                    {ok ? '正常' : '异常'}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-slate-400 text-sm">无法获取健康状态</div>
          )}
        </div>
      </div>

      {/* Recent Logs Table */}
      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-700">最近审核记录</h3>
          <span className="text-xs text-slate-400">{logs.length} 条</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-slate-50">
              <tr>
                <th className="text-left px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">Content ID</th>
                <th className="text-left px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">类型</th>
                <th className="text-left px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">步骤</th>
                <th className="text-left px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">耗时</th>
                <th className="text-left px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">时间</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {logs.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center py-8 text-slate-400 text-sm">
                    暂无审核记录
                  </td>
                </tr>
              ) : (
                logs.slice(0, 10).map((log) => (
                  <tr key={log.content_id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-5 py-3 text-sm font-mono text-slate-600">{log.content_id}</td>
                    <td className="px-5 py-3">
                      <span className="badge badge-info">{log.content_type}</span>
                    </td>
                    <td className="px-5 py-3 text-sm text-slate-600">{log.step_count}</td>
                    <td className="px-5 py-3 text-sm text-slate-600">{log.total_duration_ms.toFixed(0)}ms</td>
                    <td className="px-5 py-3 text-sm text-slate-400">{formatTime(log.start_time)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function StatCard({ title, value, icon, trend, trendUp, color }: {
  title: string; value: string; icon: string; trend: string; trendUp: boolean; color: string
}) {
  const gradients: Record<string, string> = {
    indigo: 'from-indigo-500 to-blue-500',
    green: 'from-emerald-500 to-teal-500',
    yellow: 'from-amber-500 to-orange-500',
    blue: 'from-sky-500 to-cyan-500',
    purple: 'from-violet-500 to-purple-500',
  }

  return (
    <div className="card p-5 hover:shadow-lg transition-all duration-300 group">
      <div className="flex items-start justify-between mb-3">
        <span className="text-2xl">{icon}</span>
        <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${gradients[color] || gradients.indigo} opacity-10 group-hover:opacity-20 transition-opacity`} />
      </div>
      <p className="text-xs text-slate-500 font-medium mb-1">{title}</p>
      <p className="text-2xl font-bold text-slate-800 mb-1">{value}</p>
      <span className={`text-xs ${trendUp ? 'text-emerald-600' : 'text-amber-600'}`}>
        {trend}
      </span>
    </div>
  )
}
