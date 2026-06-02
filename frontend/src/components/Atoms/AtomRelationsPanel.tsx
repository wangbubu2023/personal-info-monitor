import React, { useCallback, useEffect, useState } from 'react'
import { atomsApi } from '../../services/atoms'
import type { AtomRecord, RelationRecord } from '../../types/atoms'

interface Props {
  atom: AtomRecord
  onOpenAtom: (atomId: string) => void
  onRelationVerified?: () => void
}

const AtomRelationsPanel: React.FC<Props> = ({ atom, onOpenAtom, onRelationVerified }) => {
  const [relations, setRelations] = useState<RelationRecord[]>([])
  const [peerAtoms, setPeerAtoms] = useState<Record<string, AtomRecord>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [manualPeerId, setManualPeerId] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await atomsApi.listRelations(atom.atom_id)
      setRelations(data.items)
      const peers: Record<string, AtomRecord> = {}
      for (const rel of data.items) {
        const peerId = rel.atom_a === atom.atom_id ? rel.atom_b : rel.atom_a
        if (!peers[peerId]) {
          peers[peerId] = await atomsApi.get(peerId)
        }
      }
      setPeerAtoms(peers)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载关系失败')
    } finally {
      setLoading(false)
    }
  }, [atom.atom_id])

  useEffect(() => {
    void load()
  }, [load])

  const verifyRelation = async (relId: string) => {
    setBusyId(relId)
    try {
      await atomsApi.verifyRelation(relId)
      await load()
      onRelationVerified?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : '确认失败')
    } finally {
      setBusyId(null)
    }
  }

  const rejectRelation = async (relId: string) => {
    setBusyId(relId)
    try {
      await atomsApi.deleteRelation(relId)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '拒绝失败')
    } finally {
      setBusyId(null)
    }
  }

  const createManual = async () => {
    const peer = manualPeerId.trim()
    if (!peer) return
    setBusyId('create')
    try {
      await atomsApi.createRelation({
        atom_a: atom.atom_id,
        atom_b: peer,
        relation_type: '印证',
        direction: '双向',
        fact_confidence: 0.8,
      })
      setManualPeerId('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setBusyId(null)
    }
  }

  if (loading) {
    return <p className="text-xs text-[#536b82]">加载关联…</p>
  }

  return (
    <div className="space-y-3">
      {error && (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </p>
      )}

      {relations.length === 0 ? (
        <p className="text-xs text-[#536b82]">暂无跨文关系。启用 ATOMS_RELATIONS_ENABLED 后新原子会自动推断。</p>
      ) : (
        relations.map((rel) => {
          const peerId = rel.atom_a === atom.atom_id ? rel.atom_b : rel.atom_a
          const peer = peerAtoms[peerId]
          const isContradiction = rel.relation_type === '矛盾'
          const isCorroboration = rel.relation_type === '印证'
          return (
            <div
              key={rel.rel_id}
              className={`rounded-xl border p-3 ${
                isContradiction
                  ? 'border-amber-200 bg-amber-50'
                  : isCorroboration
                    ? 'border-emerald-200 bg-emerald-50'
                    : 'border-[#d8e4ec] bg-[#f8fbfc]'
              }`}
            >
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-medium text-[#22324a]">{rel.relation_type}</span>
                <span className="text-[#536b82]">{rel.direction}</span>
                <span className="text-[#536b82]">置信 {Math.round(rel.fact_confidence * 100)}%</span>
                {rel.verified && <span className="font-medium text-emerald-700">已确认</span>}
              </div>
              {isContradiction && peer ? (
                <div className="mt-2 grid gap-2 text-xs">
                  <p className="text-[#536b82]">本句：{atom.source_sentence}</p>
                  <p className="text-amber-900">对句：{peer.source_sentence}</p>
                </div>
              ) : peer ? (
                <p className="mt-2 line-clamp-3 text-xs text-[#536b82]">{peer.source_sentence}</p>
              ) : null}
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="text-xs font-medium text-[#0b6f91] underline"
                  onClick={() => onOpenAtom(peerId)}
                >
                  {peerId}
                </button>
                {!rel.verified && isCorroboration && (
                  <button
                    type="button"
                    disabled={busyId === rel.rel_id}
                    onClick={() => void verifyRelation(rel.rel_id)}
                    className="rounded-lg border border-emerald-300 bg-white px-2 py-1 text-xs font-medium text-emerald-800 disabled:opacity-50"
                  >
                    确认印证
                  </button>
                )}
                {!rel.verified && (
                  <button
                    type="button"
                    disabled={busyId === rel.rel_id}
                    onClick={() => void rejectRelation(rel.rel_id)}
                    className="rounded-lg border border-[#c7d6e0] bg-white px-2 py-1 text-xs font-medium text-[#536b82] disabled:opacity-50"
                  >
                    拒绝
                  </button>
                )}
              </div>
            </div>
          )
        })
      )}

      <div className="border-t border-[#d8e4ec] pt-3">
        <p className="text-xs text-[#536b82]">手动添加印证关系</p>
        <div className="mt-2 flex gap-2">
          <input
            className="min-w-0 flex-1 rounded-lg border border-[#c7d6e0] bg-white px-2 py-1.5 font-mono text-xs text-[#22324a] placeholder:text-[#7b8fa4]"
            placeholder="对方 atom_id"
            value={manualPeerId}
            onChange={(e) => setManualPeerId(e.target.value)}
          />
          <button
            type="button"
            disabled={busyId === 'create'}
            onClick={() => void createManual()}
            className="rounded-lg bg-[#22324a] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          >
            添加
          </button>
        </div>
      </div>
    </div>
  )
}

export default AtomRelationsPanel
