import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import AtomRelationsPanel from '../components/Atoms/AtomRelationsPanel'
import EntitiesPanel from '../components/Atoms/EntitiesPanel'
import EventsPanel from '../components/Atoms/EventsPanel'
import { atomsApi } from '../services/atoms'
import { configsApi } from '../services/configs'
import { systemApi } from '../services/system'
import type { AtomRecord } from '../types/atoms'

const ATOM_TYPES = ['', '信息', '观点', '数据'] as const
const DOMAINS = [
  '',
  '宏观经济',
  '金融市场',
  '科技',
  '汽车',
  '房地产',
  '能源',
  '消费',
  '医疗健康',
  '政策监管',
  '国际关系',
  '其他',
] as const

function payloadSummary(atom: AtomRecord): string {
  const p = atom.payload
  if (atom.atom_type === '信息') return String(p.what ?? '')
  if (atom.atom_type === '观点') return String(p.say_what ?? '')
  if (atom.atom_type === '数据') return `${p.metric ?? ''}: ${p.value ?? ''}${p.unit ? ` ${p.unit}` : ''}`
  return ''
}

const AtomsPage: React.FC = () => {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [items, setItems] = useState<AtomRecord[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<AtomRecord | null>(null)
  const [editPayload, setEditPayload] = useState('')
  const [saving, setSaving] = useState(false)
  const [featureSaving, setFeatureSaving] = useState(false)
  const [atomsEnabled, setAtomsEnabled] = useState<boolean | null>(null)
  const [relationsEnabled, setRelationsEnabled] = useState(false)
  const [knowledgeEnabled, setKnowledgeEnabled] = useState(false)
  const [drawerTab, setDrawerTab] = useState<'edit' | 'relations'>('edit')

  const view = (searchParams.get('view') ?? 'atoms') as 'atoms' | 'events' | 'entities'

  const filters = useMemo(() => ({
    type: searchParams.get('type') ?? '',
    domain: searchParams.get('domain') ?? '',
    verified: searchParams.get('verified') ?? '',
    search: searchParams.get('search') ?? '',
    content_id: searchParams.get('content_id') ?? '',
    status: searchParams.get('status') ?? 'active',
    page: Number(searchParams.get('page') ?? '1'),
  }), [searchParams])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await atomsApi.list({
        type: filters.type || undefined,
        domain: filters.domain || undefined,
        verified: filters.verified === '' ? undefined : filters.verified === 'true',
        search: filters.search || undefined,
        content_id: filters.content_id || undefined,
        status: filters.status || 'active',
        page: filters.page,
        page_size: 20,
      })
      setItems(data.items)
      setTotal(data.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    systemApi.getFeatures()
      .then((f) => {
        setAtomsEnabled(f.atoms_enabled)
        setRelationsEnabled(f.atoms_relations_enabled)
        setKnowledgeEnabled(Boolean(f.atoms_knowledge_enabled))
      })
      .catch(() => setAtomsEnabled(false))
  }, [])

  useEffect(() => {
    if (atomsEnabled !== true) {
      setLoading(false)
      return
    }
    void load()
  }, [load, atomsEnabled])

  useEffect(() => {
    if (selected) {
      setEditPayload(JSON.stringify(selected.payload, null, 2))
    }
  }, [selected])

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.set('page', '1')
    setSearchParams(next)
  }

  const openAtom = async (atomId: string) => {
    const atom = await atomsApi.get(atomId)
    setSelected(atom)
    setDrawerTab('edit')
  }

  const saveSelected = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const payload = JSON.parse(editPayload) as Record<string, unknown>
      const updated = await atomsApi.update(selected.atom_id, { payload })
      setSelected(updated)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const verifySelected = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const updated = await atomsApi.verify(selected.atom_id)
      setSelected(updated)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '验证失败')
    } finally {
      setSaving(false)
    }
  }

  const enableAtoms = async () => {
    setFeatureSaving(true)
    setError(null)
    try {
      const updatedSettings = await configsApi.updateSettings({ atoms_enabled: true })
      queryClient.setQueryData(['system-settings'], updatedSettings)
      void queryClient.invalidateQueries({ queryKey: ['system-settings'] })
      const features = await systemApi.getFeatures()
      setAtomsEnabled(features.atoms_enabled)
      setRelationsEnabled(features.atoms_relations_enabled)
      setKnowledgeEnabled(Boolean(features.atoms_knowledge_enabled))
    } catch (err) {
      setError(err instanceof Error ? err.message : '启用失败')
    } finally {
      setFeatureSaving(false)
    }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-4 py-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-[#293859]">新闻原子库</h1>
        <p className="mt-2 text-sm text-[#586476]">
          结构化事实、观点与数据{atomsEnabled ? `。共 ${total} 条。` : '。'}
        </p>
      </div>

      {atomsEnabled === null && (
        <p className="text-sm text-[#586476]">正在检查功能状态…</p>
      )}

      {atomsEnabled === false && (
        <div className="flex flex-col gap-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-950 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-medium">原子库尚未启用</p>
            <p className="mt-2 text-amber-900/80">
              可直接在前端开启；也可到「配置 → 模型配置 → 原子化模型配置」调整模型与关联推断设置。
            </p>
          </div>
          <button
            type="button"
            disabled={featureSaving}
            onClick={() => void enableAtoms()}
            className="shrink-0 rounded-xl border border-amber-300 bg-white px-4 py-2 text-sm font-semibold text-amber-950 shadow-sm transition hover:border-amber-400 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {featureSaving ? '正在启用…' : '启用原子库'}
          </button>
        </div>
      )}

      {error && atomsEnabled !== true && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {atomsEnabled === true && (
      <>
      <div className="flex gap-1 rounded-2xl border border-[#d8e4ec] bg-white p-1.5 shadow-sm">
        {([
          ['atoms', '原子'],
          ['events', '事件簇'],
          ['entities', '实体'],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter('view', key === 'atoms' ? '' : key)}
            className={`flex-1 rounded-xl px-4 py-2 text-sm font-medium transition ${
              view === key
                ? 'bg-[#dff3f9] text-[#0f4d68] shadow-sm'
                : 'text-[#536b82] hover:bg-[#f1f6f9] hover:text-[#22324a]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {view === 'events' && <EventsPanel knowledgeEnabled={knowledgeEnabled} />}
      {view === 'entities' && <EntitiesPanel knowledgeEnabled={knowledgeEnabled} />}

      {view === 'atoms' && (
      <>
      <div className="flex flex-wrap gap-3 rounded-2xl border border-[#d8e4ec] bg-white p-4 shadow-sm">
        <select
          className="rounded-xl border border-[#c7d6e0] bg-white px-3 py-2 text-sm text-[#22324a] shadow-sm"
          value={filters.type}
          onChange={(e) => setFilter('type', e.target.value)}
        >
          {ATOM_TYPES.map((t) => (
            <option key={t || 'all'} value={t}>{t || '全部类型'}</option>
          ))}
        </select>
        <select
          className="rounded-xl border border-[#c7d6e0] bg-white px-3 py-2 text-sm text-[#22324a] shadow-sm"
          value={filters.domain}
          onChange={(e) => setFilter('domain', e.target.value)}
        >
          {DOMAINS.map((d) => (
            <option key={d || 'all'} value={d}>{d || '全部领域'}</option>
          ))}
        </select>
        <select
          className="rounded-xl border border-[#c7d6e0] bg-white px-3 py-2 text-sm text-[#22324a] shadow-sm"
          value={filters.verified}
          onChange={(e) => setFilter('verified', e.target.value)}
        >
          <option value="">全部验证状态</option>
          <option value="true">已验证</option>
          <option value="false">未验证</option>
        </select>
        <select
          className="rounded-xl border border-[#c7d6e0] bg-white px-3 py-2 text-sm text-[#22324a] shadow-sm"
          value={filters.status}
          onChange={(e) => setFilter('status', e.target.value)}
        >
          <option value="active">当前有效</option>
          <option value="shadow">已影子化</option>
          <option value="superseded">被覆盖</option>
          <option value="conflicted">冲突</option>
          <option value="all">全部状态</option>
        </select>
        <input
          className="min-w-[12rem] flex-1 rounded-xl border border-[#c7d6e0] bg-white px-3 py-2 text-sm text-[#22324a] shadow-sm placeholder:text-[#7b8fa4]"
          placeholder="搜索句子、信源…"
          value={filters.search}
          onChange={(e) => setFilter('search', e.target.value)}
        />
        {filters.content_id && (
          <button
            type="button"
            disabled={saving}
            onClick={() => {
              void (async () => {
                setSaving(true)
                try {
                  await atomsApi.atomizeContent(filters.content_id!)
                  await load()
                } catch (err) {
                  setError(err instanceof Error ? err.message : '重新提取失败')
                } finally {
                  setSaving(false)
                }
              })()
            }}
            className="rounded-xl border border-[#49A8C9]/50 bg-[#edf9fc] px-3 py-2 text-sm font-medium text-[#0f4d68] disabled:opacity-50"
          >
            重新提取
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
        <div className="space-y-3">
          {loading ? (
            <p className="text-sm text-[#536b82]">加载中…</p>
          ) : items.length === 0 ? (
            <p className="text-sm text-[#586476]">暂无原子。新文章入库后会自动提取，也可通过 API 手动录入。</p>
          ) : (
            items.map((atom) => (
              <button
                key={atom.atom_id}
                type="button"
                onClick={() => void openAtom(atom.atom_id)}
                className={`w-full rounded-2xl border px-4 py-4 text-left transition ${
                  selected?.atom_id === atom.atom_id
                    ? 'border-[#49A8C9]/60 bg-[#edf9fc] shadow-sm'
                    : 'border-[#d8e4ec] bg-white shadow-sm hover:border-[#9ec9d8] hover:bg-[#f8fbfc]'
                }`}
              >
                <div className="flex flex-wrap items-center gap-2 text-xs text-[#536b82]">
                  <span className="rounded-full bg-[#e8f0f6] px-2 py-0.5 text-[#22324a]">{atom.atom_type}</span>
                  <span>{atom.domain}</span>
                  <span>{atom.atom_source}</span>
                  <span>置信 {Math.round(atom.fact_confidence * 100)}%</span>
                  {atom.verified && <span className="font-medium text-emerald-700">已验证</span>}
                  {atom.status && atom.status !== 'active' && (
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-800">{atom.status}</span>
                  )}
                </div>
                <p className="mt-2 text-sm font-semibold text-[#22324a]">{payloadSummary(atom)}</p>
                <p className="mt-2 line-clamp-2 text-xs text-[#5e7288]">{atom.source_sentence}</p>
              </button>
            ))
          )}
        </div>

        {selected && (
          <aside className="rounded-2xl border border-[#d8e4ec] bg-white p-4 shadow-sm lg:sticky lg:top-6 lg:self-start">
            <p className="text-xs text-[#536b82]">{selected.atom_id}</p>
            <p className="mt-2 text-sm text-[#22324a]">{selected.source_sentence}</p>
            <p className="mt-3 text-xs text-[#536b82]">
              原子信源：{selected.atom_source} · 置信度 {Math.round(selected.fact_confidence * 100)}%
              · 来源可信度 {Math.round(selected.source_credibility * 100)}%
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <a
                href={selected.source_url}
                target="_blank"
                rel="noreferrer"
                className="text-xs font-medium text-[#0b6f91] underline"
              >
                原文链接
              </a>
              <Link to={`/reader/${selected.content_id}`} className="text-xs font-medium text-[#0b6f91] underline">
                打开 Reader
              </Link>
            </div>
            {relationsEnabled && (
              <div className="mt-4 flex gap-2 border-b border-[#d8e4ec] pb-2">
                <button
                  type="button"
                  onClick={() => setDrawerTab('edit')}
                  className={`text-xs font-medium ${drawerTab === 'edit' ? 'text-[#0b6f91]' : 'text-[#536b82]'}`}
                >
                  编辑
                </button>
                <button
                  type="button"
                  onClick={() => setDrawerTab('relations')}
                  className={`text-xs font-medium ${drawerTab === 'relations' ? 'text-[#0b6f91]' : 'text-[#536b82]'}`}
                >
                  关联原子
                </button>
              </div>
            )}
            {drawerTab === 'relations' && relationsEnabled ? (
              <div className="mt-4">
                <AtomRelationsPanel
                  atom={selected}
                  onOpenAtom={(id) => void openAtom(id)}
                  onRelationVerified={() => void openAtom(selected.atom_id)}
                />
              </div>
            ) : (
              <>
                <label className="mt-4 block text-xs text-[#536b82]">payload（JSON）</label>
                <textarea
                  className="mt-1 h-48 w-full rounded-xl border border-[#c7d6e0] bg-[#f8fbfc] p-3 font-mono text-xs text-[#22324a]"
                  value={editPayload}
                  onChange={(e) => setEditPayload(e.target.value)}
                />
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    disabled={saving}
                    onClick={() => void saveSelected()}
                    className="rounded-xl bg-[#49A8C9] px-4 py-2 text-sm font-medium text-[#041018] disabled:opacity-50"
                  >
                    保存
                  </button>
                  {!selected.verified && (
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => void verifySelected()}
                      className="rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-medium text-emerald-800 disabled:opacity-50"
                    >
                      标记已验证
                    </button>
                  )}
                </div>
              </>
            )}
          </aside>
        )}
      </div>
      </>
      )}
      </>
      )}
    </div>
  )
}

export default AtomsPage
