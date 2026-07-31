import React, { useEffect, useState } from 'react'
import { ArrowLeft, CheckCircle2, Loader2, PauseCircle, Tags } from 'lucide-react'
import { Link } from 'react-router-dom'

import { CONTENT_TAG_CHOICES } from '../config/contentTags'
import { useRuntimeFeatures } from '../hooks/useRuntimeFeatures'
import { annotationsApi, type AnnotationLabelItem, type AnnotationTaskItem } from '../services/annotations'

type ReviewBucket = 'central' | 'migration'

const TASK_LABELS: Record<string, string> = {
  content_relevance: '内容相关性',
  content_quality: '内容质量',
  content_format_quality: '格式质量',
  content_fact_density: '事实密度',
  content_lane: '内容 Tag',
  event_correctness: '事件卡正确性',
  event_pair_relation: '事件关系',
  atom_validity: '原子有效性',
  atom_relation: '原子关系',
}

const TASK_CHOICES: Record<string, Array<{ value: string; label: string }>> = {
  content_relevance: [
    { value: 'high', label: '高' },
    { value: 'medium', label: '中' },
    { value: 'low', label: '低' },
    { value: 'unclear', label: '不确定' },
  ],
  content_quality: [
    { value: 'high', label: '高' },
    { value: 'medium', label: '中' },
    { value: 'low', label: '低' },
    { value: 'unclear', label: '不确定' },
  ],
  content_format_quality: [
    { value: 'high', label: '高' },
    { value: 'medium', label: '中' },
    { value: 'low', label: '低' },
  ],
  content_fact_density: [
    { value: 'dense', label: '密集' },
    { value: 'moderate', label: '适中' },
    { value: 'sparse', label: '稀少' },
    { value: 'unclear', label: '不确定' },
  ],
  content_lane: CONTENT_TAG_CHOICES.map(([value, label]) => ({ value, label })),
  event_correctness: [
    { value: 'correct', label: '准确' },
    { value: 'partial', label: '部分准确' },
    { value: 'incorrect', label: '错误' },
    { value: 'unclear', label: '不确定' },
  ],
  event_pair_relation: [
    { value: 'same_event', label: '同一事件' },
    { value: 'event_update', label: '事件更新' },
    { value: 'commentary', label: '评论解读' },
    { value: 'duplicate', label: '重复' },
    { value: 'unrelated', label: '无关' },
    { value: 'unclear', label: '不确定' },
  ],
  atom_validity: [
    { value: 'valid', label: '有效' },
    { value: 'partial', label: '需修正' },
    { value: 'invalid', label: '无效' },
    { value: 'unclear', label: '不确定' },
  ],
}

const VALUE_LABELS: Record<string, string> = {
  high: '高',
  medium: '中',
  low: '低',
  irrelevant: '低 / 不相关（旧值）',
  unclear: '不确定',
  correct: '准确',
  partial: '部分准确',
  incorrect: '错误',
  dense: '密集',
  moderate: '适中',
  sparse: '稀少',
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function taskContext(task: AnnotationTaskItem) {
  const context = task.context_snapshot
  const event = context.event && typeof context.event === 'object'
    ? context.event as Record<string, unknown>
    : {}
  const annotationContext = context.annotation_context && typeof context.annotation_context === 'object' && !Array.isArray(context.annotation_context)
    ? context.annotation_context as Record<string, unknown>
    : {}
  return {
    title: textValue(context.title) || textValue(event.title) || task.target_id,
    summary: textValue(context.content_excerpt)
      || textValue(context.summary)
      || textValue(event.summary),
    legacyLane: textValue(annotationContext.legacy_lane),
  }
}

function sourceName(label: AnnotationLabelItem, index: number) {
  if (label.annotator.includes('bootstrap')) return '首次标注'
  if (label.annotator.includes('formal')) return '复标'
  return `标注 ${index + 1}`
}

function historicalLabels(task: AnnotationTaskItem): AnnotationLabelItem[] {
  if (task.labels?.length) return task.labels
  const sources = Array.isArray(task.context_snapshot.annotation_context)
    ? task.context_snapshot.annotation_context
    : []
  return sources.flatMap((source, index) => {
    if (!source || typeof source !== 'object') return []
    const value = textValue((source as Record<string, unknown>).event_correctness)
    if (!value) return []
    return [{
      id: `context-${index}`,
      task_id: task.id,
      task_type: task.task_type,
      target_type: task.target_type,
      target_id: task.target_id,
      label_payload: { value },
      annotator: `imported-${textValue((source as Record<string, unknown>).tier) || index}`,
      task_status: task.status,
    }]
  })
}

const AnnotationReviewPage: React.FC = () => {
  const features = useRuntimeFeatures()
  const [bucket, setBucket] = useState<ReviewBucket>('central')
  const [items, setItems] = useState<AnnotationTaskItem[]>([])
  const [total, setTotal] = useState(0)
  const [bucketCounts, setBucketCounts] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rationales, setRationales] = useState<Record<string, string>>({})

  const load = async () => {
    setLoading(true)
    try {
      const response = await annotationsApi.getReviewQueue(bucket)
      setItems(response.items)
      setTotal(response.total)
      setBucketCounts(response.bucket_counts)
      setError(null)
    } catch {
      setError('待复核队列加载失败。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (features?.adjudication_queue_enabled) void load()
  }, [features?.adjudication_queue_enabled, bucket])

  if (features && !features.adjudication_queue_enabled) {
    return <div className="p-10 text-[#586476]">该页面只在本地开发模式开放。</div>
  }

  const resolveTask = async (task: AnnotationTaskItem, value: string) => {
    setSavingId(task.id)
    setError(null)
    try {
      if (task.status === 'needs_adjudication') {
        await annotationsApi.adjudicate(
          task.id,
          value,
          rationales[task.id]?.trim() || '对照两次历史标注和完整上下文后完成裁决。',
        )
      } else {
        await annotationsApi.submitLabel({
          task_type: task.task_type,
          target_type: task.target_type as 'content' | 'event' | 'atom' | 'event_pair' | 'atom_relation',
          target_id: task.target_id,
          secondary_target_id: task.secondary_target_id || undefined,
          schema_version: task.schema_version,
          label_payload: { value },
          context_snapshot: task.context_snapshot,
        })
      }
      setItems((current) => current.filter((item) => item.id !== task.id))
      setTotal((current) => Math.max(0, current - 1))
      setBucketCounts((current) => ({
        ...current,
        [bucket]: Math.max(0, Number(current[bucket] || 0) - 1),
      }))
    } catch {
      setError('保存失败，请稍后重试。')
    } finally {
      setSavingId(null)
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8 sm:px-10">
      <Link to="/" className="inline-flex items-center gap-2 text-sm font-semibold text-[#5f6f82] hover:text-[#49A8C9]">
        <ArrowLeft size={15} /> 返回消费流程
      </Link>
      <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-[#293859]">集中复核</h1>
          <p className="mt-2 text-sm text-[#5f6f82]">
            这里只处理必须对照多份信息才能决定的任务；普通标注留在阅读和事件消费过程中。
          </p>
        </div>
        <span className="rounded-full bg-[#293859] px-3 py-1.5 text-xs font-semibold text-white">{total} 条</span>
      </div>

      <div className="mt-6 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setBucket('central')}
          className={`rounded-full border px-4 py-2 text-sm font-semibold ${bucket === 'central' ? 'border-[#49A8C9] bg-[#49A8C9] text-white' : 'border-[#d5e1e9] bg-white text-[#5f6f82]'}`}
        >
          冲突与缺标 {bucketCounts.central ?? '—'}
        </button>
        <button
          type="button"
          onClick={() => setBucket('migration')}
          className={`inline-flex items-center gap-1.5 rounded-full border px-4 py-2 text-sm font-semibold ${bucket === 'migration' ? 'border-[#49A8C9] bg-[#49A8C9] text-white' : 'border-[#d5e1e9] bg-white text-[#5f6f82]'}`}
        >
          <Tags size={14} /> Tag 迁移 {bucketCounts.migration ?? '—'}
        </button>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[#d5e1e9] bg-[#eef3f7] px-4 py-2 text-sm text-[#7b8796]">
          <PauseCircle size={14} /> 已暂缓 {bucketCounts.deferred ?? '—'}
        </span>
      </div>

      {bucket === 'migration' ? (
        <div className="mt-4 rounded-2xl border border-sky-100 bg-sky-50/70 px-4 py-3 text-sm leading-relaxed text-[#4e6474]">
          这些不是冲突，而是旧 Lane 无法自动映射到新版 13 个 Tag 的历史样本。这里选择的是当前正确 Tag。
        </div>
      ) : null}
      {bucketCounts.deferred ? (
        <div className="mt-3 rounded-2xl border border-[#e1e7eb] bg-white/70 px-4 py-3 text-xs leading-relaxed text-[#6f7b89]">
          {bucketCounts.deferred} 条历史“不确定”事件已移出必做队列；没有新增证据前，不要求重复作答。
        </div>
      ) : null}

      {error ? <div className="mt-5 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div> : null}
      {loading ? (
        <div className="flex min-h-60 items-center justify-center text-[#5f6f82]"><Loader2 className="animate-spin" /></div>
      ) : items.length === 0 ? (
        <div className="mt-8 rounded-3xl border border-[#dce7ee] bg-white p-10 text-center text-[#5f6f82]">
          <CheckCircle2 className="mx-auto mb-3 text-emerald-600" />
          当前没有这一类待复核任务。
        </div>
      ) : (
        <div className="mt-7 space-y-5">
          {items.map((task) => {
            const context = taskContext(task)
            const choices = TASK_CHOICES[task.task_type] || []
            const labels = historicalLabels(task)
            const isConflict = task.status === 'needs_adjudication'
            return (
              <article key={task.id} className="rounded-3xl border border-[#dce7ee] bg-white p-6 shadow-sm">
                <div className="flex flex-wrap items-center gap-2 text-xs text-[#7a7358]">
                  <span className="rounded-full bg-[#f1f5f8] px-2.5 py-1 font-semibold">{TASK_LABELS[task.task_type] || task.task_type}</span>
                  <span>{isConflict ? '冲突裁决' : bucket === 'migration' ? '旧体系迁移' : '首次判断'}</span>
                  {task.source_dataset ? <span>· {task.source_dataset}</span> : null}
                </div>
                <h2 className="mt-4 text-lg font-semibold text-[#293859]">{context.title}</h2>
                {context.summary ? <p className="mt-3 max-h-52 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-[#5f6f82]">{context.summary}</p> : null}
                {context.legacyLane ? (
                  <p className="mt-3 text-xs text-[#7b8796]">旧 Lane：<span className="font-semibold text-[#4e6474]">{context.legacyLane}</span></p>
                ) : null}

                {labels.length ? (
                  <div className="mt-4 rounded-2xl border border-amber-200/70 bg-amber-50/70 p-3">
                    <div className="text-xs font-semibold text-amber-900">历史判断{isConflict ? '存在冲突，请给出最终答案' : ''}</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {labels.map((label, index) => {
                        const value = textValue(label.label_payload.value)
                        return (
                          <span key={label.id} className="rounded-full border border-amber-200 bg-white px-3 py-1 text-xs text-[#5f6f82]">
                            {sourceName(label, index)}：<strong className="text-[#293859]">{VALUE_LABELS[value] || value}</strong>
                          </span>
                        )
                      })}
                    </div>
                  </div>
                ) : null}

                {isConflict ? (
                  <textarea
                    value={rationales[task.id] || ''}
                    onChange={(event) => setRationales((current) => ({ ...current, [task.id]: event.target.value }))}
                    placeholder="可选：记录为什么选择这个最终答案"
                    className="mt-4 min-h-20 w-full rounded-xl border border-[#d5e1e9] bg-[#fbfdff] px-3 py-2 text-sm text-[#293859]"
                  />
                ) : null}
                <div className="mt-4 flex flex-wrap gap-2">
                  {choices.map((choice) => (
                    <button
                      key={choice.value}
                      type="button"
                      disabled={Boolean(savingId)}
                      onClick={() => void resolveTask(task, choice.value)}
                      className="rounded-full border border-[#49A8C9]/20 bg-[#f7fbfd] px-3 py-1.5 text-xs font-semibold text-[#3a8da9] hover:bg-[#49A8C9] hover:text-white disabled:opacity-50"
                    >
                      {savingId === task.id ? '保存中…' : choice.label}
                    </button>
                  ))}
                </div>
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default AnnotationReviewPage
