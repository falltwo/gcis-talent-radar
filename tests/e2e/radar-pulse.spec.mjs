// Needs a running server: python -m uvicorn api.main:app --port 8000
import { expect, test } from '@playwright/test';

const home = process.env.BASE_URL ?? 'http://127.0.0.1:8000/';

// Records when the first ring starts each ripple and the peak opacity it reaches.
const watchRipples = (page, ms) => page.evaluate(duration => new Promise(resolve => {
  const ring = document.querySelector('.radar-pulses i');
  const starts = []; let peak = 0, was = 0;
  const begin = performance.now();
  (function tick() {
    const now = performance.now(), opacity = Number(getComputedStyle(ring).opacity);
    if (opacity > 0 && was === 0) starts.push(now);
    peak = Math.max(peak, opacity); was = opacity;
    if (now - begin < duration) requestAnimationFrame(tick); else resolve({ starts, peak });
  })();
}), ms);

test('ripples start every 3 to 5 seconds and stay faint', async ({ page }) => {
  test.setTimeout(30_000);
  await page.goto(home);
  const { starts, peak } = await watchRipples(page, 17_000);
  expect(starts.length).toBeGreaterThanOrEqual(3);
  starts.slice(1).forEach((start, index) => {
    const gap = start - starts[index];
    expect(gap).toBeGreaterThan(2_900);
    expect(gap).toBeLessThan(5_200);
  });
  expect(peak).toBeLessThanOrEqual(.34);
});

test('pause clears ripples and play resumes them', async ({ page }) => {
  await page.goto(home);
  await page.getByRole('button', { name: '暫停動態' }).click();
  expect((await watchRipples(page, 5_500)).peak).toBe(0);
  await page.getByRole('button', { name: '播放動態' }).click();
  expect((await watchRipples(page, 5_500)).peak).toBeGreaterThan(0);
});

test('reduced motion never starts ripples on its own', async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: 'reduce' });
  const page = await context.newPage();
  await page.goto(home);
  expect((await watchRipples(page, 5_500)).peak).toBe(0);
  await context.close();
});

test('ripples stay inside the phone viewport', async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await page.goto(home);
  await watchRipples(page, 5_500);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await context.close();
});
