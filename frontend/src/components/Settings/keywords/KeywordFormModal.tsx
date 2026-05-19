import React from 'react'
import { Button, Form, type FormInstance, Input, Modal, Select, Switch } from 'antd'

import type { Keyword } from '../../../types'
import { parseKeywordBatchInput } from '../keywordInputUtils'
import { KEYWORD_LABEL_COLORS, matchScopeLabels } from './keywordConstants'
import KeywordColorSwatches from './KeywordColorSwatches'

const { Option } = Select

export type KeywordFormModalProps = {
  open: boolean
  editing: Keyword | null
  form: FormInstance
  onCancel: () => void
  onFinish: (values: Record<string, unknown>) => void
  submitLoading: boolean
}

const KeywordFormModal: React.FC<KeywordFormModalProps> = ({
  open,
  editing,
  form,
  onCancel,
  onFinish,
  submitLoading,
}) => {
  return (
    <Modal title={editing ? '编辑搜索词' : '添加搜索词'} open={open} onCancel={onCancel} footer={null}>
      <Form form={form} layout="vertical" onFinish={onFinish}>
        {editing ? (
          <Form.Item name="keyword" label="搜索词" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
        ) : (
          <Form.Item
            name="keywordsText"
            label="搜索词"
            rules={[
              {
                validator: async (_, value) => {
                  if (parseKeywordBatchInput(String(value || '')).keywords.length > 0) {
                    return
                  }
                  throw new Error('请至少输入一个搜索词')
                },
              },
            ]}
            extra="支持一行一个，或使用逗号、中文逗号、分号分隔。与列表中前面的词仅大小写不同的重复项会忽略并提示。"
          >
            <Input.TextArea
              autoSize={{ minRows: 4, maxRows: 8 }}
              placeholder={'例如：\nAI\nOpenAI\nAgent\n\n或输入：AI, OpenAI，Agent；RAG'}
            />
          </Form.Item>
        )}
        <Form.Item name="description" label="描述" extra="可选，仅作备注，不参与匹配。">
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} placeholder="例如：用于区分同名概念的说明" />
        </Form.Item>
        <Form.Item
          name="match_type"
          label="匹配类型"
          initialValue="contains"
          extra="「精确匹配」按词边界匹配整词（英文数字下划线）；「包含」为子串；「正则表达式」需自行编写合法模式。"
        >
          <Select>
            <Option value="exact">精确匹配</Option>
            <Option value="contains">包含</Option>
            <Option value="regex">正则表达式</Option>
          </Select>
        </Form.Item>
        <Form.Item name="match_scope" label="生效范围" initialValue="title_content">
          <Select options={Object.entries(matchScopeLabels).map(([value, label]) => ({ value, label }))} />
        </Form.Item>
        <Form.Item
          name="include_auto_equivalent_terms"
          label="合并自动翻译等价词"
          valuePropName="checked"
          extra="关闭后仅使用下方手动等价词，可避免「苹果」「元」等错误机翻参与匹配。"
        >
          <Switch />
        </Form.Item>
        <Form.Item
          name="manualEquivalentsText"
          label="手动等价词"
          extra="一行一个，或与搜索词相同的分隔方式。与主词仅大小写不同的词会保留；与主词完全相同的重复行会忽略。开启「合并自动翻译」时，下方展示为手动与自动翻译的合并结果；若只想显示本列表、不要机翻（如「开爪」），请关闭「合并自动翻译」后再保存。"
        >
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} placeholder={'例如：苹果公司\nApple Inc'} />
        </Form.Item>
        <Form.Item
          name="color"
          label="标签颜色"
          initialValue={KEYWORD_LABEL_COLORS[0]}
          extra="用于列表与摘要中的关键词标签展示。"
        >
          <KeywordColorSwatches />
        </Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
          <Switch />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" loading={submitLoading}>
            {editing ? '更新' : '创建'}
          </Button>
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default KeywordFormModal
