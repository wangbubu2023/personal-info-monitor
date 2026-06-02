import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { DigestItem } from '../../types';
import type { CategoryTab } from './dashboardTypes';
import DashboardItemCard from './DashboardItemCard';
import { Loader2, SearchX } from 'lucide-react';

interface DashboardDigestListProps {
  isLoading: boolean;
  items: DigestItem[];
  rangeLabel: string;
  activeTab: string;
  categories: CategoryTab[];
}

const DashboardDigestList: React.FC<DashboardDigestListProps> = ({
  isLoading,
  items,
  rangeLabel,
  activeTab,
  categories,
}) => (
  <div className="min-w-0" data-testid="dashboard-content-list">
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
            <Loader2 className="h-8 w-8 animate-spin text-[#49A8C9]" strokeWidth={1.5} />
            <span className="text-[13px] text-[#5f6f82]">正在加载列表…</span>
          </div>
        </motion.div>
      ) : items.length > 0 ? (
        <motion.div key="content" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
          {items.map((item) => (
            <DashboardItemCard key={item.id} item={item} activeTab={activeTab} />
          ))}
        </motion.div>
      ) : (
        <motion.div
          key="empty"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex min-h-[220px] flex-col items-center justify-center rounded-2xl border border-dashed border-[rgba(88,100,118,0.14)] bg-white/50 px-6 py-10"
        >
          <div className="flex h-12 w-12 items-center justify-center rounded-full border border-[rgba(88,100,118,0.1)] bg-white shadow-sm">
            <SearchX size={22} className="text-[#5f6f82]" strokeWidth={1.5} />
          </div>
          <h3 className="mt-4 text-[15px] font-semibold text-[#2c3a50]">这一天没有新条目</h3>
          <p className="mt-1.5 max-w-sm text-center text-[13px] leading-relaxed text-[#5f6f82]">
            {rangeLabel}
            {activeTab === 'all'
              ? ' 暂无内容。'
              : ` 在「${categories.find((c) => c.key === activeTab)?.label || ''}」分类下暂无内容。`}
          </p>
        </motion.div>
      )}
    </AnimatePresence>
  </div>
);

export default DashboardDigestList;
