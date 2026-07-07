import React, { useCallback, useEffect, useMemo } from 'react';
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom';
import { buildDashboardHomePath, buildDashboardSourcePath, buildReaderPath } from '../components/Dashboard/dashboardUtils';
import {
  ArrowLeft,
  ExternalLink,
  Globe,
  FileText,
  Loader2,
  Bookmark,
  ShieldCheck,
  Languages,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useReader } from '../hooks/useReader';
import SectionNote from '../components/ui/SectionNote';
import PageLoading from '../components/common/PageLoading';
import type { ReaderBlock } from '../services/contents';
import { getReaderNeighbor, recordReaderInteraction } from '../utils/readerFlow';
import { getReaderLayoutProfile, type ReaderLayoutProfile } from '../utils/readerLayout';

function safeHttpUrl(value?: string): string {
  if (!value) return '';
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : '';
  } catch {
    return '';
  }
}

function renderReaderBlock(block: ReaderBlock, index: number, layout: ReaderLayoutProfile): React.ReactNode {
  const key = `${block.type}-${index}`;
  if (block.type === 'heading') {
    const level = block.level || 2;
    const HeadingTag = level <= 2 ? 'h2' : level === 3 ? 'h3' : 'h4';
    const className = level <= 2
      ? 'mb-5 mt-11 text-[24px] font-semibold leading-[1.35] text-[#293859]'
      : 'mb-4 mt-9 text-[20px] font-semibold leading-[1.4] text-[#293859]';
    return (
      <HeadingTag key={key} className={className}>
        {block.text}
      </HeadingTag>
    );
  }

  if (block.type === 'image') {
    const src = safeHttpUrl(block.src);
    if (!src) return null;
    return (
      <figure key={key} className={layout.figureClassName}>
        <img
          src={src}
          alt={block.alt || block.caption || ''}
          loading="lazy"
          className="h-auto max-h-[640px] w-full object-contain"
        />
        {block.caption ? (
          <figcaption className="border-t border-[rgba(88,100,118,0.1)] px-4 py-3 text-[13px] leading-relaxed text-[#586476]">
            {block.caption}
          </figcaption>
        ) : null}
      </figure>
    );
  }

  if (block.type === 'quote') {
    return (
      <blockquote
        key={key}
        className="my-9 border-l-4 border-[#49A8C9] bg-white/70 px-6 py-5 text-[17px] leading-[1.8] text-[#293859]"
      >
        {block.text}
      </blockquote>
    );
  }

  if (block.type === 'code') {
    return (
      <pre key={key} className={layout.codeClassName}>
        <code>{block.text}</code>
      </pre>
    );
  }

  if (block.type === 'footnote') {
    return (
      <aside key={key} className={layout.footnoteClassName}>
        <span className="mr-2 font-semibold text-[#8C866A]">[{block.marker || index + 1}]</span>
        {block.text}
      </aside>
    );
  }

  if (block.type === 'link') {
    const href = safeHttpUrl(block.href);
    if (!href) return null;
    return (
      <p key={key} className="mb-9">
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex max-w-full items-center gap-2 break-all font-semibold text-[#0b6f91] underline-offset-4 hover:underline"
        >
          <ExternalLink size={16} className="shrink-0" />
          {block.text || href}
        </a>
      </p>
    );
  }

  return (
    <p key={key} className="mb-9 whitespace-pre-wrap selection:bg-[#49A8C9]/25">
      {block.text}
    </p>
  );
}

const ReaderPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const translateRequested = ['1', 'true', 'yes'].includes((searchParams.get('translate') || '').toLowerCase());
  const fromTab = searchParams.get('tab') || undefined;
  const fromSearch = searchParams.get('search') || undefined;
  const fromSourceId = searchParams.get('source_id') || undefined;
  const fromSourceName = searchParams.get('source') || undefined;
  const fromScoreLab = searchParams.get('from') === 'score-lab';
  const backHref = fromScoreLab && id
    ? `/score-lab?id=${encodeURIComponent(id)}`
    : buildDashboardHomePath(fromTab, fromSearch, fromSourceId, fromSourceName);
  const readerTogglePath = id
    ? buildReaderPath(id, {
        translate: !translateRequested,
        ...(fromScoreLab
          ? { from: 'score-lab' }
          : fromSearch || fromSourceId
            ? { search: fromSearch, sourceId: fromSourceId, sourceName: fromSourceName }
            : { tab: fromTab }),
      })
    : '/';

  const { data, loading, error, displayTitle, displayBlocks, markAsRead, setReadLater, stream } = useReader(id, translateRequested);
  const layout = useMemo(
    () => getReaderLayoutProfile(data?.original_url, data?.source_name),
    [data?.original_url, data?.source_name],
  );
  const previousItem = useMemo(() => getReaderNeighbor(id, -1), [id]);
  const nextItem = useMemo(() => getReaderNeighbor(id, 1), [id]);

  const navigateToNeighbor = useCallback((direction: -1 | 1, channel: 'keyboard' | 'click') => {
    const neighbor = direction < 0 ? previousItem : nextItem;
    if (!neighbor) return;
    recordReaderInteraction(channel, 'navigate');
    navigate(buildReaderPath(neighbor.id, {
      translate: translateRequested,
      ...(fromScoreLab
        ? { from: 'score-lab' }
        : fromSearch || fromSourceId
          ? { search: fromSearch, sourceId: fromSourceId, sourceName: fromSourceName }
          : { tab: fromTab }),
    }));
  }, [
    fromScoreLab,
    fromSearch,
    fromSourceId,
    fromSourceName,
    fromTab,
    navigate,
    nextItem,
    previousItem,
    translateRequested,
  ]);

  const markCurrentAsRead = useCallback(async (channel: 'keyboard' | 'click') => {
    if (!id || data?.read_status) return;
    recordReaderInteraction(channel, 'mark_read');
    await markAsRead();
  }, [data?.read_status, id, markAsRead]);

  const toggleReadLater = useCallback(async (channel: 'keyboard' | 'click') => {
    if (!id || !data) return;
    recordReaderInteraction(channel, 'read_later');
    await setReadLater(!data.favorited);
  }, [data, id, setReadLater]);

  useEffect(() => {
    if (!data) return;
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      if (event.key === 'j') {
        event.preventDefault();
        navigateToNeighbor(1, 'keyboard');
      } else if (event.key === 'k') {
        event.preventDefault();
        navigateToNeighbor(-1, 'keyboard');
      } else if (event.key.toLowerCase() === 'r') {
        event.preventDefault();
        void markCurrentAsRead('keyboard');
      } else if (event.key.toLowerCase() === 'l') {
        event.preventDefault();
        void toggleReadLater('keyboard');
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [data, markCurrentAsRead, navigateToNeighbor, toggleReadLater]);

  if (loading) return <PageLoading />;

  if (!data || error) {
    return (
      <div className="mx-auto max-w-2xl px-5 py-24 text-center sm:px-8" data-testid="reader-empty">
        <div className="mx-auto mb-8 flex h-16 w-16 items-center justify-center rounded-2xl border border-rose-200/80 bg-rose-50 text-rose-500">
          <Bookmark size={32} />
        </div>
        <h3 className="text-xl font-semibold tracking-tight text-[#293859]">暂无法阅读</h3>
        <p className="mt-3 text-[15px] leading-relaxed text-[#586476]">
          {error || '该内容已删除或暂时无法从存档中打开。'}
        </p>
        <Link
          to={backHref}
          className="mt-10 inline-flex items-center gap-2 text-sm font-semibold text-[#49A8C9] hover:text-[#3d94b3]"
        >
          <ArrowLeft size={16} /> 返回首页
        </Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f5f9fc] pb-36" data-testid="reader-page">
      <div className="sticky top-0 z-40 border-b border-[rgba(88,100,118,0.1)] bg-[#f5f9fc]/92 backdrop-blur-xl">
        <div className="mx-auto max-w-3xl px-5 py-5 sm:px-10">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <Link
              to={backHref}
              className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.16em] text-[#586476] hover:text-[#293859] transition-colors"
            >
              <ArrowLeft size={14} /> 返回
            </Link>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={!previousItem}
                onClick={() => navigateToNeighbor(-1, 'click')}
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-[rgba(88,100,118,0.18)] bg-white/60 text-[#586476] transition-all hover:bg-white hover:text-[#293859] disabled:cursor-not-allowed disabled:opacity-35"
                aria-label="上一篇"
              >
                <ChevronLeft size={16} />
              </button>
              <button
                type="button"
                disabled={!nextItem}
                onClick={() => navigateToNeighbor(1, 'click')}
                className="flex h-9 w-9 items-center justify-center rounded-xl border border-[rgba(88,100,118,0.18)] bg-white/60 text-[#586476] transition-all hover:bg-white hover:text-[#293859] disabled:cursor-not-allowed disabled:opacity-35"
                aria-label="下一篇"
              >
                <ChevronRight size={16} />
              </button>
              <button
                type="button"
                onClick={() => void markCurrentAsRead('click')}
                disabled={!!data.read_status}
                className={`flex items-center gap-2 rounded-xl border px-3.5 py-2 text-[12px] font-semibold transition-all ${
                  data.read_status
                    ? 'border-[#7a7358]/20 bg-[#f4f0e6] text-[#7a7358]'
                    : 'border-[rgba(88,100,118,0.18)] bg-white/60 text-[#586476] hover:bg-white hover:text-[#293859]'
                }`}
              >
                <CheckCircle2 size={14} /> {data.read_status ? '已读' : '标为已读'}
              </button>
              <button
                type="button"
                onClick={() => void toggleReadLater('click')}
                className={`flex items-center gap-2 rounded-xl border px-3.5 py-2 text-[12px] font-semibold transition-all ${
                  data.favorited
                    ? 'border-[#49A8C9]/35 bg-[#49A8C9] text-white shadow-md shadow-[#49A8C9]/20'
                    : 'border-[rgba(88,100,118,0.18)] bg-white/60 text-[#586476] hover:bg-white hover:text-[#293859]'
                }`}
              >
                <Bookmark size={14} /> {data.favorited ? '已稍后读' : '稍后读'}
              </button>
              {safeHttpUrl(data.original_url) ? (
                <a
                  href={safeHttpUrl(data.original_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-xl border border-[rgba(88,100,118,0.18)] bg-white/70 px-3.5 py-2 text-[12px] font-semibold text-[#586476] shadow-sm transition-all hover:border-[#49A8C9]/40 hover:bg-white hover:text-[#293859]"
                >
                  <ExternalLink size={14} /> 原文链接
                </a>
              ) : null}

              <Link
                to={readerTogglePath}
                className={`flex items-center gap-2 rounded-xl border px-4 py-2 text-[12px] font-semibold transition-all ${
                  translateRequested
                    ? 'border-[#49A8C9]/35 bg-[#49A8C9] text-white shadow-md shadow-[#49A8C9]/25'
                    : 'border-[rgba(88,100,118,0.18)] bg-white/60 text-[#586476] hover:bg-white hover:text-[#293859]'
                }`}
              >
                {translateRequested ? <Globe size={14} /> : <Languages size={14} />}
                {translateRequested ? '查看原文' : '翻译阅读'}
              </Link>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-3xl px-5 pt-14 sm:px-10">
        <AnimatePresence>
          {(stream.loading || stream.hint) && translateRequested && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mb-10"
            >
              <SectionNote
                compact={false}
                tone={stream.loading ? 'neutral' : 'caution'}
                title={stream.loading ? '正在生成译文' : '翻译说明'}
              >
                {stream.loading ? (
                  <div className="flex items-center gap-2">
                    <Loader2 size={12} className="animate-spin text-[#49A8C9]" />
                    已处理 {stream.chunks.length}
                    {stream.total > 0 ? ` / ${stream.total}` : ''} 段…
                  </div>
                ) : (
                  stream.hint
                )}
              </SectionNote>
            </motion.div>
          )}
        </AnimatePresence>

        <article className={layout.articleClassName} data-reader-layout={layout.key}>
          <header className="space-y-7">
            <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.2em] text-[#8C866A]">
              <ShieldCheck size={12} /> 存档条目
            </div>

            <h1 className="text-[30px] font-semibold leading-[1.25] tracking-tight text-[#293859] sm:text-[34px]">
              {displayTitle || '无标题'}
            </h1>

            <div className="flex flex-wrap items-center gap-x-8 gap-y-3 border-b border-[rgba(88,100,118,0.14)] pb-9 text-[13px] font-medium text-[#586476]">
              {data.source_id ? (
                <Link
                  to={buildDashboardSourcePath(data.source_id, data.source_name)}
                  className="flex items-center gap-1.5 text-[#49A8C9] underline-offset-2 transition-colors hover:text-[#3d94b3] hover:underline"
                  title={`查看 ${data.source_name || '该信源'} 的全部内容`}
                >
                  <Globe size={14} /> {data.source_name || '来源'}
                </Link>
              ) : (
                <div className="flex items-center gap-1.5 text-[#49A8C9]">
                  <Globe size={14} /> {data.source_name || '来源'}
                </div>
              )}
              <div className="flex items-center gap-1.5">
                <FileText size={14} /> 编号 #{id?.slice(0, 8)}
              </div>
              <div className="flex items-center gap-1.5">发布 {data.publish_time || '—'}</div>
            </div>
          </header>

          <div className={layout.bodyClassName} data-testid="reader-iframe">
            {displayBlocks.length === 0 ? (
              <div className="py-16 text-center text-[15px] font-medium italic text-[#586476]">正文为空。</div>
            ) : (
              displayBlocks.map((block, index) => renderReaderBlock(block, index, layout))
            )}
          </div>
        </article>
      </div>
    </div>
  );
};

export default ReaderPage;
