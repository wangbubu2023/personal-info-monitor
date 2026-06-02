import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Switch, message } from 'antd'
import { configsApi } from '../../services/configs'
import SettingsSection from './SettingsSection'

const ScoreLabSettingsTab: React.FC = () => {
  const queryClient = useQueryClient()
  const { data: settings, isLoading } = useQuery({
    queryKey: ['system-settings'],
    queryFn: configsApi.getSettings,
  })

  const mutation = useMutation({
    mutationFn: configsApi.updateSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['system-settings'] })
      message.success('评分实验室设置已保存')
    },
    onError: () => message.error('保存失败'),
  })

  const enabled = Boolean(settings?.score_lab_enabled)

  return (
    <SettingsSection
      title="评分实验室"
      description={
        <>
          开发模式下可用的打分调试入口：查看得分拆解、对比库内快照、提交偏高/偏低反馈。
          生产构建（<code className="rounded bg-[#eef2f8] px-1">./pim start --prod</code>）不会包含此功能。
        </>
      }
      className="max-w-2xl"
    >
      <div className="flex items-start justify-between gap-4 rounded-2xl border border-[rgba(88,100,118,0.12)] bg-white px-5 py-4">
        <div>
          <p className="font-medium text-[#293859]">显示侧栏入口</p>
          <p className="mt-1 text-sm text-[#586476]">
            关闭后隐藏「评分」导航，但 API 仍可用于 CLI 调试。
          </p>
        </div>
        <Switch
          checked={enabled}
          loading={isLoading || mutation.isPending}
          onChange={(checked) => mutation.mutate({ score_lab_enabled: checked })}
        />
      </div>
    </SettingsSection>
  )
}

export default ScoreLabSettingsTab
