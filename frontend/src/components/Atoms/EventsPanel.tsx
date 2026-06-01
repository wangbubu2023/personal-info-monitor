import React, { useCallback, useEffect, useState } from 'react'
import { atomsApi } from '../../services/atoms'
import type { EventClusterSummary } from '../../types/atoms'
import AtomMiniList from './AtomMiniList'

const DOMAINS = [
  '', '宏观经济', '金融市场', '科技', '汽车', '房地产', '能源', '消费', '医疗健康', '政策监管', '国际关系', '其他',
] as const

function formatDate(value: string | null): string {
  if (!value) return '—'
  return value.slice(0, 10)
}

const EventsPanel: React.FC<{ knowledgeEnabled: boolean }> = ({ knowledgeEnabled }) => {
  const [items, setItems] = useState<EventClusterSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [domain, setDomain] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [atomIdsByEvent, setAtomIdsByEvent] = useState<Record<string, string[]>>({})

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await atomsApi.listEvents({ domain: domain || undefined, limit: 100 })
      setItems(data.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [domain])

  useEffect(() => {
    void load()
  }, [load])

  const toggle = async (eventId: string) => {
    if (expanded === eventId) {
      setExpanded(null)
      return
    }
    setExpanded(eventId)
    if (atomIdsByEvent[eventId]) return
    try {
      const detail = await atomsApi.getEvent(eventId)
      setAtomIdsByEvent((prev) => ({ ...prev, [eventId]: detail.atom_ids }))
    } catch {
      setAtomIdsByEvent((prev) => ({ ...prev, [eventId]: [] }))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4">
        <select
          className="rounded-xl border border-white/10 bg-[#1a2636] px-3 py-2 text-sm text-[#d1e0e9]"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
        >
          {DOMAINS.map((d) => (
            <option key={d || 'all'} value={d}>{d || '全部领域'}</option>
          ))}
        </select>
        <span className="text-xs text-[#8ea3b8]">共 {items.length} 个事件簇</span>
      </div>

      {!knowledgeEnabled && (
        <div className="rounded-xl border border-amber-200/40 bg-amber-50/10 px-4 py-3 text-sm text-amber-200">
          知识层（事件聚类/实体）未开启，已有数据仍可浏览。可在「配置 → 智能引擎」开启 atoms_knowledge_enabled 后，新入库内容会自动聚类。
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div>
      )}

      {loading ? (
        <p className="text-sm text-[#8ea3b8]">加载中…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-[#586476]">暂无事件簇。开启知识层后，新入库的原子会按领域、实体与时间窗自动聚合。</p>
      ) : (
        <div className="space-y-3">
          {items.map((event) => (
            <div
              key={event.event_id}
              className="rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-4"
            >
              <button type="button" onClick={() => void toggle(event.event_id)} className="w-full text-left">
                <div className="flex flex-wrap items-center gap-2 text-xs text-[#8ea3b8]">
                  <span>{event.domain}</span>
                  <span className="rounded-full bg-white/10 px-2 py-0.5">{event.atom_count} 原子</span>
                  <span>{formatDate(event.first_seen_at)} → {formatDate(event.last_seen_at)}</span>
                  {event.status !== 'active' && (
                    <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-amber-200">{event.status}</span>
                  )}
                </div>
                <p className="mt-2 text-sm font-medium text-[#e7f1f7]">{event.title}</p>
                {event.canonical_summary && (
                  <p className="mt-1 line-clamp-2 text-xs text-[#a8bfcf]">{event.canonical_summary}</p>
                )}
              </button>
              {expanded === event.event_id && (
                <div className="mt-3 border-t border-white/10 pt-3">
                  <AtomMiniList atomIds={atomIdsByEvent[event.event_id] ?? []} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default EventsPanel
