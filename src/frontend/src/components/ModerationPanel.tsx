import { useState, useRef, useCallback } from 'react'
import { api } from '../api/client'
import type { ModerationResponse } from '../types'

const DECISION_CONFIG: Record<string, { label: string; className: string; icon: string }> = {
  PASS: { label: '通过', className: 'badge-pass', icon: '✓' },
  REVIEW: { label: '人工复核', className: 'badge-review', icon: '⚠' },
  REJECT: { label: '拒绝', className: 'badge-reject', icon: '✕' },
  UNKNOWN: { label: '未知', className: 'badge-info', icon: '?' },
}

const MODES = [
  { key: 'text' as const, label: '📝 文本', desc: '输入文本进行审核' },
  { key: 'image' as const, label: '🖼️ 图片', desc: '上传图片进行审核' },
  { key: 'audio' as const, label: '🎤 语音', desc: '上传音频进行审核' },
  { key: 'video' as const, label: '🎬 视频', desc: '上传视频进行审核' },
  { key: 'multi' as const, label: '📄 全模态', desc: '文本+多文件综合审核' },
]

export default function ModerationPanel() {
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [multiFiles, setMultiFiles] = useState<File[]>([])
  const [mode, setMode] = useState<'text' | 'image' | 'audio' | 'video' | 'multi'>('text')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ModerationResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = async () => {
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      let res: ModerationResponse
      switch (mode) {
        case 'text':
          if (!text.trim()) throw new Error('请输入审核文本')
          res = await api.moderateText(text) as ModerationResponse
          break
        case 'image':
          if (!file) throw new Error('请选择图片文件')
          res = await api.moderateImage(file) as ModerationResponse
          break
        case 'audio':
          if (!file) throw new Error('请选择音频文件')
          res = await api.moderateAudio(file) as ModerationResponse
          break
        case 'video':
          if (!file) throw new Error('请选择视频文件')
          res = await api.moderateVideo(file) as ModerationResponse
          break
        case 'multi':
          if (!text.trim() && multiFiles.length === 0) throw new Error('请输入文本或上传文件')
          res = await api.moderateMultiModal(text, multiFiles) as ModerationResponse
          break
        default:
          throw new Error('未知审核模式')
      }
      setResult(res)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '请求失败')
    } finally {
      setLoading(false)
    }
  }

  const handleFileDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f) setFile(f)
  }, [])

  const acceptTypes = {
    text: undefined,
    image: 'image/*',
    audio: 'audio/*',
    video: 'video/*',
    multi: undefined,
  }

  return (
    <div className="space-y-6 animate-fade-in">
      <div>
        <h2 className="text-xl font-bold text-slate-800">内容审核</h2>
        <p className="text-sm text-slate-500 mt-1">提交内容进行多模态智能审核</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Input Panel */}
        <div className="lg:col-span-3 space-y-4">
          {/* Mode Selector */}
          <div className="card p-1.5 flex gap-1 bg-slate-50">
            {MODES.map((m) => (
              <button
                key={m.key}
                onClick={() => { setMode(m.key); setResult(null); setError(null); setFile(null); setMultiFiles([]); setText('') }}
                className={`flex-1 py-3 px-3 rounded-lg text-sm font-medium transition-all duration-200 ${
                  mode === m.key
                    ? 'bg-white text-indigo-600 shadow-sm'
                    : 'text-slate-500 hover:text-slate-700'
                }`}
                title={m.desc}
              >
                {m.label}
              </button>
            ))}
          </div>

          {/* Content Input */}
          <div className="card p-6">
            {mode === 'text' && (
              <div className="space-y-3">
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder="请输入待审核的文本内容...&#10;&#10;支持长文本输入，系统将自动分析违规风险"
                  rows={8}
                  className="input resize-none font-sans leading-relaxed"
                />
                <div className="flex items-center justify-between">
                  <span className="text-xs text-slate-400">{text.length} 字符</span>
                  {text.length > 500 && (
                    <span className="text-xs text-amber-500">长文本可能增加审核时间</span>
                  )}
                </div>
              </div>
            )}

            {mode === 'multi' && (
              <div className="space-y-4">
                {/* 文本输入 */}
                <div>
                  <label className="text-xs font-medium text-slate-500 mb-1 block">文本内容 (可选)</label>
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    placeholder="输入文字说明或补充信息..."
                    rows={4}
                    className="input resize-none font-sans leading-relaxed"
                  />
                  <span className="text-xs text-slate-400">{text.length} 字符</span>
                </div>
                {/* 文件上传区 */}
                <div>
                  <label className="text-xs font-medium text-slate-500 mb-2 block">
                    上传文件 (PDF / Word / TXT / 图片，支持多文件)
                  </label>
                  <div
                    className={`relative border-2 border-dashed rounded-xl p-6 text-center transition-all cursor-pointer ${
                      dragOver ? 'border-indigo-400 bg-indigo-50' :
                      multiFiles.length > 0 ? 'border-green-400 bg-green-50' :
                      'border-slate-300 hover:border-indigo-300 hover:bg-slate-50'
                    }`}
                    onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={(e) => {
                      e.preventDefault()
                      setDragOver(false)
                      const newFiles = Array.from(e.dataTransfer.files)
                      setMultiFiles(prev => [...prev, ...newFiles])
                    }}
                    onClick={() => inputRef.current?.click()}
                  >
                    <input
                      ref={inputRef}
                      type="file"
                      multiple
                      onChange={(e) => {
                        const newFiles = Array.from(e.target.files || [])
                        setMultiFiles(prev => [...prev, ...newFiles])
                      }}
                      accept=".pdf,.doc,.docx,.txt,.md,.csv,.json,.xml,.html,.log,.py,.js,.ts,.java,.go,.rs,.cpp,.c,.h,.yaml,.yml,.toml,.ini,.cfg,.conf,image/*"
                      className="hidden"
                    />
                    <div className="text-3xl mb-2">{dragOver ? '📥' : '📤'}</div>
                    <p className="text-sm text-slate-500">
                      {dragOver ? '释放文件以上传' : '拖拽文件到此处，或点击选择'}
                    </p>
                    <p className="text-xs text-slate-400 mt-1">PDF / Word / TXT / 图片 (单文件≤50MB)</p>
                  </div>
                </div>
                {/* 已上传文件列表 */}
                {multiFiles.length > 0 && (
                  <div className="space-y-2 max-h-48 overflow-y-auto">
                    {multiFiles.map((f, i) => (
                      <div key={i} className="flex items-center justify-between bg-slate-50 rounded-lg px-3 py-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-lg">{getFileIcon(f.name)}</span>
                          <div className="min-w-0">
                            <p className="text-sm text-slate-700 truncate">{f.name}</p>
                            <p className="text-xs text-slate-400">{(f.size / 1024).toFixed(1)} KB · {f.type || '未知'}</p>
                          </div>
                        </div>
                        <button
                          onClick={(e) => { e.stopPropagation(); setMultiFiles(prev => prev.filter((_, j) => j !== i)) }}
                          className="text-red-400 hover:text-red-600 text-sm shrink-0 ml-2"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {multiFiles.length > 0 && (
                  <button
                    onClick={() => setMultiFiles([])}
                    className="text-xs text-red-500 hover:underline"
                  >
                    清空所有文件
                  </button>
                )}
              </div>
            )}

            {mode !== 'text' && mode !== 'multi' && (
              <div
                className={`relative border-2 border-dashed rounded-xl p-10 text-center transition-all cursor-pointer ${
                  dragOver ? 'border-indigo-400 bg-indigo-50' :
                  file ? 'border-green-400 bg-green-50' :
                  'border-slate-300 hover:border-indigo-300 hover:bg-slate-50'
                }`}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleFileDrop}
                onClick={() => inputRef.current?.click()}
              >
                <input
                  ref={inputRef}
                  type="file"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  accept={acceptTypes[mode]}
                  className="hidden"
                />
                {file ? (
                  <div className="space-y-2">
                    <div className="text-4xl">📎</div>
                    <p className="text-sm font-medium text-slate-700">{file.name}</p>
                    <p className="text-xs text-slate-500">
                      {(file.size / 1024).toFixed(1)} KB · {file.type || '未知类型'}
                    </p>
                    <button
                      onClick={(e) => { e.stopPropagation(); setFile(null) }}
                      className="text-xs text-red-500 hover:underline"
                    >
                      移除文件
                    </button>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="text-4xl">{dragOver ? '📥' : '📤'}</div>
                    <p className="text-sm text-slate-500">
                      {dragOver ? '释放文件以上传' : `拖拽${mode === 'image' ? '图片' : mode === 'audio' ? '音频' : '视频'}文件到此处，或点击选择`}
                    </p>
                    <p className="text-xs text-slate-400">
                      支持 {mode === 'image' ? 'JPG/PNG/GIF/WebP' : mode === 'audio' ? 'WAV/MP3/FLAC/OGG' : 'MP4/WebM/AVI (≤100MB)'}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={loading}
            className="btn btn-primary w-full py-3.5 text-base"
          >
            {loading ? (
              <>
                <svg className="animate-spin w-5 h-5" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                AI 审核分析中...
              </>
            ) : (
              <>🚀 提交审核</>
            )}
          </button>

          {error && (
            <div className="card p-4 bg-red-50 border-red-200 animate-slide-in">
              <div className="flex items-start gap-3">
                <span className="text-red-500 text-lg">❌</span>
                <div>
                  <p className="text-sm font-medium text-red-800">审核失败</p>
                  <p className="text-sm text-red-600 mt-0.5">{error}</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Result Panel */}
        <div className="lg:col-span-2">
          <div className="card p-6 sticky top-6">
            <h3 className="text-sm font-semibold text-slate-700 mb-4 flex items-center gap-2">
              📋 审核结果
              {result && (
                <span className={`badge text-xs ${DECISION_CONFIG[result.final_decision]?.className || 'badge-info'}`}>
                  {DECISION_CONFIG[result.final_decision]?.label || result.final_decision}
                </span>
              )}
            </h3>

            {!result && !loading && (
              <div className="text-center py-16">
                <div className="text-5xl mb-4 opacity-30">🔍</div>
                <p className="text-sm text-slate-400">提交内容后查看审核结果</p>
                <p className="text-xs text-slate-300 mt-1">支持文本/图片/语音/视频/全模态</p>
              </div>
            )}

            {loading && (
              <div className="text-center py-16">
                <div className="w-12 h-12 border-3 border-indigo-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                <p className="text-sm text-slate-500">AI Agent 正在分析中...</p>
                <p className="text-xs text-slate-400 mt-1">这可能需要几秒钟</p>
              </div>
            )}

            {result && (
              <div className="space-y-5 animate-slide-in">
                {/* Risk Score Gauge */}
                <div className="text-center">
                  <div className="relative w-28 h-28 mx-auto">
                    <svg className="w-28 h-28 -rotate-90" viewBox="0 0 120 120">
                      <circle cx="60" cy="60" r="52" fill="none" stroke="#e2e8f0" strokeWidth="10" />
                      <circle
                        cx="60" cy="60" r="52" fill="none"
                        stroke={result.risk_score > 0.7 ? '#ef4444' : result.risk_score > 0.35 ? '#f59e0b' : '#10b981'}
                        strokeWidth="10" strokeLinecap="round"
                        strokeDasharray={`${result.risk_score * 327} 327`}
                        className="transition-all duration-1000"
                      />
                    </svg>
                    <div className="absolute inset-0 flex flex-col items-center justify-center">
                      <span className="text-2xl font-bold text-slate-800">{(result.risk_score * 100).toFixed(0)}</span>
                      <span className="text-xs text-slate-400">风险分</span>
                    </div>
                  </div>
                </div>

                {/* Decision Badge */}
                <div className={`text-center py-3 rounded-xl ${
                  result.final_decision === 'PASS' ? 'bg-green-50 border border-green-200' :
                  result.final_decision === 'REJECT' ? 'bg-red-50 border border-red-200' :
                  'bg-yellow-50 border border-yellow-200'
                }`}>
                  <p className={`text-lg font-bold ${
                    result.final_decision === 'PASS' ? 'text-green-700' :
                    result.final_decision === 'REJECT' ? 'text-red-700' :
                    'text-yellow-700'
                  }`}>
                    {DECISION_CONFIG[result.final_decision]?.icon} {DECISION_CONFIG[result.final_decision]?.label}
                  </p>
                  {result.cached && <p className="text-xs text-slate-400 mt-1">（缓存命中）</p>}
                </div>

                {/* Violation Types */}
                {result.violation_types.length > 0 && (
                  <div>
                    <p className="text-xs text-slate-500 mb-2 font-medium">违规类型</p>
                    <div className="flex flex-wrap gap-1.5">
                      {result.violation_types.map((t) => (
                        <span key={t} className="badge badge-reject text-xs">{t}</span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Suggestions */}
                {result.suggestions?.length > 0 && (
                  <div>
                    <p className="text-xs text-slate-500 mb-2 font-medium">处理建议</p>
                    <div className="space-y-2">
                      {result.suggestions.map((s, i) => (
                        <div key={i} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-slate-50">
                          <span className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                            s.priority === 'HIGH' ? 'bg-red-500' : s.priority === 'MEDIUM' ? 'bg-yellow-500' : 'bg-blue-500'
                          }`} />
                          <div>
                            <p className="text-sm font-medium text-slate-700">{s.action}</p>
                            <p className="text-xs text-slate-500 mt-0.5">{s.reason}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* 推理过程 */}
                {result.agent_reasoning && Object.keys(result.agent_reasoning).length > 0 && (
                  <div className="pt-2 border-t border-slate-100">
                    <p className="text-xs text-slate-500 mb-2 font-medium">🧠 分析过程</p>
                    <div className="space-y-3">
                      {Object.entries(result.agent_reasoning).map(([agent, reasoning]) => (
                        <div key={agent} className="bg-slate-50 rounded-lg p-3">
                          <div className="flex items-center gap-2 mb-1.5">
                            <span className="text-xs font-medium text-slate-600">{agent}</span>
                            <span className={`badge text-[10px] ${
                              reasoning.violation_type !== 'none' ? 'badge-reject' : 'badge-pass'
                            }`}>
                              {reasoning.violation_type !== 'none' ? reasoning.violation_type : '正常'}
                            </span>
                            <span className="text-xs text-slate-400">置信度: {(reasoning.confidence * 100).toFixed(0)}%</span>
                          </div>
                          {reasoning.reasoning && (
                            <p className="text-xs text-slate-600 mb-1">{reasoning.reasoning}</p>
                          )}
                          {reasoning.reasoning_chain && reasoning.reasoning_chain.length > 0 && (
                            <div className="space-y-0.5 mt-1">
                              {reasoning.reasoning_chain.map((step, i) => (
                                <p key={i} className="text-xs text-slate-500">{step}</p>
                              ))}
                            </div>
                          )}
                          {reasoning.keyword_matches && reasoning.keyword_matches.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-2">
                              {reasoning.keyword_matches.map(kw => (
                                <span key={kw} className="text-[10px] bg-red-100 text-red-600 px-1.5 py-0.5 rounded">{kw}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Meta */}
                <div className="pt-3 border-t border-slate-100 space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">Content ID</span>
                    <span className="text-slate-600 font-mono">{result.content_id}</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">处理时间</span>
                    <span className="text-slate-600">{result.processing_time_ms.toFixed(0)}ms</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">内容类型</span>
                    <span className="text-slate-600">{result.content_type}</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/** 根据文件扩展名返回图标 */
function getFileIcon(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  const iconMap: Record<string, string> = {
    pdf: '📕', doc: '📘', docx: '📘',
    txt: '📄', md: '📝', csv: '📊',
    json: '📋', xml: '📋', html: '🌐', htm: '🌐',
    log: '📜', py: '🐍', js: '💛', ts: '💙',
    java: '☕', go: '🔵', rs: '🦀',
    cpp: '⚙️', c: '⚙️', h: '⚙️',
    yaml: '📋', yml: '📋', toml: '📋',
    ini: '⚙️', cfg: '⚙️', conf: '⚙️',
    png: '🖼️', jpg: '🖼️', jpeg: '🖼️', gif: '🖼️',
    webp: '🖼️', svg: '🖼️', bmp: '🖼️',
  }
  return iconMap[ext] || '📎'
}
