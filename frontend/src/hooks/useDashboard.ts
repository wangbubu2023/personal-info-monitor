import { useState, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import dayjs, { Dayjs } from 'dayjs';
import { message } from 'antd';
import { digestApi } from '../services/digest';
import { sourcesApi } from '../services/sources';
import { contentsApi } from '../services/contents';
import { systemApi } from '../services/system';
import {
  contentToDigestItem,
  getDashboardItems,
  type DashboardSortMode,
} from '../components/Dashboard/dashboardUtils';
import { DASHBOARD_CATEGORIES } from '../components/Dashboard/dashboardTypes';
import type { Content } from '../types';

const DASHBOARD_TAB_KEYS = new Set(DASHBOARD_CATEGORIES.map((c) => c.key));

export const useDashboard = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchQuery = searchParams.get('search') || '';
  const selectedSourceId = searchParams.get('source_id') || '';
  const selectedSourceName = searchParams.get('source') || '';
  const [selectedRange, setSelectedRange] = useState<[Dayjs, Dayjs]>([dayjs(), dayjs()]);
  const [sortMode, setSortMode] = useState<DashboardSortMode>('time_desc');
  const queryClient = useQueryClient();

  /** 与 URL `?tab=` 同步，刷新后保留资讯分类 tab */
  const activeTab = useMemo(() => {
    const t = searchParams.get('tab');
    if (t && DASHBOARD_TAB_KEYS.has(t)) return t;
    return 'all';
  }, [searchParams]);

  const setActiveTab = useCallback(
    (key: string) => {
      if (!DASHBOARD_TAB_KEYS.has(key)) return;
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (key === 'all') next.delete('tab');
          else next.set('tab', key);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // Queries
  const { data: contentResults, isLoading: contentLoading } = useQuery({
    queryKey: ['dashboard-contents', searchQuery, selectedSourceId],
    queryFn: () => contentsApi.list({
      search: searchQuery || undefined,
      source_id: selectedSourceId || undefined,
      page_size: 50,
    }),
    enabled: !!searchQuery || !!selectedSourceId,
  });

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: digestApi.getDashboardStats,
  });

  const { data: digest, isLoading: digestLoading } = useQuery({
    queryKey: [
      'digest',
      selectedRange[0].format('YYYY-MM-DD'),
      selectedRange[1].format('YYYY-MM-DD'),
      sortMode,
    ],
    queryFn: () => digestApi.getDigest({
      date_from: selectedRange[0].format('YYYY-MM-DD'),
      date_to: selectedRange[1].format('YYYY-MM-DD'),
      sort: sortMode,
    }),
  });

  const { data: queueStatus, isLoading: queueLoading } = useQuery({
    queryKey: ['system-queue'],
    queryFn: systemApi.getQueueStatus,
    refetchInterval: 10000,
  });

  // Mutations
  const fetchAllMutation = useMutation({
    mutationFn: sourcesApi.fetchAll,
    onSuccess: (data) => {
      message.success(`Task triggered for ${data.source_count} sources`);
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] });
        queryClient.invalidateQueries({ queryKey: ['digest'] });
        queryClient.invalidateQueries({ queryKey: ['system-queue'] });
      }, 3000);
    },
    onError: () => message.error('Fetch failed'),
  });

  // Derived State
  const currentItems = useMemo(() => getDashboardItems(digest, activeTab, sortMode), [digest, activeTab, sortMode]);
  const contentItems = useMemo(() => 
    contentResults?.items.map((content: Content) => contentToDigestItem(content)) || [], 
    [contentResults]
  );

  return {
    searchQuery,
    selectedSourceId,
    selectedSourceName,
    selectedRange,
    setSelectedRange,
    sortMode,
    setSortMode,
    activeTab,
    setActiveTab,
    stats,
    statsLoading,
    digest,
    digestLoading,
    queueStatus,
    queueLoading,
    currentItems,
    contentItems,
    contentTotal: contentResults?.total ?? 0,
    contentLoading,
    fetchAll: fetchAllMutation.mutate,
    isFetchingAll: fetchAllMutation.isPending,
    clearContentFilter: () =>
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('search');
          next.delete('source_id');
          next.delete('source');
          return next;
        },
        { replace: true },
      ),
  };
};
