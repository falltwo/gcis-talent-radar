"""OpenRouter-backed second-pass fair-hiring policy classifier."""
import json
import os
import time
from pathlib import Path
from typing import Any, Dict

import requests

DEFAULT_MODEL = "openai/gpt-oss-safeguard-20b"
POLICY_PATH = Path(__file__).resolve().parent / "policies" / "fair_hiring_zh.md"
MAX_OUTPUT_TOKENS = 384
TIMEOUT = 5
ALLOWED_CATEGORIES = {
    "種族", "階級", "語言", "思想", "宗教", "黨派", "籍貫", "出生地",
    "性別", "性傾向", "年齡", "婚姻", "容貌", "五官", "身心障礙",
    "星座", "血型", "工會會員", "懷孕", "生育", "育兒",
    "性別／性別認同", "種族／國籍／來源", "身心狀況／外貌",
    "照顧責任", "生理狀況",
    "race", "age", "gender", "marital status", "disability", "nationality",
    "religion", "sexual orientation", "none",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "violation": {"type": "boolean"},
        "category": {"type": "string", "maxLength": 80},
        "rationale": {"type": "string", "maxLength": 240},
    },
    "required": ["violation", "category", "rationale"],
    "additionalProperties": False,
}


def _result(
    *,
    called: bool,
    status: str,
    decision: str,
    category: str = "none",
    latency_ms: float = 0,
) -> Dict[str, Any]:
    """Return only fields suitable for API governance metadata and audit logs."""
    return {
        "called": called,
        "status": status,
        "decision": decision,
        "category": category[:80],
        "latency_ms": round(latency_ms, 1),
    }


def evaluate_fair_hiring(query: str) -> Dict[str, Any]:
    """Classify an eligible hiring request; all service/format errors fail open."""
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return _result(called=False, status="SKIPPED_NO_API_KEY", decision="SKIPPED")

    started = time.perf_counter()
    model = os.environ.get("GUARD_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": POLICY_PATH.read_text(encoding="utf-8")},
                {"role": "user", "content": query},
            ],
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "reasoning": {"effort": "low", "exclude": True},
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "fair_hiring_verdict", "strict": True, "schema": SCHEMA},
            },
            "provider": {"require_parameters": True},
        }
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=TIMEOUT,
        )
        elapsed = (time.perf_counter() - started) * 1000
        if not response.ok:
            return _result(called=True, status=f"HTTP_ERROR_{response.status_code}",
                           decision="FAIL_OPEN", latency_ms=elapsed)
        body = response.json()
        choices = body.get("choices") if isinstance(body, dict) else None
        message = choices[0].get("message") if isinstance(choices, list) and choices else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            return _result(called=True, status="INVALID_RESPONSE", decision="FAIL_OPEN", latency_ms=elapsed)
        verdict = json.loads(content)
        if (
            not isinstance(verdict, dict)
            or set(verdict) != {"violation", "category", "rationale"}
            or not isinstance(verdict.get("violation"), bool)
            or not isinstance(verdict.get("category"), str)
            or not isinstance(verdict.get("rationale"), str)
            or len(verdict["category"]) > 80
            or len(verdict["rationale"]) > 240
            or (verdict["violation"] and verdict["category"].strip() not in ALLOWED_CATEGORIES)
        ):
            return _result(called=True, status="INVALID_SCHEMA", decision="FAIL_OPEN", latency_ms=elapsed)
        violation = verdict["violation"]
        category = verdict["category"].strip() or "none"
        return _result(
            called=True,
            status="OK",
            decision="VIOLATION" if violation else "ALLOW",
            category=category if violation else "none",
            latency_ms=elapsed,
        )
    except requests.Timeout:
        return _result(called=True, status="TIMEOUT", decision="FAIL_OPEN",
                       latency_ms=(time.perf_counter() - started) * 1000)
    except requests.RequestException as exc:
        status = "NETWORK_ERROR" if not isinstance(exc, requests.HTTPError) else "HTTP_ERROR"
        return _result(called=True, status=status, decision="FAIL_OPEN",
                       latency_ms=(time.perf_counter() - started) * 1000)
    except (ValueError, TypeError, KeyError, IndexError, OSError):
        return _result(called=True, status="INVALID_RESPONSE", decision="FAIL_OPEN",
                       latency_ms=(time.perf_counter() - started) * 1000)
    except Exception:
        return _result(called=True, status="ERROR", decision="FAIL_OPEN",
                       latency_ms=(time.perf_counter() - started) * 1000)
