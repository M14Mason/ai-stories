// Drives the dashboard in demo mode at iPhone size and fails on any JS error.
const puppeteer = require(process.env.PUPPETEER || "puppeteer-core");
const path = require("path");
(async () => {
  const b = await puppeteer.launch({executablePath: process.env.CHROME || "/usr/bin/google-chrome", args: ["--no-sandbox"]});
  const p = await b.newPage();
  await p.setViewport({width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true});
  const errs = [];
  p.on("pageerror", e => errs.push("pageerror: " + e.message));
  p.on("console", m => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errs.push("console: " + m.text()); });
  const url = process.env.DASH_URL || ("file://" + path.resolve(__dirname, "../docs/index.html"));
  const out = process.argv[2] || "/tmp";
  await p.goto(url + "?demo", {waitUntil: "load"});
  await new Promise(r => setTimeout(r, 600));
  const cards = await p.$$eval("#todayList .card", n => n.length);
  if (!cards) errs.push("no cards on Today");
  await p.click("#todayList .card"); await new Promise(r => setTimeout(r, 400));
  await p.screenshot({path: out + "/sheet_post.png"});
  const btns = await p.$$eval("#sheetBody .btn", n => n.map(x => x.textContent));
  await p.evaluate(() => closeSheet()); await new Promise(r => setTimeout(r, 300));
  // failed post sheet
  await p.evaluate(() => openPost(S.posts.find(x => x.status === "failed").id)); await new Promise(r => setTimeout(r, 400));
  const failBtns = await p.$$eval("#sheetBody .btn", n => n.map(x => x.textContent));
  await p.evaluate(() => closeSheet());
  // series edit + save
  await p.evaluate(() => show("series")); await p.evaluate(() => editSeries(null)); await new Promise(r => setTimeout(r, 300));
  await p.type("#eName", "Sinking Ship"); await p.type("#ePrem", "You wake up in a cabin on a cruise ship that is slowly tipping over in the middle of the night.");
  await p.screenshot({path: out + "/sheet_series.png"});
  await p.evaluate(() => saveSeries("")); await new Promise(r => setTimeout(r, 300));
  const nSeries = await p.evaluate(() => S.series.length);
  // filters + settings toggles
  await p.evaluate(() => { show("posts"); postFilter = "failed"; render(); });
  const failedShown = await p.$$eval("#postList .card", n => n.length);
  await p.evaluate(() => { show("system"); setSetting("approval", "manual"); }); await new Promise(r => setTimeout(r, 200));
  const appr = await p.evaluate(() => S.settings.approval);
  // login screen without demo
  const p2 = await b.newPage(); await p2.setViewport({width: 390, height: 844, deviceScaleFactor: 2, isMobile: true});
  p2.on("pageerror", e => errs.push("login pageerror: " + e.message));
  await p2.goto(url, {waitUntil: "load"}); await new Promise(r => setTimeout(r, 300));
  const loginVisible = await p2.$eval("#login", n => getComputedStyle(n).display !== "none");
  await p2.screenshot({path: out + "/login.png"});
  await b.close();
  const res = {cards, btns, failBtns, nSeries, failedShown, appr, loginVisible, errs};
  console.log(JSON.stringify(res, null, 1));
  const ok = !errs.length && cards > 0 && nSeries === 4 && failedShown === 1 && appr === "manual" && loginVisible && failBtns.includes("Retry");
  process.exit(ok ? 0 : 1);
})();
