/* rail + launcher close-ups for the Stage 2 vision pass
 *   node design/_stage2/shot_rail.js
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const SHOTS = 'C:/Users/jayde/AppData/Local/Temp/shotkit/shots';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const b = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const p = await b.newPage();
  await p.setViewport({ width: 1920, height: 1080 });
  await p.goto('http://127.0.0.1:8787/#tools', { waitUntil: 'load' });
  await sleep(2200);
  const box = await p.evaluate(() => {
    const side = document.querySelector('.side').getBoundingClientRect();
    const pills = [...document.querySelectorAll('#mainnav .navpill')].map((x) => x.getBoundingClientRect());
    return { x: 0, y: Math.max(0, Math.floor(side.top) - 4), w: Math.ceil(side.width + 8),
      h: Math.ceil(pills[pills.length - 1].bottom - side.top + 16) };
  });
  await p.screenshot({ path: path.join(SHOTS, 'ia-rail-1920.png'),
    clip: { x: box.x, y: box.y, width: Math.min(box.w, 1920), height: Math.min(box.h, 1080) } });
  await p.screenshot({ path: path.join(SHOTS, 'ia-rail-zoom.png'),
    clip: { x: 0, y: box.y, width: 260, height: Math.min(box.h, 1080) } });
  const box2 = await p.evaluate(() => {
    const l = document.getElementById('toolsLauncher').getBoundingClientRect();
    return { x: Math.floor(l.x) - 8, y: Math.floor(l.y) - 6, width: Math.ceil(l.width) + 16, height: Math.ceil(l.height) + 14 };
  });
  await p.screenshot({ path: path.join(SHOTS, 'ia-launcher-zoom.png'), clip: box2 });
  console.log('rail box', JSON.stringify(box), 'launcher box', JSON.stringify(box2));
  await b.close();
})();
