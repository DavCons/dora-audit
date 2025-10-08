import { test, expect } from '@playwright/test'; test('app', async ({page})=>{ await page.goto('/'); await expect(page.locator('text=DORA Audit — MVP')).toBeVisible(); });
