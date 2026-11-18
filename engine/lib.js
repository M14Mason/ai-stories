window.R = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const figs = {};
  const POSES = {
    stand:  { torso: 0, head: 0, uaL: 12, laL: 4, uaR: -12, laR: -4, ulL: 6, llL: 0, ulR: -6, llR: 0 },
    scared: { torso: -8, head: -6, uaL: 150, laL: 40, uaR: -150, laR: -40, ulL: 14, llL: -10, ulR: -14, llR: 10 },
    reach:  { torso: 6, head: 8, uaL: 20, laL: 10, uaR: -160, laR: -10, ulL: 6, llL: 0, ulR: -6, llR: 0 },
    point:  { torso: 0, head: 0, uaL: 12, laL: 4, uaR: -95, laR: 0, ulL: 6, llL: 0, ulR: -6, llR: 0 },
    push:   { torso: 18, head: 6, uaL: -80, laL: -10, uaR: -95, laR: -10, ulL: 30, llL: -20, ulR: -30, llR: 0 },
    sit:    { torso: -6, head: 4, uaL: -30, laL: -60, uaR: -40, laR: -70, ulL: -90, llL: 90, ulR: -80, llR: 85 },
    crouch: { torso: 25, head: 10, uaL: -40, laL: -50, uaR: -50, laR: -60, ulL: -70, llL: 110, ulR: -40, llR: 90 },
    phone:  { torso: 4, head: 18, uaL: 10, laL: 0, uaR: -30, laR: -110, ulL: 6, llL: 0, ulR: -6, llR: 0 },
    flash:  { torso: 4, head: 6, uaL: 12, laL: 4, uaR: -80, laR: -10, ulL: 6, llL: 0, ulR: -6, llR: 0 },
    walkA:  { torso: 4, head: 0, uaL: -28, laL: -20, uaR: 28, laR: -10, ulL: -28, llL: 10, ulR: 24, llR: 30 },
    walkB:  { torso: 4, head: 0, uaL: 28, laL: -10, uaR: -28, laR: -20, ulL: 24, llL: 30, ulR: -28, llR: 10 },
    run1:   { torso: 16, head: 4, uaL: -60, laL: -80, uaR: 50, laR: -70, ulL: -55, llL: 30, ulR: 40, llR: 80 },
    run2:   { torso: 16, head: 4, uaL: 50, laL: -70, uaR: -60, laR: -80, ulL: 40, llL: 80, ulR: -55, llR: 30 },
  };
  function stick(id, opts = {}) {
    const o = Object.assign({ x: 540, y: 1500, s: 1, color: "#f4efe6", stroke: "#1b1b22", face: "", flip: false, w: 26 }, opts);
    const L = { torso: 120, ua: 62, la: 58, ul: 78, ll: 74, head: 40 };
    const seg = (name, len, child = "") =>
      `<g data-j="${name}"><line x1="0" y1="0" x2="0" y2="${len}" stroke="${o.color}" stroke-width="${o.w}" stroke-linecap="round"/>${child ? `<g transform="translate(0,${len})">${child}</g>` : ""}</g>`;
    const arm = (s) => seg("ua" + s, L.ua, seg("la" + s, L.la));
    const leg = (s) => seg("ul" + s, L.ul, seg("ll" + s, L.ll));
    const faces = {
      "": "",
      worried: `<circle cx="-12" cy="-4" r="4" fill="${o.stroke}"/><circle cx="12" cy="-4" r="4" fill="${o.stroke}"/><path d="M-10 16 Q0 10 10 16" stroke="${o.stroke}" stroke-width="4" fill="none"/>`,
      glasses: `<circle cx="-14" cy="-4" r="11" stroke="${o.stroke}" stroke-width="4" fill="none"/><circle cx="14" cy="-4" r="11" stroke="${o.stroke}" stroke-width="4" fill="none"/><line x1="-3" y1="-4" x2="3" y2="-4" stroke="${o.stroke}" stroke-width="4"/><circle cx="-14" cy="-4" r="3" fill="${o.stroke}"/><circle cx="14" cy="-4" r="3" fill="${o.stroke}"/><path d="M-8 22 L8 22" stroke="${o.stroke}" stroke-width="4"/>`,
      shock: `<circle cx="-12" cy="-6" r="5" fill="${o.stroke}"/><circle cx="12" cy="-6" r="5" fill="${o.stroke}"/><ellipse cx="0" cy="18" rx="7" ry="9" fill="${o.stroke}"/>`,
    };
    const head = `<g data-j="head"><circle cx="0" cy="${-L.head}" r="${L.head}" fill="${o.color}" stroke="${o.stroke}" stroke-width="5"/><g transform="translate(0,${-L.head})">${faces[o.face] || ""}</g></g>`;
    const torso = `<g data-j="torso"><line x1="0" y1="0" x2="0" y2="${-L.torso}" stroke="${o.color}" stroke-width="${o.w}" stroke-linecap="round"/><g transform="translate(0,${-L.torso + 10})">${arm("L")}${arm("R")}</g><g transform="translate(0,${-L.torso - 6})">${head}</g></g>`;
    const svg = `<g id="${id}" data-fig transform="translate(${o.x},${o.y}) scale(${o.flip ? -o.s : o.s},${o.s})"><g transform="translate(0,${-(L.ul + L.ll)})">${leg("L")}${leg("R")}${torso}</g></g>`;
    figs[id] = { st: Object.assign({ x: o.x, y: o.y, s: o.s, flip: o.flip }, POSES.stand), el: null };
    return svg;
  }
  function draw(id) {
    const f = figs[id];
    if (!f.el) f.el = document.getElementById(id);
    if (!f.el) return;
    const st = f.st;
    f.el.setAttribute("transform", `translate(${st.x},${st.y}) scale(${st.flip ? -st.s : st.s},${st.s})`);
    f.el.querySelectorAll("[data-j]").forEach((g) => { g.setAttribute("transform", `rotate(${st[g.dataset.j] || 0})`); });
  }
  function pose(tl, id, p, t, dur = 0.35, ease = "power2.inOut") {
    const target = typeof p === "string" ? POSES[p] : p;
    tl.to(figs[id].st, Object.assign({}, target, { duration: dur, ease, onUpdate: () => draw(id) }), t);
  }
  function set(tl, id, p, t) {
    const target = typeof p === "string" ? POSES[p] : p;
    tl.set(figs[id].st, Object.assign({}, target, { onUpdate: () => draw(id), onComplete: () => draw(id) }), t);
    tl.call(() => draw(id), null, t + 0.001);
  }
  function move(tl, id, props, t, dur, ease = "none") {
    tl.to(figs[id].st, Object.assign({}, props, { duration: dur, ease, onUpdate: () => draw(id) }), t);
  }
  function walk(tl, id, toX, t, dur, run = false) {
    const step = run ? 0.18 : 0.32;
    const a = run ? "run1" : "walkA", b = run ? "run2" : "walkB";
    let k = 0;
    for (let tt = t; tt < t + dur - 0.01; tt += step, k++) pose(tl, id, k % 2 ? b : a, tt, step, "sine.inOut");
    move(tl, id, { x: toX }, t, dur);
    pose(tl, id, "stand", t + dur, 0.25);
  }
  function idle(tl, id, t, dur) {
    for (let tt = t; tt < t + dur - 0.6; tt += 1.2) {
      tl.to(figs[id].st, { torso: "+=2", duration: 0.6, ease: "sine.inOut", onUpdate: () => draw(id) }, tt);
      tl.to(figs[id].st, { torso: "-=2", duration: 0.6, ease: "sine.inOut", onUpdate: () => draw(id) }, tt + 0.6);
    }
  }
  function drawAll() { Object.keys(figs).forEach(draw); }
  function skyline({ fire = true, night = true, seed = 3, horizon = 1250 } = {}) {
    let rnd = seed; const r = () => ((rnd = (rnd * 9301 + 49297) % 233280) / 233280);
    const sky = night
      ? `<linearGradient id="sky${seed}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1a1530"/><stop offset=".55" stop-color="#3b2340"/><stop offset="1" stop-color="${fire ? "#c2502a" : "#2a2440"}"/></linearGradient>`
      : `<linearGradient id="sky${seed}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6d8fb8"/><stop offset="1" stop-color="#e8b27a"/></linearGradient>`;
    let b = "";
    for (let x = -40; x < 1120; ) {
      const w = 90 + r() * 120, h = 300 + r() * 650, top = horizon - h;
      b += `<rect x="${x}" y="${top}" width="${w}" height="${h + 700}" fill="#151321"/>`;
      for (let wy = top + 30; wy < horizon - 20; wy += 42) for (let wx = x + 14; wx < x + w - 20; wx += 30)
        if (r() > 0.55) b += `<rect x="${wx}" y="${wy}" width="14" height="20" fill="${r() > 0.85 ? "#ffcf6a" : "#3a3550"}"/>`;
      x += w + 8 + r() * 20;
    }
    let smoke = "";
    if (fire) for (let i = 0; i < 5; i++) smoke += `<ellipse cx="${100 + r() * 880}" cy="${horizon - 500 - r() * 400}" rx="${160 + r() * 140}" ry="${90 + r() * 60}" fill="#2b2230" opacity=".55"/>`;
    return `<svg viewBox="0 0 1080 1920" width="1080" height="1920" xmlns="${NS}"><defs>${sky}</defs><rect width="1080" height="1920" fill="url(#sky${seed})"/>${smoke}${b}<rect y="${horizon}" width="1080" height="${1920 - horizon}" fill="#0e0d16"/></svg>`;
  }
  function room({ wall = "#4a3a46", floor = "#3a2a24", window = true, door = false, night = true, lamp = false } = {}) {
    const win = window ? `<g><rect x="190" y="420" width="700" height="560" fill="#0d0c14"/><foreignObject x="200" y="430" width="680" height="540"><div xmlns="http://www.w3.org/1999/xhtml" style="width:680px;height:540px;overflow:hidden"><div style="transform:scale(.63);transform-origin:0 0">${skyline({ fire: true, night, seed: 7, horizon: 1500 })}</div></div></foreignObject><rect x="190" y="420" width="700" height="560" fill="none" stroke="#2a2026" stroke-width="22"/><line x1="540" y1="420" x2="540" y2="980" stroke="#2a2026" stroke-width="14"/></g>` : "";
    const dr = door ? `<g><rect x="760" y="760" width="230" height="560" fill="#5a2e22" stroke="#2a1812" stroke-width="10"/><circle cx="790" cy="1060" r="12" fill="#d9b25a"/></g>` : "";
    const lmp = lamp ? `<g><line x1="140" y1="1320" x2="140" y2="980" stroke="#222" stroke-width="10"/><path d="M80 980 L200 980 L170 900 L110 900Z" fill="#d6b77a"/></g>` : "";
    return `<svg viewBox="0 0 1080 1920" width="1080" height="1920" xmlns="${NS}"><rect width="1080" height="1920" fill="${wall}"/>${win}${dr}${lmp}<rect y="1320" width="1080" height="600" fill="${floor}"/><rect y="1320" width="1080" height="14" fill="#00000055"/></svg>`;
  }
  function hallway({ red = false } = {}) {
    const glow = red ? "#ff2a2a" : "#e9e2c8";
    return `<svg viewBox="0 0 1080 1920" width="1080" height="1920" xmlns="${NS}"><rect width="1080" height="1920" fill="#101418"/><polygon points="0,300 420,820 420,1180 0,1920" fill="#1d3a36"/><polygon points="1080,300 660,820 660,1180 1080,1920" fill="#1a3330"/><polygon points="0,300 1080,300 660,820 420,820" fill="#141a1c"/><polygon points="0,1920 1080,1920 660,1180 420,1180" fill="#3a1414"/><rect x="420" y="820" width="240" height="360" fill="#0a0c0e"/><rect x="505" y="900" width="70" height="110" fill="${glow}" opacity=".9"/><rect x="120" y="760" width="150" height="520" fill="#2a1a12" transform="skewY(18)"/></svg>`;
  }
  function phoneAlert({ title = "EMERGENCY ALERT", sub = "EXTREME THREAT", body = "SHELTER IN PLACE.", body2 = "", foot = "Further instructions will follow." } = {}) {
    return `<div class="phone"><div class="ph-screen"><div class="ph-tri">!</div><div class="ph-t">${title}</div><div class="ph-s">${sub}</div><div class="ph-b">${body}</div><div class="ph-b2">${body2}</div><div class="ph-f">${foot}</div><div class="ph-ok">OK</div></div></div>`;
  }
  return { stick, pose, set, move, walk, idle, draw, drawAll, skyline, room, hallway, phoneAlert, POSES, figs };
})();
