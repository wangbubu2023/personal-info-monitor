import React, { useCallback, useEffect, useState } from 'react'
import { atomsApi } from '../../services/atoms'
import type { KnowledgeEntitySummary } from '../../types/atoms'
import AtomMiniList from './AtomMiniList'

const ENTITY_TYPES = ['', '企业', '政府机构', '人物', '机构', '国家/地区', '产品/品牌'] as const

const EntitiesPanel: React.FC<{ knowledgeEnabled: boolean }> = ({ knowledgeEnabled }) => {
  const [items, setItems] = useState<KnowledgeEntitySummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [entityType, setEntityType] = useState('')
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [atomIdsByEntity, setAtomIdsByEntity] = useState<Record<string, string[]>>({})

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await atomsApi.listEntities({
        entity_type: entityType || undefined,
        search: search || undefined,
        limit: 100,
      })
      setItems(data.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [entityType, search])

  useEffect(() => {
    const timer = setTimeout(() => void load(), 250)
    return () => clearTimeout(timer)
  }, [load])

  const toggle = async (entityId: string) => {
    if (expanded === entityId) {
      setExpanded(null)
      return
    }
    setExpanded(entityId)
    if (atomIdsByEntity[entityId]) return
    try {
      const detail = await atomsApi.listEntityAtoms(entityId)
      setAtomIdsByEntity((prev) => ({ ...prev, [entityId]: detail.atom_ids }))
    } catch {
      setAtomIdsByEntity((prev) => ({ ...prev, [entityId]: [] }))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4">
        <select
          className="rounded-xl border border-white/10 bg-[#1a2636] px-3 py-2 text-sm text-[#d1e0e9]"
          value={entityType}
          onChange={(e) => setEntityType(e.target.value)}
        >
          {ENTITY_TYPES.map((t) => (
            <option key={t || 'all'} value={t}>{t || '全部类型'}</option>
          ))}
        </select>
        <input
          className="min-w-[12rem] flex-1 rounded-xl border border-white/10 bg-[#1a2636] px-3 py-2 text-sm text-[#d1e0e9]"
          placeholder="搜索实体名称…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="text-xs text-[#8ea3b8]">共 {items.length} 个实体</span>
      </div>

      {!knowledgeEnabled && (
        <div className="rounded-xl border border-amber-200/40 bg-amber-50/10 px-4 py-3 text-sm text-amber-200">
          知识层（事件聚类/实体）未开启，已有数据仍可浏览。开启 atoms_knowledge_enabled 后新入库内容会自动抽取实体。
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{error}</div>
      )}

      {loading ? (
        <p className="text-sm text-[#8ea3b8]">加载中…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-[#586476]">暂无实体。开启知识层后，公司、人物、机构等会从原子 payload 自动归并。</p>
      ) : (
        <div className="space-y-2">
          {items.map((entity) => (
            <div
              key={entity.entity_id}
              className="rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-3"
            >
              <button
                type="button"
                onClick={() => void toggle(entity.entity_id)}
                className="flex w-full items-center gap-2 text-left"
              >
                <span className="rounded-full bg-white/10 px-2 py-0.5 text-[11px] text-[#8ea3b8]">{entity.entity_type}</span>
                <span className="text-sm font-medium text-[#e7f1f7]">{entity.canonical_name}</span>
                <span className="ml-auto text-xs text-[#8ea3b8]">{entity.atom_count} 原子</span>
              </button>
              {expanded === entity.entity_id && (
                <div className="mt-3 border-t border-white/10 pt-3">
                  <AtomMiniList atomIds={atomIdsByEntity[entity.entity_id] ?? []} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default EntitiesPanel
