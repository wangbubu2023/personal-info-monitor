import { expect, test } from '@playwright/test'
import { mockApi } from '../fixtures/apiMocks'

test.beforeEach(async ({ page }) => {
  await mockApi(page)
})

test('私人简报列表与详情切换可用', async ({ page }) => {
  await page.goto('/digest')

  await expect(page.getByTestId('digest-page')).toBeVisible()
  await expect(page.getByTestId('digest-title')).toHaveText('个人简报')
  await expect(page.getByTestId('digest-hour-card-10')).toBeVisible()

  await page.getByTestId('digest-hour-card-10').click()
  await expect(page.getByTestId('digest-detail')).toBeVisible()
  await expect(page.getByText('市场动态')).toBeVisible()
  await expect(page.getByTestId('digest-back-btn')).toBeVisible()

  await page.getByTestId('digest-back-btn').click()
  await expect(page.getByTestId('digest-hour-card-10')).toBeVisible()
})
