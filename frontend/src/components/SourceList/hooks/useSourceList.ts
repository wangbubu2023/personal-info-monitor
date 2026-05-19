import { useState, useEffect } from 'react'
import type React from 'react'
import { useQuery, useQueries } from '@tanstack/react-query'
import { listSources } from '../../../services/sources'
import { configsApi } from '../../../services/configs'
import { sourceKeys } from '../../../services/queryKeys'
import { sourceTypeFilterOptions } from '../../../config/sourceTypes'
import { getAxiosErrorMessage } from '../../../utils/apiError'

export const typeFilters = sourceTypeFilterOptions()

export function useSourceList() {
  const [activeTypeFilter, setActiveTypeFilter] = useState('all')
  const [searchInput, setSearchInput] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([])

  // Debounce search input
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(searchInput.trim()), 300)
    return () => window.clearTimeout(t)
  }, [searchInput])

  // Reset page on filter/search change
  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, activeTypeFilter])

  // Reset row selection when page/filter/search changes
  useEffect(() => {
    setSelectedRowKeys([])
  }, [page, pageSize, debouncedSearch, activeTypeFilter])

  const listParams = {
    page,
    page_size: pageSize,
    search: debouncedSearch || undefined,
    type: activeTypeFilter === 'all' ? undefined : activeTypeFilter,
    scope: 'library' as const,
  }

  const {
    data: listData,
    isLoading,
    isError,
    error,
    isFetching,
    refetch: refetchSources,
  } = useQuery({
    queryKey: sourceKeys.list(listParams as Record<string, unknown>),
    queryFn: () => listSources(listParams),
  })

  const { data: quotaData } = useQuery({
    queryKey: [...sourceKeys.all, 'quota-total'],
    queryFn: () => listSources({ page: 1, page_size: 1 }),
    staleTime: 30_000,
  })

  const { data: allTabCountData } = useQuery({
    queryKey: [...sourceKeys.all, 'tab-total', 'all', debouncedSearch],
    queryFn: () =>
      listSources({ page: 1, page_size: 1, search: debouncedSearch || undefined }),
    staleTime: 30_000,
  })

  const typeTabCountQueries = useQueries({
    queries: typeFilters
      .filter((f) => f.key !== 'all')
      .map((f) => ({
        queryKey: [...sourceKeys.all, 'tab-total', f.key, debouncedSearch],
        queryFn: () =>
          listSources({ page: 1, page_size: 1, type: f.key, search: debouncedSearch || undefined }),
        staleTime: 30_000,
      })),
  })

  const { data: authConfigs } = useQuery({
    queryKey: ['auth-configs'],
    queryFn: configsApi.listAuthConfigs,
  })

  const { data: systemSettings } = useQuery({
    queryKey: ['system-settings'],
    queryFn: configsApi.getSettings,
  })

  const sources = listData?.items ?? []
  const sourceCount = quotaData?.total ?? 0
  const maxSources = Number(systemSettings?.limits?.max_sources || 200)
  const remainingSources = Math.max(0, maxSources - sourceCount)
  const sourceLimitReached = sourceCount >= maxSources
  const sourceLoadError = getAxiosErrorMessage(error, '信源加载失败，请稍后重试。')

  const getTypeCount = (typeKey: string): number => {
    if (typeKey === 'all') return allTabCountData?.total ?? 0
    const idx = typeFilters.filter((f) => f.key !== 'all').findIndex((f) => f.key === typeKey)
    if (idx < 0) return 0
    return typeTabCountQueries[idx]?.data?.total ?? 0
  }

  return {
    // State
    activeTypeFilter,
    setActiveTypeFilter,
    searchInput,
    setSearchInput,
    debouncedSearch,
    page,
    setPage,
    pageSize,
    setPageSize,
    selectedRowKeys,
    setSelectedRowKeys,
    // Derived / query data
    sources,
    listData,
    isLoading,
    isError,
    error,
    isFetching,
    refetchSources,
    authConfigs,
    systemSettings,
    sourceCount,
    maxSources,
    remainingSources,
    sourceLimitReached,
    sourceLoadError,
    getTypeCount,
  }
}
