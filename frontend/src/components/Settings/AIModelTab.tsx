import React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Form,
  Input,
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
import ModelProvidersTab from './ModelProvidersTab'
import SectionNote from '../ui/SectionNote'

const { Option } = Select
const { Password } = Input

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
  const modelOptions = (currentProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const transModelOptions = (transProvider?.models || []).map((m) => ({ value: m.id, label: m.name }))
  const buildModelFilter = (inputValue: string, option: { value?: string; label?: string } | undefined, fieldName: 'model' | 'trans_model') => {
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

  React.useEffect(() => {
    if (settings) {
      form.setFieldsValue({
        provider: settings.ai_model.provider,
        model: settings.ai_model.model,
        api_base: settings.ai_model.api_base,
        temperature: settings.ai_model.temperature,
        max_tokens: settings.ai_model.max_tokens,
        trans_provider: (settings as any).translation_model?.provider || 'ollama',
        trans_model: (settings as any).translation_model?.model || 'translategemma:12b',
        trans_api_base: (settings as any).translation_model?.api_base || 'http://localhost:11434',
        translation_enabled: settings.translation_enabled,
        title_translation_enabled: (settings as any).title_translation_enabled ?? true,
        summarization_enabled: settings.summarization_enabled,
        translation_cloud_fallback_enabled: (settings as any).translation_cloud_fallback_enabled ?? false,
        summarization_cloud_fallback_enabled: (settings as any).summarization_cloud_fallback_enabled ?? false,
        max_sources: (settings as any).limits?.max_sources ?? 200,
        max_digest_candidates: (settings as any).limits?.max_digest_candidates ?? 12,
        max_hourly_digest_input_items: (settings as any).limits?.max_hourly_digest_input_items ?? 200,
      })
    }
  }, [settings, form])

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
    const currentApiBase = form.getFieldValue('api_base')
    if (!currentApiBase && currentProvider.default_api_base) {
      form.setFieldValue('api_base', currentProvider.default_api_base)
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
    const currentApiBase = form.getFieldValue('trans_api_base')
    if (
      transProvider.default_api_base &&
      (!currentApiBase || (selectedTransProvider !== 'ollama' && currentApiBase === 'http://localhost:11434'))
    ) {
      form.setFieldValue('trans_api_base', transProvider.default_api_base)
    }
  }, [transProvider, form, selectedTransProvider])

  const handleSave = (values: any) => {
    updateMutation.mutate({
      ai_model: {
        provider: values.provider,
        model: values.model,
        api_base: values.api_base,
        api_key: values.api_key,
        temperature: values.temperature,
        max_tokens: values.max_tokens,
      },
      translation_model: {
        provider: values.trans_provider,
        model: values.trans_model,
        api_base: values.trans_api_base,
        api_key: values.trans_api_key,
      },
      translation_enabled: values.translation_enabled,
      title_translation_enabled: values.title_translation_enabled,
      summarization_enabled: values.summarization_enabled,
      translation_cloud_fallback_enabled: values.translation_cloud_fallback_enabled,
      summarization_cloud_fallback_enabled: values.summarization_cloud_fallback_enabled,
      limits: {
        max_sources: values.max_sources,
        max_digest_candidates: values.max_digest_candidates,
        max_hourly_digest_input_items: values.max_hourly_digest_input_items,
      },
    })
  }

  if (isLoading) return <div>加载中...</div>

  return (
    <div>
      <Divider orientation="left">模型接入设置</Divider>
      <ModelProvidersTab />

      <SectionNote style={{ marginBottom: 16, marginTop: 24 }}>
        已接入的提供商才会出现在下面的模型选择中。
      </SectionNote>
      {selectedProvider === 'ollama' && currentProvider?.availability_message ? (
        <SectionNote tone="caution" style={{ marginBottom: 16 }}>
          {currentProvider.availability_message}
        </SectionNote>
      ) : null}
      <Form form={form} layout="vertical" onFinish={handleSave} style={{ maxWidth: 600 }}>
        <Divider orientation="left">摘要模型配置</Divider>

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
            : '云端提供商显示推荐模型列表；可直接输入自定义模型 ID。'}
        >
          <AutoComplete
            options={modelOptions}
            placeholder="选择或输入模型 ID"
            filterOption={(inputValue, option) => buildModelFilter(inputValue, option, 'model')}
          />
        </Form.Item>

        {currentProvider?.requires_api_key && (
          <Form.Item name="api_key" label="API Key" extra={settings?.ai_model?.has_api_key ? '已配置 API Key，留空则不更新' : '请输入 API Key'}>
            <Password placeholder="sk-..." />
          </Form.Item>
        )}

        <Form.Item
          name="api_base"
          label={selectedProvider === 'ollama' ? 'Ollama API 地址' : 'API Base（可选，OpenAI 兼容）'}
          extra={selectedProvider === 'ollama'
            ? '本地 Ollama 默认地址为 http://localhost:11434'
            : '如使用官方 OpenAI 可留默认；Gemini/Qwen 可填写其兼容网关地址。'}
        >
          <Input placeholder={selectedProvider === 'ollama' ? 'http://localhost:11434' : 'https://api.openai.com/v1'} />
        </Form.Item>

        <Form.Item name="temperature" label="Temperature" extra="控制输出的随机性，0 为确定性输出，2 为最大随机">
          <Slider min={0} max={2} step={0.1} marks={{ 0: '0', 0.7: '0.7', 1: '1', 2: '2' }} />
        </Form.Item>

        <Form.Item name="max_tokens" label="最大 Token 数">
          <InputNumber min={100} max={4000} style={{ width: '100%' }} />
        </Form.Item>

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
            : '云端提供商显示推荐模型列表；可直接输入自定义模型 ID。'}
        >
          <AutoComplete
            options={transModelOptions}
            placeholder="选择或输入模型 ID"
            filterOption={(inputValue, option) => buildModelFilter(inputValue, option, 'trans_model')}
          />
        </Form.Item>

        {transProvider?.requires_api_key && (
          <Form.Item
            name="trans_api_key"
            label="翻译模型 API Key"
            extra={(settings as any)?.translation_model?.has_api_key ? '已配置 API Key，留空则不更新' : '请输入翻译模型 API Key'}
          >
            <Password placeholder="sk-..." />
          </Form.Item>
        )}

        <Form.Item
          name="trans_api_base"
          label={selectedTransProvider === 'ollama' ? '翻译模型 Ollama API 地址' : '翻译模型 API Base（可选，OpenAI 兼容）'}
          extra={selectedTransProvider === 'ollama'
            ? '默认 http://localhost:11434'
            : '不填将优先使用该提供商默认地址；如需代理网关可手动覆盖。'}
        >
          <Input placeholder={selectedTransProvider === 'ollama' ? 'http://localhost:11434' : 'https://ark.cn-beijing.volces.com/api/v3'} />
        </Form.Item>

        <Divider orientation="left">功能开关</Divider>

        <Form.Item name="translation_enabled" label="自动翻译摘要" valuePropName="checked">
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        <Form.Item name="title_translation_enabled" label="自动翻译标题" valuePropName="checked">
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        <Form.Item name="summarization_enabled" label="内容摘要" valuePropName="checked">
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        <Form.Item
          name="translation_cloud_fallback_enabled"
          label="翻译云端回退（OpenAI/Google）"
          valuePropName="checked"
          extra="默认关闭。仅在本地 Ollama 失败时回退到云端。"
        >
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

        <Form.Item
          name="summarization_cloud_fallback_enabled"
          label="摘要云端回退（OpenAI）"
          valuePropName="checked"
          extra="默认关闭。仅在本地 Ollama 摘要失败时回退到云端。"
        >
          <Switch checkedChildren="开启" unCheckedChildren="关闭" />
        </Form.Item>

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
          extra="每轮简报读取的原始内容条数上限，避免输入无限增长。"
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
