import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/client'

interface DatasetStats {
  available: boolean
  root_dir: string
  stats: { categories: number; text_zh: number; text_en: number; image: number; video: number; audio: number } | null
  per_category: { category: string; text_zh: number; text_en: number; image: number; video: number; audio: number }[]
  error?: string
}

const MODALITY_LABELS: { key: 'text_zh' | 'text_en' | 'image' | 'video' | 'audio'; label: string }[] = [
  { key: 'text_zh', label: '中文文本' },
  { key: 'text_en', label: '英文文本' },
  { key: 'image', label: '图片' },
  { key: 'video', label: '视频' },
  { key: 'audio', label: '音频' },
]

export default function DatasetManagerPage() {
  const [ds, setDs] = useState<DatasetStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadData = useCallback(async () => {
    try {
      setDs(await api.getDatasetStats())
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  const totalOf = (s: DatasetStats['stats']) => (s ? s.text_zh + s.text_en + s.image + s.video + s.audio : 0)

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-4">数据集管理</h1>
      {error && <div className="text-red-600 mb-4">加载失败: {error}</div>}
      {loading ? (
        <div className="text-gray-500">加载中…</div>
      ) : (
        <div className="space-y-4">
          {!ds?.available ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 text-sm text-yellow-700">
              数据集不可用：{ds?.error || 'OutSafe-Bench 目录不存在'}（{ds?.root_dir}）
            </div>
          ) : (
            <>
              {/* 总览 */}
              <div className="bg-white rounded-lg shadow p-4">
                <div className="flex items-baseline justify-between mb-3">
                  <h2 className="font-semibold">OutSafe-Bench 概览</h2>
                  <span className="text-xs text-gray-400 font-mono">{ds.root_dir}</span>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
                  {MODALITY_LABELS.map(m => (
                    <div key={m.key} className="border rounded p-3">
                      <div className="text-xs text-gray-500">{m.label}</div>
                      <div className="text-lg font-semibold">{ds.stats ? ds.stats[m.key] : 0}</div>
                    </div>
                  ))}
                  <div className="border rounded p-3 bg-indigo-50">
                    <div className="text-xs text-gray-500">风险类别</div>
                    <div className="text-lg font-semibold">{ds.stats?.categories ?? 0} 类</div>
                  </div>
                </div>
                <p className="text-xs text-gray-400 mt-3">样本总量：{totalOf(ds.stats)}（9 类风险 × 中英文/多模态）</p>
              </div>

              {/* 分类明细 */}
              <div className="bg-white rounded-lg shadow p-4">
                <h2 className="font-semibold mb-3">分类明细（每类各模态数量）</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-gray-500 border-b">
                        <th className="py-2 pr-4">类别</th>
                        {MODALITY_LABELS.map(m => (
                          <th key={m.key} className="py-2 pr-4">{m.label}</th>
                        ))}
                        <th className="py-2">小计</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ds.per_category.map(c => (
                        <tr key={c.category} className="border-b last:border-0">
                          <td className="py-2 pr-4 font-mono text-xs">{c.category}</td>
                          {MODALITY_LABELS.map(m => (
                            <td key={m.key} className="py-2 pr-4">{c[m.key]}</td>
                          ))}
                          <td className="py-2 font-semibold">
                            {MODALITY_LABELS.reduce((sum, m) => sum + c[m.key], 0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-gray-400 mt-3">
                  真实数据源：/workspace/data/OutSafe-Bench（每类 Chinese/English Text.xlsx、pictures/、video/、audio/）。
                  用于 T2 对抗 / T5 多模态评测。
                </p>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
