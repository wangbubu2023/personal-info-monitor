import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import {
  ExternalLink,
  Clock,
  Tag,
  FileText,
  Gauge,
  Star,
  EyeOff,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { KEYWORD_MONITORING_ENABLED } from '../../config/features';
import { contentsApi } from '../../services/contents';
import type { DigestItem } from '../../types';
import { contentTagKeysFromMetadata } from '../../config/contentTags';
import ContentTagEditor from '../content/ContentTagEditor';
import {
  buildDashboardSourcePath,
  buildReaderPath,
  capDashboardListPreview,
  digestSummaryPlain,
  getDigestItemFinalScore,
  getDigestItemFulltextStatusLabel,
  getDigestItemRecommendationReason,
  getDigestItemScoreDeferred,
  getDigestItemSourceStars,
  renderDashboardTimePair,
} from './dashboardUtils';

interface DashboardItemCardProps {
  item: DigestItem;
  /** 当前资讯分类，用于阅读页返回时恢复 `?tab=` */
  activeTab: string;
  /** 若来自搜索列表，用于返回时恢复 `?search=`（优先于 tab） */
  searchReturnQuery?: string;
  /** 若来自单一信源视图，用于阅读页返回时恢复 `?source_id=` */
  sourceReturnId?: string;
  sourceReturnName?: string;
  focused?: boolean;
}

function splitSummaryLink(summary?: string): { text: string; hasInlineLink: boolean } {
  const raw = (summary || '').trim();
  if (!raw) return { text: '', hasInlineLink: false };
  const normalized = raw.replace(/\s*(?:\.{3}|…)?\s*(查看全文|查看原文)\s*$/, '').trimEnd();
  return { text: normalized, hasInlineLink: normalized !== raw };
}

const DashboardItemCard: React.FC<DashboardItemCardProps> = ({
  item,
  activeTab,
  searchReturnQuery,
  sourceReturnId,
  sourceReturnName,
  focused = false,
}) => {
  const readerOpts = {
    ...(searchReturnQuery ? { search: searchReturnQuery } : {}),
    ...(sourceReturnId ? { sourceId: sourceReturnId, sourceName: sourceReturnName } : {}),
    ...(!searchReturnQuery && !sourceReturnId ? { tab: activeTab } : {}),
  };
  const rawSummary = item.translated_summary || item.summary || '';
  const plainSummary = digestSummaryPlain(rawSummary);
  const { text: summaryText, hasInlineLink } = splitSummaryLink(plainSummary || rawSummary);
  const bodyPreview = (item.body_preview || '').trim();
  // 正文摘录优先；否则用去 HTML 后的摘要（避免 RSS 摘要带标签导致空白）
  const previewToShow = bodyPreview || summaryText;
  const displayPreview = previewToShow ? capDashboardListPreview(previewToShow) : '';
  const showReadFullLink =
    hasInlineLink || (!!bodyPreview && !summaryText);
  const timeText = renderDashboardTimePair(item.publish_time, item.fetched_at || item.publish_time);
  const finalScore = getDigestItemFinalScore(item);
  const scoreDeferred = getDigestItemScoreDeferred(item);
  const sourceStars = getDigestItemSourceStars(item);
  const fulltextLabel = getDigestItemFulltextStatusLabel(item);
  const recommendationReason = getDigestItemRecommendationReason(item);
  const queryClient = useQueryClient();
  const [favorited, setFavorited] = useState(Boolean(item.favorited));
  const [hidden, setHidden] = useState(false);
  const [pendingAction, setPendingAction] = useState<'like' | 'hide' | null>(null);

  const hasKeywords =
    KEYWORD_MONITORING_ENABLED && item.keyword_matches && item.keyword_matches.length > 0;

  useEffect(() => {
    setFavorited(Boolean(item.favorited));
    setHidden(false);
  }, [item.favorited, item.id]);

  const refreshDashboardData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] }),
      queryClient.invalidateQueries({ queryKey: ['dashboard-contents'] }),
      queryClient.invalidateQueries({ queryKey: ['digest'] }),
    ]);
  };

  const toggleLikeFromList = async () => {
    if (pendingAction) return;
    const next = !favorited;
    setPendingAction('like');
    setFavorited(next);
    try {
      const result = await contentsApi.setFavorite(item.id, next);
      setFavorited(Boolean(result.favorited));
      await refreshDashboardData();
    } catch (error) {
      setFavorited(!next);
      console.error('Failed to update favorite status', error);
    } finally {
      setPendingAction(null);
    }
  };

  const hideFromList = async () => {
    if (pendingAction) return;
    setPendingAction('hide');
    try {
      await contentsApi.update(item.id, { archived: true });
      setHidden(true);
      await refreshDashboardData();
    } catch (error) {
      console.error('Failed to hide content', error);
    } finally {
      setPendingAction(null);
    }
  };

  if (hidden) return null;

  return (
    <motion.article
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      data-reader-card-id={item.id}
      className={`group relative overflow-hidden rounded-2xl border bg-white/95 p-5 shadow-[0_8px_28px_-12px_rgba(41,56,89,0.12)] transition-all hover:border-[#49A8C9]/22 hover:bg-white hover:shadow-[0_12px_36px_-14px_rgba(41,56,89,0.14)] ${
        focused
          ? 'border-[#49A8C9]/55 ring-2 ring-[#49A8C9]/20'
          : 'border-[rgba(88,100,118,0.1)]'
      }`}
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2 text-[12px]">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            {item.source_id ? (
              <Link
                to={buildDashboardSourcePath(item.source_id, item.source_name)}
                className="font-medium tracking-tight text-[#7a7358] underline-offset-2 transition-colors hover:text-[#49A8C9] hover:underline"
                title={`查看 ${item.source_name} 的全部内容`}
              >
                {item.source_name}
              </Link>
            ) : (
              <span className="font-medium tracking-tight text-[#7a7358]">
                {item.source_name}
              </span>
            )}
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
            ) : scoreDeferred ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-[#8a96a5]/18 bg-[#eef1f4] px-2 py-0.5 text-[#8a96a5]">
                <Gauge size={11} className="shrink-0" strokeWidth={1.5} />
                暂未评分
              </span>
            ) : null}
            {fulltextLabel ? (
              <span className="inline-flex items-center gap-1 rounded-full border border-[#5f6f82]/14 bg-[#eef4f8] px-2 py-0.5 text-[#5f6f82]">
                <FileText size={11} className="shrink-0" strokeWidth={1.5} />
                {fulltextLabel}
              </span>
            ) : null}
            <span className="flex items-center gap-1 text-[#5f6f82]">
              <Clock size={12} />
              {timeText}
            </span>
            <span className="hidden text-[#d0d5db] sm:inline" aria-hidden>
              ·
            </span>
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-[12px] font-normal text-[#a8b0ba] underline-offset-2 hover:text-[#49A8C9] hover:underline"
            >
              原始出处
              <ExternalLink size={10} className="shrink-0 opacity-70" aria-hidden />
            </a>
          </div>
        </div>

        <h2 className="text-[17px] font-semibold leading-snug tracking-tight sm:text-[18px]">
          <Link
            to={buildReaderPath(item.id, readerOpts)}
            data-testid={`dashboard-title-link-${item.id}`}
            className="text-[#2c3a50] transition-colors hover:text-[#49A8C9]"
          >
            {item.translated_title || item.title}
          </Link>
        </h2>

        <div className="flex flex-wrap items-start gap-x-2 gap-y-1">
          <p className="line-clamp-2 min-w-0 max-w-full flex-1 basis-0 break-words text-[14px] leading-relaxed sm:text-[15px]">
            {displayPreview ? (
              <span className="text-[#5f6f82]">{displayPreview}</span>
            ) : (
              <span className="text-[#a8b0ba]">
                未展示摘要，可点标题或「阅读全文」查看本地正文。
              </span>
            )}
          </p>
          {(showReadFullLink && displayPreview) || !displayPreview ? (
            <Link
              to={buildReaderPath(item.id, readerOpts)}
              className="inline-flex shrink-0 items-center gap-1 text-[14px] font-semibold text-[#49A8C9] hover:text-[#3d94b3] sm:text-[15px]"
            >
              阅读全文
            </Link>
          ) : null}
        </div>

        {recommendationReason?.why_matters ? (
          <p className="line-clamp-2 rounded-lg border border-[rgba(88,100,118,0.08)] bg-[#f6fafc] px-3 py-2 text-[12px] leading-relaxed text-[#5f6f82]">
            <span className="font-semibold text-[#7a7358]">理由</span>
            <span className="ml-1">{recommendationReason.why_matters}</span>
          </p>
        ) : null}

        <ContentTagEditor tags={contentTagKeysFromMetadata(item.metadata)} compact />

        <div className="flex flex-wrap items-center gap-2 pt-0.5">
          <button
            type="button"
            onClick={() => void toggleLikeFromList()}
            disabled={pendingAction !== null}
            className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[12px] font-semibold transition-all ${
              favorited
                ? 'border-[#49A8C9]/30 bg-[#49A8C9] text-white shadow-sm shadow-[#49A8C9]/20'
                : 'border-[rgba(88,100,118,0.14)] bg-white/70 text-[#5f6f82] hover:border-[#49A8C9]/30 hover:bg-white hover:text-[#2c3a50]'
            } disabled:opacity-60`}
            aria-pressed={favorited}
          >
            <Star size={13} className={favorited ? 'fill-current' : ''} />
            {favorited ? '已标为重要' : '重要'}
          </button>
          <button
            type="button"
            onClick={() => void hideFromList()}
            disabled={pendingAction !== null}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[rgba(88,100,118,0.14)] bg-white/70 px-2.5 text-[12px] font-semibold text-[#5f6f82] transition-all hover:border-rose-300/60 hover:bg-white hover:text-rose-500 disabled:opacity-60"
          >
            <EyeOff size={13} />
            不重要
          </button>
        </div>

        {hasKeywords && (
          <div className="mt-0.5 flex flex-wrap gap-2 border-t border-[rgba(88,100,118,0.08)] pt-3">
            {item.keyword_matches?.map((kw) => (
              <span
                key={kw.id}
                className="flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[12px] font-semibold"
                style={{
                  backgroundColor: `${kw.color || '#49A8C9'}18`,
                  color: kw.color || '#49A8C9',
                  border: `1px solid ${kw.color || '#49A8C9'}30`,
                }}
              >
                <Tag size={10} />
                {kw.keyword}
              </span>
            ))}
          </div>
        )}
      </div>
    </motion.article>
  );
};

export default DashboardItemCard;
