import { expect, test } from '@playwright/test'
import { mockApi } from '../fixtures/apiMocks'

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('设置页标签与核心功能切换正常', async ({ page }) => {
  await page.goto('/settings')

  await expect(page.getByTestId('settings-page')).toBeVisible()
  await expect(page.getByTestId('settings-header-title')).toHaveText('系统设置')
  await expect(page.getByTestId('settings-tab-sources')).toBeVisible()

  await page.getByTestId('source-search-input').fill('economist')
  await expect(page.getByRole('row', { name: /Economist/ })).toBeVisible({ timeout: 10000 })

  await page.getByTestId('settings-tab-credentials').click()
  await expect(page.getByRole('button', { name: /新建站点登录/ })).toBeVisible()
  await expect(page.getByRole('heading', { name: '网页登录会话' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Auth Assistant：从本地导入登录态' })).toBeVisible()
  await expect(page.getByText('YouTube API')).toBeVisible()
  await expect(page.getByRole('row', { name: /YT Data API/ }).first()).toBeVisible()

  await page.getByTestId('settings-tab-ai-model').click()
  await expect(page.getByRole('heading', { name: '模型接入' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '每小时简报任务提示' })).toBeVisible()
  await expect(page.getByLabel('AI 提供商')).toBeVisible()
})

test('旧设置深链会迁移到合并后的模块', async ({ page }) => {
  await page.goto('/settings?tab=auth-assistant')
  await expect(page).toHaveURL(/tab=credentials/)
  await expect(page.getByRole('heading', { name: 'Auth Assistant：从本地导入登录态' })).toBeVisible()

  await page.goto('/settings?tab=task-prompts')
  await expect(page).toHaveURL(/tab=ai-model/)
  await expect(page.getByRole('heading', { name: '每小时简报任务提示' })).toBeVisible()

  await page.goto('/settings?tab=maintenance')
  await expect(page).toHaveURL(/tab=system-upgrade/)
  await expect(page.getByTestId('system-upgrade-tab')).toBeVisible()
})
