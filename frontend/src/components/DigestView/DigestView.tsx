import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { DatePicker, Spin, Empty } from 'antd';
import { 
  Clock, 
  FileText, 
  ChevronRight, 
  Calendar, 
  ArrowLeft,
  Zap,
  BarChart3,
  ExternalLink,
  Gauge,
  Star,
  Layers3,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import dayjs from 'dayjs';
import { digestApi } from '../../services/digest';
import type { HourlyDigestSummary, HourlyDigestDetail } from '../../services/digest';
import type { DigestItem } from '../../types';
import { formatLocalDateTime } from '../../utils/datetime';
import PageHeroTitle from '../common/PageHeroTitle';
import {
  buildReaderPath,
  getDigestItemFinalScore,
  getDigestItemFulltextStatusLabel,
  getDigestItemRecommendationReason,
  getDigestItemSourceStars,
} from '../Dashboard/dashboardUtils';

const renderInlineMarkdown = (text: string): React.ReactNode[] => {
  const nodes: React.ReactNode[] = [];
  const linkRegex = /\[([^\]]+)\]\((https?:\/\/[^\s)]+|\/reader\/[^\s)]+)\)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null = null;
  let key = 0;

  const pushBoldSegments = (segment: string) => {
    const parts = segment.split(/\*\*(.*?)\*\*/);
    parts.forEach((part, idx) => {
      if (!part) return;
      if (idx % 2 === 1) {
        nodes.push(<strong key={`b-${key++}`} className="font-semibold text-[#293859]">{part}</strong>);
      } else {
        nodes.push(<span key={`t-${key++}`}>{part}</span>);
      }
    });
  };

  while ((match = linkRegex.exec(text)) !== null) {
    const [full, label, url] = match;
    if (match.index > lastIndex) {
      pushBoldSegments(text.slice(lastIndex, match.index));
    }
    nodes.push(
      <a 
        key={`a-${key++}`} 
        href={url} 
        target="_blank" 
        rel="noopener noreferrer"
        className="font-medium text-[#49A8C9] underline decoration-[#49A8C9]/35 underline-offset-4 hover:text-[#3d94b3]"
      >
        {label}
      </a>
    );
    lastIndex = match.index + full.length;
  }

  if (lastIndex < text.length) {
    pushBoldSegments(text.slice(lastIndex));
  }

  return nodes;
};

const renderQualityBadges = (item: DigestItem) => {
  const finalScore = getDigestItemFinalScore(item);
  const sourceStars = getDigestItemSourceStars(item);
  const fulltextLabel = getDigestItemFulltextStatusLabel(item);
  return (
    <>
      {sourceStars ? (
        <span className="inline-flex items-center gap-1 rounded-full border border-[#8C866A]/18 bg-[#8C866A]/8 px-2 py-0.5 text-[#7a7358]">
          <Star size={11} className="shrink-0 fill-current" strokeWidth={1.5} />
          {sourceStars}星
        </span>
      ) : null}
      {finalScore !== undefined ? (
        <span className="inline-flex items-center gap-1 rounded-full border border-[#49A8C9]/18 bg-[#49A8C9]/8 px-2 py-0.5 text-[#3a8da9]">
          <Gauge size={11} className="shrink-0" strokeWidth={1.5} />
          {Math.round(finalScore)}分
        </span>
      ) : null}
      {fulltextLabel ? (
        <span className="inline-flex items-center gap-1 rounded-full border border-[#5f6f82]/14 bg-[#eef4f8] px-2 py-0.5 text-[#5f6f82]">
          <FileText size={11} className="shrink-0" strokeWidth={1.5} />
          {fulltextLabel}
        </span>
      ) : null}
    </>
  );
};

const estimateReadingMinutes = (count: number, minutesPerItem = 1.5) => Math.max(1, Math.ceil(Math.max(1, count) * minutesPerItem));

const DigestView: React.FC = () => {
  const [selectedDate, setSelectedDate] = useState(dayjs());
  const [selectedHour, setSelectedHour] = useState<number | null>(null);

  const selectedDateString = selectedDate.format('YYYY-MM-DD');

  const { data: hourlyDigests, isLoading: listLoading } = useQuery<HourlyDigestSummary[]>({
    queryKey: ['hourly-digests', selectedDateString],
    queryFn: () => digestApi.getHourlyDigests(selectedDateString),
  });

  const { data: todayHighlights, isLoading: highlightsLoading } = useQuery({
    queryKey: ['today-highlights', selectedDateString],
    queryFn: () => digestApi.getTodayHighlights(selectedDateString),
  });

  const { data: digestDetail, isLoading: detailLoading } = useQuery<HourlyDigestDetail | null>({
    queryKey: ['hourly-digest-detail', selectedDateString, selectedHour],
    queryFn: () => {
      if (selectedHour === null) return Promise.resolve(null);
      return digestApi.getHourlyDigestDetail(selectedHour, selectedDateString);
    },
    enabled: selectedHour !== null,
  });

  const topEventTitles = todayHighlights?.items?.slice(0, 3).map((item) => item.title) ?? [];
  const selectedEventCount = digestDetail?.event_items?.length ?? 0;
  const selectedMaterialCount = digestDetail?.items?.length ?? digestDetail?.content_count ?? 0;

  return (
    <div className="min-h-screen bg-[#f5f9fc] pb-24" data-testid="digest-page">
      <div className="mx-auto max-w-page pl-5 pr-6 sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10">
        <div className="flex flex-col gap-3.5 border-b border-[rgba(88,100,118,0.1)] pb-3 pt-4 sm:gap-4 sm:pt-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
            <PageHeroTitle
              titleZh="个人简报"
              titleEn="Personal Digest"
              data-testid="digest-title"
            />
            <div className="flex shrink-0 items-center gap-1.5 rounded-lg border border-[rgba(88,100,118,0.1)] bg-white/95 px-2.5 py-1.5 shadow-sm sm:justify-end">
              <Calendar size={15} className="ml-0.5 shrink-0 text-[#5f6f82]" strokeWidth={1.5} />
              <DatePicker
                value={selectedDate}
                onChange={(date) => {
                  if (date) {
                    setSelectedDate(date);
                    setSelectedHour(null);
                  }
                }}
                allowClear={false}
                size="small"
                className="!min-w-0 !border-none !bg-transparent !shadow-none !text-[13px] !text-[#4a5a6e] hover:!text-[#2c3a50] focus:!text-[#2c3a50]"
                suffixIcon={null}
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <div className="flex items-center gap-2 rounded-lg border border-[rgba(88,100,118,0.08)] bg-white/90 px-2.5 py-1.5 shadow-sm">
              <BarChart3 className="h-3.5 w-3.5 shrink-0 text-[#3a9eb8]" strokeWidth={1.5} />
              <span className="text-[12px] text-[#5f6f82]">可选简报</span>
              <span className="text-[14px] font-semibold tabular-nums text-[#2c3a50]">{hourlyDigests?.length || 0}</span>
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-[rgba(88,100,118,0.08)] bg-white/90 px-2.5 py-1.5 shadow-sm">
              <Layers3 className="h-3.5 w-3.5 shrink-0 text-[#8C866A]" strokeWidth={1.5} />
              <span className="text-[12px] text-[#5f6f82]">今日看点</span>
              <span className="text-[14px] font-semibold tabular-nums text-[#2c3a50]">{todayHighlights?.items?.length || 0}</span>
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-[rgba(88,100,118,0.08)] bg-white/90 px-2.5 py-1.5 shadow-sm">
              <Clock className="h-3.5 w-3.5 shrink-0 text-[#6d684f]" strokeWidth={1.5} />
              <span className="text-[12px] text-[#5f6f82]">预计阅读</span>
              <span className="text-[14px] font-semibold tabular-nums text-[#2c3a50]">
                {todayHighlights?.items?.length ? `${estimateReadingMinutes(todayHighlights.items.length)} 分钟` : '—'}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto mt-5 max-w-page pl-5 pr-6 sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10">
        <AnimatePresence mode="wait">
          {selectedHour === null ? (
            // Hourly List View
            <motion.div
              key="list"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="space-y-3"
            >
              {listLoading ? (
                <div className="flex h-64 items-center justify-center">
                  <Spin indicator={<Zap className="animate-pulse text-[#49A8C9]" size={32} />} />
                </div>
              ) : hourlyDigests && hourlyDigests.length > 0 ? (
                <>
                  {highlightsLoading ? null : topEventTitles.length ? (
                    <section
                      className="mb-5 rounded-3xl border border-[#8C866A]/18 bg-white/90 p-5 shadow-[0_18px_50px_-22px_rgba(41,56,89,0.22)] sm:p-6"
                      data-testid="digest-today-brief-overview"
                    >
                      <div className="mb-5 rounded-2xl border border-[#49A8C9]/12 bg-[#eef4f8]/75 p-4">
                        <div className="mb-2 flex items-center justify-between gap-3">
                          <h2 className="flex items-center gap-2 text-[16px] font-semibold tracking-tight text-[#293859]">
                            <Zap size={16} className="text-[#49A8C9]" strokeWidth={1.75} />
                            今日看点
                          </h2>
                          <span className="rounded-full border border-[#49A8C9]/18 bg-white/80 px-2.5 py-1 text-[12px] font-semibold text-[#3a8da9]">
                            {todayHighlights?.items?.length || 0} 个事件 · 约 {estimateReadingMinutes(todayHighlights?.items?.length || 0)} 分钟
                          </span>
                        </div>
                        <div className="grid gap-2 md:grid-cols-3">
                          {topEventTitles.map((title, idx) => (
                            <div key={`${idx}-${title}`} className="rounded-xl bg-white/80 px-3 py-2 text-[13px] font-medium leading-snug text-[#293859]">
                              {idx + 1}. {title}
                            </div>
                          ))}
                        </div>
                      </div>
                      <div className="mb-4 flex items-center justify-between gap-3">
                        <div>
                          <h2 className="flex items-center gap-2 text-[18px] font-semibold tracking-tight text-[#293859]">
                            <Layers3 size={18} className="text-[#8C866A]" strokeWidth={1.75} />
                            今日重点
                          </h2>
                          <p className="mt-1 text-[12px] text-[#5f6f82]">
                            事件级卡片只在简报页展示；资讯页卡继续保留完整 timeline。
                          </p>
                        </div>
                        <span className="rounded-full border border-[#49A8C9]/18 bg-[#49A8C9]/8 px-2.5 py-1 text-[12px] font-semibold text-[#3a8da9]">
                          {todayHighlights?.items?.length || 0} 个事件
                        </span>
                      </div>
                      <div className="grid gap-3 lg:grid-cols-3">
                        {(todayHighlights?.items ?? []).map((eventItem) => (
                          <Link
                            key={eventItem.event_id}
                            to={`/events/${eventItem.event_id}`}
                            className="group rounded-2xl border border-[rgba(88,100,118,0.12)] bg-[#fbfdff] p-4 transition-all hover:border-[#49A8C9]/28 hover:bg-white hover:shadow-[0_12px_32px_-22px_rgba(41,56,89,0.25)]"
                          >
                            <div className="mb-2 flex items-center justify-between gap-2 text-[11px] font-semibold uppercase tracking-wide text-[#8C866A]">
                              <span>{eventItem.section === 'brewing' ? '酝酿中' : '必看'}</span>
                              <span className="flex items-center gap-1.5">
                                {eventItem.has_updates ? (
                                  <span className="rounded-full bg-[#fff7ed] px-1.5 py-0.5 text-[10px] text-[#b45309]" data-testid="today-highlight-update-badge">有更新</span>
                                ) : null}
                                {typeof eventItem.importance_score === 'number' ? <span>{Math.round(eventItem.importance_score)}分</span> : null}
                              </span>
                            </div>
                            <h3 className="line-clamp-2 text-[15px] font-semibold leading-snug text-[#293859] group-hover:text-[#49A8C9]">
                              {eventItem.title}
                            </h3>
                            {eventItem.why_matters ? (
                              <p className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-[#5f6f82]">
                                {eventItem.why_matters}
                              </p>
                            ) : null}
                            {eventItem.what_changed ? (
                              <p className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-[#7a7358]">
                                <span className="font-semibold">变化</span> {eventItem.what_changed}
                              </p>
                            ) : null}
                            <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-[#5f6f82]">
                              <span>{eventItem.independent_source_count || eventItem.source_names.length} 个独立来源</span>
                              {eventItem.updated_at ? <span>{formatLocalDateTime(eventItem.updated_at)}</span> : null}
                            </div>
                          </Link>
                        ))}
                      </div>
                    </section>
                  ) : null}
                  {hourlyDigests.map((digest) => (
                  <button
                    key={digest.hour}
                    type="button"
                    onClick={() => setSelectedHour(digest.hour)}
                    data-testid={`digest-hour-card-${digest.hour}`}
                    className="group flex w-full items-center gap-6 rounded-2xl border border-[rgba(88,100,118,0.12)] bg-white/85 p-6 text-left shadow-[0_12px_40px_-18px_rgba(41,56,89,0.14)] transition-all hover:border-[#49A8C9]/28 hover:bg-white focus:outline-none focus:ring-2 focus:ring-[#49A8C9]/25"
                  >
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-[rgba(88,100,118,0.1)] bg-[#eef4f8] text-[#49A8C9] shadow-sm transition-all group-hover:scale-105 group-hover:border-[#49A8C9]/25 group-hover:bg-[#49A8C9] group-hover:text-white">
                      <Clock size={20} />
                    </div>
                    <div className="flex min-w-0 flex-1 flex-col items-start text-left">
                      <h3 className="text-lg font-semibold text-[#293859] transition-colors group-hover:text-[#49A8C9]">
                        {selectedDate.month() + 1} 月 {selectedDate.date()} 日 · {digest.hour}:00
                      </h3>
                      <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[12px] font-medium text-[#586476]">
                        <span className="flex items-center gap-1">
                          <FileText size={12} /> {digest.content_count} 条
                        </span>
                        <span className="hidden h-1 w-1 rounded-full bg-[#586476]/40 sm:inline" />
                        <span className="max-w-full truncate text-[12px] uppercase tracking-wide text-[#8C866A]">
                          {Object.entries(digest.sources)
                            .filter(([, v]) => v > 0)
                            .map(([k]) => k)
                            .join(', ') || '—'}
                        </span>
                      </div>
                    </div>
                    <ChevronRight
                      className="shrink-0 text-[#586476]/50 transition-all group-hover:translate-x-0.5 group-hover:text-[#49A8C9]"
                      size={20}
                    />
                  </button>
                  ))}
                </>
              ) : (
                <Empty
                  description={<span className="text-[#586476]">该日暂无简报。</span>}
                  className="py-20"
                />
              )}
            </motion.div>
          ) : (
            // Detail Briefing View
            <motion.div
              key="detail"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="space-y-6"
            >
              {detailLoading ? (
                <div className="flex h-96 flex-col items-center justify-center gap-4">
                  <Spin size="large" />
                  <span className="animate-pulse text-[12px] font-medium tracking-wide text-[#5f6f82] sm:text-[13px]">
                    正在生成摘要…
                  </span>
                </div>
              ) : digestDetail ? (
                <article
                  className="rounded-3xl border border-[rgba(88,100,118,0.12)] bg-white/92 p-8 shadow-[0_18px_50px_-18px_rgba(41,56,89,0.2)] backdrop-blur-sm sm:p-10"
                  data-testid="digest-detail"
                >
                  <header className="mb-10 flex flex-col gap-6 sm:mb-11 sm:gap-7">
                    <button
                      type="button"
                      onClick={() => setSelectedHour(null)}
                      data-testid="digest-back-btn"
                      className="flex w-fit items-center gap-2 text-[13px] font-medium text-[#5f6f82] transition-colors hover:text-[#49A8C9] sm:text-[14px]"
                    >
                      <ArrowLeft size={16} className="shrink-0 text-[#8C866A]" strokeWidth={1.75} /> 返回列表
                    </button>

                    <h2 className="text-[24px] font-semibold leading-snug tracking-tight text-[#293859] sm:text-[28px]">
                      {digestDetail.title || `${selectedHour}:00 简报`}
                    </h2>

                    <div className="grid grid-cols-2 gap-5 rounded-2xl border border-[rgba(88,100,118,0.08)] border-l-[3px] border-l-[#8C866A]/40 bg-[#eef4f8]/80 p-5 sm:gap-6 md:grid-cols-5">
                      <div className="space-y-1.5">
                        <div className="text-[12px] font-semibold text-[#5f6f82] sm:text-[13px]">生成时间</div>
                        <div className="text-[15px] font-semibold tabular-nums text-[#293859] sm:text-base">
                          {digestDetail.generated_at
                            ? formatLocalDateTime(digestDetail.generated_at, 'zh-CN', {
                                hour: '2-digit',
                                minute: '2-digit',
                              })
                            : '—'}
                        </div>
                      </div>
                      <div className="space-y-1.5">
                        <div className="text-[12px] font-semibold text-[#5f6f82] sm:text-[13px]">事件数</div>
                        <div className="text-[15px] font-semibold text-[#293859] sm:text-base">{selectedEventCount || selectedMaterialCount} 个</div>
                      </div>
                      <div className="space-y-1.5">
                        <div className="text-[12px] font-semibold text-[#5f6f82] sm:text-[13px]">预计阅读</div>
                        <div className="text-[15px] font-semibold text-[#293859] sm:text-base">约 {estimateReadingMinutes(selectedEventCount || selectedMaterialCount)} 分钟</div>
                      </div>
                      <div className="space-y-1.5">
                        <div className="text-[12px] font-semibold text-[#5f6f82] sm:text-[13px]">输入素材</div>
                        <div className="text-[15px] font-semibold text-[#293859] sm:text-base">{digestDetail.content_count} 条</div>
                      </div>
                      <div className="col-span-2 space-y-1.5 md:col-span-1">
                        <div className="text-[12px] font-semibold text-[#5f6f82] sm:text-[13px]">主要来源</div>
                        <div className="truncate text-[15px] font-semibold text-[#293859] sm:text-base">
                          {digestDetail.sources?.slice(0, 3).join(', ') || '—'}
                        </div>
                      </div>
                    </div>
                  </header>

                  <div className="max-w-none text-[15px] leading-relaxed text-[#293859] sm:text-[15px] sm:leading-[1.7]">
                    {digestDetail.summary?.split('\n').map((line, idx) => {
                      if (line.startsWith('## ')) {
                        const h2Text = line.replace('## ', '').trim();
                        if (h2Text === (digestDetail.title || '').trim()) return null;
                        return (
                          <h2
                            key={idx}
                            className="mb-6 mt-12 border-l-[3px] border-[#8C866A] pl-4 text-lg font-semibold tracking-tight text-[#293859] sm:text-xl"
                          >
                            {h2Text}
                          </h2>
                        );
                      }
                      if (line.startsWith('### ')) {
                        const cat = line.replace('### ', '').trim();
                        return (
                          <h3
                            key={idx}
                            className="mb-4 mt-9 flex items-center gap-2 border-l-[3px] border-[#8C866A]/55 pl-3 text-[13px] font-semibold tracking-wide sm:mt-10 sm:text-[14px]"
                          >
                            <Zap size={14} className="shrink-0 text-[#8C866A]" strokeWidth={1.75} aria-hidden />
                            <span className="text-[#8C866A]">{cat}</span>
                          </h3>
                        );
                      }
                      if (/^\*\*(.+)\*\*$/.test(line.trim())) {
                        return (
                          <div key={idx} className="mb-4 mt-8 text-[17px] font-semibold leading-snug text-[#293859] sm:text-lg">
                            {renderInlineMarkdown(line.trim())}
                          </div>
                        );
                      }
                      if (line.startsWith('- ')) {
                        return (
                          <div key={idx} className="my-2.5 flex gap-3 pl-1 leading-relaxed">
                            <span className="select-none pt-0.5 font-bold text-[#8C866A]">•</span>
                            <span className="flex-1">{renderInlineMarkdown(line.replace('- ', ''))}</span>
                          </div>
                        );
                      }
                      if (line.startsWith('---')) return <hr key={idx} className="my-10 border-[rgba(88,100,118,0.12)]" />;
                      if (line.startsWith('*') && line.endsWith('*')) {
                        return (
                          <p
                            key={idx}
                            className="my-6 border-l-2 border-[#8C866A]/35 pl-4 text-[13px] italic leading-relaxed text-[#5f6f82] sm:text-[14px]"
                          >
                            {line.replace(/^\*|\*$/g, '')}
                          </p>
                        );
                      }
                      if (line.trim() === '') return <div key={idx} className="h-4" />;
                      return (
                        <p key={idx} className="my-4 leading-relaxed">
                          {renderInlineMarkdown(line)}
                        </p>
                      );
                    })}
                  </div>

                  {digestDetail.event_items?.length ? (
                    <section className="mt-10 border-t border-[rgba(88,100,118,0.12)] pt-7">
                      <div className="mb-4 flex items-center justify-between gap-3">
                        <h3 className="inline-flex items-center gap-2 text-[15px] font-semibold tracking-tight text-[#293859]">
                          <Layers3 size={15} className="shrink-0 text-[#8C866A]" strokeWidth={1.75} />
                          事件卡片
                        </h3>
                        <span className="text-[12px] font-medium text-[#5f6f82]">{digestDetail.event_items.length} 条</span>
                      </div>
                      <div className="grid gap-3 md:grid-cols-2">
                        {digestDetail.event_items.map((eventItem) => (
                          <article
                            key={eventItem.content_id}
                            className="border border-[rgba(88,100,118,0.12)] bg-[#fbfdff] p-4"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <Link
                                to={eventItem.event_id ? `/events/${eventItem.event_id}` : buildReaderPath(eventItem.content_id)}
                                className="min-w-0 text-[14px] font-semibold leading-snug text-[#293859] transition-colors hover:text-[#49A8C9]"
                              >
                                {eventItem.title}
                              </Link>
                              {typeof eventItem.score === 'number' ? (
                                <span className="shrink-0 rounded-full border border-[#49A8C9]/18 bg-[#49A8C9]/8 px-2 py-0.5 text-[11px] font-semibold text-[#3a8da9]">
                                  {Math.round(eventItem.score)}分
                                </span>
                              ) : null}
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-[#5f6f82]">
                              <span className="font-medium text-[#7a7358]">{eventItem.source_name}</span>
                              {eventItem.lane ? <span>{eventItem.lane}</span> : null}
                              {eventItem.duplicate_group_id ? <span>同组</span> : null}
                            </div>
                            {eventItem.what_happened || eventItem.summary ? (
                              <p className="mt-2 line-clamp-3 text-[12px] leading-relaxed text-[#5f6f82]">
                                {eventItem.what_happened || eventItem.summary}
                              </p>
                            ) : null}
                            {eventItem.why_matters || eventItem.new_signal ? (
                              <p className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-[#7a7358]">
                                {eventItem.new_signal ? <><span className="font-semibold">变化</span> {eventItem.new_signal}</> : eventItem.why_matters}
                              </p>
                            ) : null}
                            <a
                              href={eventItem.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="mt-3 inline-flex items-center gap-1 text-[12px] font-medium text-[#8a96a5] hover:text-[#49A8C9]"
                            >
                              原文
                              <ExternalLink size={11} className="shrink-0" strokeWidth={1.75} />
                            </a>
                          </article>
                        ))}
                      </div>
                    </section>
                  ) : null}

                  {digestDetail.items?.length ? (
                    <section className="mt-10 border-t border-[rgba(88,100,118,0.12)] pt-7">
                      <div className="mb-4 flex items-center justify-between gap-3">
                        <h3 className="text-[15px] font-semibold tracking-tight text-[#293859]">入选素材</h3>
                        <span className="text-[12px] font-medium text-[#5f6f82]">{digestDetail.items.length} 条</span>
                      </div>
                      <div className="divide-y divide-[rgba(88,100,118,0.1)]">
                        {digestDetail.items.map((item) => (
                          <div key={item.id} className="py-4 first:pt-0 last:pb-0">
                            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                              <Link
                                to={buildReaderPath(item.id)}
                                className="min-w-0 flex-1 text-[14px] font-semibold leading-snug text-[#293859] transition-colors hover:text-[#49A8C9] sm:text-[15px]"
                              >
                                {item.translated_title || item.title}
                              </Link>
                              <a
                                href={item.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex shrink-0 items-center gap-1 text-[12px] font-medium text-[#8a96a5] hover:text-[#49A8C9]"
                              >
                                原文
                                <ExternalLink size={11} className="shrink-0" strokeWidth={1.75} />
                              </a>
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
                              <span className="font-medium text-[#7a7358]">{item.source_name}</span>
                              {renderQualityBadges(item)}
                            </div>
                            {(() => {
                              const reason = getDigestItemRecommendationReason(item);
                              return reason?.why_matters ? (
                                <p className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-[#5f6f82]">
                                  <span className="font-semibold text-[#7a7358]">理由</span>
                                  <span className="ml-1">{reason.why_matters}</span>
                                  {reason.caveat ? <span className="ml-1 text-[#8a96a5]">{reason.caveat}</span> : null}
                                </p>
                              ) : null;
                            })()}
                          </div>
                        ))}
                      </div>
                    </section>
                  ) : null}
                </article>
              ) : (
                <Empty description="简报暂不可用" />
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default DigestView;
