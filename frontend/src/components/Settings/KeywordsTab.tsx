import React, { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, ColorPicker, Form, Input, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'

import { keywordsApi } from '../../services/keywords'
import type { Keyword, KeywordCreate } from '../../types'

const { Option } = Select

const KeywordsTab: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingKeyword, setEditingKeyword] = useState<Keyword | null>(null)
  const [form] = Form.useForm()
  const queryClient = useQueryClient()

  const { data: keywordsData, isLoading } = useQuery({
    queryKey: ['keywords'],
    queryFn: () => keywordsApi.list(),
  })

  const createMutation = useMutation({
    mutationFn: keywordsApi.create,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['keywords'] }); message.success('创建成功'); setIsModalOpen(false); form.resetFields() },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<KeywordCreate> }) => keywordsApi.update(id, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['keywords'] }); message.success('更新成功'); setIsModalOpen(false); setEditingKeyword(null); form.resetFields() },
  })

  const deleteMutation = useMutation({
    mutationFn: keywordsApi.delete,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['keywords'] }); message.success('删除成功') },
  })

  const columns = [
    { title: '关键词', dataIndex: 'keyword', key: 'keyword', render: (keyword: string, record: Keyword) => <Tag color={record.color}>{keyword}</Tag> },
    { title: '匹配类型', dataIndex: 'match_type', key: 'match_type', render: (type: string) => ({ exact: '精确匹配', contains: '包含', regex: '正则表达式' }[type] || type) },
    { title: '通知', dataIndex: 'notify', key: 'notify', render: (notify: boolean) => <Tag color={notify ? 'green' : 'default'}>{notify ? '开启' : '关闭'}</Tag> },
    { title: '状态', dataIndex: 'enabled', key: 'enabled', render: (enabled: boolean) => <Tag color={enabled ? 'green' : 'default'}>{enabled ? '启用' : '禁用'}</Tag> },
    {
      title: '操作', key: 'actions',
      render: (_: unknown, record: Keyword) => (
        <Space>
          <Button icon={<EditOutlined />} size="small" onClick={() => { setEditingKeyword(record); form.setFieldsValue(record); setIsModalOpen(true) }}>编辑</Button>
          <Popconfirm title="确定要删除这个关键词吗？" onConfirm={() => deleteMutation.mutate(record.id)}><Button icon={<DeleteOutlined />} size="small" danger>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingKeyword(null); form.resetFields(); setIsModalOpen(true) }} style={{ marginBottom: 16 }}>添加搜索词</Button>
      <Table columns={columns} dataSource={keywordsData?.items || []} loading={isLoading} rowKey="id" />
      <Modal title={editingKeyword ? '编辑搜索词' : '添加搜索词'} open={isModalOpen} onCancel={() => setIsModalOpen(false)} footer={null}>
        <Form form={form} layout="vertical" onFinish={(values) => editingKeyword ? updateMutation.mutate({ id: editingKeyword.id, data: values }) : createMutation.mutate(values)}>
          <Form.Item name="keyword" label="搜索词" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea /></Form.Item>
          <Form.Item name="match_type" label="匹配类型" initialValue="contains"><Select><Option value="exact">精确匹配</Option><Option value="contains">包含</Option><Option value="regex">正则表达式</Option></Select></Form.Item>
          <Form.Item name="color" label="颜色" initialValue="#ff4d4f"><ColorPicker format="hex" /></Form.Item>
          <Form.Item name="notify" label="通知" valuePropName="checked" initialValue={true}><Switch /></Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}><Switch /></Form.Item>
          <Form.Item><Button type="primary" htmlType="submit">{editingKeyword ? '更新' : '创建'}</Button></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default KeywordsTab
