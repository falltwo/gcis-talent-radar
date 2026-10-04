"""
ETL 共用工具
- http：GCIS 憑證相容的 session、禮貌延遲
- 原始檔：存檔並寫入 data/raw/_manifest.csv（網址、抓取時間、大小、SHA-256），讓每個數字都能追到下載的那一份檔案
- 個資：刪除代表人、負責人、電話等欄位
- 產出：寫 data/processed/*.csv，並更新 data/processed/_catalog.json（來源、粒度、欄位、列數）
"""
import csv
import datetime as dt
import hashlib
import io
import json
import re
import ssl
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from config import DATA_DIR, PROCESSED_DATA_DIR, RAW_DATA_DIR  # noqa: E402

MANIFEST = RAW_DATA_DIR / "_manifest.csv"
CATALOG = PROCESSED_DATA_DIR / "_catalog.json"
USER_AGENT = "Mozilla/5.0 (research; gcis-talent-radar ETL)"

TAICHUNG = "臺中市"
TAICHUNG_ZIP = {
    "400": "中區", "401": "東區", "402": "南區", "403": "西區", "404": "北區", "406": "北屯區",
    "407": "西屯區", "408": "南屯區", "411": "太平區", "412": "大里區", "413": "霧峰區", "414": "烏日區",
    "420": "豐原區", "421": "后里區", "422": "石岡區", "423": "東勢區", "424": "和平區", "426": "新社區",
    "427": "潭子區", "428": "大雅區", "429": "神岡區", "432": "大肚區", "433": "沙鹿區", "434": "龍井區",
    "435": "梧棲區", "436": "清水區", "437": "大甲區", "438": "外埔區", "439": "大安區",
}
TAICHUNG_DISTRICTS = list(TAICHUNG_ZIP.values())

PII_PATTERN = re.compile(r"代表人|負責人|聯絡人|電話|市話|手機|行動電話|傳真|電子郵件|e-?mail|Responsible_Name", re.I)


class _GcisTLS(HTTPAdapter):
    """GCIS 憑證缺 Subject Key Identifier，Python 3.13+ 的 VERIFY_X509_STRICT 會拒絕；只關 strict，仍驗證憑證鏈與主機名稱"""

    def init_poolmanager(self, *a, **kw):
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
        kw["ssl_context"] = ctx
        return super().init_poolmanager(*a, **kw)


def session() -> requests.Session:
    s = requests.Session()
    s.mount("https://data.gcis.nat.gov.tw", _GcisTLS())
    s.mount("https://serv.gcis.nat.gov.tw", _GcisTLS())
    s.headers["User-Agent"] = USER_AGENT
    return s


def _record(source_id: str, url: str, path: Path, content: bytes):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    new = not MANIFEST.exists()
    with MANIFEST.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["source_id", "url", "path", "fetched_at", "bytes", "sha256"])
        w.writerow([source_id, url, path.relative_to(DATA_DIR.parent).as_posix(),
                    dt.datetime.now().isoformat(timespec="seconds"), len(content), hashlib.sha256(content).hexdigest()])


def fetch(s: requests.Session, source_id: str, url: str, dest: Path, *, force: bool = False,
          min_bytes: int = 50, delay: float = 0.5, retries: int = 3, **kw) -> bytes:
    """下載到 dest（已存在就直接讀，除非 force）；成功下載時寫入 manifest"""
    if dest.exists() and not force:
        return dest.read_bytes()
    last = None
    for attempt in range(retries):
        try:
            r = s.get(url, timeout=120, **kw)
            if r.status_code == 200 and len(r.content) >= min_bytes and b"\xe7\xb3\xbb\xe7\xb5\xb1\xe5\xbf\x99\xe7\xa2\x8c" not in r.content[:2000]:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                _record(source_id, url, dest, r.content)
                time.sleep(delay)
                return r.content
            last = f"HTTP {r.status_code}, {len(r.content)} bytes"
        except requests.RequestException as e:
            last = repr(e)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"下載失敗 {url}：{last}")


def read_csv_bytes(b: bytes, **kw) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp950", "big5"):
        try:
            return pd.read_csv(io.BytesIO(b), encoding=enc, **kw)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError("無法解碼 CSV")


def drop_pii(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in df.columns if PII_PATTERN.search(str(c))]
    return df.drop(columns=cols)


def roc_to_ad_year(y) -> int:
    return int(y) + 1911


def write_processed(df: pd.DataFrame, name: str, *, sources: List[str], grain: str,
                    notes: Optional[List[str]] = None) -> Path:
    """寫出長表並登錄到 _catalog.json；寫出前檢查欄位沒有個資"""
    leaked = [c for c in df.columns if PII_PATTERN.search(str(c))]
    if leaked:
        raise ValueError(f"{name} 含個資欄位：{leaked}")
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = PROCESSED_DATA_DIR / f"{name}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else {}
    catalog[name] = {"file": path.name, "rows": int(len(df)), "columns": list(map(str, df.columns)),
                     "grain": grain, "sources": sources, "notes": notes or [],
                     "built_at": dt.datetime.now().isoformat(timespec="seconds")}
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {path.relative_to(DATA_DIR.parent)}：{len(df):,} 列")
    return path


def month_gaps(months: Iterable[str], start: str, end: str) -> List[str]:
    have = set(months)
    return [str(p) for p in pd.period_range(start, end, freq="M") if str(p) not in have]
