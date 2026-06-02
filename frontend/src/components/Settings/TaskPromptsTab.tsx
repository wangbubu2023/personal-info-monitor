import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, Input, message } from 'antd'
import { HOURLY_DIGEST_DEFAULT_PROMPT } from '../../config/taskPromptDefaults'
import { configsApi } from '../../services/configs'
import type { SystemSettings } from '../../types'
import PanelLoading from '../common/PanelLoading'
import SettingsSection from './SettingsSection'

const { TextArea } = Input

const READONLY_BOX_CLASS =
  'min-h-[280px] w-full max-w-[720px] rounded-lg border border-[#e8ecf2] bg-[#f4f6fa] px-3 py-3 font-mono text-[13px] leading-relaxed text-[#5c6b80] whitespace-pre-wrap'

const TaskPromptsTab: React.FC = () => {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draftPrompt, setDraftPrompt] = useState('')

  const { data: settings, isLoading } = useQuery({
    queryKey: ['system-settings'],
    queryFn: configsApi.getSettings,
  })

  const storedPrompt = typeof settings?.hourly_digest?.prompt === 'string' ? settings.hourly_digest.prompt : ''
  const pe = settings?.hourly_digest?.prompt_effective
  const effectivePrompt = pe && pe.trim() ? pe : HOURLY_DIGEST_DEFAULT_PROMPT

  const updateMutation = useMutation({
    mutationFn: configsApi.updateSettings,
    onSuccess: (data: SystemSettings) => {
      queryClient.setQueryData(['system-settings'], data)
      setEditing(false)
      message.success('已保存，下一次简报时生效')
    },
    onError: () => message.error('保存失败，请确认后端已启动且 API 可访问'),
  })

  const startEdit = () => {
    // Pre-fill with whatever is currently in effect (saved custom → legacy
    // two-field → built-in default). Users expect to edit from the live text,
    // not from an empty box — an empty box led several users to believe the
    // built-in was "gone" and accidentally save a blank prompt.
    setDraftPrompt(storedPrompt.trim() ? storedPrompt : effectivePrompt)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setDraftPrompt('')
  }

  const save = () => {
    updateMutation.mutate({
      hourly_digest: {
        prompt: draftPrompt.trim(),
      },
    })
  }

  const readOnlyBody = storedPrompt.trim() ? storedPrompt : effectivePrompt
  const usingBuiltin = !storedPrompt.trim()

  if (isLoading) {
    return <PanelLoading message="正在读取任务提示…" />
  }

  return (
    <SettingsSection
      title="每小时简报"
      description="配置选稿与综述任务使用的提示词。系统会从每个简报周期内新增入库内容中取分数排名前 20 的篇目作为候选。"
      className="max-w-[800px]"
    >
      <div className="mb-2 text-sm font-medium text-[#293859]">任务提示词（选稿 + 综述）</div>

      {!editing ? (
        <>
          <div className={READONLY_BOX_CLASS}>{readOnlyBody}</div>
          <p className="mt-2 text-[13px] leading-relaxed text-[#7a8799]">
            {usingBuiltin
              ? '当前生效：系统内置文案（未保存自定义）。点击「编辑」可在此基础上修改并保存。'
              : '当前生效：已保存的自定义文案，下一次简报将使用它。清空并保存可恢复为内置。'}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button type="primary" onClick={startEdit}>
              编辑
            </Button>
          </div>
        </>
      ) : (
        <>
          <TextArea
            rows={14}
            value={draftPrompt}
            onChange={(e) => setDraftPrompt(e.target.value)}
            className="font-mono text-[13px] leading-relaxed text-[#293859]"
            placeholder="输入任务提示词；可留空，保存后表示使用系统内置说明"
          />
          <p className="mt-2 text-[13px] text-[#7a8799]">
            留空并保存：不写入自定义文案，简报仍照常生成，提示词为系统内置。
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button type="primary" onClick={save} loading={updateMutation.isPending}>
              保存
            </Button>
            <Button onClick={cancelEdit} disabled={updateMutation.isPending}>
              取消
            </Button>
          </div>
        </>
      )}
    </SettingsSection>
  )
}

export default TaskPromptsTab
