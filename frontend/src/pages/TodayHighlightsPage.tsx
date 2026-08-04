import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { DatePicker, Empty, Spin } from 'antd'
import dayjs from 'dayjs'
import { Calendar, Layers3, Newspaper, RefreshCw, Sparkles } from 'lucide-react'
import PageHeroTitle from '../components/common/PageHeroTitle'
import { digestApi } from '../services/digest'
import { formatLocalDateTime } from '../utils/datetime'

const iconStroke = 1.6

const TodayHighlightsPage: React.FC = () => {
  const [selectedDate, setSelectedDate] = useState(dayjs())
  const selectedDateString = selectedDate.format('YYYY-MM-DD')

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['today-highlights-page', selectedDateString],
    queryFn: () => digestApi.getTodayHighlights(selectedDateString),
  })

  const items = data?.items ?? []
  const eventCount = items.length

  return (
    <div className="min-h-screen bg-[#f5f9fc] pb-20" data-testid="today-highlights-page">
      <div className="mx-auto max-w-page pl-5 pr-6 sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10">
        <div className="flex flex-col gap-3.5 border-b border-[rgba(88,100,118,0.1)] pb-3 pt-4 sm:gap-4 sm:pt-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <PageHeroTitle titleZh="今日重点" titleEn="Today Highlights" data-testid="today-highlights-title" />
            <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
              <div className="flex items-center gap-1.5 rounded-lg border border-[rgba(88,100,118,0.1)] bg-white/95 px-2.5 py-1.5 shadow-sm">
                <Calendar size={15} className="ml-0.5 shrink-0 text-[#5f6f82]" strokeWidth={iconStroke} />
                <DatePicker
                  value={selectedDate}
                  onChange={(date) => {
                    if (date) setSelectedDate(date)
                  }}
                  allowClear={false}
                  size="small"
                  className="!min-w-0 !border-none !bg-transparent !shadow-none !text-[13px] !text-[#4a5a6e] hover:!text-[#2c3a50] focus:!text-[#2c3a50]"
                  suffixIcon={null}
                />
              </div>
              <button
                type="button"
                onClick={() => refetch()}
                disabled={isFetching}
                className="flex h-9 shrink-0 items-center justify-center gap-2 rounded-lg border border-[#49A8C9]/28 bg-[#49A8C9] px-4 text-[13px] font-medium text-white shadow-sm shadow-[#49A8C9]/15 transition-all hover:bg-[#3d94b3] disabled:cursor-not-allowed disabled:bg-[#9ecfe0]"
              >
                <RefreshCw size={14} strokeWidth={iconStroke} className={isFetching ? 'animate-spin' : ''} />
                刷新
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-2 rounded-lg border border-[rgba(88,100,118,0.08)] bg-white/90 px-2.5 py-1.5 shadow-sm">
              <Layers3 className="h-3.5 w-3.5 shrink-0 text-[#8C866A]" strokeWidth={iconStroke} />
              <span className="text-[12px] text-[#5f6f82]">重点事件</span>
              <span className="text-[14px] font-semibold tabular-nums text-[#2c3a50]">{eventCount}</span>
            </div>
            <div className="rounded-lg border border-[rgba(88,100,118,0.08)] bg-white/90 px-2.5 py-1.5 text-[12px] font-medium text-[#5f6f82] shadow-sm">
              滚动 48 小时
            </div>
            <Link
              to="/timeline"
              className="inline-flex items-center gap-1.5 rounded-lg border border-[rgba(88,100,118,0.08)] bg-white/90 px-2.5 py-1.5 text-[12px] font-medium text-[#5f6f82] shadow-sm transition-colors hover:text-[#49A8C9]"
            >
              <Newspaper className="h-3.5 w-3.5" strokeWidth={iconStroke} />
              查看全部动态
            </Link>
          </div>
        </div>
      </div>

      <div className="mx-auto mt-5 max-w-page pl-5 pr-6 sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10">
        {isLoading ? (
          <div className="flex h-72 items-center justify-center rounded-3xl border border-[rgba(88,100,118,0.1)] bg-white/90">
            <Spin />
          </div>
        ) : items.length ? (
          <div className="grid gap-4 lg:grid-cols-2" data-testid="today-highlight-cards">
            {items.map((eventItem) => (
              <Link
                key={eventItem.event_id}
                to={`/events/${eventItem.event_id}`}
                className="group rounded-3xl border border-[rgba(88,100,118,0.12)] bg-white/92 p-5 shadow-[0_18px_50px_-24px_rgba(41,56,89,0.2)] transition-all hover:border-[#49A8C9]/28 hover:bg-white hover:shadow-[0_18px_48px_-20px_rgba(41,56,89,0.25)]"
              >
                <div className="mb-3 flex items-center justify-between gap-3 text-[11px] font-semibold uppercase tracking-wide text-[#8C866A]">
                  <span className="inline-flex items-center gap-1.5">
                    <Sparkles size={12} strokeWidth={iconStroke} />
                    事件
                  </span>
                  <span className="flex items-center gap-1.5">
                    {typeof eventItem.importance_score === 'number' ? <span>{Math.round(eventItem.importance_score)}分</span> : null}
                  </span>
                </div>
                <h2 className="text-[18px] font-semibold leading-snug tracking-tight text-[#293859] transition-colors group-hover:text-[#49A8C9]">
                  {eventItem.title}
                </h2>
                {eventItem.what_changed ? (
                  <p className="mt-3 text-[13px] leading-relaxed text-[#7a7358]">
                    <span className="font-semibold">变化：</span>{eventItem.what_changed}
                  </p>
                ) : null}
                {eventItem.why_matters ? (
                  <p className="mt-2 text-[13px] leading-relaxed text-[#5f6f82]">
                    <span className="font-semibold text-[#293859]">为什么重要：</span>{eventItem.why_matters}
                  </p>
                ) : null}
                <div className="mt-4 flex flex-wrap items-center gap-2 text-[12px] text-[#5f6f82]">
                  <span className="rounded-full border border-[#49A8C9]/18 bg-[#49A8C9]/8 px-2 py-0.5 text-[#3a8da9]">
                    {eventItem.independent_source_count || eventItem.source_names.length} 个独立来源
                  </span>
                  {eventItem.updated_at ? <span>{formatLocalDateTime(eventItem.updated_at)}</span> : null}
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="rounded-3xl border border-[rgba(88,100,118,0.1)] bg-white/92 py-20 shadow-[0_18px_50px_-24px_rgba(41,56,89,0.16)]">
            <Empty description="所选 48 小时窗口内暂无由至少两个独立信源聚合形成的事件。你仍可在全部动态查看 RSS、X 和网站信息流。" />
            <div className="mt-5 flex justify-center">
              <Link
                to="/timeline"
                className="rounded-lg border border-[#49A8C9]/28 bg-[#49A8C9] px-4 py-2 text-[13px] font-medium text-white shadow-sm shadow-[#49A8C9]/15 transition-all hover:bg-[#3d94b3]"
              >
                查看全部动态
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default TodayHighlightsPage
