import { Modal, Input } from 'antd'
import React from 'react'

export function promptApiKey(): Promise<string | null> {
  return new Promise((resolve) => {
    let currentValue = ''
    Modal.confirm({
      title: '请输入 PIM API Key',
      icon: null,
      content: React.createElement(Input.Password, {
        placeholder: 'API Key',
        autoFocus: true,
        onChange: (e: React.ChangeEvent<HTMLInputElement>) => {
          currentValue = e.target.value
        },
      }),
      okText: '确认',
      cancelText: '取消',
      onOk: () => {
        const trimmed = currentValue.trim()
        resolve(trimmed || null)
      },
      onCancel: () => resolve(null),
    })
  })
}
