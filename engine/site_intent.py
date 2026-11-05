"""選址需求文字解析：gpt-6-luna 從 HR 打的需求讀出產業、要加重或不考慮的條件、職務與相關科系。

前端（ui/static/site-scan.js）送來可選的產業、條件與科系清單，模型只能從清單裡選；不在清單裡的答案丟掉。
沒有金鑰、模型失敗或回應格式不對時回 available=False，前端改用原本的關鍵字規則，流程不中斷。
職務名稱經過個人特徵過濾（年齡、性別等），不會帶到刊登召募或獵頭。
"""
from typing import Any, Optional

from sourcing import llm
from sourcing.planner import PERSONAL_TRAIT

SYSTEM = (
    "你把企業的擴廠選址需求轉成條件，給選址排名與招募功能使用。只回 JSON。\n"
    "industry：從產業清單選最符合的一個，看不出來給 null。\n"
    "boost：需求明確重視的條件 id（例如寫到上下游、聚落就是同業群聚）；沒提到的不要放。\n"
    "avoid：需求明確說不需要、不在意的條件 id（例如「不需要靠近交流道」就是 avoid 交通便利）；沒說的不要放。\n"
    "注意條件名稱本身的方向：「避開競爭」這個條件是指少跟別人搶人，所以「不想搶人」「避開競爭」要放 boost，不是 avoid。\n"
    "role：要招的現場職務，例如 CNC 技術員、焊接技術員、作業員，沒寫給 null。\n"
    "senior：要招的主管或工程師職務，例如廠長、機械工程師，沒寫給 null。\n"
    "department：校園徵才要找的相關科系，從科系清單選一個，看不出來給 null。\n"
    "職務只寫職稱，不可包含年齡、性別、國籍、婚育、宗教等個人特徵。"
)


def _clean_title(value: Any) -> Optional[str]:
    text = " ".join(str(value or "").split())
    if not text or len(text) > 20 or PERSONAL_TRAIT.search(text):
        return None
    return text


def parse_intent(text: str, preference: str, industries: list[str], criteria: list[dict],
                 departments: list[str]) -> dict:
    ids = [c["id"] for c in criteria]
    if not text.strip() or not llm.has_key() or not ids:
        return {"available": False, "reason": "沒有需求文字或未設定 OPENROUTER_API_KEY"}
    schema = {
        "type": "object",
        "properties": {
            "industry": {"type": ["string", "null"], "enum": industries + [None]},
            "boost": {"type": "array", "items": {"type": "string", "enum": ids}},
            "avoid": {"type": "array", "items": {"type": "string", "enum": ids}},
            "role": {"type": ["string", "null"]},
            "senior": {"type": ["string", "null"]},
            "department": {"type": ["string", "null"], "enum": departments + [None]},
        },
        "required": ["industry", "boost", "avoid", "role", "senior", "department"],
        "additionalProperties": False,
    }
    listing = "\n".join(f"- {c['id']}：{c.get('label', '')}（{c.get('hint', '')}）" for c in criteria)
    user = (f"需求：{text}\n偏好按鈕：{preference or '無'}\n條件清單：\n{listing}\n"
            f"產業清單：{'、'.join(industries)}\n科系清單：{'、'.join(departments)}")
    out = llm.chat_json(SYSTEM, user, "site_intent", schema, max_tokens=200)
    if not isinstance(out, dict):
        return {"available": False, "reason": "模型暫時無法使用"}
    avoid = [i for i in dict.fromkeys(out.get("avoid") or []) if i in ids]
    return {
        "available": True,
        "source": "llm",
        "industry": out.get("industry") if out.get("industry") in industries else None,
        "boost": [i for i in dict.fromkeys(out.get("boost") or []) if i in ids and i not in avoid],
        "avoid": avoid,
        "role": _clean_title(out.get("role")),
        "senior": _clean_title(out.get("senior")),
        "department": out.get("department") if out.get("department") in departments else None,
    }
