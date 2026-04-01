import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { DatePicker, Spin, Empty } from 'antd'
import { ClockCircleOutlined, FileTextOutlined, RightOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { digestApi } from '../../services/digest'
import type { HourlyDigestSummary, HourlyDigestDetail } from '../../services/digest'
import { formatLocalDateTime } from '../../utils/datetime'

const formatDigestTitle = (dateObj: dayjs.Dayjs, hour: number): string => {
  return `${dateObj.month() + 1} 月 ${dateObj.date()} 日 ${hour} 时简报`
}

const renderInlineMarkdown = (text: string): React.ReactNode[] => {
  const nodes: React.ReactNode[] = []
  const linkRegex = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g
  let lastIndex = 0
  let match: RegExpExecArray | null = null
  let key = 0

  const pushBoldSegments = (segment: string) => {
    const parts = segment.split(/\*\*(.*?)\*\*/)
    parts.forEach((part, idx) => {
      if (!part) return
      if (idx % 2 === 1) {
        nodes.push(<strong key={`b-${key++}`}>{part}</strong>)
      } else {
        nodes.push(<span key={`t-${key++}`}>{part}</span>)
      }
    })
  }

  while ((match = linkRegex.exec(text)) !== null) {
    const [full, label, url] = match
    if (match.index > lastIndex) {
      pushBoldSegments(text.slice(lastIndex, match.index))
    }
    nodes.push(
      <a key={`a-${key++}`} href={url} target="_blank" rel="noopener noreferrer">
        {label}
      </a>
    )
    lastIndex = match.index + full.length
  }

  if (lastIndex < text.length) {
    pushBoldSegments(text.slice(lastIndex))
  }

  return nodes
}

const DigestView: React.FC = () => {
  const [selectedDate, setSelectedDate] = useState(dayjs())
  const [selectedHour, setSelectedHour] = useState<number | null>(null)

  // 获取当天每小时的简报列表
  const { data: hourlyDigests, isLoading: listLoading } = useQuery<HourlyDigestSummary[]>({
    queryKey: ['hourly-digests', selectedDate.format('YYYY-MM-DD')],
    queryFn: () => digestApi.getHourlyDigests(selectedDate.format('YYYY-MM-DD')),
  })

  // 获取某小时的详细简报
  const { data: digestDetail, isLoading: detailLoading } = useQuery<HourlyDigestDetail | null>({
    queryKey: ['hourly-digest-detail', selectedDate.format('YYYY-MM-DD'), selectedHour],
    queryFn: () => {
      if (selectedHour === null) return Promise.resolve(null)
      return digestApi.getHourlyDigestDetail(selectedHour, selectedDate.format('YYYY-MM-DD'))
    },
    enabled: selectedHour !== null,
  })

  return (
    <div style={{ backgroundColor: '#fff', minHeight: '100vh' }} data-testid="digest-page">
      {/* 页面头部 - 单行精简设计 */}
      <div style={{
        backgroundColor: '#f5f5f5',
        borderBottom: '1px solid #eee',
      }}>
        <div style={{
          maxWidth: 1200,
          margin: '0 auto',
          padding: '16px 24px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
            <h1
              data-testid="digest-title"
              style={{
              fontSize: 20,
              fontWeight: 500,
              color: '#333',
              margin: 0,
            }}
            >
              私人简报
            </h1>
            {selectedHour !== null ? (
              <>
                <span style={{ color: '#ccc' }}>/</span>
                <span style={{ fontSize: 15, color: '#666' }}>
                  {digestDetail?.title || formatDigestTitle(selectedDate, selectedHour)}
                </span>
              </>
            ) : (
              <>
                <span style={{ color: '#ccc' }}>|</span>
                <span style={{ fontSize: 13, color: '#999' }}>每小时自动生成的资讯摘要</span>
              </>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 13, color: '#666' }}>
              共 <strong style={{ color: '#6b7c3f' }}>{hourlyDigests?.length || 0}</strong> 份
            </span>
            <DatePicker
              value={selectedDate}
              onChange={(date) => {
                if (date) {
                  setSelectedDate(date)
                  setSelectedHour(null)
                }
              }}
              allowClear={false}
              size="small"
              style={{ width: 120 }}
            />
          </div>
        </div>
      </div>

      {/* 内容区域 */}
      <div style={{
        maxWidth: 1200,
        margin: '0 auto',
        padding: '24px',
      }}>
        {selectedHour === null ? (
          // 简报列表
          listLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
              <Spin size="large" />
            </div>
          ) : hourlyDigests && hourlyDigests.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {hourlyDigests.map((digest) => (
                <div
                  key={digest.hour}
                  onClick={() => setSelectedHour(digest.hour)}
                  data-testid={`digest-hour-card-${digest.hour}`}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '16px 20px',
                    backgroundColor: '#fafafa',
                    borderRadius: 8,
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    border: '1px solid #eee',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = '#f0f5e8'
                    e.currentTarget.style.borderColor = '#6b7c3f'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = '#fafafa'
                    e.currentTarget.style.borderColor = '#eee'
                  }}
                >
                  {/* 时间 */}
                  <div style={{ 
                    display: 'flex', 
                    alignItems: 'center', 
                    gap: 8,
                    minWidth: 220,
                  }}>
                    <ClockCircleOutlined style={{ color: '#6b7c3f', fontSize: 16 }} />
                    <span style={{ 
                      fontSize: 15, 
                      fontWeight: 500, 
                      color: '#333',
                    }}>
                      {digest.title || formatDigestTitle(selectedDate, digest.hour)}
                    </span>
                  </div>

                  {/* 内容统计 */}
                  <div style={{ 
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                    marginLeft: 24,
                  }}>
                    <span style={{ fontSize: 14, color: '#666' }}>
                      <FileTextOutlined style={{ marginRight: 6 }} />
                      {digest.content_count} 条内容
                    </span>
                    <div style={{ 
                      display: 'flex', 
                      gap: 12, 
                      fontSize: 12, 
                      color: '#999',
                    }}>
                      {digest.sources.websites > 0 && (
                        <span>网站 {digest.sources.websites}</span>
                      )}
                      {digest.sources.x > 0 && (
                        <span>X {digest.sources.x}</span>
                      )}
                      {digest.sources.youtube > 0 && (
                        <span>YouTube {digest.sources.youtube}</span>
                      )}
                    </div>
                  </div>

                  {/* 箭头 */}
                  <RightOutlined style={{ color: '#999', fontSize: 12 }} />
                </div>
              ))}
            </div>
          ) : (
            <Empty
              description={
                <span style={{ color: '#999' }}>
                  {selectedDate.format('YYYY年MM月DD日')} 暂无简报
                </span>
              }
              style={{ padding: 64 }}
            />
          )
        ) : (
          // 简报详情
          detailLoading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}>
              <Spin size="large" tip="AI 正在生成简报..." />
            </div>
          ) : digestDetail ? (
            <div>
              <div data-testid="digest-detail">
              {/* 返回按钮 */}
              <button
                onClick={() => setSelectedHour(null)}
                data-testid="digest-back-btn"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '8px 0',
                  marginBottom: 24,
                  backgroundColor: 'transparent',
                  border: 'none',
                  color: '#6b7c3f',
                  fontSize: 14,
                  cursor: 'pointer',
                }}
              >
                ← 返回简报列表
              </button>

              {/* 简报元信息 */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 16,
                marginBottom: 24,
                padding: '12px 16px',
                backgroundColor: '#f9f9f9',
                borderRadius: 6,
                fontSize: 13,
                color: '#666',
              }}>
                <span>
                  <ClockCircleOutlined style={{ marginRight: 6 }} />
                  生成时间：{digestDetail.generated_at ? formatLocalDateTime(digestDetail.generated_at, 'zh-CN', { hour: '2-digit', minute: '2-digit' }) : '--'}
                </span>
                <span>
                  <FileTextOutlined style={{ marginRight: 6 }} />
                  基于 {digestDetail.content_count} 条内容
                </span>
                <span>
                  来源：{digestDetail.sources?.slice(0, 3).join('、')}
                  {digestDetail.sources && digestDetail.sources.length > 3 && ' 等'}
                </span>
              </div>

              {/* 简报内容 - Markdown 渲染 */}
              <div style={{
                fontSize: 15,
                lineHeight: 1.8,
                color: '#333',
              }}>
                {digestDetail.summary?.split('\n').map((line, idx) => {
                  // 简单的 Markdown 渲染
                  if (line.startsWith('## ')) {
                    const headingText = line.replace('## ', '').trim()
                    if (headingText === (digestDetail.title || '').trim()) {
                      return null
                    }
                    return (
                      <h2 key={idx} style={{ 
                        fontSize: 22, 
                        fontWeight: 500, 
                        margin: '24px 0 16px',
                        color: '#333',
                        borderBottom: '2px solid #6b7c3f',
                        paddingBottom: 8,
                      }}>
                        {headingText}
                      </h2>
                    )
                  }
                  if (line.startsWith('### ')) {
                    return (
                      <h3 key={idx} style={{ 
                        fontSize: 17, 
                        fontWeight: 600, 
                        margin: '20px 0 12px',
                        color: '#6b7c3f',
                      }}>
                        {line.replace('### ', '')}
                      </h3>
                    )
                  }
                  if (/^\*\*(.+)\*\*$/.test(line.trim())) {
                    return (
                      <div
                        key={idx}
                        style={{
                          margin: '18px 0 6px',
                          fontSize: 18,
                          fontWeight: 600,
                          color: '#2f3426',
                          lineHeight: 1.5,
                        }}
                      >
                        {renderInlineMarkdown(line.trim())}
                      </div>
                    )
                  }
                  if (line.startsWith('- ')) {
                    const content = line.replace('- ', '')
                    return (
                      <div key={idx} style={{ 
                        margin: '8px 0', 
                        paddingLeft: 16,
                        display: 'flex',
                        gap: 8,
                      }}>
                        <span style={{ color: '#6b7c3f' }}>•</span>
                        <span>
                          {renderInlineMarkdown(content)}
                        </span>
                      </div>
                    )
                  }
                  if (line.startsWith('---')) {
                    return <hr key={idx} style={{ margin: '24px 0', border: 'none', borderTop: '1px solid #eee' }} />
                  }
                  if (line.startsWith('*') && line.endsWith('*')) {
                    return (
                      <p key={idx} style={{ 
                        margin: '16px 0', 
                        fontSize: 13, 
                        color: '#999',
                        fontStyle: 'italic',
                      }}>
                        {line.replace(/^\*|\*$/g, '')}
                      </p>
                    )
                  }
                  if (line.trim() === '') {
                    return <div key={idx} style={{ height: 8 }} />
                  }
                  return <p key={idx} style={{ margin: '8px 0' }}>{renderInlineMarkdown(line)}</p>
                })}
              </div>
              </div>
            </div>
          ) : (
            <Empty description="无法加载简报内容" />
          )
        )}
      </div>
    </div>
  )
}

export default DigestView
