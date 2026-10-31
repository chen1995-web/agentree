// Round 2: start a real run, capture the agent tree + event stream
const task = await taskSpace("agentree-portfolio-shots");
const page = task.page("p1");

await page.goto("http://127.0.0.1:8767/");
await page.waitForSelector("textarea", { timeout: 15000 });
await page.waitForTimeout(800);

// Task that encourages spawning sub-agents (English for an international portfolio)
await page.fill("textarea", "Research the pros and cons of Milvus, Qdrant, and Weaviate vector databases. Spawn a sub-agent for each and run them in parallel, then summarize a comparison table.");
await page.waitForTimeout(400);

// Click "Start run" by text
await page.evaluate(() => {
  const btns = [...document.querySelectorAll('button')];
  const b = btns.find((x) => x.textContent.includes('Start run'));
  if (b) b.click();
});

// Wait for the agent tree to render (while running)
await page.waitForTimeout(25000);

const treeShot = await page.screenshot({ path: "/Users/chenzhifeng/Desktop/EB/北京/agentree/screenshots/03-agent-tree.png", fullPage: true });
console.log({ treeShot, url: await page.url() });
console.log(await page.snapshot());
