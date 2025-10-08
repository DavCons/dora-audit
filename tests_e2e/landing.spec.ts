import { test, expect } from '@playwright/test'; test('landing', async ({page})=>{ await page.goto('/'); await expect(page.locator('text=DORA Audit')).toBeVisible(); });
