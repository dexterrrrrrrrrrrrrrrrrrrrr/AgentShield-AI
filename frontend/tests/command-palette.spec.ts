import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

test('command palette supports shortcuts, filtering, keyboard navigation and focus restoration', async ({page}) => {
  const email=`palette-${randomUUID()}@example.com`,password='palette test long passphrase';
  const {csrf_token}=await (await page.request.get('/api/auth/csrf')).json();
  const headers={Origin:'http://localhost:3001','X-CSRF-Token':csrf_token};
  expect((await page.request.post('/api/auth/register',{headers,data:{full_name:'Palette Tester',email,password,confirm_password:password}})).status()).toBe(201);
  expect((await page.request.post('/api/auth/login',{headers,data:{email,password}})).status()).toBe(200);
  await page.goto('/');
  const trigger=page.getByRole('button',{name:'Open command palette'});
  await trigger.focus(); await page.keyboard.press('Control+k');
  const dialog=page.getByRole('dialog',{name:'Quick navigation'});
  await expect(dialog).toBeVisible();
  const input=dialog.getByRole('combobox'); await expect(input).toBeFocused();
  await expect(dialog.getByRole('option')).toHaveCount(6);
  await input.press('ArrowDown'); await expect(dialog.getByRole('option',{name:'Playground'})).toHaveAttribute('aria-selected','true');
  await input.press('ArrowUp'); await expect(dialog.getByRole('option',{name:'Dashboard'})).toHaveAttribute('aria-selected','true');
  await input.fill('does not exist'); await expect(dialog.getByRole('status')).toContainText('No matching pages');
  await input.fill('sand'); await input.press('Enter'); await expect(page).toHaveURL(/\/sandbox$/); await expect(dialog).not.toBeVisible();
  await trigger.focus(); await page.keyboard.press('Meta+k'); await expect(dialog).toBeVisible();
  await input.press('Escape'); await expect(dialog).not.toBeVisible(); await expect(trigger).toBeFocused();
  await page.setViewportSize({width:375,height:812}); await page.emulateMedia({reducedMotion:'reduce'});
  await trigger.click(); await expect(dialog).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await dialog.getByRole('option',{name:'Profile'}).click(); await expect(page).toHaveURL(/\/profile$/);
});
