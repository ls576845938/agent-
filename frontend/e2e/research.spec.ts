import { test, expect } from '@playwright/test';

test('Research page loads and shows experiments', async ({ page }) => {
  await page.goto('/research');
  await expect(page.locator('h2')).toContainText('研究台');
  // Should show loading, then data or empty state
  await page.waitForSelector('[data-testid="research-content"]', { timeout: 10000 });
});

test('Portfolio page loads and shows summary', async ({ page }) => {
  await page.goto('/portfolio');
  await expect(page.locator('h2')).toContainText('投资组合');
  await page.waitForSelector('[data-testid="portfolio-content"]', { timeout: 10000 });
});
