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
  ChevronLeft,
  ChevronRight,
  EyeOff,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useReader } from '../hooks/useReader';
import SectionNote from '../components/ui/SectionNote';
import PageLoading from '../components/common/PageLoading';
import { type ReaderBlock } from '../services/contents';
import { getReaderNeighbor, recordReaderInteraction } from '../utils/readerFlow';
import { getReaderLayoutProfile, type ReaderLayoutProfile } from '../utils/readerLayout';
import ContentInlineAnnotation from '../components/annotations/ContentInlineAnnotation';

function safeHttpUrl(value?: string): string {
  if (!value) return '';
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.toString() : '';
  } catch {
    return '';
  }
}

function formatDiagnosticRatio(value?: number): string {
  return value == null ? '—' : `${Math.round(value * 100)}%`;
}

function ShortcutHint({ children }: { children: React.ReactNode }) {
  return (
    <kbd
      aria-hidden="true"
      className="inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-current/20 bg-white/45 px-1.5 font-mono text-[10px] font-bold leading-none text-current opacity-80"
    >
      {children}
    </kbd>
  );
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

  const { data, loading, error, displayTitle, displayBlocks, setLiked, hide, stream } = useReader(id, translateRequested);
  const layout = useMemo(
    () => getReaderLayoutProfile(data?.original_url, data?.source_name),
    [data?.original_url, data?.source_name],
  );
  const previousItem = useMemo(() => getReaderNeighbor(id, -1), [id]);
  const nextItem = useMemo(() => getReaderNeighbor(id, 1), [id]);

  const navigateToNeighbor = useCallback((direction: -1 | 1, channel: 'keyboard' | 'click', record = true) => {
    const neighbor = direction < 0 ? previousItem : nextItem;
    if (!neighbor) return;
    if (record) recordReaderInteraction(channel, 'navigate');
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

  const toggleLiked = useCallback(async (channel: 'keyboard' | 'click') => {
    if (!id || !data) return;
    recordReaderInteraction(channel, 'like');
    await setLiked(!data.favorited);
  }, [data, id, setLiked]);

  const hideCurrent = useCallback(async (channel: 'keyboard' | 'click') => {
    if (!id || !data) return;
    recordReaderInteraction(channel, 'hide');
    await hide();
    // Hidden means "not interested" — leave the article immediately.
    if (nextItem) {
      navigateToNeighbor(1, channel, false);
    } else {
      navigate(backHref);
    }
  }, [backHref, data, hide, id, navigate, navigateToNeighbor, nextItem]);

  useEffect(() => {
    if (!data) return;
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const key = event.key.toLowerCase();

      if (key === 'j') {
        event.preventDefault();
        navigateToNeighbor(1, 'keyboard');
      } else if (key === 'k') {
        event.preventDefault();
        navigateToNeighbor(-1, 'keyboard');
      } else if (key === 'l') {
        event.preventDefault();
        void toggleLiked('keyboard');
      } else if (key === 'h') {
        event.preventDefault();
        void hideCurrent('keyboard');
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [data, hideCurrent, navigateToNeighbor, toggleLiked]);

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
          <div className="flex items-center justify-between gap-4">
            <Link
              to={backHref}
              className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.16em] text-[#586476] hover:text-[#293859] transition-colors"
            >
              <ArrowLeft size={14} /> 返回
            </Link>

            <div className="flex shrink-0 items-center rounded-xl border border-[rgba(88,100,118,0.16)] bg-white/65 p-1 shadow-sm">
              <button
                type="button"
                disabled={!previousItem}
                onClick={() => navigateToNeighbor(-1, 'click')}
                className="flex h-8 items-center justify-center gap-1.5 rounded-lg px-2 text-[#586476] transition-all hover:bg-white hover:text-[#293859] disabled:cursor-not-allowed disabled:opacity-35"
                aria-label="上一篇（K）"
              >
                <ChevronLeft size={16} />
                <ShortcutHint>K</ShortcutHint>
              </button>
              <button
                type="button"
                disabled={!nextItem}
                onClick={() => navigateToNeighbor(1, 'click')}
                className="flex h-8 items-center justify-center gap-1.5 rounded-lg px-2 text-[#586476] transition-all hover:bg-white hover:text-[#293859] disabled:cursor-not-allowed disabled:opacity-35"
                aria-label="下一篇（J）"
              >
                <ChevronRight size={16} />
                <ShortcutHint>J</ShortcutHint>
              </button>
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

            <div className="flex flex-wrap items-center gap-x-8 gap-y-3 text-[13px] font-medium text-[#586476]">
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

            <div className="flex flex-wrap items-center justify-between gap-3 border-y border-[rgba(88,100,118,0.12)] py-4">
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  to={readerTogglePath}
                  className={`flex items-center gap-2 rounded-xl border px-3.5 py-2 text-[12px] font-semibold transition-all ${
                    translateRequested
                      ? 'border-[#49A8C9]/35 bg-[#49A8C9] text-white shadow-sm shadow-[#49A8C9]/20'
                      : 'border-[#49A8C9]/25 bg-[#49A8C9]/8 text-[#3a8da9] hover:bg-[#49A8C9]/12'
                  }`}
                >
                  {translateRequested ? <Globe size={14} /> : <Languages size={14} />}
                  {translateRequested ? '查看原文' : '翻译阅读'}
                </Link>
                {safeHttpUrl(data.original_url) ? (
                  <a
                    href={safeHttpUrl(data.original_url)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 rounded-xl border border-[rgba(88,100,118,0.16)] bg-white/70 px-3.5 py-2 text-[12px] font-semibold text-[#586476] transition-all hover:border-[#49A8C9]/35 hover:bg-white hover:text-[#293859]"
                  >
                    <ExternalLink size={14} /> 原文链接
                  </a>
                ) : null}
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void toggleLiked('click')}
                  className={`flex items-center gap-2 rounded-xl border px-3.5 py-2 text-[12px] font-semibold transition-all ${
                    data.favorited
                      ? 'border-[#49A8C9]/35 bg-[#49A8C9] text-white shadow-sm shadow-[#49A8C9]/20'
                      : 'border-[rgba(88,100,118,0.16)] bg-white/70 text-[#586476] hover:bg-white hover:text-[#293859]'
                  }`}
                >
                  <Bookmark size={14} /> {data.favorited ? '已标为重要' : '重要'} <ShortcutHint>L</ShortcutHint>
                </button>
                <button
                  type="button"
                  onClick={() => void hideCurrent('click')}
                  className="flex items-center gap-2 rounded-xl border border-rose-200/80 bg-white/70 px-3.5 py-2 text-[12px] font-semibold text-rose-500 transition-all hover:border-rose-300 hover:bg-rose-50 hover:text-rose-600"
                >
                  <EyeOff size={14} /> 不重要 <ShortcutHint>H</ShortcutHint>
                </button>
              </div>
            </div>
          </header>

          {data.web_clean ? (
            <details
              className="mt-8 rounded-2xl border border-[rgba(88,100,118,0.14)] bg-white/65 px-5 py-4 text-[13px] text-[#586476]"
              data-testid="web-clean-diagnostic"
            >
              <summary className="cursor-pointer font-semibold text-[#293859]">网页清洗诊断</summary>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div>模式：{data.web_clean.shadow ? 'Shadow' : '已启用'}</div>
                <div>方法：{data.web_clean.extraction_method || '—'}</div>
                <div>模板：{data.web_clean.template_id || '通用模板'}</div>
                <div>质量：{data.web_clean.quality_status || 'unknown'} / {formatDiagnosticRatio(data.web_clean.quality_score)}</div>
                <div>访问控制：{data.web_clean.blocked ? '命中' : '未命中'}</div>
                <div>正文：{data.web_clean.text_chars ?? 0} 字符 · {data.web_clean.paragraph_count ?? 0} 段</div>
                <div>噪音 / 链接：{formatDiagnosticRatio(data.web_clean.boilerplate_ratio)} / {formatDiagnosticRatio(data.web_clean.link_density)}</div>
                <div>Shadow DOM：{data.web_clean.shadow_materialized_count ?? 0} 个{data.web_clean.shadow_timeout ? '（超时降级）' : ''}</div>
                <div>HTML 截断：{data.web_clean.truncated ? '是' : '否'}</div>
              </div>
              {data.web_clean.shadow_diff ? (
                <div className="mt-3">旧/新正文：{data.web_clean.shadow_diff.old_chars ?? 0} → {data.web_clean.shadow_diff.new_chars ?? 0} 字符（Δ {data.web_clean.shadow_diff.char_delta ?? 0}）</div>
              ) : null}
              {data.web_clean.rejected_reasons?.length ? (
                <div className="mt-3 break-words text-amber-700">候选拒绝：{data.web_clean.rejected_reasons.join('；')}</div>
              ) : null}
              {data.web_clean.template_validation_errors?.length ? (
                <div className="mt-3 break-words text-rose-600">模板错误：{data.web_clean.template_validation_errors.join('；')}</div>
              ) : null}
            </details>
          ) : null}

          <div className={layout.bodyClassName} data-testid="reader-iframe">
            {displayBlocks.length === 0 ? (
              <div className="py-16 text-center text-[15px] font-medium italic text-[#586476]">正文为空。</div>
            ) : (
              displayBlocks.map((block, index) => renderReaderBlock(block, index, layout))
            )}
          </div>

          <div className="mt-12">
            <ContentInlineAnnotation
              contentId={data.id}
              title={displayTitle}
              summary={(data.body_zh || data.body_raw || '').slice(0, 1200)}
            />
          </div>
        </article>
      </div>
    </div>
  );
};

export default ReaderPage;
