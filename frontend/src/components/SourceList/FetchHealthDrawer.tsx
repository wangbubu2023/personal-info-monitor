import React from 'react'
import {
  Drawer,
  Descriptions,
  Tag,
  Statistic,
  Row,
  Col,
  Progress,
  Collapse,
  Empty,
  Spin,
  Alert,
  Button,
  Space,
  Tooltip,
} from 'antd'
import { SyncOutlined, RadarChartOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { sourcesApi } from '../../services/sources'
import { sourceKeys } from '../../services/queryKeys'
import { formatLocalDateTime } from '../../utils/datetime'
import type { Source } from '../../types'
import {
  failureCodeLabel,
  formatCooldownRemaining,
  formatLatency,
  formatRate,
  rssHealthColor,
  rssHealthLabel,
  HEALTH_SEVERITY_META,
  deriveHealthSeverity,
} from '../../utils/fetchHealth'

interface FetchHealthDrawerProps {
  source: Source | null
  open: boolean
  onClose: () => void
  onFetch?: (id: string) => void
  onProbe?: (id: string) => void
  fetchLoading?: boolean
  probeLoading?: boolean
}

const labelStyle = { width: 132, color: '#5f6f82' }

const FetchHealthDrawer: React.FC<FetchHealthDrawerProps> = ({
  source,
  open,
  onClose,
  onFetch,
  onProbe,
  fetchLoading,
  probeLoading,
}) => {
  // Re-fetch the single source while the drawer is open so the metadata
  // (profile / failure / rss_health) reflects the latest fetch cycle.
  const { data: detail, isLoading } = useQuery({
    queryKey: [...sourceKeys.all, 'detail', source?.id],
    queryFn: () => sourcesApi.get(source!.id),
    enabled: open && !!source?.id,
    initialData: source ?? undefined,
  })

  const s = detail ?? source
  const summary = s?.fetch_profile_summary
  const failure = s?.metadata?.fetch_failure
  const rssHealth = s?.metadata?.rss_health
  const discovery = s?.metadata?.discovery_diagnostics
  const webClean = s?.metadata?.web_clean_profile
  const severity = s ? deriveHealthSeverity(s) : 'unknown'
  const sevMeta = HEALTH_SEVERITY_META[severity]
  const cooldownRemaining = formatCooldownRemaining(s?.cooldown_until)

  const fulltextRate = summary?.fulltext_success_rate_7d ?? null
  const successRate = summary?.success_rate_7d ?? null

  return (
    <Drawer
      title={
        <Space size={8} align="center">
          <span>抓取健康诊断</span>
          {s ? <Tag color={sevMeta.color === '#52c41a' ? 'green' : undefined} style={{ color: sevMeta.color, borderColor: sevMeta.color }}>{sevMeta.label}</Tag> : null}
        </Space>
      }
      width={520}
      open={open}
      onClose={onClose}
      data-testid="fetch-health-drawer"
      extra={
        s ? (
          <Space>
            <Tooltip title="探测可抓取性">
              <Button
                size="small"
                icon={<RadarChartOutlined />}
                loading={probeLoading}
                onClick={() => onProbe?.(s.id)}
              />
            </Tooltip>
            <Button
              size="small"
              type="primary"
              icon={<SyncOutlined />}
              loading={fetchLoading}
              onClick={() => onFetch?.(s.id)}
            >
              立即抓取
            </Button>
          </Space>
        ) : null
      }
    >
      {!s ? (
        <Empty description="未选择监测源" />
      ) : isLoading && !detail ? (
        <div className="flex justify-center py-12">
          <Spin />
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {cooldownRemaining ? (
            <Alert
              type="warning"
              showIcon
              message={`冷却中：约 ${cooldownRemaining}后恢复自动抓取`}
              description={
                failure?.last_code
                  ? `触发原因：${failureCodeLabel(failure.last_code)}。手动「立即抓取」可绕过冷却。`
                  : '手动「立即抓取」可绕过冷却。'
              }
            />
          ) : null}

          {/* 基本状态 */}
          <Descriptions
            size="small"
            column={1}
            bordered
            labelStyle={labelStyle}
            title="基本状态"
          >
            <Descriptions.Item label="名称">{s.name}</Descriptions.Item>
            <Descriptions.Item label="抓取状态">
              <span style={{ color: sevMeta.color }}>{sevMeta.label}</span>
              {s.fetch_status_message ? (
                <span className="ml-2 text-[12px] text-[#8a96a5]">{s.fetch_status_message}</span>
              ) : null}
            </Descriptions.Item>
            <Descriptions.Item label="最近失败">
              {failure?.last_code ? (
                <Tag color="red">{failureCodeLabel(failure.last_code)}</Tag>
              ) : (
                '—'
              )}
              {failure?.last_status ? (
                <span className="text-[12px] text-[#8a96a5]">HTTP {failure.last_status}</span>
              ) : null}
            </Descriptions.Item>
            <Descriptions.Item label="连续失败次数">
              {failure?.consecutive_failures ?? 0}
            </Descriptions.Item>
            <Descriptions.Item label="最后抓取">
              {s.last_fetched_at ? formatLocalDateTime(s.last_fetched_at, 'zh-CN') : '—'}
            </Descriptions.Item>
            {s.last_error ? (
              <Descriptions.Item label="错误详情">
                <span className="break-all text-[12px] text-[#b04a4a]">{s.last_error}</span>
              </Descriptions.Item>
            ) : null}
          </Descriptions>

          {/* 7 天画像 */}
          <div>
            <div className="mb-2 text-[13px] font-medium text-[#2c3a50]">近 7 天抓取画像</div>
            {summary && summary.attempts_7d > 0 ? (
              <>
                <Row gutter={12}>
                  <Col span={8}>
                    <Statistic title="抓取次数" value={summary.attempts_7d} />
                  </Col>
                  <Col span={8}>
                    <Statistic title="入库条数" value={summary.saved_count_7d} />
                  </Col>
                  <Col span={8}>
                    <Statistic title="平均耗时" value={formatLatency(summary.avg_latency_ms_7d)} />
                  </Col>
                </Row>
                <Row gutter={12} className="mt-3" align="middle">
                  <Col span={12}>
                    <div className="text-[12px] text-[#5f6f82]">成功率</div>
                    <Progress
                      percent={successRate !== null ? Math.round(successRate * 100) : 0}
                      size="small"
                      status={successRate !== null && successRate < 0.5 ? 'exception' : 'normal'}
                      format={() => formatRate(successRate)}
                    />
                  </Col>
                  <Col span={12}>
                    <div className="text-[12px] text-[#5f6f82]">正文完整率</div>
                    <Progress
                      percent={fulltextRate !== null ? Math.round(fulltextRate * 100) : 0}
                      size="small"
                      strokeColor="#49A8C9"
                      format={() => formatRate(fulltextRate)}
                    />
                  </Col>
                </Row>
                <div className="mt-2 text-[12px] text-[#8a96a5]">
                  成功 {summary.success_count_7d} · 失败 {summary.failure_count_7d} · 空跑{' '}
                  {summary.empty_count_7d}
                  {summary.preferred_strategy ? ` · 偏好策略 ${summary.preferred_strategy}` : ''}
                </div>
              </>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="近 7 天暂无抓取记录" />
            )}
          </div>

          {webClean ? (
            <Descriptions
              size="small"
              column={1}
              bordered
              labelStyle={labelStyle}
              title="网页清洗诊断"
            >
              <Descriptions.Item label="运行模式">
                {webClean.shadow ? <Tag color="blue">Shadow</Tag> : <Tag color="green">已启用</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="抽取方法">
                {webClean.extraction_method ?? '—'}
              </Descriptions.Item>
              <Descriptions.Item label="模板 ID">
                {webClean.template_id ?? '通用模板'}
              </Descriptions.Item>
              <Descriptions.Item label="正文质量">
                <Space>
                  <Tag>{webClean.quality_status ?? 'unknown'}</Tag>
                  {webClean.quality_score != null
                    ? `${Math.round(webClean.quality_score * 100)} 分`
                    : '—'}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="正文信号">
                {webClean.text_chars ?? 0} 字符 · {webClean.paragraph_count ?? 0} 段
              </Descriptions.Item>
              <Descriptions.Item label="噪音/链接密度">
                {webClean.boilerplate_ratio != null
                  ? `${Math.round(webClean.boilerplate_ratio * 100)}%`
                  : '—'}
                {' / '}
                {webClean.link_density != null
                  ? `${Math.round(webClean.link_density * 100)}%`
                  : '—'}
              </Descriptions.Item>
            </Descriptions>
          ) : null}

          {/* RSS 健康 / 发现诊断 */}
          {(rssHealth || discovery) && (
            <Collapse
              size="small"
              defaultActiveKey={rssHealth ? ['rss'] : []}
              items={[
                ...(rssHealth
                  ? [
                      {
                        key: 'rss',
                        label: (
                          <Space>
                            <span>RSS 健康</span>
                            <Tag color={rssHealthColor(rssHealth.status)}>
                              {rssHealthLabel(rssHealth.status)}
                            </Tag>
                          </Space>
                        ),
                        children: (
                          <Descriptions size="small" column={1} labelStyle={labelStyle}>
                            <Descriptions.Item label="条目数">
                              {rssHealth.item_count ?? '—'}
                            </Descriptions.Item>
                            <Descriptions.Item label="最近更新">
                              {rssHealth.last_update
                                ? formatLocalDateTime(rssHealth.last_update, 'zh-CN')
                                : '—'}
                            </Descriptions.Item>
                            <Descriptions.Item label="陈旧天数">
                              {rssHealth.stale_days ?? '—'}
                            </Descriptions.Item>
                            {rssHealth.feed_url ? (
                              <Descriptions.Item label="Feed URL">
                                <span className="break-all text-[12px]">{rssHealth.feed_url}</span>
                              </Descriptions.Item>
                            ) : null}
                          </Descriptions>
                        ),
                      },
                    ]
                  : []),
                ...(discovery
                  ? [
                      {
                        key: 'discovery',
                        label: `列表页发现（保留 ${discovery.kept ?? 0}/${discovery.total ?? 0}）`,
                        children: (
                          <div className="text-[12px] text-[#5f6f82]">
                            <div>同域过滤：{discovery.dropped_off_domain ?? 0}</div>
                            <div>命中拒绝规则：{discovery.dropped_deny ?? 0}</div>
                            <div>未命中允许规则：{discovery.dropped_allow_miss ?? 0}</div>
                            <div>标题过短：{discovery.dropped_short_title ?? 0}</div>
                            <div>重复：{discovery.dropped_duplicate ?? 0}</div>
                            <div>过期：{discovery.dropped_stale ?? 0}</div>
                            <div>超出上限截断：{discovery.truncated ?? 0}</div>
                          </div>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          )}
        </div>
      )}
    </Drawer>
  )
}

export default FetchHealthDrawer
