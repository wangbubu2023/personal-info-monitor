import React from 'react';
import type { CategoryTab } from './dashboardTypes';
import CategoryPillTabs from '../common/CategoryPillTabs';

interface DashboardCategoryTabsProps {
  categories: CategoryTab[];
  activeTab: string;
  getCategoryCount: (key: string) => number;
  onSelect: (key: string) => void;
  borderless?: boolean;
}

const DashboardCategoryTabs: React.FC<DashboardCategoryTabsProps> = ({
  categories,
  activeTab,
  getCategoryCount,
  onSelect,
  borderless = false,
}) => (
  <CategoryPillTabs
    items={categories.map((c) => ({ key: c.key, label: c.label }))}
    activeKey={activeTab}
    getCount={getCategoryCount}
    onSelect={onSelect}
    borderless={borderless}
    layoutId="dashboard-tab-pill"
    data-testid="dashboard-tabs"
    getTabTestId={(key) => `dashboard-tab-${key}`}
  />
);

export default DashboardCategoryTabs;
