import React from 'react';
import { motion } from 'framer-motion';

export interface CategoryPillTabItem {
  key: string;
  label: string;
}

interface CategoryPillTabsProps {
  items: CategoryPillTabItem[];
  activeKey: string;
  getCount: (key: string) => number;
  onSelect: (key: string) => void;
  /** 与顶栏一体时去掉外层底边 */
  borderless?: boolean;
  /** 同屏多个实例时需唯一，避免 framer-motion layout 串台 */
  layoutId?: string;
  'data-testid'?: string;
  getTabTestId?: (key: string) => string;
}

/**
 * 资讯页「信源分类」与设置页监测源类型筛选共用：圆角胶囊 + 数字徽章，视觉一致。
 */
const CategoryPillTabs: React.FC<CategoryPillTabsProps> = ({
  items,
  activeKey,
  getCount,
  onSelect,
  borderless = false,
  layoutId = 'category-pill-tabs',
  'data-testid': testId,
  getTabTestId,
}) => (
  <div
    className={`min-w-0 flex-1 ${borderless ? '' : 'border-b border-[rgba(88,100,118,0.1)]'} pb-0.5`}
    data-testid={testId}
  >
    <div className="-mx-0.5 flex flex-wrap gap-1 px-0.5">
      {items.map((cat) => {
        const isActive = activeKey === cat.key;
        const count = getCount(cat.key);
        return (
          <button
            key={cat.key}
            type="button"
            onClick={() => onSelect(cat.key)}
            data-testid={getTabTestId ? getTabTestId(cat.key) : undefined}
            className={`group relative flex items-center gap-1.5 rounded-full py-2 pl-3.5 pr-2 text-[12px] font-medium transition-colors sm:text-[13px] ${
              isActive ? 'text-[#2c3a50]' : 'text-[#5f6f82] hover:text-[#2c3a50]'
            }`}
          >
            <span className="relative z-10 whitespace-nowrap">{cat.label}</span>
            <span
              className={`relative z-10 min-w-[1.125rem] rounded-full px-1 py-0.5 text-center text-[12px] font-semibold tabular-nums transition-colors ${
                isActive
                  ? 'bg-[#49A8C9] text-white'
                  : 'bg-[rgba(88,100,118,0.08)] text-[#5f6f82] group-hover:bg-[rgba(88,100,118,0.12)]'
              }`}
            >
              {count}
            </span>
            {isActive && (
              <motion.div
                layoutId={layoutId}
                className="absolute inset-0 z-0 rounded-full border border-[rgba(88,100,118,0.08)] bg-white shadow-sm"
                transition={{ type: 'spring', bounce: 0.2, duration: 0.55 }}
              />
            )}
          </button>
        );
      })}
    </div>
  </div>
);

export default CategoryPillTabs;
