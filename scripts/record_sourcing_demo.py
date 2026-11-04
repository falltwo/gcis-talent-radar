"""錄一次找人流程，給 docs/demo/sourcing-replay.html 回放。

用法：python scripts/record_sourcing_demo.py "找會 Python 的後端工程師，在台中" --sites github --max 3

輸出到 docs/demo/recording/（已列在 .gitignore）：截圖存成 jpg，事件存成 events.js。
截圖是真實的公開個人頁，含真人姓名與大頭照，不要 commit 或公開散布。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sourcing import service  # noqa: E402

OUT = ROOT / "docs" / "demo" / "recording"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--sites", default="", help="以逗號分隔的網站 id，例如 github")
    ap.add_argument("--max", type=int, default=3)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.jpg"):
        old.unlink()
    prep = service.prepare(args.query, max_candidates=args.max,
                           site_ids=[s for s in args.sites.split(",") if s] or None)
    events, started = [], time.perf_counter()
    for event in service.stream(prep):
        event["t"] = round(time.perf_counter() - started, 2)
        shot = event.get("screenshot")
        if shot:
            name = f"{event['n']:02d}-{event['site']}-{event['action']}.jpg"
            (OUT / name).write_bytes(base64.b64decode(shot.split(",", 1)[1]))
            event["screenshot"] = f"recording/{name}"
        events.append(event)
        print(f"[{event['t']:5.1f}s] {event['type']:<12} {event.get('detail') or event.get('reason') or ''}")
    payload = {"query": args.query, "recorded_at": time.strftime("%Y-%m-%d %H:%M"), "events": events}
    (OUT / "events.js").write_text("window.SOURCING_RECORDING = " + json.dumps(payload, ensure_ascii=False, indent=1) + ";\n",
                                   encoding="utf-8")
    print(f"wrote {OUT / 'events.js'} ({len(events)} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
