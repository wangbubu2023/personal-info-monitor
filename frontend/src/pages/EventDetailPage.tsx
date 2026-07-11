import React, { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, CheckCircle2, Clock, ExternalLink, GitMerge, MessageSquareWarning } from 'lucide-react'
import { motion } from 'framer-motion'
import { digestApi } from '../services/digest'
import { formatLocalDateTime } from '../utils/datetime'
import PageHeroTitle from '../components/common/PageHeroTitle'

const EventDetailPage: React.FC = () => {
  const { eventId = '' } = useParams()
  const queryClient = useQueryClient()
  const [note, setNote] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['event-detail', eventId],
    queryFn: () => digestApi.getEventDetail(eventId),
    enabled: Boolean(eventId),
    retry: false,
  })

  const feedbackMutation = useMutation({
    mutationFn: (type: 'event_wrong_merge' | 'event_missing_merge') => digestApi.submitEventFeedback(eventId, { type, note }),
    onSuccess: async () => {
      setNote('')
      await queryClient.invalidateQueries({ queryKey: ['event-detail', eventId] })
    },
  })

  if (isLoading) {
    return <div className="flex min-h-[50vh] items-center justify-center text-[#5f6f82]">正在加载事件…</div>
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-page px-6 py-10">
        <Link to="/digest" className="inline-flex items-center gap-2 text-sm font-medium text-[#5f6f82] hover:text-[#49A8C9]">
          <ArrowLeft size={16} /> 返回简报
        </Link>
        <div className="mt-8 rounded-2xl border border-red-200 bg-red-50 p-6 text-red-700">事件不存在或暂不可用。</div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#f5f9fc] pb-24">
      <div className="mx-auto max-w-page px-6 py-6 sm:px-8 lg:px-10">
        <Link to="/digest" className="mb-5 inline-flex items-center gap-2 text-sm font-medium text-[#5f6f82] hover:text-[#49A8C9]">
          <ArrowLeft size={16} /> 返回简报
        </Link>
        <PageHeroTitle titleZh="事件详情" titleEn="Event Detail" />

        <motion.article
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-5 rounded-3xl border border-[rgba(88,100,118,0.12)] bg-white/94 p-6 shadow-[0_18px_50px_-18px_rgba(41,56,89,0.2)] sm:p-8"
          data-testid="event-detail-page"
        >
          <div className="flex flex-col gap-4 border-b border-[rgba(88,100,118,0.1)] pb-6">
            <div className="flex flex-wrap items-center gap-2 text-[12px] font-medium text-[#5f6f82]">
              <span className="rounded-full border border-[#49A8C9]/18 bg-[#49A8C9]/8 px-2 py-0.5 text-[#3a8da9]">
                {data.independent_source_count} 个独立来源
              </span>
              {data.updated_at ? <span>更新于 {formatLocalDateTime(data.updated_at)}</span> : null}
              <span>Event ID: {data.event_id}</span>
            </div>
            <h1 className="text-[26px] font-semibold leading-tight tracking-tight text-[#293859] sm:text-[32px]">{data.title}</h1>
            <p className="text-[15px] leading-relaxed text-[#293859]">{data.current_conclusion}</p>
            {data.why_matters ? (
              <p className="rounded-2xl border border-[#8C866A]/18 bg-[#8C866A]/8 p-4 text-[14px] leading-relaxed text-[#6f684f]">
                <strong>为什么重要：</strong>{data.why_matters}
              </p>
            ) : null}
          </div>

          <section className="mt-7 grid gap-5 lg:grid-cols-[1.2fr_0.8fr]">
            <div>
              <h2 className="mb-4 flex items-center gap-2 text-[16px] font-semibold text-[#293859]">
                <Clock size={16} className="text-[#8C866A]" /> 变化时间线
              </h2>
              <div className="space-y-3">
                {data.timeline.map((item) => (
                  <article key={item.content_id} className="rounded-2xl border border-[rgba(88,100,118,0.1)] bg-[#fbfdff] p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="mb-1 flex flex-wrap items-center gap-2 text-[11px] font-semibold text-[#8C866A]">
                          <span>{item.role === 'primary' ? '主报道' : '关联报道'}</span>
                          <span>{item.source_name}</span>
                        </div>
                        <Link to={`/reader/${item.content_id}`} className="text-[15px] font-semibold text-[#293859] hover:text-[#49A8C9]">
                          {item.title}
                        </Link>
                      </div>
                      <a href={item.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-[12px] text-[#8a96a5] hover:text-[#49A8C9]">
                        原文 <ExternalLink size={12} />
                      </a>
                    </div>
                    {item.summary ? <p className="mt-2 text-[13px] leading-relaxed text-[#5f6f82]">{item.summary}</p> : null}
                    <div className="mt-2 text-[11px] text-[#8a96a5]">{item.publish_time ? formatLocalDateTime(item.publish_time) : item.fetched_at ? formatLocalDateTime(item.fetched_at) : '—'}</div>
                  </article>
                ))}
              </div>
            </div>

            <aside className="space-y-5">
              <section className="rounded-2xl border border-[rgba(88,100,118,0.1)] bg-[#fbfdff] p-4">
                <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-[#293859]">
                  <GitMerge size={15} className="text-[#8C866A]" /> 独立验证
                </h2>
                <div className="space-y-2 text-[13px] text-[#5f6f82]">
                  {data.independent_verification?.length ? data.independent_verification.map((group) => (
                    <div key={group.key} className="flex items-center justify-between rounded-xl bg-white px-3 py-2">
                      <span className="font-medium text-[#293859]">{group.title}</span>
                      <span>{group.content_ids.length} 条</span>
                    </div>
                  )) : <p>暂无独立验证分组。</p>}
                </div>
              </section>

              <section className="rounded-2xl border border-[rgba(88,100,118,0.1)] bg-[#fbfdff] p-4">
                <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-[#293859]">
                  <GitMerge size={15} className="text-[#8C866A]" /> 版本快照
                </h2>
                <div className="space-y-3">
                  {data.snapshots.length ? data.snapshots.map((snapshot) => (
                    <div key={snapshot.version} className="border-l-2 border-[#8C866A]/35 pl-3">
                      <div className="text-[12px] font-semibold text-[#8C866A]">v{snapshot.version} · {snapshot.created_at ? formatLocalDateTime(snapshot.created_at) : '—'}</div>
                      {snapshot.what_changed ? <p className="mt-1 text-[13px] text-[#293859]">{snapshot.what_changed}</p> : null}
                    </div>
                  )) : <p className="text-[13px] text-[#5f6f82]">暂无版本快照。</p>}
                </div>
              </section>

              <section className="rounded-2xl border border-[rgba(88,100,118,0.1)] bg-[#fbfdff] p-4">
                <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-[#293859]">
                  <GitMerge size={15} className="text-[#8C866A]" /> 观点 / 关联讨论
                </h2>
                <div className="space-y-2 text-[13px] text-[#5f6f82]">
                  {data.related_discussions?.length ? data.related_discussions.map((group) => (
                    <div key={group.key} className="rounded-xl bg-white px-3 py-2">
                      <span className="font-medium text-[#293859]">{group.title}</span>
                      <span className="ml-2">{group.content_ids.length} 条</span>
                    </div>
                  )) : <p>暂无关联讨论。</p>}
                </div>
              </section>

              <section className="rounded-2xl border border-[rgba(88,100,118,0.1)] bg-[#fbfdff] p-4">
                <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-[#293859]">
                  <MessageSquareWarning size={15} className="text-[#8C866A]" /> 反馈误合/漏合
                </h2>
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="可选：说明哪条报道误合或漏合"
                  className="min-h-20 w-full rounded-xl border border-[rgba(88,100,118,0.12)] bg-white px-3 py-2 text-[13px] text-[#293859] outline-none focus:border-[#49A8C9]/40"
                />
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => feedbackMutation.mutate('event_wrong_merge')}
                    className="inline-flex items-center gap-1 rounded-full border border-red-200 bg-red-50 px-3 py-1.5 text-[12px] font-semibold text-red-700 hover:bg-red-100"
                  >
                    <AlertTriangle size={13} /> 误合
                  </button>
                  <button
                    type="button"
                    onClick={() => feedbackMutation.mutate('event_missing_merge')}
                    className="inline-flex items-center gap-1 rounded-full border border-[#49A8C9]/18 bg-[#49A8C9]/8 px-3 py-1.5 text-[12px] font-semibold text-[#3a8da9] hover:bg-[#49A8C9]/12"
                  >
                    <CheckCircle2 size={13} /> 漏合
                  </button>
                </div>
                {data.feedback.length ? (
                  <div className="mt-4 space-y-2 text-[12px] text-[#5f6f82]">
                    {data.feedback.map((item, index) => (
                      <div key={`${item.type}-${index}`} className="rounded-xl bg-white p-2">
                        <span className="font-semibold text-[#293859]">{item.type}</span>
                        {item.note ? <span className="ml-1">{item.note}</span> : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </section>
            </aside>
          </section>
        </motion.article>
      </div>
    </div>
  )
}

export default EventDetailPage
