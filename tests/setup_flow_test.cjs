// Runs the real (non-demo) dashboard against a fake GitHub API and checks secrets are sealed correctly
// and the OAuth callback hands the code to the connect workflow.
const puppeteer = require(process.env.PUPPETEER || "puppeteer-core");
const fs = require("fs");
const BASE = process.env.DASH_BASE || "http://127.0.0.1:8811/";
const PK = fs.readFileSync(process.argv[2], "utf8").trim();
(async () => {
  const b = await puppeteer.launch({executablePath: "/usr/bin/google-chrome", args: ["--no-sandbox"]});
  const p = await b.newPage();
  await p.setViewport({width: 390, height: 844, isMobile: true});
  const errs = [], puts = [], dispatches = [];
  p.on("pageerror", e => errs.push(e.message));
  await p.setRequestInterception(true);
  const files = {"config/settings.json": {channel: "AI Stories", timezone: "America/Los_Angeles", platforms: {instagram: {enabled: true}, youtube: {enabled: true}, tiktok: {enabled: true, mode: "inbox"}}}, "config/series.json": [{id: "homedepot", name: "Home Depot Outbreak", active: true}]};
  p.on("request", r => {
    const u = r.url();
    if (!u.startsWith("https://api.github.com")) return r.continue();
    const path = u.replace("https://api.github.com", "");
    const json = (o, s = 200) => r.respond({status: s, contentType: "application/json", headers: {"Access-Control-Allow-Origin": "*"}, body: JSON.stringify(o)});
    if (r.method() === "OPTIONS") return r.respond({status: 204, headers: {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*"}});
    if (path.includes("/actions/secrets/public-key")) return json({key: PK, key_id: "K9"});
    if (path.includes("/actions/secrets?")) return json({secrets: [{name: "GH_PAT"}]});
    if (r.method() === "PUT" && path.includes("/actions/secrets/")) { puts.push({name: path.split("/").pop(), body: JSON.parse(r.postData())}); return r.respond({status: 201, headers: {"Access-Control-Allow-Origin": "*"}, body: ""}); }
    if (path.includes("/dispatches")) { dispatches.push({wf: path.split("/")[6], body: JSON.parse(r.postData())}); return r.respond({status: 204, headers: {"Access-Control-Allow-Origin": "*"}}); }
    if (path.includes("/actions/runs")) return json({workflow_runs: []});
    const m = path.match(/\/contents\/([^?]+)/);
    if (m && r.method() === "GET") {
      if (!(m[1] in files)) return json({message: "Not Found"}, 404);
      return json({sha: "s1", content: Buffer.from(JSON.stringify(files[m[1]])).toString("base64")});
    }
    if (m && r.method() === "PUT") { const bd = JSON.parse(r.postData()); files[m[1]] = JSON.parse(Buffer.from(bd.content, "base64").toString()); return json({content: {sha: "s2"}}); }
    return json({message: "unexpected " + path}, 500);
  });
  await p.goto(BASE + "index.html", {waitUntil: "load"});
  await p.evaluate(() => { localStorage.setItem("as_repo", "me/ai-stories"); localStorage.setItem("as_tok", "github_pat_xxxxxxxxxxxxxxxxxxxx"); });
  await p.goto(BASE + "index.html", {waitUntil: "load"}); await new Promise(r => setTimeout(r, 800));
  const view = await p.evaluate(() => document.querySelector(".view.on").id);
  await p.screenshot({path: "/tmp/shots1/setup.png", fullPage: true});
  await p.type("#kClaude", "sk-ant-test-key"); await p.evaluate(() => saveField("kClaude", "ANTHROPIC_API_KEY")); await new Promise(r => setTimeout(r, 400));
  await p.evaluate(() => document.querySelectorAll("details").forEach(d => d.open = true));
  await p.type("#kYTid", "123.apps.googleusercontent.com"); await p.type("#kYTsec", "GOCSPX-abc"); await p.evaluate(() => saveClient("youtube")); await new Promise(r => setTimeout(r, 600));
  const ytEnabled = await p.$eval("button[onclick=\"startOAuth('youtube')\"]", b => !b.disabled);
  // simulate Google redirect landing on callback.html
  const state = await p.evaluate(() => { const s = "as_youtube_abc123"; localStorage.setItem("as_oauth_state", s); return s; });
  await p.goto(BASE + "callback.html?code=4%2F0AUTHCODE&state=" + state, {waitUntil: "load"}); await new Promise(r => setTimeout(r, 1500));
  const after = p.url();
  await b.close();
  console.log(JSON.stringify({view, ytEnabled, after, puts: puts.map(x => x.name), dispatches, errs, settings: files["config/settings.json"].oauth}, null, 1));
  fs.writeFileSync("/tmp/sb/puts.json", JSON.stringify(puts));
})();
