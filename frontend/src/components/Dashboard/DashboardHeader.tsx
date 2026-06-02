import React from 'react';
import { DatePicker, Segmented } from 'antd';
import { RefreshCw, Calendar, Inbox, TrendingUp, ArrowDownWideNarrow } from 'lucide-react';
import type { Dayjs } from 'dayjs';
import type { DashboardStats } from '../../types';
import PageHeroTitle from '../common/PageHeroTitle';
import type { DashboardSortMode } from './dashboardUtils';

const iconStroke = 1.5

interface DashboardHeaderProps {
  stats?: DashboardStats;
  selectedRange: [Dayjs, Dayjs];
  onRangeChange: (range: [Dayjs, Dayjs]) => void;
  sortMode: DashboardSortMode;
  onSortModeChange: (mode: DashboardSortMode) => void;
  onFetchAll: () => void;
  isFetching: boolean;
}

const DashboardHeader: React.FC<DashboardHeaderProps> = ({
  stats,
  selectedRange,
  onRangeChange,
  sortMode,
  onSortModeChange,
  onFetchAll,
  isFetching,
}) => (
  <div className="flex flex-col gap-3.5 pb-1 pt-4 sm:gap-4 sm:pt-5">
    {/* 标题区与日期/抓取同一行，纵向与整块标题（中英）居中对齐 */}
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <PageHeroTitle
        titleZh="资讯中心"
        titleEn="Information Center"
        data-testid="dashboard-title"
      />
      <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
        <div className="flex items-center gap-1.5 rounded-lg border border-[rgba(88,100,118,0.1)] bg-white/95 px-2.5 py-1.5 shadow-sm">
          <Calendar size={15} className="ml-0.5 shrink-0 text-[#5f6f82]" strokeWidth={iconStroke} />
          <DatePicker.RangePicker
            value={selectedRange}
            onChange={(range) => {
              if (range?.[0] && range?.[1]) onRangeChange([range[0], range[1]])
            }}
            allowClear={false}
            size="small"
            className="!w-[220px] !min-w-0 !border-none !bg-transparent !shadow-none !text-[13px] !text-[#4a5a6e] hover:!text-[#2c3a50] focus:!text-[#2c3a50] sm:!w-[250px]"
            suffixIcon={null}
          />
        </div>

        <div className="flex items-center gap-1.5 rounded-lg border border-[rgba(88,100,118,0.1)] bg-white/95 px-2 py-1.5 shadow-sm">
          <ArrowDownWideNarrow size={15} className="ml-0.5 shrink-0 text-[#5f6f82]" strokeWidth={iconStroke} />
          <Segmented
            size="small"
            value={sortMode}
            onChange={(value) => onSortModeChange(value as DashboardSortMode)}
            options={[
              { label: '时间倒排', value: 'time_desc' },
              { label: '得分倒排', value: 'score_desc' },
            ]}
          />
        </div>

        <button
          type="button"
          onClick={onFetchAll}
          disabled={isFetching}
          data-testid="dashboard-fetch-all-btn"
          className={`flex h-9 shrink-0 items-center justify-center gap-2 rounded-lg px-4 text-[13px] font-medium transition-all ${
            isFetching
              ? 'cursor-not-allowed border border-[rgba(88,100,118,0.1)] bg-[#eef3f8] text-[#8a96a5]'
              : 'border border-[#49A8C9]/28 bg-[#49A8C9] text-white shadow-sm shadow-[#49A8C9]/15 hover:bg-[#3d94b3] active:scale-[0.99]'
          }`}
        >
          <RefreshCw size={14} strokeWidth={iconStroke} className={isFetching ? 'animate-spin' : ''} />
          {isFetching ? '同步中' : '重新抓取'}
        </button>
      </div>
    </div>

    <div className="flex flex-wrap items-center gap-2 sm:gap-3">
      <div className="flex items-center gap-2 rounded-lg border border-[rgba(88,100,118,0.08)] bg-white/90 px-2.5 py-1.5 shadow-sm">
        <TrendingUp className="h-3.5 w-3.5 shrink-0 text-[#3a9eb8]" strokeWidth={iconStroke} />
        <span className="text-[12px] text-[#5f6f82]">收录</span>
        <span className="text-[14px] font-semibold tabular-nums text-[#2c3a50]">{stats?.today_total ?? 0}</span>
      </div>
      <div className="flex items-center gap-2 rounded-lg border border-[rgba(88,100,118,0.08)] bg-white/90 px-2.5 py-1.5 shadow-sm">
        <Inbox className="h-3.5 w-3.5 shrink-0 text-[#6d684f]" strokeWidth={iconStroke} />
        <span className="text-[12px] text-[#5f6f82]">待读</span>
        <span className="text-[14px] font-semibold tabular-nums text-[#2c3a50]">{stats?.unread_count ?? 0}</span>
      </div>
    </div>
  </div>
);

export default DashboardHeader;
