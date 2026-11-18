#!/usr/bin/env python3
"""One-shot Reel builder: story.json -> voice, captions, scenes, sound -> final MP4.
Usage: python3 build.py story.json [--draft] [--only-audio]"""
import json, os, re, shutil, subprocess, sys, html
import numpy as np, soundfile as sf

ROOT = os.path.dirname(os.path.abspath(__file__))
REELS = os.path.dirname(ROOT)
SR = 24000

def sh(cmd, **kw):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(f"FAILED: {cmd}\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return r.stdout

def clean(t):
    return re.sub(r"[*_]", "", t)

def emph(text):
    em, warn = set(), set()
    for m in re.findall(r"\*([^*]+)\*", text): em |= {w.lower() for w in re.findall(r"[\w']+", m)}
    for m in re.findall(r"_([^_]+)_", text): warn |= {w.lower() for w in re.findall(r"[\w']+", m)}
    return em, warn

def eleven_tts(story):
    """ElevenLabs voice if ELEVENLABS_API_KEY is set (pasted per chat, never saved). Returns clips or None."""
    import urllib.request, urllib.error
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key or story.get("tts") == "kokoro": return None
    H = {"xi-api-key": key, "Content-Type": "application/json"}
    try:
        want = story.get("el_voice", "Brian")
        vid = want
        if len(want) != 20:
            req = urllib.request.Request("https://api.elevenlabs.io/v1/voices", headers=H)
            voices = json.load(urllib.request.urlopen(req, timeout=30))["voices"]
            match = [v for v in voices if want.lower() in v["name"].lower()] or voices
            vid = match[0]["voice_id"]; print("  ElevenLabs voice:", match[0]["name"])
        clips = []
        for sc in story["scenes"]:
            if not sc.get("text"):
                clips.append(np.zeros(int(SR * sc.get("dur", 1.5)), dtype=np.float32)); continue
            body = json.dumps({"text": clean(sc["text"]), "model_id": story.get("el_model", "eleven_multilingual_v2"),
                               "voice_settings": {"stability": story.get("el_stability", 0.45), "similarity_boost": 0.8,
                                                  "style": story.get("el_style", 0.35), "speed": story.get("speed", 1.0)}}).encode()
            req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}?output_format=pcm_24000", data=body, headers=H)
            a = np.frombuffer(urllib.request.urlopen(req, timeout=120).read(), dtype=np.int16).astype(np.float32) / 32768
            idx = np.where(np.abs(a) > 0.01)[0]
            if len(idx): a = a[max(0, idx[0] - 600): idx[-1] + 1200]
            clips.append(a)
        return clips
    except urllib.error.HTTPError as e:
        print("  ElevenLabs failed, using Kokoro:", e.code, e.read()[:200].decode(errors="ignore"))
    except Exception as e:
        print("  ElevenLabs failed, using Kokoro:", str(e)[:200])
    return None

def tts(story, out_dir):
    el = eleven_tts(story)
    if el is not None: return el
    from kokoro_onnx import Kokoro
    k = Kokoro(f"{REELS}/models/kokoro-v1.0.onnx", f"{REELS}/models/voices-v1.0.bin")
    voice, speed = story.get("voice", "am_onyx"), story.get("speed", 1.05)
    clips = []
    for i, sc in enumerate(story["scenes"]):
        if not sc.get("text"):
            clips.append(np.zeros(int(SR * sc.get("dur", 1.5)), dtype=np.float32)); continue
        a, sr = k.create(clean(sc["text"]), voice=sc.get("voice", voice), speed=sc.get("speed", speed), lang="en-us")
        assert sr == SR
        idx = np.where(np.abs(a) > 0.01)[0]
        if len(idx): a = a[max(0, idx[0] - 600): idx[-1] + 1200]
        clips.append(a.astype(np.float32))
    return clips

def words_for(clips, out_dir):
    from faster_whisper import WhisperModel
    import soxr
    m = WhisperModel("base.en", device="cpu", compute_type="int8")
    res = []
    for a in clips:
        if len(a) < SR * 0.3 or np.abs(a).max() < 0.01: res.append([]); continue
        a16 = soxr.resample(a, SR, 16000).astype(np.float32)
        segs, _ = m.transcribe(a16, word_timestamps=True, beam_size=5)
        ws = []
        for s in segs:
            for w in s.words:
                tok = w.word.strip()
                if ws and re.match(r"^[,.]\d", tok):  # "35" ",000" -> "35,000"
                    ws[-1] = (ws[-1][0] + tok, ws[-1][1], w.end)
                else:
                    ws.append((tok, w.start, w.end))
        res.append(ws)
    return res

def align_script(story, words):
    out = []
    for sc, ws in zip(story["scenes"], words):
        toks = clean(sc.get("text", "")).split()
        if toks and len(toks) == len(ws):
            ws = [(tok, s, e) for tok, (_, s, e) in zip(toks, ws)]
        out.append(ws)
    return out

def chunk_words(words, maxw=3):
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= maxw or re.search(r"[.,!?;:]$", w[0]) or (len(cur) == 2 and len("".join(x[0] for x in cur)) > 13):
            chunks.append(cur); cur = []
    if cur: chunks.append(cur)
    return chunks

def synth_music(kind, dur, path):
    t = np.arange(int(48000 * dur)) / 48000
    rng = np.random.default_rng(7)
    if kind == "none":
        sig = np.zeros_like(t)
    else:
        base = 55.0 if kind == "drone" else 41.2
        sig = 0.30 * np.sin(2 * np.pi * base * t) + 0.18 * np.sin(2 * np.pi * base * 1.5 * t + 0.4 * np.sin(2 * np.pi * 0.07 * t))
        sig += 0.10 * np.sin(2 * np.pi * base * 2.02 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * t))
        noise = rng.standard_normal(len(t)); b = np.cumsum(noise); b -= np.convolve(b, np.ones(4800) / 4800, "same")
        sig += 0.02 * b / (np.abs(b).max() + 1e-9)
        if kind == "pulse":
            env = np.zeros_like(t)
            for beat in np.arange(0.5, dur, 0.9):
                for off in (0, 0.22):
                    i0 = int((beat + off) * 48000); n = int(0.18 * 48000)
                    if i0 + n < len(t): env[i0:i0 + n] += np.exp(-np.linspace(0, 6, n)) * (1 if off == 0 else .6)
            sig += 0.9 * env * np.sin(2 * np.pi * 48 * t)
        fade = np.minimum(1, np.minimum(t / 2.0, (dur - t) / 1.0))
        sig *= fade
    sf.write(path, (sig / (np.abs(sig).max() + 1e-9) * 0.5).astype(np.float32), 48000)

def alarm(path, dur=2.4):
    t = np.arange(int(48000 * dur)) / 48000
    f = np.where((t * 2.5).astype(int) % 2 == 0, 740.0, 990.0)
    s = 0.5 * np.sign(np.sin(2 * np.pi * np.cumsum(f) / 48000)) * 0.4 + 0.3 * np.sin(2 * np.pi * np.cumsum(f) / 48000)
    s *= np.minimum(1, (dur - t) * 4)
    sf.write(path, s.astype(np.float32), 48000)

def build(story_path, draft=False, only_audio=False):
    story = json.load(open(story_path))
    name = story.get("slug") or os.path.splitext(os.path.basename(story_path))[0]
    proj = f"{REELS}/out/{name}"
    os.makedirs(f"{proj}/assets", exist_ok=True)
    gap = story.get("gap", 0.12)

    print("1/5 voice"); clips = tts(story, proj)
    print("2/5 word timing"); words = align_script(story, words_for(clips, proj))

    t, scenes = 0.0, []
    vo = []
    for sc, a, ws in zip(story["scenes"], clips, words):
        lead = sc.get("lead", 0.15)
        d = lead + len(a) / SR + sc.get("hold", gap)
        d = max(d, sc.get("min", 0))
        scenes.append(dict(sc, start=round(t, 3), dur=round(d, 3), words=[(w, round(t + lead + s, 3), round(t + lead + e, 3)) for w, s, e in ws]))
        vo.append((t + lead, a))
        t += d
    total = round(t, 3)

    print("3/5 sound")
    vo_track = np.zeros(int(SR * (total + 1)), dtype=np.float32)
    for st, a in vo:
        i = int(st * SR); vo_track[i:i + len(a)] += a
    sf.write(f"{proj}/vo.wav", vo_track, SR)
    synth_music(story.get("music", "drone"), total + 1, f"{proj}/music.wav")
    alarm(f"{REELS}/sfx/alarm.wav")
    inputs, filt, n = [f"-i {proj}/vo.wav", f"-i {proj}/music.wav"], [], 2
    filt.append(f"[1]volume={story.get('music_vol', 0.22)}[m]")
    mixes = ["[0]", "[m]"]
    for sc in scenes:
        for fx in sc.get("sfx", []):
            p = f"{REELS}/sfx/{fx['id']}.wav"
            if not os.path.exists(p): print("  missing sfx", fx["id"]); continue
            at = sc["start"] + fx.get("at", 0)
            inputs.append(f"-i {p}")
            filt.append(f"[{n}]adelay={int(at*1000)}|{int(at*1000)},volume={fx.get('vol', 0.6)}[f{n}]")
            mixes.append(f"[f{n}]"); n += 1
    filt.append(f"{''.join(mixes)}amix=inputs={len(mixes)}:normalize=0,atrim=0:{total},loudnorm=I=-14:TP=-1.5:LRA=11[out]")
    sh(f"ffmpeg -y -v error {' '.join(inputs)} -filter_complex \"{';'.join(filt)}\" -map [out] -ar 48000 {proj}/mix.wav")
    if only_audio: return

    print("4/5 scenes")
    for src, dst in [("node_modules/@fontsource/anton/files/anton-latin-400-normal.woff2", "anton.woff2"),
                     ("node_modules/@fontsource/lilita-one/files/lilita-one-latin-400-normal.woff2", "lilita.woff2"),
                     ("node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-700-normal.woff2", "mono.woff2"),
                     ("node_modules/gsap/dist/gsap.min.js", "gsap.min.js")]:
        shutil.copy(f"{REELS}/{src}", f"{proj}/assets/{dst}")
    shutil.copy(f"{ROOT}/lib.js", f"{proj}/assets/lib.js")
    shutil.copy(f"{ROOT}/style.css", f"{proj}/assets/style.css")
    if story.get("css"): open(f"{proj}/assets/extra.css", "w").write(story["css"])
    three = story.get("three")
    if three:
        if not os.path.exists(f"{proj}/assets/three"):
            shutil.copytree(f"{REELS}/node_modules/three/build", f"{proj}/assets/three/build")
            for sub in ("loaders", "utils", "postprocessing", "shaders", "libs"):
                shutil.copytree(f"{REELS}/node_modules/three/examples/jsm/{sub}", f"{proj}/assets/three/jsm/{sub}", dirs_exist_ok=True)
        shutil.copy(f"{ROOT}/threekit.js", f"{proj}/assets/threekit.js")
        for a in three.get("assets", []):
            shutil.copy(f"{REELS}/assets3d/{a}", f"{proj}/assets/{a}")

    body, js, builds = [], [], []
    hud = story.get("hud", {})
    for i, sc in enumerate(scenes):
        S, D = sc["start"], sc["dur"]
        attrs = f'data-start="{S}" data-duration="{D}" data-track-index="0"'
        body.append(f'<div class="clip scene" id="s{i}" {attrs}><div class="cam" id="cam{i}">{sc.get("html","")}</div>'
                     f'{"" if sc.get("vignette") is False else "<div class=vig></div>"}</div>')
        if sc.get("hud", not sc.get("ask")) and hud:
            tm = sc.get("time", hud.get("time", ""))
            tm_html = re.sub(r"\s*(AM|PM)$", r"<small>\1</small>", tm)
            body.append(f'<div class="clip hud" {attrs.replace("track-index=\"0\"","track-index=\"1\"")} style="inset:auto;left:34px;top:120px"><div class="day">{hud.get("day","")}</div><div class="time">{tm_html}</div><div class="fl">{hud.get("place","")}</div></div>')
        if sc.get("banner"):
            tag, big = (sc["banner"].split("|", 1) + [""])[:2] if "|" in sc["banner"] else ("", sc["banner"])
            body.append(f'<div class="clip banner" id="b{i}" data-start="{S}" data-duration="{D}" data-track-index="2" style="inset:auto;left:0;right:0;top:300px">'
                        f'{f"<div class=tag>{html.escape(tag)}</div>" if tag else ""}<div class="big">{html.escape(big)}</div></div>')
            js.append(f'tl.from("#b{i} .tag",{{scale:2.2,opacity:0,duration:.25,ease:"back.out(2)"}},{S});'
                      f'tl.from("#b{i} .big",{{y:40,opacity:0,duration:.3,ease:"power3.out"}},{S+0.12});')
        if sc.get("who"):
            body.append(f'<div class="clip who" data-start="{S}" data-duration="{D}" data-track-index="3" style="inset:auto;left:0;right:0;top:{sc.get("cap_y", story.get("cap_y", 1100)) - 80}px"><span>{html.escape(sc["who"])}</span></div>')
        if sc.get("build"):
            builds.append(f'document.getElementById("cam{i}").innerHTML += (()=>{{{sc["build"]}}})();')
        cam = sc.get("cam", {"from": 1.0, "to": 1.08})
        if cam:
            js.append(f'tl.fromTo("#cam{i}",{{scale:{cam.get("from",1)},x:{cam.get("x0",0)},y:{cam.get("y0",0)}}},{{scale:{cam.get("to",1.08)},x:{cam.get("x1",0)},y:{cam.get("y1",0)},duration:{D},ease:"none"}},{S});')
        if sc.get("shake"):
            for k in range(6):
                js.append(f'tl.to("#cam{i}",{{x:"+={(-1)**k*14}",y:"+={(-1)**(k+1)*8}",duration:.05}},{S + sc["shake"] + k*0.05});')
        if sc.get("anim"):
            js.append(f"((S,D)=>{{{sc['anim']}}})({S},{D});")
        if sc.get("flash"):
            body.append(f'<div class="clip" id="fl{i}" data-start="{S}" data-duration="0.4" data-track-index="4" style="background:#fff"></div>')
            js.append(f'tl.fromTo("#fl{i}",{{opacity:.9}},{{opacity:0,duration:.35}},{S});')
        if sc.get("captions", not sc.get("ask")) and sc["words"]:
            em, warn = emph(sc.get("text", ""))
            chs = chunk_words(sc["words"], story.get("cap_words", 3))
            for j, ch in enumerate(chs):
                cs = ch[0][1] - 0.04
                ce = chs[j + 1][0][1] - 0.04 if j + 1 < len(chs) else min(S + D, ch[-1][2] + 0.35)
                parts = []
                for w, _, _ in ch:
                    key = re.sub(r"[^\w']", "", w).lower()
                    cls = "em" if key in em else "warn" if key in warn else ""
                    parts.append(f'<span class="{cls}">{html.escape(re.sub(r"[.,;:]$", "", w))}</span>')
                cid = f"c{i}_{j}"
                body.append(f'<div class="clip cap" id="{cid}" data-start="{cs:.3f}" data-duration="{max(0.1, ce-cs):.3f}" data-track-index="5" style="inset:auto;left:60px;right:60px;top:{sc.get("cap_y", story.get("cap_y", 1100))}px">{" ".join(parts)}</div>')
                js.append(f'tl.fromTo("#{cid}",{{scale:.6,opacity:0}},{{scale:1,opacity:1,duration:.12,ease:"back.out(3)"}},{cs:.3f});')

    if story.get("title"):
        tdur = story.get("title_dur", total)
        body.append(f'<div class="clip qtitle" id="qt" data-start="0" data-duration="{tdur}" data-track-index="6" style="inset:auto;left:50px;right:50px;top:230px">{html.escape(story["title"])}</div>')
        js.append('tl.from("#qt",{y:-30,opacity:0,duration:.3,ease:"power3.out"},0);')
    ctr = story.get("counter")
    if ctr:
        cend = max((sc["start"] + sc["dur"] for sc in scenes if "count" in sc), default=total)
        body.append(f'<div class="clip counter" id="ctr" data-start="0" data-duration="{cend}" data-track-index="7" style="inset:auto;right:44px;top:{ctr.get("y",430)}px"><div class="lbl">{html.escape(ctr.get("label",""))}</div><div class="val" id="ctrv"></div><div class="unit">{html.escape(ctr.get("unit",""))}</div></div>')
        dec = ctr.get("decimals", 0)
        js.append(f'const CV={{v:{ctr.get("start",0)}}}; const CF=()=>document.getElementById("ctrv").textContent=CV.v.toLocaleString("en-US",{{minimumFractionDigits:{dec},maximumFractionDigits:{dec}}}); tl.set(CV,{{onUpdate:CF,onComplete:CF}},0); CF();')
        for sc in scenes:
            if "count" in sc:
                land = (sc["words"][-1][1] - sc["start"]) if sc["words"] else sc["dur"] * 0.6
                js.append(f'tl.to(CV,{{v:{sc["count"]},duration:{max(0.4, land):.2f},ease:"{ctr.get("ease","power2.out")}",onUpdate:CF}},{sc["start"]});')
    for i, sc in enumerate(scenes):
        if sc.get("ask"):
            a = sc["ask"]
            body.append(f'<div class="clip ask" id="ask{i}" data-start="{sc["start"]}" data-duration="{sc["dur"]}" data-track-index="8"><div class="q">{html.escape(a["q"])}</div><div class="opts"><div class="o a">{html.escape(a["a"])}</div><div class="o b">{html.escape(a["b"])}</div></div><div class="c">{html.escape(a.get("cta","COMMENT YOUR ANSWER"))}</div></div>')
            js.append(f'tl.from("#ask{i} .q",{{scale:1.3,opacity:0,duration:.3,ease:"back.out(2)"}},{sc["start"]});tl.from("#ask{i} .o",{{y:60,opacity:0,stagger:.12,duration:.3,ease:"back.out(2)"}},{sc["start"]+0.3});')
    if story.get("require_question", True) and not scenes[-1].get("ask"):
        sys.exit("STORY ERROR: last scene must have an \"ask\" (viewer question with two choices).")

    three_head, three_js = "", ""
    if three:
        until = three.get("until") or total
        body.insert(0, f'<div class="clip" id="three-wrap" data-start="0" data-duration="{until}" data-track-index="0"><canvas id="three" width="1080" height="1920" style="width:1080px;height:1920px;display:block"></canvas></div>')
        ckeys = []
        for sc in scenes:
            if "count" in sc:
                land = (sc["words"][-1][1] - sc["start"]) if sc["words"] else sc["dur"] * 0.6
                ckeys.append([sc["start"], round(max(0.4, land), 2), sc["count"]])
        three_head = '<script type="importmap">{"imports":{"three":"./assets/three/build/three.module.js","three/addons/":"./assets/three/jsm/"}}</script>'
        three_js = f"""<script type="module">
import * as THREE from "three"; import * as K from "./assets/threekit.js";
window.COUNT_KEYS = {json.dumps(ckeys)}; window.COUNT_START = {json.dumps((story.get("counter") or {}).get("start", 0))};
window.SCENES = {json.dumps([[sc["start"], sc["dur"]] for sc in scenes])};
const canvas = document.getElementById("three");
async function userSetup() {{
{three["code"]}
}}
window.__hf = window.__hf || {{}}; window.__hf.buildReady = window.__hf.buildReady || {{}};
let renderAt = null;
window.__hf.buildReady.three = (async () => {{ renderAt = await userSetup(); renderAt(0); }})();
window.addEventListener("hf-seek", (e) => {{ if (renderAt) renderAt(e.detail.time); }});
</script>"""

    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=1080, height=1920">
<link rel="stylesheet" href="assets/style.css">{'<link rel="stylesheet" href="assets/extra.css">' if story.get("css") else ""}
{three_head}<script src="assets/gsap.min.js"></script><script src="assets/lib.js"></script></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1080" data-height="1920" data-fps="30">
{chr(10).join(body)}
</div>
<script>
{chr(10).join(builds)}
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(js)}
tl.set({{}}, {{}}, {total});
window.__timelines["main"] = tl;
R.drawAll(); tl.seek(0);
</script>{three_js}</body></html>"""
    open(f"{proj}/index.html", "w").write(page)
    if not os.path.exists(f"{proj}/hyperframes.json"):
        for f in ("hyperframes.json", "meta.json", "package.json"):
            shutil.copy(f"{REELS}/hf/demo/{f}", f"{proj}/{f}")

    if "--no-render" in sys.argv: print("HTML ready", proj); return
    print(f"5/5 render ({total:.1f}s)")
    q = "draft" if draft else "delivery"
    sh(f"cd {proj} && npx --prefix {REELS}/hf hyperframes render . -o {proj}/video.mp4 -q {q} --quiet", timeout=1800)
    final = f"{REELS}/out/{name}.mp4"
    sh(f"ffmpeg -y -v error -i {proj}/video.mp4 -i {proj}/mix.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -shortest {final}")
    print("DONE", final)
    return final

if __name__ == "__main__":
    build(sys.argv[1], draft="--draft" in sys.argv, only_audio="--only-audio" in sys.argv)
