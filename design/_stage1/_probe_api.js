/* Are the localhost /api request failures a shell regression or harness/server noise?
 *   node design/_stage1/_probe_api.js
 * Loads / twice and lists every failed request by kind.
 */
'use strict';
const puppeteer = require('F:/VSC Projects/pb-bench/node_modules/puppeteer-core');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  for (let pass = 1; pass <= 2; pass++) {
    const page = await browser.newPage();
    const fails = [];
    await page.setViewport({ width: 1920, height: 1080 });
    page.on('requestfailed', (r) => fails.push(r.url() + ' :: ' + ((r.failure() || {}).errorText || '')));
    await page.goto('http://127.0.0.1:8787/', { waitUntil: 'load', timeout: 30000 });
    await sleep(2500);
    const api = fails.filter((u) => u.includes('/api/'));
    const img = fails.filter((u) => u.includes('warframe.market'));
    const other = fails.filter((u) => !u.includes('/api/') && !u.includes('warframe.market'));
    console.log('pass ' + pass + ': api=' + api.length + ' cdnImg=' + img.length + ' other=' + other.length);
    if (api.length) console.log('   api  : ' + JSON.stringify(api.slice(0, 4)));
    if (other.length) console.log('   other: ' + JSON.stringify(other.slice(0, 4)));
    await page.close();
  }
  await browser.close();
})();
