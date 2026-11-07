import { test, expect, type Page } from '@playwright/test';
import { randomUUID } from 'node:crypto';

async function caret(page: Page) {
  const input = page.locator('#source-code');
  await expect.poll(() => input.evaluate(el => {
    const p=el.parentElement!.querySelector('pre')!;
    return Math.max(Math.abs(el.scrollLeft-p.scrollLeft),Math.abs(el.scrollTop-p.scrollTop));
  })).toBeLessThanOrEqual(1);
  const geometry = await input.evaluate((element) => {
    const t = element as HTMLTextAreaElement;
    const p = t.parentElement!.querySelector('pre')!;
    const metrics = ['fontFamily','fontSize','fontWeight','lineHeight','letterSpacing','paddingLeft','paddingRight','paddingTop','paddingBottom','tabSize','whiteSpace','borderLeftWidth','borderTopWidth'] as const;
    const a = getComputedStyle(t), b = getComputedStyle(p);
    const styles = metrics.map(k => [k, a[k], b[k]]);
    let left = t.selectionStart;
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode()!;
    while (left > node.textContent!.length) { left -= node.textContent!.length; node = walker.nextNode()!; }
    const range = document.createRange(); range.setStart(node, left); range.collapse(true);
    const rect = range.getBoundingClientRect(), box = t.getBoundingClientRect();
    t.style.caretColor = 'rgb(255, 0, 255)';
    return { styles, x: rect.x - box.x, y: rect.y - box.y, height: rect.height,
      scroll: [t.scrollLeft,p.scrollLeft,t.scrollTop,p.scrollTop] };
  });
  for (const [name, actual, expected] of geometry.styles) expect(actual, name).toBe(expected);
  expect(Math.abs(geometry.scroll[0]-geometry.scroll[1])).toBeLessThanOrEqual(1);
  expect(Math.abs(geometry.scroll[2]-geometry.scroll[3])).toBeLessThanOrEqual(1);
  // Inspect the browser-painted caret, not a selectionStart-only approximation.
  await expect.poll(async () => {
    const png = await input.screenshot({ caret: 'initial' });
    return page.evaluate(async ({ data, x, y, height }) => {
      const image = await createImageBitmap(new Blob([Uint8Array.from(atob(data), c => c.charCodeAt(0))], { type: 'image/png' }));
      const canvas = document.createElement('canvas'); canvas.width=image.width; canvas.height=image.height;
      const ctx=canvas.getContext('2d')!; ctx.drawImage(image,0,0);
      const pixels=ctx.getImageData(0,0,canvas.width,canvas.height).data;
      let count=0;
      for(let py=Math.max(0,Math.floor(y)-3);py<Math.min(canvas.height,y+height+3);py++)
        for(let px=Math.max(0,Math.floor(x)-2);px<Math.min(canvas.width,x+3);px++) {
          const i=(py*canvas.width+px)*4;
          if(pixels[i]>220 && pixels[i+1]<50 && pixels[i+2]>220) count++;
        }
      return count;
    }, { data: png.toString('base64'), ...geometry });
  }, { timeout: 5000 }).toBeGreaterThan(5);
}

test('painted caret aligns with highlighted characters while editing and scrolling', async ({ page }) => {
  await page.setViewportSize({width:1280,height:1000});
  const email=`caret-${randomUUID()}@example.com`, password='editor test passphrase long';
  const {csrf_token}=await (await page.request.get('/api/auth/csrf')).json();
  const headers={Origin:'http://localhost:3001','X-CSRF-Token':csrf_token};
  expect((await page.request.post('/api/auth/register',{headers,data:{full_name:'Caret Tester',email,password,confirm_password:password}})).status()).toBe(201);
  expect((await page.request.post('/api/auth/login',{headers,data:{email,password}})).status()).toBe(200);
  await page.goto('/sandbox');
  await page.evaluate(() => document.fonts.ready);
  const input=page.locator('#source-code');
  for(const language of ['python','javascript']) {
    await page.getByLabel('Language',{exact:true}).selectOption(language);
    const line=language==='python' ? 'print("AgentShield main branch verified")' : 'console.log("AgentShield main branch verified");';
    await input.fill(line);
    const end = await page.locator('.editor-surface pre').evaluate((el, offset) => {
      const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT); let node=walker.nextNode()!;
      while(offset>node.textContent!.length) { offset-=node.textContent!.length; node=walker.nextNode()!; }
      const r=document.createRange(); r.setStart(node,offset); r.collapse(true); const b=r.getBoundingClientRect(); return {x:b.x,y:b.y+b.height/2};
    }, line.length);
    await page.mouse.click(end.x,end.y); await caret(page);
    await input.press('X'); await expect(input).toHaveValue(line+'X'); await caret(page);
    await input.press('Backspace'); await expect(input).toHaveValue(line); await caret(page);
    await input.press('ArrowLeft'); await caret(page);
    await input.press('Delete'); await expect(input).toHaveValue(line.slice(0,-1)); await caret(page);
    await input.fill(line);
    const point=await page.locator('.editor-surface pre span').filter({ hasText: /print|console/ }).first().evaluate(el=> {
      const r=document.createRange(); r.setStart(el.firstChild!,2); r.collapse(true); const b=r.getBoundingClientRect(); return {x:b.x,y:b.y+b.height/2};
    });
    await page.mouse.click(point.x,point.y); await caret(page);
    await input.press('Shift+ArrowRight');
    expect(await input.evaluate(el=>(el as HTMLTextAreaElement).selectionEnd-(el as HTMLTextAreaElement).selectionStart)).toBe(1);
    await input.press('ArrowRight'); await caret(page);
    await input.fill(Array.from({length:40},(_,i)=>`${i}\t${line} ${'x'.repeat(160)}`).join('\n'));
    await input.press('Control+End'); await caret(page);
    expect(await input.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
    expect(await input.evaluate(el=>el.scrollTop)).toBeGreaterThan(0);
    await input.press('Control+Home'); await caret(page);
    await expect(page.locator('.editor-surface pre .text-amber-200').first()).toBeVisible();
  }
});
