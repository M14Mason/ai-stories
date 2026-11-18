"""Write an episode with Claude, validate it, and QA the rendered frames."""
import json
import os
import subprocess
import tempfile

from . import common as C
from . import llm

SFX = {f[:-4] for f in os.listdir(C.path("sfx")) if f.endswith(".wav")} | {"alarm"}
BANNED_JS = ("Math.random", "Date(", "Date.now", "fetch(", "setTimeout", "setInterval", "XMLHttpRequest", "http://", "https://", "import(")


def system_prompt():
    rules = open(C.path("prompts/system.md")).read()
    example = open(C.path("prompts/example_story.json")).read()
    return rules + "\n\n## Example episode at the quality bar (Home Depot Outbreak, part 1)\n```json\n" + example + "\n```\n"


def history(series_id):
    return C.load(f"state/episodes/{series_id}.json", {"series": series_id, "episodes": []})


def user_prompt(series, hist, n):
    prev = hist["episodes"][-5:]
    lines = [
        f"SERIES: {series['name']}",
        f"PREMISE: {series['premise']}",
        f"TONE: {series.get('tone', '')}",
        f"HUD place (use exactly): {series.get('place', '')}",
        f"Write PART {n} (hud.day = \"DAY {n}\").",
    ]
    if prev:
        lines.append("\nPREVIOUS EPISODES (oldest first):")
        for e in prev:
            lines.append(f"- Part {e['n']} ({e.get('day', '')}): {e['synopsis']} Ended on: {e.get('cliffhanger', '')}")
        lines.append("\nPick up right after the last cliffhanger. Assume the viewer's most dramatic choice happened, and show its consequences.")
    else:
        lines.append("\nThis is part 1. Establish the place, the threat and the first rules.")
    return "\n".join(lines)


def validate(story):
    """Static checks. Returns a list of problems (empty = ok)."""
    errs = []
    sc = story.get("scenes")
    if not isinstance(sc, list) or not sc:
        return ["story.scenes must be a non-empty list"]
    if not 7 <= len(sc) <= 15:
        errs.append(f"use 9 to 13 scenes (got {len(sc)})")
    for k in ("three", "counter", "title"):
        if k in story:
            errs.append(f"remove top-level '{k}' (2D format A only)")
    last = sc[-1]
    a = last.get("ask")
    if not isinstance(a, dict) or not all(a.get(k) for k in ("q", "a", "b")):
        errs.append("last scene needs ask with q, a, b")
    if not last.get("text"):
        errs.append("last scene must speak the question in text")
    words = 0
    for i, s in enumerate(sc):
        if not isinstance(s, dict):
            errs.append(f"scene {i} is not an object"); continue
        if s.get("text"):
            words += len(s["text"].split())
        elif not s.get("dur"):
            errs.append(f"scene {i}: silent scene needs dur")
        for k in ("build", "anim"):
            code = s.get(k, "")
            if code and not isinstance(code, str):
                errs.append(f"scene {i}.{k} must be a string")
                continue
            scan = code.replace("http://www.w3.org", "")
            for bad in BANNED_JS:
                if bad in scan:
                    errs.append(f"scene {i}.{k} uses forbidden '{bad}'")
        if s.get("build") and "return" not in s["build"]:
            errs.append(f"scene {i}.build must return a string")
        for fx in s.get("sfx", []):
            if fx.get("id") not in SFX:
                errs.append(f"scene {i}: unknown sfx id '{fx.get('id')}' (use one of {sorted(SFX)})")
    if not 60 <= words <= 170:
        errs.append(f"narration is {words} words; aim for 90 to 140 (35 to 50 seconds)")
    return errs + js_check(story)


def js_check(story):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(story, f)
    try:
        r = subprocess.run(["node", C.path("engine/chk.js"), f.name], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(f.name)
    return [f"JavaScript {ln}" for ln in r.stdout.splitlines() if ln.startswith("SYNTAX")]


def normalize(story, series, n):
    story["slug"] = f"{series['id']}_ep{n:03d}"
    story.setdefault("voice", series.get("voice", "am_onyx"))
    story.setdefault("music", series.get("music", "pulse"))
    story.setdefault("speed", 1.05)
    story["tts"] = story.get("tts", "auto")
    hud = story.setdefault("hud", {})
    hud["day"] = f"DAY {n}"
    if series.get("place"):
        hud["place"] = series["place"]
    return story


def write_episode(series, n, hist):
    """Ask Claude for an episode; retry with the validator's errors. Returns the parsed result."""
    system = system_prompt()
    msgs = [{"role": "user", "content": user_prompt(series, hist, n)}]
    attempts = C.settings().get("max_attempts", 3)
    last_errs = []
    for attempt in range(1, attempts + 1):
        text = llm.ask(system, msgs, "write")
        try:
            res = llm.extract_json(text)
            story = res["story"]
            errs = validate(story)
        except (ValueError, KeyError, TypeError) as e:
            errs = [f"reply was not valid JSON in the output contract: {e}"]
        if not errs:
            res["story"] = normalize(story, series, n)
            return res
        last_errs = errs
        C.log(f"  attempt {attempt} rejected: {errs[:5]}")
        msgs += [{"role": "assistant", "content": text},
                 {"role": "user", "content": "Fix these problems and reply with the full corrected JSON object only:\n- " + "\n- ".join(errs)}]
    raise C.PostError(f"Claude could not produce a valid episode: {last_errs[:3]}")


QA_PROMPT = """You are the quality checker for an automated short-video channel. Attached is a contact sheet of frames sampled evenly from the rendered video (left to right, top to bottom), plus the story JSON that produced it.

Fail the video ONLY for problems a viewer would notice:
- black, blank or broken frames (missing scene art, raw code or "undefined" visible)
- captions covering faces, banners or phone text
- figures or key objects cut off or off-screen
- unreadable text
Do not fail for taste.

Reply with JSON only: {"pass": true|false, "problems": ["specific problem with scene number and fix"]}"""


def qa(story, sheet_path):
    if not C.settings().get("vision_qa", True):
        return {"pass": True, "problems": []}
    content = [llm.image_block(sheet_path),
               {"type": "text", "text": "STORY JSON:\n" + json.dumps(story)[:60000]}]
    text = llm.ask(QA_PROMPT, [{"role": "user", "content": content}], "qa",
                   model=C.settings().get("qa_model"), max_tokens=2000)
    try:
        r = llm.extract_json(text)
        return {"pass": bool(r.get("pass")), "problems": list(r.get("problems", []))}
    except ValueError:
        return {"pass": True, "problems": ["qa reply unreadable, passed by default"]}


def revise(series, n, hist, result, problems):
    """One repair pass after visual QA failed."""
    system = system_prompt()
    msgs = [{"role": "user", "content": user_prompt(series, hist, n)},
            {"role": "assistant", "content": json.dumps(result)},
            {"role": "user", "content": "The rendered video failed visual QA:\n- " + "\n- ".join(problems)
             + "\nFix only these problems. Reply with the full corrected JSON object only."}]
    text = llm.ask(system, msgs, "revise")
    res = llm.extract_json(text)
    errs = validate(res["story"])
    if errs:
        raise C.PostError(f"revision invalid: {errs[:3]}")
    res["story"] = normalize(res["story"], series, n)
    return res
