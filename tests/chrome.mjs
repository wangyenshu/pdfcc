// Opens a PDF in Chrome's real PDF viewer and runs a small script of actions.
// Needs puppeteer-core (npm i puppeteer-core) and a display (e.g. Xvfb :99).
//
//   node tests/chrome.mjs file.pdf '[{"wait":3000},{"shot":"a.png"},{"click":[x,y]},
//                                    {"type":"abc"},{"key":"Enter"},{"hold":"w","ms":500}]'
//
// Env: CHROME (default /usr/bin/google-chrome), DISPLAY (default :99), WIN=1400,950
import puppeteer from "puppeteer-core";
import path from "node:path";

const [pdf, actionsJson = '[{"wait":5000},{"shot":"shot.png"}]'] = process.argv.slice(2);
const actions = JSON.parse(actionsJson);

const browser = await puppeteer.launch({
  executablePath: process.env.CHROME || "/usr/bin/google-chrome",
  headless: false,
  env: { ...process.env, DISPLAY: process.env.DISPLAY || ":99" },
  defaultViewport: null,
  args: ["--no-sandbox", "--window-size=" + (process.env.WIN || "1400,950") + "", "--no-first-run",
         "--disable-features=Translate", "--user-data-dir=/tmp/chrome-prof-" + process.pid],
});
const page = (await browser.pages())[0];
await page.goto("file://" + path.resolve(pdf));
for (const a of actions) {
  if (a.wait) await new Promise(r => setTimeout(r, a.wait));
  if (a.shot) { await page.screenshot({ path: a.shot }); console.log("shot", a.shot); }
  if (a.click) await page.mouse.click(a.click[0], a.click[1]);
  if (a.down) { await page.mouse.move(a.down[0], a.down[1]); await page.mouse.down(); }
  if (a.up) await page.mouse.up();
  if (a.type) await page.keyboard.type(a.type, { delay: a.delay ?? 30 });
  if (a.key) await page.keyboard.press(a.key);
  if (a.hold) { await page.keyboard.down(a.hold); await new Promise(r => setTimeout(r, a.ms ?? 500)); await page.keyboard.up(a.hold); }
}
await browser.close();
