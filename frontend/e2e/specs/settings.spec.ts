import { expect, test } from '@playwright/test'
import { mockApi } from '../fixtures/apiMocks'

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('设置页标签与核心功能切换正常', async ({ page }) => {
  await page.goto('/settings')

  await expect(page.getByTestId('settings-page')).toBeVisible()
  await expect(page.getByTestId('settings-header-title')).toHaveText('设置')
  await expect(page.getByTestId('settings-tab-sources')).toBeVisible()

  await page.getByTestId('source-search-input').fill('economist')
  await expect(page.getByRole('row', { name: /Economist/ })).toBeVisible({ timeout: 10000 })

  await page.getByTestId('settings-tab-api-keys').click()
  await expect(page.getByRole('button', { name: '添加共享 X 登录态' })).toBeVisible()
  await expect(page.getByRole('row', { name: /YouTube/ }).first()).toBeVisible()

  await page.getByTestId('settings-tab-ai-model').click()
  await expect(page.getByText('模型接入设置')).toBeVisible()
  await expect(page.getByLabel('AI 提供商')).toBeVisible()
})
