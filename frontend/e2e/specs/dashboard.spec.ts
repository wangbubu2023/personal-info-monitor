import { expect, test } from '@playwright/test'
import { mockApi } from '../fixtures/apiMocks'

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('首页展示、搜索与手动抓取流程可用', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByTestId('dashboard-page')).toBeVisible()
  await expect(page.getByTestId('dashboard-title')).toHaveText('资讯监控中心')
  await expect(page.getByText('WSJ：美股科技板块再次走强')).toBeVisible()

  await page.getByTestId('dashboard-fetch-all-btn').click()
  await expect(page.getByText('已触发抓取任务，共 3 个监控源')).toBeVisible()

  await page.getByTestId('global-search-input').fill('economist')
  await page.keyboard.press('Enter')

  await expect(page).toHaveURL(/\/\?search=economist/)
  await expect(page.getByText('搜索结果')).toBeVisible()
  await expect(page.getByText('"economist" 共 1 条')).toBeVisible()

  await page.getByRole('button', { name: '清除搜索' }).click()
  await expect(page).toHaveURL('/')
  await expect(page.getByTestId('dashboard-page')).toBeVisible()
})

test('从首页点击阅读译文可打开阅读页', async ({ page }) => {
  await page.goto('/')

  await page.getByTestId('read-translation-content-1').click()

  await expect(page).toHaveURL(/\/reader\/content-1\?translate=1$/)
  await expect(page.getByTestId('reader-page')).toBeVisible()
  await expect(page.getByTestId('reader-iframe')).toBeVisible()
  await expect(page.getByRole('button', { name: '打开原文' })).toBeVisible()
})
