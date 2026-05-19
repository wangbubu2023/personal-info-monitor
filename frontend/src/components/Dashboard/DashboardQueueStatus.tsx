import React from 'react';
import { Tooltip } from 'antd';
import { Loader2, Zap, Brain, AlertCircle, CheckCircle } from 'lucide-react';
import type { QueueStatus } from '../../services/system';

const iconStroke = 1.5

interface DashboardQueueStatusProps {
  queueStatus?: QueueStatus;
  isLoading: boolean;
  /** 与分类 Tab 同排时的紧凑条样式 */
  variant?: 'bar' | 'inline';
}

const DashboardQueueStatus: React.FC<DashboardQueueStatusProps> = ({
  queueStatus,
  isLoading,
  variant = 'bar',
}) => {
  const isInline = variant === 'inline';

  const inner = (
    <>
      <div className={`flex shrink-0 items-center gap-1.5 ${isInline ? 'text-[#5f6f82]' : 'font-medium text-[#4a5a6e]'}`}>
        <Zap size={isInline ? 13 : 15} className="shrink-0 text-[#49A8C9]" strokeWidth={iconStroke} />
        <span className={isInline ? 'text-[12px]' : 'text-[13px]'}>任务状态</span>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-1.5 text-[#5f6f82]">
          <Loader2 size={13} className="animate-spin" strokeWidth={iconStroke} />
          <span className="text-[12px]">同步中…</span>
        </div>
      ) : queueStatus ? (
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px]">
          <Tooltip title="并行抓取 worker 数">
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <span className="text-[#5f6f82]">抓取</span>
              <span
                className={`tabular-nums font-semibold ${queueStatus.running_fetches > 0 ? 'text-[#2a8f65]' : 'text-[#8a96a5]'}`}
              >
                {queueStatus.running_fetches}/{queueStatus.fetch_concurrency}
              </span>
            </span>
          </Tooltip>

          <span className="hidden text-[rgba(88,100,118,0.25)] sm:inline">·</span>

          <Tooltip title="AI 处理任务">
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <Brain
                size={13}
                strokeWidth={iconStroke}
                className={queueStatus.running_processes > 0 ? 'text-[#49A8C9]' : 'text-[#8a96a5]'}
              />
              <span className="text-[#5f6f82]">处理</span>
              <span
                className={`tabular-nums font-semibold ${queueStatus.running_processes > 0 ? 'text-[#49A8C9]' : 'text-[#8a96a5]'}`}
              >
                {queueStatus.running_processes}
              </span>
            </span>
          </Tooltip>

          {queueStatus.sources_status?.some((s) => s.last_error) ? (
            <span className="inline-flex items-center gap-1 whitespace-nowrap text-rose-600">
              <AlertCircle size={13} strokeWidth={iconStroke} />
              {queueStatus.sources_status.filter((s) => s.last_error).length} 源异常
            </span>
          ) : (
            <span className="hidden items-center gap-1 whitespace-nowrap text-[#2a8f65] lg:inline-flex">
              <CheckCircle size={13} strokeWidth={iconStroke} />
              正常
            </span>
          )}
        </div>
      ) : (
        <span className="truncate text-[12px] text-[#7d8b9a]">无法连接后端</span>
      )}
    </>
  );

  if (isInline) {
    return (
      <div
        className="flex min-w-0 max-w-full shrink-0 flex-wrap items-center gap-x-2 gap-y-1 sm:max-w-[min(100%,22rem)] sm:justify-end lg:max-w-none"
        data-testid="dashboard-fetch-status"
      >
        {inner}
      </div>
    );
  }

  return (
    <div
      className="border-y border-[rgba(88,100,118,0.08)] bg-white/55 py-2.5 backdrop-blur-[2px]"
      data-testid="dashboard-fetch-status"
    >
      <div className="mx-auto flex max-w-page flex-wrap items-center gap-x-5 gap-y-2 pl-5 pr-6 text-[13px] leading-snug sm:pl-7 sm:pr-8 lg:pl-9 lg:pr-10">
        {inner}
      </div>
    </div>
  );
};

export default DashboardQueueStatus;
