import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './components/Dashboard'
import ModerationPanel from './components/ModerationPanel'
import HistoryList from './components/HistoryList'
import HistoryDetailPage from './components/HistoryDetailPage'
import SystemMonitor from './components/SystemMonitor'
import HumanReviewPanel from './components/HumanReviewPanel'
import OptimizationMonitor from './components/OptimizationMonitor'
import AsyncModeration from './components/AsyncModeration'
import TechLab from './components/TechLab'
import PolicyManager from './components/PolicyManager'
import DatasetManagerPage from './components/DatasetManagerPage'
import LogViewer from './components/LogViewer'
import SkillManager from './components/SkillManager'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/moderate" element={<ModerationPanel />} />
        <Route path="/review" element={<HumanReviewPanel />} />
        <Route path="/optimization" element={<OptimizationMonitor />} />
        <Route path="/skills" element={<SkillManager />} />
        <Route path="/history" element={<HistoryList />} />
        <Route path="/history/:contentId" element={<HistoryDetailPage />} />
        <Route path="/system" element={<SystemMonitor />} />
        <Route path="/async" element={<AsyncModeration />} />
        <Route path="/lab" element={<TechLab />} />
        <Route path="/policies" element={<PolicyManager />} />
        <Route path="/dataset" element={<DatasetManagerPage />} />
        <Route path="/logs" element={<LogViewer />} />
      </Routes>
    </Layout>
  )
}
