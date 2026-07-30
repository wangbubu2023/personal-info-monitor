import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { Input, Select, message } from 'antd'
import { BookOpen } from 'lucide-react'
import PageHeroTitle from '../components/common/PageHeroTitle'
import { buildReaderPath } from '../components/Dashboard/dashboardUtils'
import { SCORE_LAB_BUILD_ENABLED } from '../config/features'
import { useScoreLabEnabled } from '../hooks/useScoreLabEnabled'
import {
  scoreLabApi,
  type ScoreExplainPayload,
  type ScoreFeedbackDirection,
  type ScoreLaneDefinition,
  type ScoreLabContentSummary,
} from '../services/scoreLab'

const STATUS_OPTIONS = [
  { value: '', label: '全部状态' },
  { value: 'selected', label: 'selected' },
  { value: 'candidate', label: 'candidate' },
  { value: 'rejected', label: 'rejected' },
]

function statusBadge(status?: string | null) {
  const map: Record<string, string> = {
    selected: 'bg-[#e8f7ef] text-[#1f7a4d]',
    candidate: 'bg-[#fff6e6] text-[#9a6b00]',
    rejected: 'bg-[#f3f4f6] text-[#586476]',
  }
  const cls = map[status || ''] || 'bg-[#eef2f8] text-[#586476]'
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
      {status || '—'}
    </span>
  )
}

function DimensionRow({
  label,
  before,
  after,
  cap,
}: {
  label: string
  before?: number
  after?: number
  cap?: number
}) {
  const capped = cap !== undefined && before !== undefined && after !== undefined && after < before
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span className="text-[#586476]">{label}</span>
      <span className="font-medium text-[#293859]">
        {after?.toFixed(1) ?? '—'}
        {capped ? (
          <span className="ml-2 text-[12px] font-normal text-[#b45309]">
            (原 {before?.toFixed(1)}，cap {cap})
          </span>
        ) : null}
      </span>
    </div>
  )
}

const ScoreLabDetail: React.FC<{
  explain: ScoreExplainPayload | null
  loading: boolean
  onFeedback: (direction: ScoreFeedbackDirection, note?: string) => void
  feedbackPending: boolean
  submittedDirection: ScoreFeedbackDirection | null
}> = ({ explain, loading, onFeedback, feedbackPending, submittedDirection }) => {
  const [note, setNote] = useState('')

  useEffect(() => {
    setNote('')
  }, [explain?.content?.id])

  if (loading) {
    return <div className="p-8 text-sm text-[#586476]">正在解析得分…</div>
  }
  if (!explain) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-sm text-[#8a96a5]">
        从左侧选择一篇文章查看得分拆解
      </div>
    )
  }

  const score = explain.recomputed.article_score
  const caps = explain.impact_caps_applied || {}

  return (
    <div className="space-y-5 p-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-3xl font-semibold text-[#293859]">{score.toFixed(1)}</span>
          {statusBadge(explain.recomputed.selection_status)}
          {explain.score_delta != null && Math.abs(explain.score_delta) >= 0.05 ? (
            <span className="text-[12px] text-[#b45309]">
              与库内差 {explain.score_delta > 0 ? '+' : ''}
              {explain.score_delta.toFixed(1)}
            </span>
          ) : null}
        </div>
        <h2 className="mt-3 text-base font-semibold leading-snug text-[#293859]">
          {explain.content?.title || explain.scoring_title}
        </h2>
        <p className="mt-1 text-[12px] text-[#8a96a5]">
          {explain.content?.source_name || '—'} · {explain.lane_label} · {explain.score_version}
        </p>
      </div>

      <section className="rounded-2xl border border-[rgba(88,100,118,0.1)] bg-white p-4">
        <h3 className="text-sm font-semibold text-[#293859]">合分公式</h3>
        <div className="mt-3 space-y-2">
          {explain.weight_breakdown.map((row) => (
            <div key={row.dimension} className="flex justify-between text-sm">
              <span className="text-[#586476]">
                {row.label} {row.score.toFixed(1)} × {Math.round(row.weight * 100)}%
              </span>
              <span className="font-medium text-[#293859]">{row.weighted.toFixed(2)}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 border-t border-[rgba(88,100,118,0.08)] pt-3 text-sm text-[#586476]">
          加权和 {explain.weighted_sum_0_10.toFixed(2)} × 10 ={' '}
          <span className="font-semibold text-[#293859]">{score.toFixed(1)}</span>
        </p>
        <p className="mt-1 text-[12px] text-[#8a96a5]">
          阈值：selected ≥ {explain.thresholds.selected}，candidate ≥ {explain.thresholds.candidate}
        </p>
      </section>

      <section className="rounded-2xl border border-[rgba(88,100,118,0.1)] bg-white p-4">
        <h3 className="text-sm font-semibold text-[#293859]">五维得分</h3>
        <div className="mt-3 space-y-2">
          <DimensionRow label="显著性" before={explain.dimension_scores_before_cap.salience} after={explain.dimension_scores.salience} cap={caps.salience} />
          <DimensionRow label="影响面" before={explain.dimension_scores_before_cap.reach} after={explain.dimension_scores.reach} cap={caps.reach} />
          <DimensionRow label="权威" before={explain.dimension_scores_before_cap.authority} after={explain.dimension_scores.authority} cap={caps.authority} />
          <DimensionRow label="深度" before={explain.dimension_scores_before_cap.depth} after={explain.dimension_scores.depth} cap={caps.depth} />
          <DimensionRow label="主观" before={explain.dimension_scores_before_cap.subjective} after={explain.dimension_scores.subjective} />
        </div>
        {explain.impact_cap_scope ? (
          <p className="mt-3 text-[12px] text-[#b45309]">impact cap：{explain.impact_cap_scope}</p>
        ) : null}
      </section>

      <section className="rounded-2xl border border-[rgba(88,100,118,0.1)] bg-white p-4 text-sm">
        <h3 className="font-semibold text-[#293859]">命中与语料</h3>
        <div className="mt-3 space-y-2 text-[#586476]">
          <p>reach 档位：{explain.reach_level}</p>
          {explain.matched_signals.commerce.length ? (
            <p>commerce 信号：{explain.matched_signals.commerce.join('、')}</p>
          ) : null}
          {explain.matched_signals.narrow.length ? (
            <p>narrow 信号：{explain.matched_signals.narrow.join('、')}</p>
          ) : null}
          {explain.entity_hits.length ? (
            <p>
              实体命中：
              {explain.entity_hits.slice(0, 6).map((h) => `${h.term}(${h.tier})`).join('、')}
            </p>
          ) : null}
          {explain.user_keywords.matched.length ? (
            <p>用户关键词：{explain.user_keywords.matched.join('、')}</p>
          ) : null}
          <p className="text-[12px] leading-relaxed text-[#8a96a5]">
            headline 语料：{explain.corpus.headline.slice(0, 180)}
            {explain.corpus.headline.length > 180 ? '…' : ''}
          </p>
          <p>
            验收 / 正文：{explain.fetch_acceptance || '—'} · {explain.fulltext_status || '—'}
          </p>
        </div>
      </section>

      <section className="rounded-2xl border border-[rgba(88,100,118,0.1)] bg-[#f6fafc] p-4">
        <h3 className="text-sm font-semibold text-[#293859]">人工反馈</h3>
        <Input.TextArea
          rows={2}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="可选备注，例如「促销文不应进 selected」"
          className="mt-3"
        />
        <div className="mt-3 flex flex-wrap gap-2">
          {([
            ['too_high', '偏高'],
            ['too_low', '偏低'],
            ['ok', '合理'],
          ] as const).map(([dir, label]) => {
            const isSubmitted = dir === submittedDirection
            return (
              <button
                key={dir}
                type="button"
                disabled={feedbackPending}
                onClick={() => onFeedback(dir, note.trim() || undefined)}
                className={
                  isSubmitted
                    ? 'rounded-xl border border-[#1f7a4d] bg-[#e8f7ef] px-3 py-1.5 text-sm font-medium text-[#1f7a4d] disabled:opacity-50'
                    : 'rounded-xl border border-[rgba(88,100,118,0.15)] bg-white px-3 py-1.5 text-sm font-medium text-[#293859] hover:border-[#49A8C9] hover:text-[#49A8C9] disabled:opacity-50'
                }
              >
                {isSubmitted ? `✓ ${label}（已记录）` : label}
              </button>
            )
          })}
        </div>
        {submittedDirection && (
          <p className="mt-2 text-[12px] text-[#8a96a5]">点击其他选项可重新提交</p>
        )}
      </section>

      {explain.content?.id ? (
        <Link
          to={buildReaderPath(explain.content.id, { from: 'score-lab' })}
          className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#49A8C9] hover:text-[#3d94b3]"
        >
          <BookOpen size={14} />
          在阅读器打开
        </Link>
      ) : null}
    </div>
  )
}

const ScoreLabPage: React.FC = () => {
  const scoreLabEnabled = useScoreLabEnabled()
  const [searchParams, setSearchParams] = useSearchParams()
  const [items, setItems] = useState<ScoreLabContentSummary[]>([])
  const [laneDefinitions, setLaneDefinitions] = useState<ScoreLaneDefinition[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [explain, setExplain] = useState<ScoreExplainPayload | null>(null)
  const [explainLoading, setExplainLoading] = useState(false)
  const [feedbackPending, setFeedbackPending] = useState(false)
  const [submittedFeedback, setSubmittedFeedback] = useState<ScoreFeedbackDirection | null>(null)

  const filters = useMemo(
    () => ({
      selection_status: searchParams.get('selection_status') ?? '',
      lane: searchParams.get('lane') ?? '',
      search: searchParams.get('search') ?? '',
      selected: searchParams.get('id') ?? '',
    }),
    [searchParams],
  )

  const loadList = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await scoreLabApi.listContents({
        selection_status: filters.selection_status || undefined,
        lane: filters.lane || undefined,
        search: filters.search || undefined,
      })
      setItems(data.items)
      setTotal(data.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [filters.lane, filters.search, filters.selection_status])

  const loadExplain = useCallback(async (contentId: string) => {
    setExplainLoading(true)
    try {
      const data = await scoreLabApi.explain(contentId)
      setExplain(data)
    } catch (err) {
      message.error(err instanceof Error ? err.message : '解析失败')
      setExplain(null)
    } finally {
      setExplainLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadList()
  }, [loadList])

  useEffect(() => {
    void scoreLabApi.listLanes()
      .then(setLaneDefinitions)
      .catch(() => message.error('Lane 分类加载失败'))
  }, [])

  useEffect(() => {
    setSubmittedFeedback(null)
  }, [filters.selected])

  useEffect(() => {
    if (filters.selected) {
      void loadExplain(filters.selected)
    } else if (items[0]?.id) {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        next.set('id', items[0].id)
        return next
      }, { replace: true })
    } else {
      setExplain(null)
    }
  }, [filters.selected, items, loadExplain, setSearchParams])

  const handleFeedback = async (direction: ScoreFeedbackDirection, note?: string) => {
    const contentId = explain?.content?.id || filters.selected
    if (!contentId) return
    setFeedbackPending(true)
    try {
      await scoreLabApi.submitFeedback({ content_id: contentId, direction, note })
      setSubmittedFeedback(direction)
      message.success('反馈已记录')
    } catch (err) {
      message.error(err instanceof Error ? err.message : '提交失败')
    } finally {
      setFeedbackPending(false)
    }
  }

  if (!SCORE_LAB_BUILD_ENABLED) {
    return <Navigate to="/" replace />
  }
  if (!scoreLabEnabled) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-16 text-center">
        <p className="text-[#586476]">评分实验室已在设置中关闭。</p>
        <Link to="/settings?tab=score-lab" className="mt-4 inline-block text-[#49A8C9]">
          前往设置开启
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-full min-h-0 max-w-[1400px] flex-col px-4 py-6 sm:px-6">
      <PageHeroTitle titleZh="评分实验室" titleEn="Score Lab" />
      <p className="mb-4 text-sm text-[#586476]">
        最新 50 篇入库内容，按分数从高到低排列；点击标题进入阅读器，点击条目查看得分拆解。
      </p>

      <div className="mb-4 flex flex-wrap gap-3">
        <Select
          value={filters.selection_status}
          options={STATUS_OPTIONS}
          className="min-w-[140px]"
          onChange={(value) =>
            setSearchParams((prev) => {
              const next = new URLSearchParams(prev)
              if (value) next.set('selection_status', value)
              else next.delete('selection_status')
              next.delete('id')
              return next
            })
          }
        />
        <Select
          value={filters.lane}
          options={[
            { value: '', label: '全部分类' },
            ...laneDefinitions.map((lane) => ({
              value: lane.value,
              label: `${lane.label_zh} / ${lane.label_en}`,
              title: lane.description,
            })),
          ]}
          className="min-w-[220px]"
          onChange={(value) =>
            setSearchParams((prev) => {
              const next = new URLSearchParams(prev)
              if (value) next.set('lane', value)
              else next.delete('lane')
              next.delete('id')
              return next
            })
          }
        />
        <Input.Search
          allowClear
          placeholder="搜索标题"
          defaultValue={filters.search}
          onSearch={(value) =>
            setSearchParams((prev) => {
              const next = new URLSearchParams(prev)
              if (value.trim()) next.set('search', value.trim())
              else next.delete('search')
              next.delete('id')
              return next
            })
          }
          className="max-w-xs"
        />
      </div>

      {error ? <p className="mb-3 text-sm text-red-600">{error}</p> : null}

      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
        <div className="overflow-hidden rounded-2xl border border-[rgba(88,100,118,0.12)] bg-white">
          <div className="border-b border-[rgba(88,100,118,0.08)] px-4 py-3 text-sm text-[#586476]">
            最新 {total} 篇 · 按分数排序
          </div>
          <div className="max-h-[calc(100vh-280px)] overflow-y-auto">
            {loading ? (
              <p className="p-4 text-sm text-[#8a96a5]">加载中…</p>
            ) : (
              items.map((item) => {
                const active = item.id === filters.selected
                const readerPath = buildReaderPath(item.id, { from: 'score-lab' })
                return (
                  <div
                    key={item.id}
                    role="button"
                    tabIndex={0}
                    onClick={() =>
                      setSearchParams((prev) => {
                        const next = new URLSearchParams(prev)
                        next.set('id', item.id)
                        return next
                      })
                    }
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSearchParams((prev) => {
                          const next = new URLSearchParams(prev)
                          next.set('id', item.id)
                          return next
                        })
                      }
                    }}
                    className={`block w-full cursor-pointer border-b border-[rgba(88,100,118,0.06)] px-4 py-3 text-left transition-colors ${
                      active ? 'bg-[#eef7fb]' : 'hover:bg-[#f6fafc]'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-lg font-semibold text-[#293859]">
                        {item.article_score?.toFixed(1) ?? '—'}
                      </span>
                      <div className="flex items-center gap-2">
                        {statusBadge(item.selection_status)}
                        <Link
                          to={readerPath}
                          onClick={(e) => e.stopPropagation()}
                          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold text-[#49A8C9] hover:bg-[#eef7fb]"
                          title="在阅读器打开"
                        >
                          <BookOpen size={12} />
                          阅读
                        </Link>
                      </div>
                    </div>
                    <Link
                      to={readerPath}
                      onClick={(e) => e.stopPropagation()}
                      className="mt-1 line-clamp-2 block text-sm font-medium text-[#293859] hover:text-[#49A8C9]"
                    >
                      {item.title}
                    </Link>
                    <p className="mt-1 text-[11px] text-[#8a96a5]">
                      {item.source_name || '—'} · {item.lane_label || item.lane || '—'}
                    </p>
                  </div>
                )
              })
            )}
          </div>
        </div>

        <div className="overflow-y-auto rounded-2xl border border-[rgba(88,100,118,0.12)] bg-[#fafcfe]">
          <ScoreLabDetail
            explain={explain}
            loading={explainLoading}
            onFeedback={handleFeedback}
            feedbackPending={feedbackPending}
            submittedDirection={submittedFeedback}
          />
        </div>
      </div>
    </div>
  )
}

export default ScoreLabPage
