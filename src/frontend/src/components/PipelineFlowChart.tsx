import { useState } from 'react'
import type { PipelineLog, PipelineStep } from '../types'
import { formatTime } from '../utils/time'

// ── 节点配置：识别 pipeline 中的关键节点 ──

interface FlowNode {
  id: string
  label: string
  icon: string
  step?: PipelineStep
  children?: FlowNode[]
  isParallel?: boolean
}

const NODE_PATTERNS: { pattern: string; label: string; icon: string; category: string }[] = [
  { pattern: 'GATEWAY', label: '网关', icon: '🚪', category: 'entry' },
  { pattern: 'SUPERVISOR', label: 'Supervisor', icon: '🧠', category: 'orchestration' },
  { pattern: 'FILE_AGENT', label: 'FileAgent', icon: '📁', category: 'orchestration' },
  { pattern: 'TEXT_AGENT', label: 'TextAgent', icon: '📝', category: 'agent' },
  { pattern: 'IMAGE_AGENT', label: 'ImageAgent', icon: '🖼️', category: 'agent' },
  { pattern: 'AUDIO_AGENT', label: 'AudioAgent', icon: '🎤', category: 'agent' },
  { pattern: 'VIDEO_AGENT', label: 'VideoAgent', icon: '🎬', category: 'agent' },
  { pattern: 'AGENTIC_RAG', label: 'RAG检索', icon: '🔍', category: 'rag' },
  { pattern: 'GRAPH_RAG', label: 'GraphRAG', icon: '🔗', category: 'rag' },
  { pattern: 'RISK_ASSESS', label: '风险评估', icon: '📊', category: 'decision' },
  { pattern: 'HUMAN_REVIEW', label: '人工审核', icon: '👤', category: 'decision' },
  { pattern: 'BLACKHAT', label: '黑产检测', icon: '🕵️', category: 'agent' },
  { pattern: 'DEBATE', label: '辩论面板', icon: '⚖️', category: 'decision' },
  { pattern: 'REFLEXION', label: '自我反思', icon: '🔄', category: 'decision' },
  { pattern: 'TRIAGE', label: '分诊台', icon: '🚦', category: 'orchestration' },
  { pattern: 'LANE_ROUTE', label: '车道路由', icon: '🚀', category: 'orchestration' },
  { pattern: 'FAST_LANE', label: '快车道', icon: '⚡', category: 'agent' },
  { pattern: 'BRAIN', label: '大脑仲裁', icon: '🧠', category: 'decision' },
  { pattern: 'TERMINATION', label: '终止双签', icon: '🛑', category: 'decision' },
  { pattern: 'HUMAN_RESUME', label: '人工恢复', icon: '▶️', category: 'decision' },
  { pattern: 'HUMAN_ANNOTATE', label: '人工标注', icon: '🏷️', category: 'decision' },
  { pattern: 'RISK_VOTE', label: '意见投票', icon: '🗳️', category: 'decision' },
  { pattern: 'EVAL_RUN', label: '评测', icon: '🧪', category: 'other' },
  { pattern: 'RED_TEAM', label: '红队测试', icon: '🎯', category: 'other' },
  { pattern: 'PLANNER', label: 'Planner', icon: '🗺️', category: 'orchestration' },
]

function matchNode(step: PipelineStep): { label: string; icon: string; category: string } | null {
  const nodeName = step.node.replace(/^\S+\s+/, '').trim() || step.node
  for (const np of NODE_PATTERNS) {
    if (step.node.includes(np.pattern) || nodeName.includes(np.pattern)) {
      return { label: np.label, icon: np.icon, category: np.category }
    }
  }
  // Fallback: parse from the node string itself (removing emoji prefix)
  const clean = nodeName.replace(/^[^\w一-鿿]+/, '').trim()
  return { label: clean || step.node, icon: '⚙️', category: 'other' }
}

// ── 构建流程拓扑 ──

function buildFlowGraph(steps: PipelineStep[]): FlowNode[] {
  if (!steps.length) return []

  const nodes: FlowNode[] = []
  const agentSteps: FlowNode[] = []
  const ragSteps: FlowNode[] = []
  const decisionSteps: FlowNode[] = []

  for (const step of steps) {
    const info = matchNode(step)
    if (!info) continue
    const node: FlowNode = {
      id: `step-${step.seq}`,
      label: info.label,
      icon: info.icon,
      step,
    }

    if (info.category === 'entry') {
      nodes.push(node)
    } else if (info.category === 'orchestration') {
      nodes.push(node)
    } else if (info.category === 'agent') {
      // Deduplicate multiple image/video agents
      const existing = agentSteps.find(n => n.label === info.label)
      if (existing && (info.label === 'ImageAgent' || info.label === 'VideoAgent')) {
        // Keep the one with highest risk or duration
        const existingScore = existing.step?.duration_ms ?? 0
        const newScore = step.duration_ms ?? 0
        if (newScore > existingScore) {
          existing.step = step
          existing.id = `step-${step.seq}`
        }
      } else {
        agentSteps.push(node)
      }
    } else if (info.category === 'rag') {
      ragSteps.push(node)
    } else if (info.category === 'decision') {
      decisionSteps.push(node)
    }
  }

  // Count how many images/videos were processed
  const imageCount = steps.filter(s => s.node.includes('IMAGE_AGENT')).length
  const videoCount = steps.filter(s => s.node.includes('VIDEO_AGENT')).length
  const audioCount = steps.filter(s => s.node.includes('AUDIO_AGENT')).length

  // Add count badges
  for (const node of agentSteps) {
    if (node.label === 'ImageAgent' && imageCount > 0) {
      node.label = `ImageAgent ×${imageCount}`
    }
    if (node.label === 'VideoAgent' && videoCount > 0) {
      node.label = `VideoAgent ×${videoCount}`
    }
    if (node.label === 'AudioAgent' && audioCount > 0) {
      node.label = `AudioAgent ×${audioCount}`
    }
  }

  // Agent nodes as parallel group
  if (agentSteps.length > 0) {
    nodes.push({
      id: 'parallel-agents',
      label: '多模态并行分析',
      icon: '⚡',
      children: agentSteps,
      isParallel: true,
    })
  }

  // RAG nodes
  nodes.push(...ragSteps)

  // Decision nodes
  nodes.push(...decisionSteps)

  return nodes
}

// ── 提取输出摘要 ──

function getOutputSummary(step: PipelineStep): string | null {
  if (!step.output) return null
  const o = step.output as Record<string, unknown>
  if (o.violation_type && o.violation_type !== 'none') {
    return `⚠️ ${o.violation_type} (risk: ${o.risk_score ?? '?'})`
  }
  if (o.risk_score !== undefined && Number(o.risk_score) > 0) {
    return `risk: ${Number(o.risk_score).toFixed(2)}`
  }
  if (o.decision) return `→ ${o.decision}`
  if (o.file_count !== undefined) return `${o.file_count} 文件, ${o.total_chars ?? 0} 字符`
  if (o.results !== undefined) return `${o.results} 条结果`
  if (o.related_types) return `关联类型: ${String(o.related_types).substring(0, 40)}...`
  return null
}

// ── 颜色 ──

function getNodeColor(category: string, step?: PipelineStep): string {
  if (step?.level === 'ERROR') return '#ef4444'
  if (step?.level === 'WARN') return '#f59e0b'
  const colors: Record<string, string> = {
    entry: '#6366f1',
    orchestration: '#8b5cf6',
    agent: '#3b82f6',
    rag: '#10b981',
    decision: '#f59e0b',
    other: '#94a3b8',
  }
  return colors[category] || '#94a3b8'
}

function getCategoryBg(category: string): string {
  const colors: Record<string, string> = {
    entry: '#eef2ff',
    orchestration: '#f5f3ff',
    agent: '#eff6ff',
    rag: '#ecfdf5',
    decision: '#fffbeb',
    other: '#f8fafc',
  }
  return colors[category] || '#f8fafc'
}

// ── 单节点组件 ──

function FlowNodeCard({
  node,
  isLast,
  onSelect,
  isSelected,
}: {
  node: FlowNode
  isLast: boolean
  onSelect: (n: FlowNode) => void
  isSelected: boolean
}) {
  const info = node.step ? matchNode(node.step) : null
  const category = info?.category || 'other'
  const color = getNodeColor(category, node.step)
  const summary = node.step ? getOutputSummary(node.step) : null

  return (
    <div className="flex items-start gap-0">
      {/* 节点主体 */}
      <div
        className={`relative flex items-center gap-3 px-4 py-3 rounded-xl border-2 cursor-pointer transition-all duration-200 min-w-[180px] ${
          isSelected ? 'shadow-lg scale-[1.02]' : 'shadow-sm hover:shadow-md'
        }`}
        style={{
          borderColor: isSelected ? color : `${color}40`,
          background: isSelected ? getCategoryBg(category) : '#fff',
        }}
        onClick={() => onSelect(node)}
      >
        {/* 图标 */}
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center text-lg shrink-0"
          style={{ background: `${color}18` }}
        >
          {node.icon}
        </div>
        {/* 标签 */}
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-700 whitespace-nowrap">{node.label}</div>
          {node.step && (
            <div className="text-xs text-slate-400 font-mono">
              {node.step.duration_ms > 0 ? `${node.step.duration_ms.toFixed(0)}ms` : '<1ms'}
            </div>
          )}
          {summary && (
            <div className="text-xs mt-0.5 truncate max-w-[200px]" style={{ color }}>
              {summary}
            </div>
          )}
        </div>
        {/* 详情指示器 */}
        {node.step && (
          <div className="text-slate-300 text-xs shrink-0">{isSelected ? '▼' : '▶'}</div>
        )}
      </div>

      {/* 连接线到下一个节点 */}
      {!isLast && (
        <div className="flex flex-col items-center shrink-0 mx-1 self-center">
          <div className="w-0.5 h-8 rounded" style={{ background: `${color}40` }} />
          <div
            className="w-0 h-0"
            style={{
              borderLeft: '5px solid transparent',
              borderRight: '5px solid transparent',
              borderTop: `6px solid ${color}40`,
            }}
          />
        </div>
      )}
    </div>
  )
}

// ── 并行节点组 ──

function ParallelGroup({
  node,
  onSelect,
  isSelected,
}: {
  node: FlowNode
  onSelect: (n: FlowNode) => void
  isSelected: boolean
}) {
  const children = node.children || []
  return (
    <div className="flex flex-col gap-2">
      {/* 并行标签 */}
      <div
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold self-start"
        style={{ background: '#eff6ff', color: '#3b82f6' }}
      >
        ⚡ {node.label}
        {children.length > 0 && (
          <span className="text-slate-400 font-normal">({children.length} 个Agent并行)</span>
        )}
      </div>
      {/* 并行节点 */}
      <div className="flex flex-wrap gap-3 ml-6">
        {children.map((child, i) => (
          <FlowNodeCard
            key={child.id}
            node={child}
            isLast={i === children.length - 1}
            onSelect={onSelect}
            isSelected={isSelected && child.id === (isSelected as unknown as string)}
          />
        ))}
      </div>
    </div>
  )
}

// ── 详情面板 ──

function StepDetailPanel({ step }: { step: PipelineStep }) {
  if (!step) return null
  const info = matchNode(step)
  const category = info?.category || 'other'
  const color = getNodeColor(category, step)

  return (
    <div
      className="rounded-xl border overflow-hidden animate-fade-in"
      style={{ borderColor: `${color}30`, background: `${getCategoryBg(category)}80` }}
    >
      {/* 头部 */}
      <div className="px-5 py-3 flex items-center justify-between" style={{ background: `${color}0d` }}>
        <div className="flex items-center gap-2">
          <span className="text-lg">{info?.icon || '⚙️'}</span>
          <span className="text-sm font-bold text-slate-700">{info?.label || step.node}</span>
          <span className="text-xs text-slate-400 font-mono">#{step.seq}</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span>耗时: <strong className="text-slate-700 font-mono">{step.duration_ms > 0 ? `${step.duration_ms.toFixed(0)}ms` : '<1ms'}</strong></span>
          <span>累计: <strong className="text-slate-700 font-mono">+{step.elapsed_ms.toFixed(0)}ms</strong></span>
        </div>
      </div>
      {/* 内容 */}
      <div className="px-5 py-4 grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* 输入 */}
        <div>
          <div className="text-xs font-semibold text-slate-500 mb-2 uppercase tracking-wide">📥 输入</div>
          {step.input && Object.keys(step.input).length > 0 ? (
            <pre className="text-xs text-slate-600 bg-white rounded-lg p-3 border border-slate-100 max-h-48 overflow-auto font-mono leading-relaxed whitespace-pre-wrap">
              {JSON.stringify(step.input, null, 2)}
            </pre>
          ) : (
            <p className="text-xs text-slate-400 italic">无输入数据</p>
          )}
        </div>
        {/* 输出 */}
        <div>
          <div className="text-xs font-semibold text-slate-500 mb-2 uppercase tracking-wide">📤 输出</div>
          {step.output && Object.keys(step.output as object).length > 0 ? (
            <pre className="text-xs text-slate-600 bg-white rounded-lg p-3 border border-slate-100 max-h-48 overflow-auto font-mono leading-relaxed whitespace-pre-wrap">
              {JSON.stringify(step.output, null, 2)}
            </pre>
          ) : (
            <p className="text-xs text-slate-400 italic">无输出数据</p>
          )}
        </div>
      </div>
    </div>
  )
}

// ── 主组件 ──

interface Props {
  pipeline: PipelineLog
}

export default function PipelineFlowChart({ pipeline }: Props) {
  const [selectedNode, setSelectedNode] = useState<FlowNode | null>(null)

  if (!pipeline.steps || pipeline.steps.length === 0) {
    return (
      <div className="text-center py-8">
        <div className="text-3xl mb-2 opacity-20">📋</div>
        <p className="text-sm text-slate-400">暂无 Pipeline 日志</p>
      </div>
    )
  }

  const graph = buildFlowGraph(pipeline.steps)
  const totalSteps = pipeline.steps.length
  const totalAgents = pipeline.steps.filter(s =>
    ['TEXT_AGENT', 'IMAGE_AGENT', 'AUDIO_AGENT', 'VIDEO_AGENT'].some(t => s.node.includes(t))
  ).length

  return (
    <div className="space-y-4">
      {/* 头部统计 */}
      <div className="flex items-center gap-4 text-xs text-slate-500 flex-wrap">
        <span>📋 <strong>{totalSteps}</strong> 个步骤</span>
        <span>🤖 <strong>{totalAgents}</strong> 个 Agent</span>
        <span>⏱ 总耗时 <strong className="text-slate-700">{pipeline.total_duration_ms.toFixed(0)}ms</strong></span>
        <span className="text-slate-300">|</span>
        <span className="text-slate-400">点击节点查看详情</span>
      </div>

      {/* 流程拓扑图 */}
      <div className="flex flex-wrap items-start gap-1 overflow-x-auto pb-4 pt-2">
        {graph.map((node, i) => {
          const isSelected = selectedNode?.id === node.id
          if (node.isParallel && node.children) {
            return (
              <div key={node.id} className="flex items-start gap-0">
                {i > 0 && (
                  <div className="flex flex-col items-center shrink-0 mx-1 self-center">
                    <div className="w-0.5 h-8 rounded" style={{ background: '#94a3b840' }} />
                    <div
                      className="w-0 h-0"
                      style={{
                        borderLeft: '5px solid transparent',
                        borderRight: '5px solid transparent',
                        borderTop: '6px solid #94a3b840',
                      }}
                    />
                  </div>
                )}
                <ParallelGroup
                  node={node}
                  onSelect={setSelectedNode}
                  isSelected={isSelected}
                />
                {i < graph.length - 1 && (
                  <div className="flex flex-col items-center shrink-0 mx-1 self-center">
                    <div className="w-0.5 h-8 rounded" style={{ background: '#94a3b840' }} />
                    <div
                      className="w-0 h-0"
                      style={{
                        borderLeft: '5px solid transparent',
                        borderRight: '5px solid transparent',
                        borderTop: '6px solid #94a3b840',
                      }}
                    />
                  </div>
                )}
              </div>
            )
          }
          return (
            <FlowNodeCard
              key={node.id}
              node={node}
              isLast={i === graph.length - 1}
              onSelect={setSelectedNode}
              isSelected={isSelected}
            />
          )
        })}
      </div>

      {/* 选中节点详情 */}
      {selectedNode?.step && (
        <div className="animate-fade-in">
          <StepDetailPanel step={selectedNode.step} />
        </div>
      )}
    </div>
  )
}
