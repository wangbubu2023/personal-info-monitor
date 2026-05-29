import React from 'react';
import { Button } from 'antd';
import { Search, Loader2, SearchX } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import type { DigestItem } from '../../types';
import DashboardItemCard from './DashboardItemCard';

interface DashboardSearchResultsProps {
  searchQuery?: string;
  sourceName?: string;
  sourceId?: string;
  total: number;
  items: DigestItem[];
  isLoading: boolean;
  onClear: () => void;
}

const DashboardSearchResults: React.FC<DashboardSearchResultsProps> = ({
  searchQuery,
  sourceName,
  sourceId,
  total,
  items,
  isLoading,
  onClear,
}) => {
  const hasSearch = Boolean(searchQuery);
  const hasSource = Boolean(sourceId);
  const title = hasSource ? '信源内容' : '搜索结果';
  const emptyText = hasSource ? '该信源暂无匹配内容。' : '试试更短的关键词，或换一种说法。';

  return (
  <div className="space-y-4 pb-16 pt-1" data-testid="dashboard-search-page">
    <div className="mx-auto max-w-feed pl-5 pr-6 sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10">
      <div className="flex flex-col gap-3.5 border-b border-[rgba(88,100,118,0.1)] pb-3 pt-4 sm:gap-4 sm:pt-5">
        {/* 第一层：图标 + 标题 */}
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-[#49A8C9]/22 bg-white/95 text-[#3a9eb8] shadow-sm">
            <Search size={18} strokeWidth={1.5} />
          </div>
          <h1 className="text-[19px] font-semibold leading-tight tracking-tight text-[#2c3a50] sm:text-[20px]">
            {title}
          </h1>
        </div>

        {/* 第二层：摘要文案 */}
        <p className="max-w-2xl text-[12px] leading-relaxed text-[#6b7c8f] sm:text-[13px]">
          共 <span className="font-semibold tabular-nums text-[#2c3a50]">{total}</span> 条
          {hasSource ? (
            <>
              来自信源 <span className="font-medium text-[#49A8C9]">「{sourceName || '当前信源'}」</span>
            </>
          ) : null}
          {hasSearch ? (
            <>
              {hasSource ? '，且' : ''}与关键词{' '}
              <span className="font-medium text-[#49A8C9]">「{searchQuery}」</span>
              匹配
            </>
          ) : null}
          。
        </p>

        {/* 第三层：操作 */}
        <div className="flex justify-end">
          <Button
            onClick={onClear}
            className="!h-9 !rounded-lg !border-[rgba(88,100,118,0.12)] !bg-white/95 !px-4 !text-[13px] !font-medium !text-[#5f6f82] hover:!border-[#49A8C9]/28 hover:!text-[#2c3a50]"
          >
            返回全部
          </Button>
        </div>
      </div>
    </div>

    <div className="mx-auto max-w-feed pl-5 pr-6 sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10">
      <AnimatePresence mode="wait">
        {isLoading ? (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex min-h-[200px] items-center justify-center py-12"
          >
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="h-8 w-8 animate-spin text-[#49A8C9]" />
              <span className="text-[13px] font-medium text-[#586476]">搜索中…</span>
            </div>
          </motion.div>
        ) : items.length > 0 ? (
          <motion.div key="results" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
            {items.map((item) => (
              <DashboardItemCard
                key={item.id}
                item={item}
                activeTab="all"
                searchReturnQuery={searchQuery}
                sourceReturnId={sourceId}
                sourceReturnName={sourceName}
              />
            ))}
          </motion.div>
        ) : (
          <motion.div
            key="no-result"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex min-h-[220px] flex-col items-center justify-center rounded-2xl border border-dashed border-[rgba(88,100,118,0.14)] bg-white/50 px-6 py-10"
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-full border border-[rgba(88,100,118,0.1)] bg-white shadow-sm">
              <SearchX size={22} className="text-[#5f6f82]" strokeWidth={1.5} />
            </div>
            <h3 className="mt-4 text-[15px] font-semibold text-[#2c3a50]">没有匹配结果</h3>
            <p className="mt-1.5 max-w-xs text-center text-[13px] leading-relaxed text-[#5f6f82]">
              {emptyText}
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  </div>
  );
};

export default DashboardSearchResults;
