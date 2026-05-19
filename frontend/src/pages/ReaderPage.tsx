import React from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import { buildDashboardHomePath, buildReaderPath } from '../components/Dashboard/dashboardUtils';
import {
  ArrowLeft,
  ExternalLink,
  Globe,
  FileText,
  Loader2,
  Bookmark,
  ShieldCheck,
  Languages,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useReader } from '../hooks/useReader';
import SectionNote from '../components/ui/SectionNote';
import PageLoading from '../components/common/PageLoading';

const ReaderPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const translateRequested = ['1', 'true', 'yes'].includes((searchParams.get('translate') || '').toLowerCase());
  const fromTab = searchParams.get('tab') || undefined;
  const fromSearch = searchParams.get('search') || undefined;
  const backHref = buildDashboardHomePath(fromTab, fromSearch);
  const readerTogglePath = id
    ? buildReaderPath(id, {
        translate: !translateRequested,
        ...(fromSearch ? { search: fromSearch } : { tab: fromTab }),
      })
    : '/';

  const { data, loading, error, displayTitle, displayParagraphs, stream } = useReader(id, translateRequested);

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
              <a
                href={data.original_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 rounded-xl border border-[rgba(88,100,118,0.18)] bg-white/70 px-3.5 py-2 text-[12px] font-semibold text-[#586476] shadow-sm transition-all hover:border-[#49A8C9]/40 hover:bg-white hover:text-[#293859]"
              >
                <ExternalLink size={14} /> 原文链接
              </a>

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

        <article className="space-y-14">
          <header className="space-y-7">
            <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.2em] text-[#8C866A]">
              <ShieldCheck size={12} /> 存档条目
            </div>

            <h1 className="text-[30px] font-semibold leading-[1.25] tracking-tight text-[#293859] sm:text-[34px]">
              {displayTitle || '无标题'}
            </h1>

            <div className="flex flex-wrap items-center gap-x-8 gap-y-3 border-b border-[rgba(88,100,118,0.14)] pb-9 text-[13px] font-medium text-[#586476]">
              <div className="flex items-center gap-1.5 text-[#49A8C9]">
                <Globe size={14} /> {data.source_name || '来源'}
              </div>
              <div className="flex items-center gap-1.5">
                <FileText size={14} /> 编号 #{id?.slice(0, 8)}
              </div>
              <div className="flex items-center gap-1.5">发布 {data.publish_time || '—'}</div>
            </div>
          </header>

          <div className="max-w-none text-[18px] leading-[1.85] text-[#293859]" data-testid="reader-iframe">
            {displayParagraphs.length === 0 ? (
              <div className="py-16 text-center text-[15px] font-medium italic text-[#586476]">正文为空。</div>
            ) : (
              displayParagraphs.map((paragraph, index) => (
                <p
                  key={`${index}-${paragraph.slice(0, 20)}`}
                  className="mb-9 whitespace-pre-wrap selection:bg-[#49A8C9]/25"
                >
                  {paragraph}
                </p>
              ))
            )}
          </div>
        </article>
      </div>
    </div>
  );
};

export default ReaderPage;
