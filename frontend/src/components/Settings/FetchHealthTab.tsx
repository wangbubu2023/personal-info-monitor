import React from 'react'
import { Table, Tag, Button, Tooltip, Alert, Empty, message, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { SyncOutlined } from '@ant-design/icons'
import { FileDown, HeartPulse } from 'lucide-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { sourcesApi } from '../../services/sources'
import { systemApi } from '../../services/system'
import { sourceKeys } from '../../services/queryKeys'
import type { Source } from '../../types'
import { formatLocalDateTime } from '../../utils/datetime'
import FetchHealthDrawer from '../SourceList/FetchHealthDrawer'
import {
  deriveHealthSeverity,
  failureCodeLabel,
  formatCooldownRemaining,
  formatLatency,
  formatRate,
  rssHealthColor,
  rssHealthLabel,
  HEALTH_SEVERITY_META,
  HEALTH_SEVERITY_ORDER,
  type HealthSeverity,
} from '../../utils/fetchHealth'
import SettingsSection from './SettingsSection'

const typeLabels: Record<string, string> = {
  website: '网站',
  rss: 'RSS',
  x: 'X',
  youtube: 'YouTube',
  podcast: '播客',
}

const SummaryCard: React.FC<{ label: string; value: number; color: string }> = ({
  label,
  value,
  color,
}) => (
  <div className="flex min-w-[88px] flex-1 flex-col gap-1 rounded-xl border border-[rgba(88,100,118,0.1)] bg-white px-4 py-3 shadow-sm">
    <span className="text-[12px] text-[#6b7c8f]">{label}</span>
    <span className="text-[22px] font-semibold tabular-nums" style={{ color }}>
      {value}
    </span>
  </div>
)

const FetchHealthTab: React.FC = () => {
  const [healthSource, setHealthSource] = React.useState<Source | null>(null)

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: [...sourceKeys.all, 'fetch-health-all'],
    queryFn: () => sourcesApi.listAll(),
    refetchInterval: 30000,
  })

  const { data: paidMatrix, isLoading: paidMatrixLoading, refetch: refetchPaidMatrix } = useQuery({
    queryKey: [...sourceKeys.all, 'paid-source-matrix'],
    queryFn: () => sourcesApi.getPaidMatrix(),
    refetchInterval: 30000,
  })

  const supportBundleMutation = useMutation({
    mutationFn: systemApi.downloadSupportBundle,
    onSuccess: () => message.success('诊断包已导出'),
    onError: () => message.error('无法导出诊断包，请检查后端日志'),
  })

  const sources = React.useMemo(() => data ?? [], [data])

  const counts = React.useMemo(() => {
    const acc: Record<HealthSeverity, number> = { error: 0, cooling: 0, warning: 0, ok: 0, unknown: 0 }
    for (const s of sources) acc[deriveHealthSeverity(s)] += 1
    return acc
  }, [sources])

  const sorted = React.useMemo(
    () =>
      [...sources].sort(
        (a, b) =>
          HEALTH_SEVERITY_ORDER[deriveHealthSeverity(a)] -
          HEALTH_SEVERITY_ORDER[deriveHealthSeverity(b)],
      ),
    [sources],
  )

  const columns: ColumnsType<Source> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
      ellipsis: true,
      render: (name: string) => <span className="font-medium text-[#293859]">{name}</span>,
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      width: 80,
      render: (t: string) => <Tag>{typeLabels[t] || t}</Tag>,
    },
    {
      title: '健康',
      key: 'health',
      width: 96,
      render: (_, record) => {
        const sev = deriveHealthSeverity(record)
        const meta = HEALTH_SEVERITY_META[sev]
        return (
          <Tooltip title={record.fetch_status_message || undefined}>
            <Tag style={{ color: meta.color, borderColor: meta.color, background: 'transparent' }}>
              {meta.label}
            </Tag>
          </Tooltip>
        )
      },
    },
    {
      title: '最近失败',
      key: 'last_failure_code',
      width: 130,
      render: (_, record) =>
        record.last_failure_code ? (
          <Tag color="red">{failureCodeLabel(record.last_failure_code)}</Tag>
        ) : (
          <span className="text-[#8a96a5]">—</span>
        ),
    },
    {
      title: '冷却至',
      key: 'cooldown',
      width: 120,
      render: (_, record) => {
        const remaining = formatCooldownRemaining(record.cooldown_until)
        return remaining ? (
          <Tag color="purple">约 {remaining}</Tag>
        ) : (
          <span className="text-[#8a96a5]">—</span>
        )
      },
    },
    {
      title: '成功率(7d)',
      key: 'success_rate',
      width: 100,
      align: 'right' as const,
      render: (_, record) => formatRate(record.fetch_profile_summary?.success_rate_7d),
    },
    {
      title: '正文完整率(7d)',
      key: 'fulltext_rate',
      width: 120,
      align: 'right' as const,
      render: (_, record) => formatRate(record.fetch_profile_summary?.fulltext_success_rate_7d),
    },
    {
      title: '入库(7d)',
      key: 'saved',
      width: 90,
      align: 'right' as const,
      render: (_, record) => record.fetch_profile_summary?.saved_count_7d ?? '—',
    },
    {
      title: '平均耗时',
      key: 'latency',
      width: 100,
      align: 'right' as const,
      render: (_, record) => formatLatency(record.fetch_profile_summary?.avg_latency_ms_7d),
    },
    {
      title: 'RSS',
      key: 'rss',
      width: 90,
      render: (_, record) => {
        const h = record.metadata?.rss_health
        return h?.status ? (
          <Tag color={rssHealthColor(h.status)}>{rssHealthLabel(h.status)}</Tag>
        ) : (
          <span className="text-[#8a96a5]">—</span>
        )
      },
    },
    {
      title: '最后抓取',
      dataIndex: 'last_fetched_at',
      key: 'last_fetched_at',
      width: 150,
      render: (time: string | null) => (time ? formatLocalDateTime(time, 'zh-CN') : '—'),
    },
    {
      title: '诊断',
      key: 'actions',
      width: 80,
      fixed: 'right' as const,
      align: 'center' as const,
      render: (_, record) => (
        <Tooltip title="抓取健康诊断">
          <Button
            type="text"
            size="small"
            icon={<HeartPulse size={15} strokeWidth={1.8} />}
            className="!inline-flex !items-center !text-[#5f6f82] hover:!text-[#49A8C9]"
            data-testid={`fetch-health-row-${record.id}`}
            onClick={() => setHealthSource(record)}
          />
        </Tooltip>
      ),
    },
  ]

  return (
    <div className="flex flex-col gap-5" data-testid="fetch-health-tab">
      <SettingsSection
        title="抓取健康总览"
        description="按失败、冷却、告警和正常状态聚合所有信源，每 30 秒自动刷新。"
        actions={
          <Button
            icon={<SyncOutlined spin={isFetching} />}
            onClick={() => refetch()}
            size="small"
          >
            刷新
          </Button>
        }
      >
        <div className="flex flex-1 flex-wrap gap-2.5">
          <SummaryCard label="信源总数" value={sources.length} color="#2c3a50" />
          <SummaryCard label="失败" value={counts.error} color={HEALTH_SEVERITY_META.error.color} />
          <SummaryCard label="冷却中" value={counts.cooling} color={HEALTH_SEVERITY_META.cooling.color} />
          <SummaryCard label="告警" value={counts.warning} color={HEALTH_SEVERITY_META.warning.color} />
          <SummaryCard label="正常" value={counts.ok} color={HEALTH_SEVERITY_META.ok.color} />
        </div>
      </SettingsSection>

      {isError ? (
        <Alert
          type="error"
          showIcon
          message="抓取健康数据加载失败"
          action={
            <Button size="small" onClick={() => refetch()}>
              重试
            </Button>
          }
        />
      ) : null}

      <SettingsSection
        title="抓取诊断包"
        description="导出抓取健康、失败摘要和最近日志尾部，便于排查问题；不会包含数据库、Cookie、runtime-secrets.json 或 API Key。"
        actions={
          <Button
            type="primary"
            size="small"
            icon={<FileDown size={14} strokeWidth={1.6} />}
            onClick={() => supportBundleMutation.mutate()}
            loading={supportBundleMutation.isPending}
          >
            导出诊断包
          </Button>
        }
      >
        <div className="grid gap-3 text-[13px] text-[#586476] md:grid-cols-3">
          <div>
            <span className="text-[#7a8799]">格式</span>
            <span className="ml-2 text-[#293859]">ZIP</span>
          </div>
          <div>
            <span className="text-[#7a8799]">日志</span>
            <span className="ml-2 text-[#293859]">最近尾部</span>
          </div>
          <div>
            <span className="text-[#7a8799]">隐私</span>
            <span className="ml-2 text-[#293859]">已脱敏</span>
          </div>
        </div>
      </SettingsSection>

      <SettingsSection
        title="付费源 Matrix"
        description="按站点跟踪发现方式、正文路径、验收 URL、最近成功、7 日成功率、失败码与恢复动作。"
        actions={
          <Button size="small" onClick={() => refetchPaidMatrix()}>
            刷新
          </Button>
        }
        contentClassName="pt-0"
      >
        <div className="min-w-0 overflow-x-auto">
          <Table
            rowKey="source_id"
            loading={paidMatrixLoading}
            dataSource={paidMatrix?.items ?? []}
            size="middle"
            scroll={{ x: 1280 }}
            pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (t) => `共 ${t} 个付费源` }}
            locale={{ emptyText: <Empty description="暂无需要登录或已标记为付费的信源" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
            columns={[
              {
                title: '站点',
                key: 'source_name',
                width: 180,
                render: (_, record) => (
                  <div className="min-w-0">
                    <div className="truncate font-medium text-[#293859]">{record.source_name}</div>
                    <div className="truncate text-[12px] text-[#8a96a5]">{record.host}</div>
                  </div>
                ),
              },
              { title: '发现方式', dataIndex: 'discovery', key: 'discovery', width: 120 },
              { title: '正文路径', dataIndex: 'body_path', key: 'body_path', width: 160 },
              {
                title: '验收 URL',
                dataIndex: 'validation_url',
                key: 'validation_url',
                width: 240,
                render: (url: string) => <Typography.Text copyable ellipsis className="!max-w-[220px] !text-[12px]">{url}</Typography.Text>,
              },
              {
                title: '最近成功',
                dataIndex: 'last_success_at',
                key: 'last_success_at',
                width: 150,
                render: (time: string | null) => (time ? formatLocalDateTime(time, 'zh-CN') : '—'),
              },
              {
                title: '7 日成功率',
                dataIndex: 'success_rate_7d',
                key: 'success_rate_7d',
                width: 110,
                align: 'right' as const,
                render: (rate: number | null) => formatRate(rate),
              },
              {
                title: '失败码',
                dataIndex: 'failure_code',
                key: 'failure_code',
                width: 130,
                render: (code: string | null) => (code ? <Tag color="red">{failureCodeLabel(code)}</Tag> : <span className="text-[#8a96a5]">—</span>),
              },
              {
                title: '会话',
                key: 'session',
                width: 130,
                render: (_, record) => record.session_status ? <Tag>{record.session_status}</Tag> : <span className="text-[#8a96a5]">—</span>,
              },
              { title: '恢复动作', dataIndex: 'recovery_action', key: 'recovery_action', width: 220 },
            ]}
          />
        </div>
      </SettingsSection>

      <SettingsSection
        title="信源明细"
        description="失败码、冷却、7 天画像与 RSS 健康由后端抓取链路实时记录。"
        contentClassName="pt-0"
      >
        <div className="min-w-0 overflow-x-auto">
          <Table
            rowKey="id"
            columns={columns}
            dataSource={sorted}
            loading={isLoading}
            size="middle"
            scroll={{ x: 1320 }}
            pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (t) => `共 ${t} 个信源` }}
            locale={{
              emptyText: <Empty description="暂无信源" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
            }}
            style={{ backgroundColor: '#fff' }}
          />
        </div>
      </SettingsSection>

      <FetchHealthDrawer
        source={healthSource}
        open={!!healthSource}
        onClose={() => setHealthSource(null)}
        onFetch={(id) => sourcesApi.triggerFetch(id)}
        onProbe={(id) => sourcesApi.probeSource(id)}
      />
    </div>
  )
}

export default FetchHealthTab
