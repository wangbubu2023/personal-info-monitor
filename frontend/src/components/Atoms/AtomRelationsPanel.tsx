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
    return <p className="text-xs text-[#8ea3b8]">加载关联…</p>
  }

  return (
    <div className="space-y-3">
      {error && (
        <p className="rounded-lg border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {error}
        </p>
      )}

      {relations.length === 0 ? (
        <p className="text-xs text-[#8ea3b8]">暂无跨文关系。启用 ATOMS_RELATIONS_ENABLED 后新原子会自动推断。</p>
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
                  ? 'border-amber-400/30 bg-amber-500/5'
                  : isCorroboration
                    ? 'border-emerald-400/30 bg-emerald-500/5'
                    : 'border-white/10 bg-white/[0.02]'
              }`}
            >
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-medium text-[#e7f1f7]">{rel.relation_type}</span>
                <span className="text-[#8ea3b8]">{rel.direction}</span>
                <span className="text-[#8ea3b8]">置信 {Math.round(rel.fact_confidence * 100)}%</span>
                {rel.verified && <span className="text-emerald-300">已确认</span>}
              </div>
              {isContradiction && peer ? (
                <div className="mt-2 grid gap-2 text-xs">
                  <p className="text-[#8ea3b8]">本句：{atom.source_sentence}</p>
                  <p className="text-amber-100/90">对句：{peer.source_sentence}</p>
                </div>
              ) : peer ? (
                <p className="mt-2 line-clamp-3 text-xs text-[#8ea3b8]">{peer.source_sentence}</p>
              ) : null}
              <div className="mt-2 flex flex-wrap gap-2">
                <button
                  type="button"
                  className="text-xs text-[#89dcef] underline"
                  onClick={() => onOpenAtom(peerId)}
                >
                  {peerId}
                </button>
                {!rel.verified && isCorroboration && (
                  <button
                    type="button"
                    disabled={busyId === rel.rel_id}
                    onClick={() => void verifyRelation(rel.rel_id)}
                    className="rounded-lg border border-emerald-400/40 px-2 py-1 text-xs text-emerald-200 disabled:opacity-50"
                  >
                    确认印证
                  </button>
                )}
                {!rel.verified && (
                  <button
                    type="button"
                    disabled={busyId === rel.rel_id}
                    onClick={() => void rejectRelation(rel.rel_id)}
                    className="rounded-lg border border-white/15 px-2 py-1 text-xs text-[#8ea3b8] disabled:opacity-50"
                  >
                    拒绝
                  </button>
                )}
              </div>
            </div>
          )
        })
      )}

      <div className="border-t border-white/10 pt-3">
        <p className="text-xs text-[#8ea3b8]">手动添加印证关系</p>
        <div className="mt-2 flex gap-2">
          <input
            className="min-w-0 flex-1 rounded-lg border border-white/10 bg-[#0f1724] px-2 py-1.5 font-mono text-xs text-[#d1e0e9]"
            placeholder="对方 atom_id"
            value={manualPeerId}
            onChange={(e) => setManualPeerId(e.target.value)}
          />
          <button
            type="button"
            disabled={busyId === 'create'}
            onClick={() => void createManual()}
            className="rounded-lg bg-white/10 px-3 py-1.5 text-xs text-[#d1e0e9] disabled:opacity-50"
          >
            添加
          </button>
        </div>
      </div>
    </div>
  )
}

export default AtomRelationsPanel
