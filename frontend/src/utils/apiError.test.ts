import { describe, expect, it } from 'vitest'
import { formatApiErrorDetail, getAxiosErrorMessage } from './apiError'

describe('formatApiErrorDetail', () => {
  it('formats FastAPI validation array without throwing', () => {
    const detail = [
      {
        type: 'value_error',
        loc: ['body', 'url'],
        msg: 'Value error, URL must start with http:// or https://',
        input: 'www.bbc.com/zhongwen/simp',
      },
    ]
    expect(formatApiErrorDetail(detail)).toBe(
      'URL：URL 格式无法解析，请补全地址（可省略 https://）',
    )
  })

  it('returns string detail as-is after localization', () => {
    expect(formatApiErrorDetail('信源已达上限')).toBe('信源已达上限')
  })
})

describe('getAxiosErrorMessage', () => {
  it('reads detail array from axios-like error', () => {
    const err = {
      response: {
        data: {
          detail: [{ loc: ['body', 'url'], msg: 'Value error, URL must include a valid host' }],
        },
      },
    }
    expect(getAxiosErrorMessage(err, '失败')).toBe('URL：URL 格式无法解析，请检查地址是否正确')
  })
})
