"""Claude API calls with prompt caching, budget guard and usage tracking."""
import base64
import json
import re

from . import common as C


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=C.secret("ANTHROPIC_API_KEY"), max_retries=4)


def month_key():
    return C.now().astimezone(C.tz()).strftime("%Y-%m")


def month_cost():
    return C.load("state/usage.json", {}).get(month_key(), {}).get("usd", 0.0)


def _record(usage, model, purpose):
    p = C.settings()["price_per_mtok"]
    cost = (usage.input_tokens * p["input"] + usage.output_tokens * p["output"]
            + (getattr(usage, "cache_read_input_tokens", 0) or 0) * p["cache_read"]
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * p["cache_write"]) / 1e6
    u = C.load("state/usage.json", {})
    m = u.setdefault(month_key(), {"usd": 0.0, "calls": 0, "output_tokens": 0, "by_purpose": {}})
    m["usd"] = round(m["usd"] + cost, 4)
    m["calls"] += 1
    m["output_tokens"] += usage.output_tokens
    m["by_purpose"][purpose] = round(m["by_purpose"].get(purpose, 0) + cost, 4)
    C.save("state/usage.json", u)
    C.log(f"  claude {purpose}: in={usage.input_tokens} out={usage.output_tokens} ${cost:.3f} (month ${m['usd']:.2f})")
    return cost


def check_budget():
    b = C.settings().get("monthly_budget_usd", 20)
    spent = month_cost()
    if spent >= b:
        raise C.PostError(f"monthly Claude budget reached (${spent:.2f} of ${b}). Raise it in Settings.")


def ask(system, messages, purpose, model=None, max_tokens=32000):
    """Send a request. `system` is a long cached string. Returns the text reply."""
    check_budget()
    model = model or C.settings()["model"]
    client = _client()
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=messages,
    ) as s:
        msg = s.get_final_message()
    _record(msg.usage, model, purpose)
    if msg.stop_reason == "max_tokens":
        raise ValueError("reply was cut off at max_tokens")
    return "".join(b.text for b in msg.content if b.type == "text")


def image_block(path):
    data = base64.standard_b64encode(open(path, "rb").read()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def extract_json(text):
    """Pull the first JSON object out of a reply (handles ```json fences and chatter)."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    if not raw:
        raise ValueError("no JSON object in reply")
    return json.loads(raw)
