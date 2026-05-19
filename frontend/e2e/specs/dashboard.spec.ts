import { expect, test } from '@playwright/test'
import { mockApi } from '../fixtures/apiMocks'

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('首页展示、搜索与手动抓取流程可用', async ({ page }) => {
  await page.goto('/')

  await expect(page.getByTestId('dashboard-page')).toBeVisible()
  await expect(page.getByTestId('dashboard-title')).toHaveText('资讯中心')
  await expect(page.getByText('WSJ：美股科技板块再次走强')).toBeVisible()

  await page.getByTestId('dashboard-fetch-all-btn').click()
  await expect(page.getByText('已触发抓取任务，共 3 个监控源')).toBeVisible()

  await page.goto('/?search=economist')

  await expect(page).toHaveURL(/\/\?search=economist/)
  await expect(page.getByText('搜索结果')).toBeVisible()
  await expect(page.getByText(/共 1 条/)).toBeVisible()
  await expect(page.getByText(/economist/)).toBeVisible()

  await page.getByRole('button', { name: '清除' }).click()
  await expect(page).toHaveURL('/')
  await expect(page.getByTestId('dashboard-page')).toBeVisible()
})

test('从首页点击标题可打开阅读页', async ({ page }) => {
  await page.goto('/')

  await page.getByTestId('dashboard-title-link-content-1').click()

  await expect(page).toHaveURL(/\/reader\/content-1$/)
  await expect(page.getByTestId('reader-page')).toBeVisible()
  await expect(page.getByTestId('reader-iframe')).toBeVisible()
  await expect(page.getByRole('link', { name: '原文链接' })).toBeVisible()
})
