import React, { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Spin, Tooltip, Progress, message } from 'antd'
import { Link } from 'react-router-dom'
import { useSearchParams } from 'react-router-dom'
import dayjs from 'dayjs'
import { digestApi } from '../../services/digest'
import { sourcesApi } from '../../services/sources'
import { contentsApi } from '../../services/contents'
import { systemApi } from '../../services/system'
import type { Content, DigestItem } from '../../types'
import DashboardHeader from './DashboardHeader'
import DashboardQueueStatus from './DashboardQueueStatus'
import DashboardCategoryTabs from './DashboardCategoryTabs'
import DashboardDigestList from './DashboardDigestList'
import { DASHBOARD_CATEGORIES, type TranslationProgress } from './dashboardTypes'
import {
  contentToDigestItem,
  getDashboardCategoryCount,
  getDashboardItems,
  renderDashboardTimePair,
} from './dashboardUtils'

const DashboardSearchResults = lazy(() => import('./DashboardSearchResults'))

const PageLoading: React.FC = () => (
  <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
    <Spin size="large" />
  </div>
)

const Dashboard: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const searchQuery = searchParams.get('search') || ''
  const [selectedDate, setSelectedDate] = useState(dayjs())
  const [activeTab, setActiveTab] = useState('all')
  const [translationProgress, setTranslationProgress] = useState<Record<string, TranslationProgress>>({})
  const translationControllersRef = useRef<Record<string, AbortController>>({})
  const queryClient = useQueryClient()

  useEffect(() => {
    return () => {
      Object.values(translationControllersRef.current).forEach((controller) => controller.abort())
      translationControllersRef.current = {}
    }
  }, [])

  const { data: searchResults, isLoading: searchLoading } = useQuery({
    queryKey: ['search-contents', searchQuery],
    queryFn: () => contentsApi.list({ search: searchQuery, page_size: 50 }),
    enabled: !!searchQuery,
  })

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: digestApi.getDashboardStats,
  })

  const { data: digest, isLoading: digestLoading } = useQuery({
    queryKey: ['digest', selectedDate.format('YYYY-MM-DD')],
    queryFn: () => digestApi.getDigest({ date: selectedDate.format('YYYY-MM-DD') }),
  })

  const { data: queueStatus, isLoading: queueLoading } = useQuery({
    queryKey: ['system-queue'],
    queryFn: systemApi.getQueueStatus,
    refetchInterval: 10000,
  })

  const fetchAllMutation = useMutation({
    mutationFn: sourcesApi.fetchAll,
    onSuccess: (data) => {
      message.success(`已触发抓取任务，共 ${data.source_count} 个监控源`)
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] })
        queryClient.invalidateQueries({ queryKey: ['digest'] })
        queryClient.invalidateQueries({ queryKey: ['system-queue'] })
      }, 3000)
    },
    onError: () => {
      message.error('抓取失败，请稍后重试')
    },
  })

  const currentItems = getDashboardItems(digest, activeTab)
  const searchItems = searchResults?.items.map((content: Content) => contentToDigestItem(content)) || []

  const hasTranslationReady = (item: DigestItem): boolean => {
    const meta = item.metadata as Record<string, unknown> | undefined
    if (!meta) {
      return false
    }
    if (meta.reader_translation_ready === true) {
      return true
    }
    const cached = meta.reader_translated_full_content
    return typeof cached === 'string' && cached.trim().length > 0
  }

  const startTranslationGeneration = async (item: DigestItem) => {
    const current = translationProgress[item.id]
    if (current?.status === 'generating') {
      return
    }

    const prevController = translationControllersRef.current[item.id]
    if (prevController) {
      prevController.abort()
    }
    const controller = new AbortController()
    translationControllersRef.current[item.id] = controller

    setTranslationProgress((prev) => ({
      ...prev,
      [item.id]: {
        status: 'generating',
        done: 0,
        total: 0,
      },
    }))

    try {
      await contentsApi.streamReaderTranslation(item.id, {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === 'init') {
            setTranslationProgress((prev) => ({
              ...prev,
              [item.id]: {
                status: 'generating',
                done: 0,
                total: event.paragraphs_total || 0,
              },
            }))
            return
          }
          if (event.type === 'chunk') {
            setTranslationProgress((prev) => {
              const old = prev[item.id] || { status: 'generating', done: 0, total: 0 }
              return {
                ...prev,
                [item.id]: {
                  status: 'generating',
                  done: old.done + 1,
                  total: old.total,
                },
              }
            })
            return
          }

          if (event.type === 'done') {
            const isReady = Boolean(event.translated) && !event.partial_fallback
            if (isReady) {
              setTranslationProgress((prev) => ({
                ...prev,
                [item.id]: {
                  status: 'ready',
                  done: event.paragraphs_streamed || event.paragraphs_total || 0,
                  total: event.paragraphs_total || 0,
                  message: '译文已生成',
                },
              }))
              queryClient.invalidateQueries({ queryKey: ['digest'] })
              queryClient.invalidateQueries({ queryKey: ['search-contents'] })
              return
            }

            setTranslationProgress((prev) => ({
              ...prev,
              [item.id]: {
                status: 'failed',
                done: event.paragraphs_streamed || 0,
                total: event.paragraphs_total || 0,
                message: event.message || (event.partial_fallback ? '译文不完整，已回退原文' : '译文生成失败'),
              },
            }))
          }
        },
      })
    } catch (error) {
      if (controller.signal.aborted) {
        return
      }
      const errMsg = error instanceof Error ? error.message : '译文生成失败'
      setTranslationProgress((prev) => ({
        ...prev,
        [item.id]: {
          status: 'failed',
          done: prev[item.id]?.done || 0,
          total: prev[item.id]?.total || 0,
          message: errMsg,
        },
      }))
      message.error('译文生成失败，请重试')
    } finally {
      if (translationControllersRef.current[item.id] === controller) {
        delete translationControllersRef.current[item.id]
      }
    }
  }

  const renderTranslationAction = (item: DigestItem) => {
    const local = translationProgress[item.id]
    const ready = local?.status === 'ready' || hasTranslationReady(item)
    if (ready) {
      return (
        <Link
          to={`/reader/${item.id}?translate=1`}
          data-testid={`read-translation-${item.id}`}
          style={{ marginLeft: 10, fontSize: 13, fontWeight: 400, color: '#6b7c3f' }}
        >
          阅读译文
        </Link>
      )
    }

    if (local?.status === 'generating') {
      const percent = local.total > 0 ? Math.min(99, Math.round((local.done / local.total) * 100)) : 0
      return (
        <span style={{ marginLeft: 10, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: '#6b7c3f' }}>生成中 {local.done}/{local.total || '?'}</span>
          <Progress percent={percent} size={[84, 6]} showInfo={false} strokeColor="#6b7c3f" />
        </span>
      )
    }

    const label = local?.status === 'failed' ? '重试生成' : '生成译文'
    const button = (
      <button
        type="button"
        onClick={(e) => {
          e.preventDefault()
          void startTranslationGeneration(item)
        }}
        style={{
          marginLeft: 10,
          fontSize: 13,
          fontWeight: 400,
          color: local?.status === 'failed' ? '#c41d7f' : '#6b7c3f',
          background: 'transparent',
          border: 'none',
          padding: 0,
          cursor: 'pointer',
        }}
      >
        {label}
      </button>
    )
    return local?.message ? <Tooltip title={local.message}>{button}</Tooltip> : button
  }

  if (statsLoading && !searchQuery) {
    return <PageLoading />
  }

  if (searchQuery) {
    return (
      <Suspense fallback={<PageLoading />}>
        <DashboardSearchResults
          searchQuery={searchQuery}
          total={searchResults?.total || 0}
          items={searchItems}
          isLoading={searchLoading}
          onClearSearch={() => setSearchParams({})}
          renderTimePair={renderDashboardTimePair}
          renderTranslationAction={renderTranslationAction}
        />
      </Suspense>
    )
  }

  return (
    <div style={{ backgroundColor: '#fff', minHeight: '100vh' }} data-testid="dashboard-page">
      <DashboardHeader
        stats={stats}
        selectedDate={selectedDate}
        onDateChange={setSelectedDate}
        onFetchAll={() => fetchAllMutation.mutate()}
        isFetching={fetchAllMutation.isPending}
      />

      <DashboardQueueStatus queueStatus={queueStatus} isLoading={queueLoading} />

      <DashboardCategoryTabs
        categories={DASHBOARD_CATEGORIES}
        activeTab={activeTab}
        getCategoryCount={(key) => getDashboardCategoryCount(digest, key)}
        onSelect={setActiveTab}
      />

      <DashboardDigestList
        isLoading={digestLoading}
        items={currentItems}
        selectedDate={selectedDate}
        activeTab={activeTab}
        categories={DASHBOARD_CATEGORIES}
        renderTimePair={renderDashboardTimePair}
        renderTranslationAction={renderTranslationAction}
      />
    </div>
  )
}

export default Dashboard
