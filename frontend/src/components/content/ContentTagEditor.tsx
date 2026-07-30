import React, { useEffect, useState } from 'react'
import { Check, Loader2, Tag } from 'lucide-react'

import { CONTENT_TAG_CHOICES, CONTENT_TAG_LABELS, normalizeContentTagKeys, type ContentTagKey } from '../../config/contentTags'
import { contentsApi } from '../../services/contents'

interface ContentTagEditorProps {
  contentId?: string
  tags: string[]
  editable?: boolean
  compact?: boolean
}

const ContentTagEditor: React.FC<ContentTagEditorProps> = ({
  contentId,
  tags,
  editable = false,
  compact = false,
}) => {
  const normalized = normalizeContentTagKeys(tags)
  const [current, setCurrent] = useState<ContentTagKey[]>(normalized)
  const [draft, setDraft] = useState<ContentTagKey[]>(normalized)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const next = normalizeContentTagKeys(tags)
    setCurrent(next)
    setDraft(next)
  }, [tags])

  const toggle = (value: ContentTagKey) => {
    setDraft((previous) => {
      if (previous.includes(value)) return previous.filter((item) => item !== value)
      if (previous.length >= 4) return previous
      return [...previous, value]
    })
  }

  const save = async () => {
    if (!contentId || !draft.length || saving) return
    setSaving(true)
    setError(null)
    try {
      const result = await contentsApi.setTags(contentId, draft)
      const next = normalizeContentTagKeys(result.tags)
      setCurrent(next)
      setDraft(next)
      setEditing(false)
    } catch {
      setError('标签保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={compact ? 'flex flex-wrap items-center gap-1.5' : 'space-y-2'} data-testid="content-tags">
      <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#8C866A]">
        <Tag size={11} /> 标签
      </span>
      <div className="flex flex-wrap gap-1.5">
        {current.length ? current.map((key) => (
          <span
            key={key}
            className="rounded-full border border-[#8C866A]/18 bg-[#8C866A]/8 px-2.5 py-1 text-[11px] font-semibold text-[#6f684f]"
          >
            {CONTENT_TAG_LABELS[key]}
          </span>
        )) : (
          <span className="text-[11px] text-[#8a96a5]">暂无标签</span>
        )}
        {editable && contentId ? (
          <button
            type="button"
            onClick={() => {
              setDraft(current)
              setEditing((value) => !value)
              setError(null)
            }}
            className="rounded-full border border-[rgba(88,100,118,0.14)] bg-white/75 px-2.5 py-1 text-[11px] font-semibold text-[#5f6f82] hover:border-[#49A8C9]/30 hover:text-[#293859]"
          >
            {editing ? '收起' : '调整标签'}
          </button>
        ) : null}
      </div>
      {editing ? (
        <div className="mt-3 rounded-2xl border border-[rgba(88,100,118,0.12)] bg-white/75 p-3">
          <p className="mb-2 text-[11px] text-[#8a96a5]">可选 1–4 个；第一个标签继续兼容后台 Lane。</p>
          <div className="flex flex-wrap gap-1.5">
            {CONTENT_TAG_CHOICES.map(([value, label]) => {
              const selected = draft.includes(value)
              return (
                <button
                  key={value}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => toggle(value)}
                  className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
                    selected
                      ? 'border-[#49A8C9]/35 bg-[#49A8C9] text-white'
                      : 'border-[rgba(88,100,118,0.14)] bg-white text-[#5f6f82]'
                  }`}
                >
                  {selected ? <Check size={11} /> : null}{label}
                </button>
              )
            })}
          </div>
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              disabled={!draft.length || saving}
              onClick={() => void save()}
              className="inline-flex items-center gap-1 rounded-lg bg-[#49A8C9] px-3 py-1.5 text-[11px] font-semibold text-white disabled:opacity-50"
            >
              {saving ? <Loader2 size={11} className="animate-spin" /> : null}保存标签
            </button>
            {draft.length >= 4 ? <span className="text-[11px] text-[#8a96a5]">最多 4 个</span> : null}
            {error ? <span className="text-[11px] text-rose-600">{error}</span> : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default ContentTagEditor
