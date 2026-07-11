import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import type { DigestItem } from '../../types';
import type { CategoryTab } from './dashboardTypes';
import DashboardItemCard from './DashboardItemCard';
import { ChevronDown, ChevronRight, Loader2, SearchX } from 'lucide-react';
import { buildReaderPath } from './dashboardUtils';
import { recordReaderInteraction, saveReaderSequence } from '../../utils/readerFlow';

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
}) => {
  const navigate = useNavigate();
  const [focusedIndex, setFocusedIndex] = useState(0);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  const groups = useMemo(() => buildDigestGroups(items), [items]);
  const visibleItems = useMemo(
    () => groups.flatMap((group) => (group.collapsed && !expandedGroups[group.key] ? [] : group.items)),
    [groups, expandedGroups],
  );

  useEffect(() => {
    saveReaderSequence(items);
  }, [items]);

  useEffect(() => {
    setFocusedIndex(0);
  }, [items, activeTab]);

  useEffect(() => {
    const maxIndex = Math.max(0, visibleItems.length - 1);
    if (focusedIndex > maxIndex) setFocusedIndex(maxIndex);
  }, [focusedIndex, visibleItems.length]);

  useEffect(() => {
    if (!visibleItems.length) return;

    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      if (event.key === 'j' || event.key === 'ArrowDown') {
        event.preventDefault();
        recordReaderInteraction('keyboard', 'navigate');
        setFocusedIndex((index) => Math.min(visibleItems.length - 1, index + 1));
      } else if (event.key === 'k' || event.key === 'ArrowUp') {
        event.preventDefault();
        recordReaderInteraction('keyboard', 'navigate');
        setFocusedIndex((index) => Math.max(0, index - 1));
      } else if (event.key === 'Enter') {
        const item = visibleItems[focusedIndex];
        if (!item) return;
        event.preventDefault();
        recordReaderInteraction('keyboard', 'open');
        navigate(buildReaderPath(item.id, { tab: activeTab }));
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [activeTab, focusedIndex, navigate, visibleItems]);

  return (
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
          {groups.map((group) => (
            <React.Fragment key={group.key}>
              {group.collapsed && !expandedGroups[group.key] ? (
                <button
                  type="button"
                  className="flex w-full items-center justify-between rounded-xl border border-[rgba(88,100,118,0.1)] bg-[#f7fafc] px-4 py-3 text-left text-[13px] text-[#5f6f82] transition-colors hover:border-[#49A8C9]/22 hover:bg-white"
                  onClick={() => setExpandedGroups((prev) => ({ ...prev, [group.key]: true }))}
                >
                  <span className="min-w-0 truncate">
                    已读事件簇 · {group.items.length} 条 · {group.items[0]?.translated_title || group.items[0]?.title}
                  </span>
                  <ChevronRight size={16} className="shrink-0 text-[#49A8C9]" />
                </button>
              ) : (
                <>
                  {group.collapsed ? (
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 px-1 text-left text-[12px] font-medium text-[#8a96a5] hover:text-[#586476]"
                      onClick={() => setExpandedGroups((prev) => ({ ...prev, [group.key]: false }))}
                    >
                      <ChevronDown size={14} /> 已展开事件簇
                    </button>
                  ) : null}
                  {group.items.map((item) => {
                    const visibleIndex = visibleItems.findIndex((visible) => visible.id === item.id);
                    return (
                      <DashboardItemCard
                        key={item.id}
                        item={item}
                        activeTab={activeTab}
                        focused={visibleIndex === focusedIndex}
                      />
                    );
                  })}
                </>
              )}
            </React.Fragment>
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
              ? ' 当前模式下暂无内容。'
              : ` 在「${categories.find((c) => c.key === activeTab)?.label || ''}」分类下暂无内容。`}
          </p>
        </motion.div>
      )}
    </AnimatePresence>
  </div>
  );
};

function eventGroupKey(item: DigestItem): string {
  const metadata = item.metadata || {};
  const duplicateGroup = metadata.duplicate_group_id || metadata.canonical_external_id || metadata.event_id;
  return duplicateGroup ? `event:${String(duplicateGroup)}` : `item:${item.id}`;
}

function buildDigestGroups(items: DigestItem[]) {
  const byKey = new Map<string, DigestItem[]>();
  const order: string[] = [];
  for (const item of items) {
    const key = eventGroupKey(item);
    if (!byKey.has(key)) {
      byKey.set(key, []);
      order.push(key);
    }
    byKey.get(key)?.push(item);
  }
  return order.map((key) => {
    const groupItems = byKey.get(key) || [];
    return {
      key,
      items: groupItems,
      collapsed: groupItems.length > 1 && groupItems.every((item) => item.read_status),
    };
  });
}

export default DashboardDigestList;
