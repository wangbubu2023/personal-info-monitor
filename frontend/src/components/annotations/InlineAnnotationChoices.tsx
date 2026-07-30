import React, { useEffect, useMemo, useState } from 'react'
import { Check, Loader2 } from 'lucide-react'

import { useRuntimeFeatures } from '../../hooks/useRuntimeFeatures'
import {
  annotationsApi,
  type AnnotationTargetType,
} from '../../services/annotations'

export interface AnnotationChoice {
  value: string
  label: string
}

interface InlineAnnotationChoicesProps {
  taskType: string
  targetType: AnnotationTargetType
  targetId: string
  label: string
  choices: AnnotationChoice[]
  context?: Record<string, unknown>
  prediction?: Record<string, unknown>
  compact?: boolean
  loadExisting?: boolean
}

const InlineAnnotationChoices: React.FC<InlineAnnotationChoicesProps> = ({
  taskType,
  targetType,
  targetId,
  label,
  choices,
  context = {},
  prediction = {},
  compact = false,
  loadExisting = true,
}) => {
  const features = useRuntimeFeatures()
  const enabled = Boolean(features?.inline_annotations_enabled)
  const [selected, setSelected] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const choiceValues = useMemo(() => new Set(choices.map((choice) => choice.value)), [choices])

  useEffect(() => {
    if (!enabled || !loadExisting || !targetId) return
    let active = true
    void annotationsApi.getTarget(targetType, targetId)
      .then((tasks) => {
        const value = tasks.find((task) => task.task_type === taskType)?.latest_label?.label_payload.value
        if (active && typeof value === 'string' && choiceValues.has(value)) setSelected(value)
      })
      .catch(() => {
        // Annotation status is supplementary; never interrupt reading.
      })
    return () => {
      active = false
    }
  }, [choiceValues, enabled, loadExisting, targetId, targetType, taskType])

  if (!enabled) return null

  const submit = async (value: string) => {
    if (saving) return
    setSaving(value)
    setError(null)
    try {
      await annotationsApi.submitLabel({
        task_type: taskType,
        target_type: targetType,
        target_id: targetId,
        label_payload: { value },
        context_snapshot: context,
        prediction_snapshot: prediction,
      })
      setSelected(value)
    } catch {
      setError('保存失败')
    } finally {
      setSaving(null)
    }
  }

  return (
    <div className={compact ? 'flex flex-wrap items-center gap-1.5' : 'space-y-2'}>
      <span className={compact ? 'text-[11px] font-medium text-[#8a96a5]' : 'block text-[12px] font-semibold text-[#5f6f82]'}>
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5">
        {choices.map((choice) => {
          const active = selected === choice.value
          return (
            <button
              key={choice.value}
              type="button"
              onClick={() => void submit(choice.value)}
              disabled={Boolean(saving)}
              aria-label={`${label}：${choice.label}`}
              aria-pressed={active}
              className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-all disabled:opacity-60 ${
                active
                  ? 'border-[#49A8C9]/35 bg-[#49A8C9] text-white'
                  : 'border-[rgba(88,100,118,0.14)] bg-white/80 text-[#5f6f82] hover:border-[#49A8C9]/30 hover:text-[#293859]'
              }`}
            >
              {saving === choice.value ? <Loader2 size={11} className="animate-spin" /> : active ? <Check size={11} /> : null}
              {choice.label}
            </button>
          )
        })}
      </div>
      {error ? <span className="text-[11px] text-rose-600">{error}</span> : null}
    </div>
  )
}

export default InlineAnnotationChoices
