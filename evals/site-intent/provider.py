"""promptfoo provider: runs the real engine.site_intent.parse, so the eval checks shipped code."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import server  # noqa: E402

server.load_local_env()
from engine import site_intent  # noqa: E402


def call_api(prompt, options, context):
    vars_ = context.get("vars", {})
    result = site_intent.parse(vars_.get("text", prompt), vars_.get("preference", ""))
    if result.get("source") != "llm":
        return {"error": f"model unavailable: {result.get('reason')}"}
    return {"output": json.dumps(result["intent"], ensure_ascii=False), "cost": result["usage"]["cost_usd"]}
