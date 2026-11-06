import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("neo-brutalist workspace is responsive, keyboard navigable and safely renders code", async ({ page }, testInfo) => {
  test.setTimeout(90000);
  const email = `design-${randomUUID()}@example.com`;
  const password = "responsive browser test passphrase";
  const csrf = await (await page.request.get('/api/auth/csrf')).json();
  const headers = { Origin: 'http://localhost:3001', 'X-CSRF-Token': csrf.csrf_token };
  expect((await page.request.post('/api/auth/register', { headers, data: { full_name: 'Design Reviewer', email, password, confirm_password: password } })).status()).toBe(201);
  expect((await page.request.post('/api/auth/login', { headers, data: { email, password } })).status()).toBe(200);
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 960 });
    for (const path of ['/', '/playground', '/sandbox', '/monitoring', '/settings', '/profile']) {
      await page.goto(path);
      await expect(page.locator('main h1')).toBeVisible();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor)).toBe('rgb(9, 9, 11)');
      const primary = page.locator('.button-primary, button[class*="bg-teal-300"]').first();
      if (await primary.count()) {
        const style = await primary.evaluate(el => ({ size: parseFloat(getComputedStyle(el).fontSize), weight: Number(getComputedStyle(el).fontWeight) }));
        expect(style.size).toBeGreaterThanOrEqual(18.67);
        expect(style.weight).toBeGreaterThanOrEqual(700);
      }
      if (width < 900) {
        const toggle = page.getByRole('button', { name: 'Open navigation' });
        await toggle.click();
        await expect(page.getByRole('dialog', { name: 'Navigation menu' })).toBeVisible();
        await page.keyboard.press('Escape');
        await expect(page.getByRole('dialog', { name: 'Navigation menu' })).not.toBeVisible();
        await expect(toggle).toBeFocused();
      }
      if (width === 1440 || width === 375) await page.screenshot({ path: testInfo.outputPath(`${path.slice(1) || 'dashboard'}-${width}.png`), fullPage: true });
    }
    for (const path of ['/login','/register']) {
      await page.goto(path);
      await expect(page.locator('main h1')).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      if (width === 1440 || width === 375) await page.screenshot({ path: testInfo.outputPath(`${path.slice(1)}-${width}.png`), fullPage: true });
    }
  }
  await page.goto('/playground');
  await page.getByLabel('Task or instructions').fill('markdown ui fixture');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Copy code', exact: true })).toBeVisible();
  await expect(page.locator('.safe-markdown strong')).toHaveText('Example');
  await expect(page.locator('.safe-markdown')).toContainText('<img src=x onerror=alert(1)>');
  await expect(page.locator('.safe-markdown img')).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('playground-response-1440.png'), fullPage: true });
});
