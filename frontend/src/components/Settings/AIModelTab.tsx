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
  Divider,
} from 'antd'
import { configsApi } from '../../services/configs'
import type { AIModelTabFormValues } from '../../types'
import ModelProvidersTab from './ModelProvidersTab'
import SectionNote from '../ui/SectionNote'
import PanelLoading from '../common/PanelLoading'
import OllamaCtxSlider, { snapOllamaNumCtx } from './OllamaCtxSlider'

const { Option } = Select

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

  const updateMutation = useMutation({
    mutationFn: configsApi.updateSettings,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['system-settings'] }); message.success('设置已保存') },
    onError: () => message.error('保存失败'),
  })

  const selectedProvider = Form.useWatch('provider', form)
  const currentProvider = modelsData?.providers?.find(p => p.id === selectedProvider)
  const selectedTransProvider = Form.useWatch('trans_provider', form)
  const transProvider = modelsData?.providers?.find(p => p.id === selectedTransProvider)
  const selectedAtomProvider = Form.useWatch('atom_provider', form)
  const atomProvider = modelsData?.providers?.find(p => p.id === selectedAtomProvider)
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
  const atomModelOptions = (atomProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const scoreModelOptions = (scoreProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const transFbModelOptions = (transFbProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const sumFbModelOptions = (sumFbProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const buildModelFilter = (inputValue: string, option: { value?: string; label?: string } | undefined, fieldName: 'model' | 'trans_model' | 'atom_model' | 'score_model' | 'trans_fallback_model' | 'sum_fallback_model') => {
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
      atom_provider: settings.atom_model?.provider || settings.ai_model.provider,
      atom_model: settings.atom_model?.model || '',
      atom_temperature: settings.atom_model?.temperature ?? 0.1,
      atom_max_tokens: settings.atom_model?.max_tokens ?? 4000,
      atom_ollama_num_ctx: snapOllamaNumCtx(settings.atom_model?.ollama_num_ctx, 8192),
      atom_ollama_no_think: settings.atom_model?.ollama_no_think ?? false,
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
      trans_fallback_provider: settings.translation_fallback?.provider,
      trans_fallback_model: settings.translation_fallback?.model,
      sum_fallback_provider: settings.summarization_fallback?.provider,
      sum_fallback_model: settings.summarization_fallback?.model,
      max_sources: settings.limits?.max_sources ?? 200,
      max_digest_candidates: settings.limits?.max_digest_candidates ?? 12,
      max_hourly_digest_input_items: settings.limits?.max_hourly_digest_input_items ?? 200,
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
      atom_model: {
        provider: values.atom_provider,
        model: values.atom_model,
        temperature: values.atom_temperature,
        max_tokens: values.atom_max_tokens,
        ...(values.atom_provider === 'ollama'
          ? {
              ollama_num_ctx: values.atom_ollama_num_ctx,
              ollama_no_think: values.atom_ollama_no_think === true,
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
      limits: {
        max_sources: values.max_sources,
        max_digest_candidates: values.max_digest_candidates,
        max_hourly_digest_input_items: values.max_hourly_digest_input_items,
      },
    })
  }

  if (isLoading) {
    return <PanelLoading message="正在读取模型与系统设置…" />
  }

  return (
    <div>
      <Divider orientation="left">模型接入设置</Divider>
      <ModelProvidersTab />

      <SectionNote style={{ marginBottom: 16, marginTop: 24 }}>
        已接入的提供商才会出现在下面的模型选择中。API Key 与网关地址只在上方「模型接入」维护；此处仅选择提供商、模型及生成参数（Temperature 等）。
      </SectionNote>
      {selectedProvider === 'ollama' && currentProvider?.availability_message ? (
        <SectionNote tone="caution" style={{ marginBottom: 16 }}>
          {currentProvider.availability_message}
        </SectionNote>
      ) : null}
      <Form form={form} layout="vertical" onFinish={handleSave} style={{ maxWidth: 600 }}>
        <Divider orientation="left">写作模型配置</Divider>

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

        <Divider orientation="left">翻译模型配置</Divider>

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

        <Divider orientation="left">原子化模型配置</Divider>

        <SectionNote style={{ marginBottom: 16 }}>
          新闻原子库 LLM 提取专用模型。模型名称留空时将回退使用上方「写作模型」；建议为结构化 JSON 任务选择更强模型。
        </SectionNote>

        <Form.Item name="atom_provider" label="原子化模型提供商" rules={[{ required: true }]}>
          <Select placeholder="选择 AI 提供商">
            {modelsData?.providers?.map(p => (
              <Option key={p.id} value={p.id}>{p.name}</Option>
            ))}
          </Select>
        </Form.Item>

        <Form.Item
          name="atom_model"
          label="原子化模型"
          extra={selectedAtomProvider === 'ollama'
            ? '留空则使用写作模型；填写后优先使用该模型做原子提取。'
            : '留空则使用写作模型。'}
        >
          <AutoComplete
            options={atomModelOptions}
            placeholder="留空 = 使用写作模型"
            filterOption={(inputValue, option) => buildModelFilter(inputValue, option, 'atom_model')}
          />
        </Form.Item>

        {selectedAtomProvider ? (
          renderEffectiveBase('当前原子化通道服务地址', atomProvider?.default_api_base)
        ) : null}

        <Form.Item name="atom_temperature" label="Temperature">
          <Slider min={0} max={1} step={0.05} />
        </Form.Item>

        <Form.Item name="atom_max_tokens" label="Max Tokens">
          <InputNumber min={512} max={16000} step={256} style={{ width: '100%' }} />
        </Form.Item>

        {selectedAtomProvider === 'ollama' ? (
          <>
            <Form.Item
              name="atom_ollama_num_ctx"
              label="Context 窗口 (num_ctx)"
              extra="原子提取使用的 Ollama 上下文长度，默认 8K。"
            >
              <OllamaCtxSlider />
            </Form.Item>
            <Form.Item
              name="atom_ollama_no_think"
              label="关闭思维链 (/no_think)"
              valuePropName="checked"
              extra="结构化 JSON 提取建议开启，减少思维链输出干扰。"
            >
              <Switch checkedChildren="开启" unCheckedChildren="关闭" />
            </Form.Item>
          </>
        ) : null}

        <Divider orientation="left">评分模型配置</Divider>

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
          <InputNumber min={32} max={2000} step={32} style={{ width: '100%' }} />
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

        <Divider orientation="left">系统上限</Divider>

        <Form.Item
          name="max_sources"
          label="监控源上限"
          extra="达到上限后，后端会拒绝新增 source（创建与批量导入都会校验）。"
        >
          <InputNumber min={1} max={5000} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          name="max_digest_candidates"
          label="每小时简报候选事件上限"
          extra="每轮简报最多让模型处理的事件簇数量。"
        >
          <InputNumber min={3} max={30} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          name="max_hourly_digest_input_items"
          label="每小时简报输入内容上限"
          extra="每轮简报读取的原始内容条数上限，避免输入无限增长。选稿与综述提示词在「任务提示」选项卡。"
        >
          <InputNumber min={20} max={2000} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item>
          <Button type="primary" htmlType="submit" loading={updateMutation.isPending}>保存设置</Button>
        </Form.Item>
      </Form>
    </div>
  )
}

export default AIModelTab
