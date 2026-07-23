import React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Form,
  Button,
  Select,
  AutoComplete,
  Switch,
  message,
  InputNumber,
  Slider,
  Tag,
} from 'antd'
import { configsApi } from '../../services/configs'
import type { AIModelTabFormValues } from '../../types'
import ModelProvidersTab from './ModelProvidersTab'
import SectionNote from '../ui/SectionNote'
import PanelLoading from '../common/PanelLoading'
import OllamaCtxSlider, { snapOllamaNumCtx } from './OllamaCtxSlider'
import SettingsSection from './SettingsSection'
import TaskPromptsTab from './TaskPromptsTab'

const { Option } = Select

const AI_POLICY_REASON_LABELS: Record<string, string> = {
  ready: '模型就绪',
  disabled: '已关闭',
  waiting_model_config: '等待配置模型',
  model_unavailable: '模型不可访问',
  budget_exhausted: '预算已耗尽',
  credentials_invalid: '凭据无效',
  provider_unreachable: 'Provider 不可达',
  rate_limited: 'Provider 限流',
  circuit_open: '熔断器已打开',
  paused: '已被全局暂停',
  hard_disabled: '已被部署策略禁用',
}

const policyReasonText = (reason?: string) => AI_POLICY_REASON_LABELS[reason || ''] || reason || '未知'

const FormGroupHeading: React.FC<{ children: React.ReactNode; first?: boolean }> = ({
  children,
  first = false,
}) => (
  <h4
    className={`${first ? 'mt-0' : 'mt-8 border-t border-[rgba(88,100,118,0.1)] pt-5'} mb-4 text-[14px] font-semibold tracking-tight text-[#2c3a50]`}
  >
    {children}
  </h4>
)

const AIModelTab: React.FC = () => {
  const [form] = Form.useForm()
  const queryClient = useQueryClient()

  const { data: settings, isLoading } = useQuery({
    queryKey: ['system-settings'],
    queryFn: configsApi.getSettings,
  })

  const { data: modelsData } = useQuery({
    queryKey: ['available-models'],
    queryFn: configsApi.getAvailableModels,
  })

  const { data: migration } = useQuery({
    queryKey: ['ai-policy-migration'],
    queryFn: configsApi.getAiMigration,
  })

  const updateMutation = useMutation({
    mutationFn: configsApi.updateSettings,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['system-settings'] }); message.success('设置已保存') },
    onError: () => message.error('保存失败'),
  })

  const selectedProvider = Form.useWatch('provider', form)
  const currentProvider = modelsData?.providers?.find(p => p.id === selectedProvider)
  const selectedTransProvider = Form.useWatch('trans_provider', form)
  const transProvider = modelsData?.providers?.find(p => p.id === selectedTransProvider)
  const selectedScoreProvider = Form.useWatch('score_provider', form)
  const scoreProvider = modelsData?.providers?.find(p => p.id === selectedScoreProvider)
  const selectedTransFbProvider = Form.useWatch('trans_fallback_provider', form)
  const transFbProvider = modelsData?.providers?.find(p => p.id === selectedTransFbProvider)
  const selectedSumFbProvider = Form.useWatch('sum_fallback_provider', form)
  const sumFbProvider = modelsData?.providers?.find(p => p.id === selectedSumFbProvider)
  const translationFallbackOn = Form.useWatch('translation_fallback_enabled', form)
  const summarizationFallbackOn = Form.useWatch('summarization_fallback_enabled', form)
  const modelOptions = (currentProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const transModelOptions = (transProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const scoreModelOptions = (scoreProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const transFbModelOptions = (transFbProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const sumFbModelOptions = (sumFbProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const buildModelFilter = (inputValue: string, option: { value?: string; label?: string } | undefined, fieldName: 'model' | 'trans_model' | 'score_model' | 'trans_fallback_model' | 'sum_fallback_model') => {
    const normalizedInput = String(inputValue || '').toLowerCase().trim()
    if (!normalizedInput) return true
    const currentValue = String(form.getFieldValue(fieldName) || '').toLowerCase().trim()
    if (currentValue && normalizedInput === currentValue) {
      return true
    }
    return (
      String(option?.value || '').toLowerCase().includes(normalizedInput) ||
      String(option?.label || '').toLowerCase().includes(normalizedInput)
    )
  }
  const renderEffectiveBase = (label: string, base?: string) => (
    <SectionNote style={{ marginBottom: 16 }}>
      {label}（模型接入或厂商默认）：{' '}
      <code className="text-[13px]">{base || '—'}</code>
    </SectionNote>
  )
  const renderPolicyStatus = (
    label: string,
    state?: {
      enabled: boolean
      runtime_configured: boolean
      runtime_ready: boolean
      effective: boolean
      reason: string
    },
  ) => {
    const color = state?.effective ? 'success' : state?.reason === 'disabled' ? 'default' : 'warning'
    const enabledText = state?.enabled ? '已启用' : '已关闭'
    return (
      <div className="flex items-center justify-between rounded-xl border border-[#e5eaf2] bg-[#fbfcff] px-3 py-2 text-[13px]">
        <span className="font-medium text-[#2c3a50]">{label}</span>
        <Tag color={color}>
          {enabledText} · 配置{state?.runtime_configured ? '完成' : '缺失'} ·
          {state?.runtime_ready ? '运行时就绪' : '运行时未就绪'} · {policyReasonText(state?.reason)}
        </Tag>
      </div>
    )
  }

  React.useEffect(() => {
    if (!settings) return
    form.setFieldsValue({
      provider: settings.ai_model.provider,
      model: settings.ai_model.model,
      temperature: settings.ai_model.temperature,
      ollama_num_ctx: snapOllamaNumCtx(settings.ai_model.ollama_num_ctx, 8192),
      ollama_no_think: settings.ai_model.ollama_no_think ?? false,
      trans_provider: settings.translation_model?.provider || 'ollama',
      trans_model: settings.translation_model?.model || 'translategemma:12b',
      trans_ollama_num_ctx: snapOllamaNumCtx(settings.translation_model?.ollama_num_ctx, 2048),
      trans_ollama_no_think: settings.translation_model?.ollama_no_think ?? true,
      score_provider: settings.score_model?.provider || settings.ai_model.provider,
      score_model: settings.score_model?.model || '',
      score_temperature: settings.score_model?.temperature ?? 0.1,
      score_max_tokens: settings.score_model?.max_tokens ?? 150,
      score_ollama_num_ctx: snapOllamaNumCtx(settings.score_model?.ollama_num_ctx, 2048),
      score_ollama_no_think: settings.score_model?.ollama_no_think ?? true,
      translation_fallback_enabled:
        settings.translation_fallback_enabled ?? settings.translation_cloud_fallback_enabled ?? false,
      summarization_fallback_enabled:
        settings.summarization_fallback_enabled ?? settings.summarization_cloud_fallback_enabled ?? false,
      auto_summary_enabled: settings.auto_summary_enabled ?? true,
      auto_listing_translation_enabled: settings.auto_listing_translation_enabled ?? true,
      ai_subjective_scoring_enabled: settings.ai_subjective_scoring_enabled ?? false,
      ai_processing_paused: settings.ai_processing_paused ?? false,
      trans_fallback_provider: settings.translation_fallback?.provider,
      trans_fallback_model: settings.translation_fallback?.model,
      sum_fallback_provider: settings.summarization_fallback?.provider,
      sum_fallback_model: settings.summarization_fallback?.model,
    })
  }, [settings, form])

  /** 备用模型只使用当前「可用模型」列表里已有的提供商；避免后端默认的 openai 出现在未接入 OpenAI 时。 */
  React.useEffect(() => {
    if (!settings || !modelsData?.providers?.length) return
    const providers = modelsData.providers
    const ids = new Set(providers.map((p) => p.id))
    const coerce = (fb?: { provider?: string; model?: string } | null) => {
      const p = fb?.provider
      const m = fb?.model
      if (p && ids.has(p)) {
        const prov = providers.find((x) => x.id === p)!
        const mids = new Set((prov.models || []).map((x) => x.id))
        const model = m && mids.has(m) ? m : (prov.models?.[0]?.id ?? m ?? '')
        return { provider: p, model }
      }
      const first = providers[0]
      return { provider: first.id, model: first.models?.[0]?.id ?? '' }
    }
    const tf = coerce(settings.translation_fallback)
    const sf = coerce(settings.summarization_fallback)
    form.setFieldsValue({
      trans_fallback_provider: tf.provider,
      trans_fallback_model: tf.model,
      sum_fallback_provider: sf.provider,
      sum_fallback_model: sf.model,
    })
  }, [settings, modelsData, form])

  React.useEffect(() => {
    if (!currentProvider) return
    const model = form.getFieldValue('model')
    const ids = new Set((currentProvider.models || []).map((m) => m.id))
    if (!model || !ids.has(model)) {
      const fallback = currentProvider.models?.[0]?.id
      if (fallback) {
        form.setFieldValue('model', fallback)
      }
    }
  }, [currentProvider, form])

  React.useEffect(() => {
    if (!transProvider) return
    const model = form.getFieldValue('trans_model')
    const ids = new Set((transProvider.models || []).map((m) => m.id))
    if (!model || !ids.has(model)) {
      const fallback = transProvider.models?.[0]?.id
      if (fallback) {
        form.setFieldValue('trans_model', fallback)
      }
    }
  }, [transProvider, form])

  React.useEffect(() => {
    if (!transFbProvider) return
    const model = form.getFieldValue('trans_fallback_model')
    const ids = new Set((transFbProvider.models || []).map((m) => m.id))
    if (!model || !ids.has(model)) {
      const fallback = transFbProvider.models?.[0]?.id
      if (fallback) {
        form.setFieldValue('trans_fallback_model', fallback)
      }
    }
  }, [transFbProvider, form])

  React.useEffect(() => {
    if (!sumFbProvider) return
    const model = form.getFieldValue('sum_fallback_model')
    const ids = new Set((sumFbProvider.models || []).map((m) => m.id))
    if (!model || !ids.has(model)) {
      const fallback = sumFbProvider.models?.[0]?.id
      if (fallback) {
        form.setFieldValue('sum_fallback_model', fallback)
      }
    }
  }, [sumFbProvider, form])

  const handleSave = (values: AIModelTabFormValues) => {
    // onFinish 的 values 可能省略未触发的 Switch 字段，JSON 序列化会丢掉 undefined，导致 PATCH 不写布尔键、后端仍为 false
    const translationFallbackEnabled = form.getFieldValue('translation_fallback_enabled')
    const summarizationFallbackEnabled = form.getFieldValue('summarization_fallback_enabled')
    updateMutation.mutate({
      ai_model: {
        provider: values.provider,
        model: values.model,
        temperature: values.temperature,
        max_tokens: settings?.ai_model.max_tokens ?? 1024,
        ...(values.provider === 'ollama'
          ? {
              ollama_num_ctx: values.ollama_num_ctx,
              ollama_no_think: values.ollama_no_think === true,
            }
          : {}),
      },
      translation_model: {
        provider: values.trans_provider,
        model: values.trans_model,
        ...(values.trans_provider === 'ollama'
          ? {
              ollama_num_ctx: values.trans_ollama_num_ctx,
              ollama_no_think: values.trans_ollama_no_think === true,
            }
          : {}),
      },
      score_model: {
        provider: values.score_provider,
        model: values.score_model,
        temperature: values.score_temperature,
        max_tokens: values.score_max_tokens,
        ...(values.score_provider === 'ollama'
          ? {
              ollama_num_ctx: values.score_ollama_num_ctx,
              ollama_no_think: values.score_ollama_no_think === true,
            }
          : {}),
      },
      auto_summary_enabled: values.auto_summary_enabled === true,
      auto_listing_translation_enabled: values.auto_listing_translation_enabled === true,
      ai_subjective_scoring_enabled: values.ai_subjective_scoring_enabled === true,
      ai_processing_paused: values.ai_processing_paused === true,
      translation_fallback_enabled: translationFallbackEnabled === true,
      translation_fallback: {
        provider: values.trans_fallback_provider,
        model: values.trans_fallback_model,
      },
      summarization_fallback_enabled: summarizationFallbackEnabled === true,
      summarization_fallback: {
        provider: values.sum_fallback_provider,
        model: values.sum_fallback_model,
      },
    })
  }

  if (isLoading) {
    return <PanelLoading message="正在读取模型与系统设置…" />
  }

  return (
    <div className="flex flex-col gap-5">
      <SettingsSection
        title="模型接入"
        description={
          <>
            先配置可用的模型供应商。云端接口填写 API Key 和必要的 API Base；Ollama 本地填写服务地址，默认{' '}
            <code className="rounded bg-[#eef2f8] px-1 text-[12px]">http://localhost:11434</code>，无需 Key。
          </>
        }
      >
        <ModelProvidersTab />
      </SettingsSection>

      <SettingsSection
        title="模型选择与生成参数"
        description="已接入的提供商才会出现在这里；此处只选择写作、翻译和评分通道使用的模型与生成参数。"
      >
      {selectedProvider === 'ollama' && currentProvider?.availability_message ? (
        <SectionNote tone="caution" style={{ marginBottom: 16 }}>
          {currentProvider.availability_message}
        </SectionNote>
      ) : null}
      <Form form={form} layout="vertical" onFinish={handleSave} style={{ maxWidth: 600 }}>
        <FormGroupHeading first>写作模型配置</FormGroupHeading>

        <Form.Item name="provider" label="AI 提供商" rules={[{ required: true }]}>
          <Select placeholder="选择 AI 提供商">
            {modelsData?.providers?.map(p => (
              <Option key={p.id} value={p.id}>{p.name}</Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item
          name="model"
          label="模型"
          rules={[{ required: true }]}
          extra={selectedProvider === 'ollama'
            ? 'Ollama 模型列表来自本机已安装模型（实时读取）。'
            : undefined}
        >
          <AutoComplete
            options={modelOptions}
            placeholder="选择或输入模型 ID"
            filterOption={(inputValue, option) => buildModelFilter(inputValue, option, 'model')}
          />
        </Form.Item>

        {selectedProvider ? (
          renderEffectiveBase('当前通道服务地址', currentProvider?.default_api_base)
        ) : null}

        <Form.Item name="temperature" label="Temperature" extra="控制输出的随机性，0 为确定性输出，2 为最大随机">
          <Slider min={0} max={2} step={0.1} marks={{ 0: '0', 0.7: '0.7', 1: '1', 2: '2' }} />
        </Form.Item>

        {selectedProvider === 'ollama' ? (
          <>
            <Form.Item
              name="ollama_num_ctx"
              label="Context 窗口 (num_ctx)"
              extra="写作任务使用的 Ollama 上下文长度，默认 8K。"
            >
              <OllamaCtxSlider />
            </Form.Item>
            <Form.Item
              name="ollama_no_think"
              label="关闭思维链 (/no_think)"
              valuePropName="checked"
              extra="写作任务通常不需要思维链；开启后会在 system prompt 末尾追加 /no_think。"
            >
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
          </>
        ) : null}

        <Form.Item
          name="summarization_fallback_enabled"
          label="启用写作备用（fallback）模型"
          valuePropName="checked"
          extra="关闭后，写作失败将退回截断正文，不再尝试备用模型。"
        >
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        {summarizationFallbackOn ? (
          <>
            <Form.Item name="sum_fallback_provider" label="写作备用 · 提供商" rules={[{ required: true }]}>
              <Select placeholder="选择提供商">
                {modelsData?.providers?.map(p => (
                  <Option key={p.id} value={p.id}>{p.name}</Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item
              name="sum_fallback_model"
              label="写作备用 · 模型"
              rules={[{ required: true }]}
              extra={selectedSumFbProvider === 'ollama'
                ? '列表来自本机已安装模型（与上方列表同源）。'
                : undefined}
            >
              <AutoComplete
                options={sumFbModelOptions}
                placeholder="选择或输入模型 ID"
                filterOption={(inputValue, option) => buildModelFilter(inputValue, option, 'sum_fallback_model')}
              />
            </Form.Item>
            {selectedSumFbProvider ? (
              renderEffectiveBase('写作备用通道地址', sumFbProvider?.default_api_base)
            ) : null}
          </>
        ) : null}

        <FormGroupHeading>翻译模型配置</FormGroupHeading>

        <Form.Item name="trans_provider" label="翻译模型提供商" rules={[{ required: true }]}>
          <Select placeholder="选择提供商">
            {modelsData?.providers?.map(p => (
              <Option key={p.id} value={p.id}>{p.name}</Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item
          name="trans_model"
          label="翻译模型"
          extra={selectedTransProvider === 'ollama'
            ? '翻译模型来自本机 Ollama 已安装模型。'
            : undefined}
        >
          <AutoComplete
            options={transModelOptions}
            placeholder="选择或输入模型 ID"
            filterOption={(inputValue, option) => buildModelFilter(inputValue, option, 'trans_model')}
          />
        </Form.Item>

        {selectedTransProvider ? (
          renderEffectiveBase('当前翻译通道服务地址', transProvider?.default_api_base)
        ) : null}

        {selectedTransProvider === 'ollama' ? (
          <>
            <Form.Item
              name="trans_ollama_num_ctx"
              label="Context 窗口 (num_ctx)"
              extra="翻译任务使用的 Ollama 上下文长度，默认 2K。"
            >
              <OllamaCtxSlider />
            </Form.Item>
            <Form.Item
              name="trans_ollama_no_think"
              label="关闭思维链 (/no_think)"
              valuePropName="checked"
              extra="翻译任务建议开启，避免模型输出冗长思考过程。"
            >
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
          </>
        ) : null}

        <Form.Item
          name="translation_fallback_enabled"
          label="启用翻译备用（fallback）模型"
          valuePropName="checked"
          extra="关闭后，翻译失败即停止，不再尝试备用模型。"
        >
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        {translationFallbackOn ? (
          <>
            <Form.Item name="trans_fallback_provider" label="翻译备用 · 提供商" rules={[{ required: true }]}>
              <Select placeholder="选择提供商">
                {modelsData?.providers?.map(p => (
                  <Option key={p.id} value={p.id}>{p.name}</Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item
              name="trans_fallback_model"
              label="翻译备用 · 模型"
              rules={[{ required: true }]}
              extra={selectedTransFbProvider === 'ollama'
                ? '列表来自本机已安装模型（与上方列表同源）。'
                : undefined}
            >
              <AutoComplete
                options={transFbModelOptions}
                placeholder="选择或输入模型 ID"
                filterOption={(inputValue, option) => buildModelFilter(inputValue, option, 'trans_fallback_model')}
              />
            </Form.Item>
            {selectedTransFbProvider ? (
              renderEffectiveBase('翻译备用通道地址', transFbProvider?.default_api_base)
            ) : null}
          </>
        ) : null}

        <FormGroupHeading>评分模型配置</FormGroupHeading>

        <SectionNote style={{ marginBottom: 16 }}>
          内容主观评分专用模型。模型名称留空时后端会回退到固定基线；开启 LLM 主观评分后才会调用该通道。
        </SectionNote>

        <Form.Item name="score_provider" label="评分模型提供商" rules={[{ required: true }]}>
          <Select placeholder="选择 AI 提供商">
            {modelsData?.providers?.map(p => (
              <Option key={p.id} value={p.id}>{p.name}</Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item
          name="score_model"
          label="评分模型"
          extra={selectedScoreProvider === 'ollama'
            ? '留空则使用固定基线；填写后在启用 LLM 主观评分时优先使用该模型。'
            : '留空则使用固定基线。'}
        >
          <AutoComplete
            options={scoreModelOptions}
            placeholder="留空 = 使用固定基线"
            filterOption={(inputValue, option) => buildModelFilter(inputValue, option, 'score_model')}
          />
        </Form.Item>

        {selectedScoreProvider ? (
          renderEffectiveBase('当前评分通道服务地址', scoreProvider?.default_api_base)
        ) : null}

        <Form.Item name="score_temperature" label="Temperature">
          <Slider min={0} max={1} step={0.05} />
        </Form.Item>

        <Form.Item name="score_max_tokens" label="Max Tokens">
          <InputNumber min={32} max={150} step={16} style={{ width: '100%' }} />
        </Form.Item>

        {selectedScoreProvider === 'ollama' ? (
          <>
            <Form.Item
              name="score_ollama_num_ctx"
              label="Context 窗口 (num_ctx)"
              extra="评分任务使用的 Ollama 上下文长度，默认 2K。"
            >
              <OllamaCtxSlider />
            </Form.Item>
            <Form.Item
              name="score_ollama_no_think"
              label="关闭思维链 (/no_think)"
              valuePropName="checked"
              extra="短评分任务建议开启，避免模型输出冗长思考过程。"
            >
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
          </>
        ) : null}

        <FormGroupHeading>功能状态与开关</FormGroupHeading>

        <SectionNote style={{ marginBottom: 16 }}>
          模型配置只决定系统可调用什么模型；下面的开关决定哪些自动能力允许运行。用户主动点击阅读器翻译不受“自动翻译标题和摘要”开关影响。
        </SectionNote>

        {migration ? (
          <SectionNote style={{ marginBottom: 16 }}>
            旧版 AI 环境开关已完成一次性迁移（版本 {migration.migration_version}
            {migration.migrated_at ? `，${migration.migrated_at}` : ''}）；后续环境变量变化不会改写这里的产品开关。
          </SectionNote>
        ) : null}

        <div className="mb-4 grid gap-2">
          {renderPolicyStatus('写作模型通道', settings?.ai_policy?.writing)}
          {renderPolicyStatus('自动生成 AI 摘要', settings?.ai_policy?.auto_summary)}
          {renderPolicyStatus('自动翻译标题和摘要', settings?.ai_policy?.auto_listing_translation)}
          {renderPolicyStatus('阅读器按需翻译', settings?.ai_policy?.reader_translation)}
          {renderPolicyStatus('AI 主观评分', settings?.ai_policy?.subjective_scoring)}
        </div>

        <Form.Item
          name="auto_summary_enabled"
          label="自动生成 AI 摘要"
          valuePropName="checked"
          extra="默认开启。只处理新入库且通过验收的内容；模型不可用时保留抽取式摘要。"
        >
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        <Form.Item
          name="auto_listing_translation_enabled"
          label="自动翻译标题和摘要"
          valuePropName="checked"
          extra="默认开启。只控制后台列表翻译，不影响阅读器里用户主动点击翻译。"
        >
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        <Form.Item
          name="ai_subjective_scoring_enabled"
          label="启用 AI 主观评分"
          valuePropName="checked"
          extra="默认关闭。每条合格新内容至多调用一次；实际费用取决于所选 Provider。当前只影子记录 subjective_meta，权重为 0，不改变最终分数和排序。"
        >
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        <Form.Item
          name="ai_processing_paused"
          label="暂停所有 AI 处理"
          valuePropName="checked"
          extra="高级开关：开启后阻止新的 AI 摘要、翻译、简报增强和主观评分调用；已落库内容不删除。"
        >
          <Switch checkedChildren="暂停" unCheckedChildren="运行" />
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={updateMutation.isPending}>保存设置</Button>
        </Form.Item>
      </Form>
      </SettingsSection>

      <TaskPromptsTab />
    </div>
  )
}

export default AIModelTab
