import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { atomsApi } from '../../services/atoms'
import type { AtomRecord } from '../../types/atoms'

function str(value: unknown): string {
  if (value === null || value === undefined) return ''
  return String(value)
}

function atomSummary(atom: AtomRecord): string {
  if (atom.canonical_text) return atom.canonical_text
  const p = atom.payload
  if (atom.atom_type === '信息') return str(p.what) || atom.source_sentence
  if (atom.atom_type === '观点') return str(p.say_what) || atom.source_sentence
  if (atom.atom_type === '数据') {
    const unit = str(p.unit)
    return `${str(p.metric)}: ${str(p.value)}${unit ? ` ${unit}` : ''}`.trim() || atom.source_sentence
  }
  return atom.source_sentence
}

interface AtomMiniListProps {
  atomIds: string[]
  limit?: number
}

const AtomMiniList: React.FC<AtomMiniListProps> = ({ atomIds, limit = 12 }) => {
  const [atoms, setAtoms] = useState<AtomRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    const ids = atomIds.slice(0, limit)
    Promise.all(
      ids.map((id) => atomsApi.get(id).catch(() => null)),
    )
      .then((results) => {
        if (cancelled) return
        setAtoms(results.filter((a): a is AtomRecord => a !== null))
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : '加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [atomIds, limit])

  if (loading) return <p className="text-xs text-[#8ea3b8]">加载关联原子…</p>
  if (error) return <p className="text-xs text-red-300">{error}</p>
  if (atoms.length === 0) return <p className="text-xs text-[#586476]">无关联原子。</p>

  return (
    <div className="space-y-2">
      {atoms.map((atom) => (
        <div
          key={atom.atom_id}
          className="rounded-xl border border-white/[0.08] bg-white/[0.025] px-3 py-2"
        >
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-[#8ea3b8]">
            <span className="rounded-full bg-white/10 px-2 py-0.5">{atom.atom_type}</span>
            <span>{atom.atom_source}</span>
            {atom.status !== 'active' && (
              <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-amber-200">{atom.status}</span>
            )}
            <Link to={`/reader/${atom.content_id}`} className="ml-auto text-[#89dcef] underline">
              Reader
            </Link>
          </div>
          <p className="mt-1 text-xs text-[#d1e0e9]">{atomSummary(atom)}</p>
        </div>
      ))}
      {atomIds.length > limit && (
        <p className="text-[11px] text-[#586476]">仅显示前 {limit} 条，共 {atomIds.length} 条。</p>
      )}
    </div>
  )
}

export default AtomMiniList
