import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Modal, Tag, message } from 'antd'
import { DownloadCloud, FileDown, RefreshCw } from 'lucide-react'
import { systemApi, type UpgradeStatus } from '../../services/system'
import { formatLocalDateTime } from '../../utils/datetime'
import SettingsSection from './SettingsSection'

const iconStroke = 1.6

const statusMeta: Record<UpgradeStatus['status'], { label: string; color: string }> = {
  idle: { label: '未运行', color: 'default' },
  running: { label: '升级中', color: 'processing' },
  succeeded: { label: '已完成', color: 'success' },
  failed: { label: '失败', color: 'error' },
}

const commandText = (status?: UpgradeStatus) =>
  status?.command?.length ? status.command.join(' ') : './pim upgrade'

const MaintenanceTab: React.FC = () => {
  const queryClient = useQueryClient()
  const { data: status, isFetching, refetch } = useQuery({
    queryKey: ['system-upgrade-status'],
    queryFn: systemApi.getUpgradeStatus,
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 3000 : false),
  })
  const { data: updateCheck, isFetching: isCheckingUpdate, refetch: refetchUpdateCheck } = useQuery({
    queryKey: ['system-update-check'],
    queryFn: systemApi.checkForUpdates,
    staleTime: 1000 * 60 * 30,
  })

  const startMutation = useMutation({
    mutationFn: systemApi.startUpgrade,
    onSuccess: (next) => {
      queryClient.setQueryData(['system-upgrade-status'], next)
      message.success(next.status === 'running' ? '升级已开始' : '升级状态已刷新')
    },
    onError: () => message.error('无法启动升级，请检查后端日志'),
  })

  const supportBundleMutation = useMutation({
    mutationFn: systemApi.downloadSupportBundle,
    onSuccess: () => message.success('诊断包已导出'),
    onError: () => message.error('无法导出诊断包，请检查后端日志'),
  })

  const running = status?.status === 'running' || startMutation.isPending
  const meta = statusMeta[status?.status || 'idle']

  const confirmUpgrade = () => {
    Modal.confirm({
      title: '开始升级 PIM',
      content: '升级会执行 ./pim upgrade，期间后端可能短暂重启，页面可能需要刷新后继续查看状态。',
      okText: '开始升级',
      cancelText: '取消',
      okButtonProps: { loading: startMutation.isPending },
      onOk: () => startMutation.mutateAsync(),
    })
  }

  return (
    <div className="flex flex-col gap-5" data-testid="maintenance-tab">
      <SettingsSection
        title="诊断包"
        description="导出当前环境、健康检查、抓取失败摘要、浏览器会话状态与最近日志尾部；不会包含数据库、Cookie、runtime-secrets.json 或 API Key。"
        actions={
          <Button
            type="primary"
            size="small"
            icon={<FileDown size={14} strokeWidth={iconStroke} />}
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
        title="版本升级"
        description="从当前服务器上的 Git checkout 拉取更新、刷新依赖与前端产物，并按 ./pim 的策略重启服务。"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              size="small"
              icon={<RefreshCw size={14} strokeWidth={iconStroke} />}
              onClick={() => {
                refetch()
                refetchUpdateCheck()
              }}
              loading={isFetching || isCheckingUpdate}
            >
              刷新
            </Button>
            <Button
              type="primary"
              size="small"
              icon={<DownloadCloud size={14} strokeWidth={iconStroke} />}
              onClick={confirmUpgrade}
              loading={running}
              disabled={running}
            >
              升级
            </Button>
          </div>
        }
      >
        <div className="flex flex-col gap-4">
          {updateCheck?.status === 'ok' ? (
            <Alert
              type={updateCheck.update_available ? 'info' : 'success'}
              showIcon
              message={
                updateCheck.update_available
                  ? `发现新版本 v${updateCheck.latest_version || updateCheck.latest_tag}`
                  : `当前已是最新版本 v${updateCheck.current_version}`
              }
              description={
                updateCheck.update_available ? (
                  <div className="space-y-2">
                    <div>
                      当前版本 v{updateCheck.current_version}，最新版本 v{updateCheck.latest_version || updateCheck.latest_tag}。
                    </div>
                    {updateCheck.release_notes ? <div className="whitespace-pre-line">{updateCheck.release_notes}</div> : null}
                    {updateCheck.release_url ? (
                      <a href={updateCheck.release_url} target="_blank" rel="noreferrer" className="text-[#2f8fb0]">
                        查看 GitHub Release
                      </a>
                    ) : null}
                  </div>
                ) : undefined
              }
            />
          ) : updateCheck?.status === 'disabled' ? (
            <Alert type="warning" showIcon message="未启用版本检测" description={updateCheck.message} />
          ) : null}

          <div className="grid gap-3 text-[13px] text-[#586476] md:grid-cols-2">
            <div className="flex items-center gap-2">
              <span className="text-[#7a8799]">状态</span>
              <Tag color={meta.color}>{meta.label}</Tag>
            </div>
            <div>
              <span className="text-[#7a8799]">命令</span>
              <code className="ml-2 rounded bg-[#eef2f8] px-1.5 py-0.5 text-[#293859]">
                {commandText(status)}
              </code>
            </div>
            <div>
              <span className="text-[#7a8799]">开始</span>
              <span className="ml-2 text-[#293859]">
                {status?.started_at ? formatLocalDateTime(status.started_at, 'zh-CN') : '—'}
              </span>
            </div>
            <div>
              <span className="text-[#7a8799]">结束</span>
              <span className="ml-2 text-[#293859]">
                {status?.finished_at ? formatLocalDateTime(status.finished_at, 'zh-CN') : '—'}
              </span>
            </div>
          </div>

          {status?.message ? (
            <Alert
              type={status.status === 'failed' ? 'error' : status.status === 'succeeded' ? 'success' : 'info'}
              showIcon
              message={status.message}
            />
          ) : null}

          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <span className="text-[13px] font-medium text-[#293859]">升级日志</span>
              <span className="truncate text-[12px] text-[#8a96a5]">{status?.log_path || ''}</span>
            </div>
            <pre className="max-h-[360px] min-h-[160px] overflow-auto rounded-lg border border-[#e4eaf1] bg-[#111827] px-3 py-3 text-[12px] leading-relaxed text-[#d1d5db]">
              {status?.log_tail?.trim() || '暂无升级日志'}
            </pre>
          </div>
        </div>
      </SettingsSection>
    </div>
  )
}

export default MaintenanceTab
