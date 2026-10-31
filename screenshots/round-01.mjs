// Round 1: clear auth -> login screenshot -> demo login -> console screenshot
const task = await taskSpace("agentree-portfolio-shots");
const page = task.page("p1");

// Clear persisted demo token so the login panel shows
await page.goto("http://127.0.0.1:8767/");
await page.evaluate(() => { try { localStorage.clear(); } catch (e) {} });
await page.goto("http://127.0.0.1:8767/");
await page.waitForSelector(".login-panel", { timeout: 15000 });
await page.waitForTimeout(1500);

const loginShot = await page.screenshot({ path: "/Users/chenzhifeng/Desktop/EB/北京/agentree/screenshots/01-login.png", fullPage: true });
console.log({ loginShot, url: await page.url() });

// Click demo login
await page.click(".demo-btn", { label: "click demo login" });
await page.waitForURL("**/#/console**", { timeout: 15000 }).catch(() => {});
await page.waitForTimeout(2000);

const consoleShot = await page.screenshot({ path: "/Users/chenzhifeng/Desktop/EB/北京/agentree/screenshots/02-console.png", fullPage: true });
console.log({ consoleShot, url: await page.url() });
