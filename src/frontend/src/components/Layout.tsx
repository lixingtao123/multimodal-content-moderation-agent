import { useLocation, useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'

const NAV_ITEMS = [
  { path: '/dashboard', label: '数据看板', icon: '📊' },
  { path: '/moderate', label: '内容审核', icon: '🛡️' },
  { path: '/async', label: '异步审核', icon: '⚡' },
  { path: '/review', label: '人工审核', icon: '👤' },
  { path: '/optimization', label: '优化监控', icon: '🧪' },
  { path: '/skills', label: 'Skill 管理', icon: '🧠' },
  { path: '/history', label: '审核历史', icon: '📋' },
  { path: '/logs', label: '运行日志', icon: '🧾' },
  { path: '/lab', label: '技术实验室', icon: '🔬' },
  { path: '/dataset', label: '数据集', icon: '🗂️' },
  { path: '/policies', label: '策略管理', icon: '📐' },
  { path: '/system', label: '系统状态', icon: '⚙️' },
]

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="sidebar flex flex-col">
        {/* Logo */}
        <div className="px-5 py-6 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white text-lg font-bold shadow-lg shadow-indigo-500/25">
              S
            </div>
            <div>
              <h1 className="text-white text-sm font-bold leading-tight">智能风控</h1>
              <p className="text-slate-400 text-xs">Content Moderation</p>
            </div>
          </div>
        </div>

        {/* Nav Links */}
        <nav className="flex-1 py-4 space-y-0.5">
          {NAV_ITEMS.map((item) => (
            <a
              key={item.path}
              className={`sidebar-link ${location.pathname === item.path ? 'active' : ''}`}
              onClick={() => navigate(item.path)}
            >
              <span className="icon">{item.icon}</span>
              <span>{item.label}</span>
            </a>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-white/10">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
            系统运行中
          </div>
          <p className="text-xs text-slate-600 mt-1">v3.3.0</p>
        </div>
      </aside>

      {/* Main Content */}
      <div className="main-content flex-1">
        {children}
      </div>
    </div>
  )
}
