import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Empty, Spin } from 'antd'
import { Clock3, Network, RefreshCw } from 'lucide-react'

import PageHeroTitle from '../components/common/PageHeroTitle'
import { digestApi } from '../services/digest'
import { formatLocalDateTime } from '../utils/datetime'

const WINDOWS = [
  { hours: 24, label: '最近 24 小时' },
  { hours: 168, label: '最近 7 天' },
  { hours: 720, label: '最近 30 天' },
]

const EventsPage: React.FC = () => {
  const [hours, setHours] = useState(168)
  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['event-feed', hours],
    queryFn: () => digestApi.getEventFeed(hours),
  })

  const items = data?.items ?? []

  return (
    <div className="min-h-screen bg-[#f5f9fc] pb-20" data-testid="events-page">
      <div className="mx-auto max-w-page px-6 pt-5 sm:px-8 lg:px-10">
        <div className="flex flex-col gap-4 border-b border-[rgba(88,100,118,0.1)] pb-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <PageHeroTitle titleZh="事件" titleEn="Events" />
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-[#5f6f82]">
              浏览已经形成的事件卡，包括尚未达到“今日重点”门槛的单一来源事件。
            </p>
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex h-9 items-center justify-center gap-2 self-start rounded-lg bg-[#49A8C9] px-4 text-[13px] font-semibold text-white disabled:opacity-60 sm:self-auto"
          >
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} /> 刷新
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {WINDOWS.map((window) => (
            <button
              key={window.hours}
              type="button"
              onClick={() => setHours(window.hours)}
              className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
                hours === window.hours
                  ? 'border-[#49A8C9] bg-[#49A8C9] text-white'
                  : 'border-[rgba(88,100,118,0.14)] bg-white text-[#5f6f82]'
              }`}
            >
              {window.label}
            </button>
          ))}
          <span className="ml-auto text-xs text-[#7b8796]">
            已显示 {items.length || '—'} / 共 {data?.total ?? '—'} 个事件
          </span>
        </div>

        {isLoading ? (
          <div className="flex h-72 items-center justify-center"><Spin /></div>
        ) : items.length ? (
          <div className="mt-5 space-y-3">
            {items.map((event) => (
              <Link
                key={event.event_id}
                to={`/events/${event.event_id}`}
                className="group block rounded-2xl border border-[rgba(88,100,118,0.11)] bg-white/94 p-5 shadow-[0_12px_36px_-28px_rgba(41,56,89,0.35)] transition-all hover:border-[#49A8C9]/30 hover:shadow-[0_18px_42px_-28px_rgba(41,56,89,0.42)]"
              >
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] font-semibold text-[#7a7358]">
                      <span className="inline-flex items-center gap-1 rounded-full bg-[#eef4f8] px-2 py-1">
                        <Network size={11} /> 事件
                      </span>
                      <span>{event.independent_source_count || 1} 个独立来源</span>
                      {typeof event.importance_score === 'number' ? <span>重要度 {Math.round(event.importance_score)}</span> : null}
                      {event.has_updates ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700">有更新</span> : null}
                    </div>
                    <h2 className="text-[17px] font-semibold leading-snug text-[#293859] transition-colors group-hover:text-[#3a8da9]">
                      {event.title}
                    </h2>
                    {event.summary ? (
                      <p className="mt-2 line-clamp-2 text-[13px] leading-relaxed text-[#5f6f82]">{event.summary}</p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5 text-[11px] text-[#8a96a5]">
                    <Clock3 size={12} />
                    {event.updated_at ? formatLocalDateTime(event.updated_at) : '—'}
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {event.source_names.slice(0, 4).map((source) => (
                    <span key={source} className="rounded-full border border-[rgba(88,100,118,0.1)] bg-[#fbfdff] px-2 py-0.5 text-[10px] text-[#7b8796]">
                      {source}
                    </span>
                  ))}
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="mt-8 rounded-3xl border border-[rgba(88,100,118,0.1)] bg-white py-20">
            <Empty description="这个时间范围内还没有形成事件卡。" />
          </div>
        )}
      </div>
    </div>
  )
}

export default EventsPage
