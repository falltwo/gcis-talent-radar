"""Strict, dependency-free input contract for immutable comparison reports."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from config import TAICHUNG_DISTRICTS

CLASSIFICATION_VERSION = "mfg-divisions-v1"
RETRIEVAL_VERSION = "job-rules-v1"
SCHEMA_VERSION = "1.0"
DIVISIONS = dict(zip((f"{i:02d}" for i in range(8, 35)), [
    "食品製造業", "飲料製造業", "菸草製造業", "紡織業", "成衣及服飾品製造業",
    "皮革、毛皮及其製品製造業", "木竹製品製造業", "紙漿、紙及紙製品製造業",
    "印刷及資料儲存媒體複製業", "石油及煤製品製造業", "化學材料及肥料製造業",
    "其他化學製品製造業", "藥品及醫用化學製品製造業", "橡膠製品製造業", "塑膠製品製造業",
    "非金屬礦物製品製造業", "基本金屬製造業", "金屬製品製造業", "電子零組件製造業",
    "電腦、電子產品及光學製品製造業", "電力設備及配備製造業", "機械設備製造業",
    "汽車及其零件製造業", "其他運輸工具及其零件製造業", "家具製造業", "其他製造業",
    "產業用機械設備維修及安裝業",
]))
_MONTH = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


class ReportError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def month_index(value: str) -> int:
    if not isinstance(value, str) or not _MONTH.fullmatch(value) or int(value[:4]) < 1900:
        raise ReportError("INVALID_MONTH", "月份請使用 YYYY-MM，年份須不早於 1900 年。")
    return int(value[:4]) * 12 + int(value[5:]) - 1


def index_month(index: int) -> str:
    year, month = divmod(index, 12)
    return f"{year:04d}-{month + 1:02d}"


def _shape(value: Any, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ReportError("INVALID_SCENARIO", f"{label}欄位不完整或包含未核准欄位。")
    return value


def _text(value: Any, label: str, limit: int = 160) -> str:
    if not isinstance(value, str):
        raise ReportError("INVALID_SCENARIO", f"{label}必須是文字。")
    value = unicodedata.normalize("NFKC", value).strip()
    if not 1 <= len(value) <= limit or any(ord(c) < 32 for c in value):
        raise ReportError("INVALID_SCENARIO", f"{label}長度或字元不正確。")
    return value


def validate_scenario(value: Any) -> dict:
    obj = _shape(value, {"schema_version", "districts", "manufacturing", "occupation", "observation", "hiring_plan"}, "情境")
    if obj["schema_version"] != SCHEMA_VERSION:
        raise ReportError("SCHEMA_VERSION", "情境版本已變更，請重新載入選項。")
    regions = obj["districts"]
    if not isinstance(regions, list) or not 2 <= len(regions) <= 3:
        raise ReportError("INVALID_DISTRICTS", "請選擇 2 至 3 個行政區。")
    regions = [_text(region, "行政區", 12).replace("臺中市", "").replace("台中市", "") for region in regions]
    if len(set(regions)) != len(regions) or any(region not in TAICHUNG_DISTRICTS for region in regions):
        raise ReportError("INVALID_DISTRICTS", "行政區須為臺中市且不得重複。")
    manufacturing = _shape(obj["manufacturing"], {"division_code", "classification_version"}, "製造中類")
    code = _text(manufacturing["division_code"], "製造中類", 2)
    if code not in DIVISIONS or manufacturing["classification_version"] != CLASSIFICATION_VERSION:
        raise ReportError("CATALOG_STALE", "製造中類或分類版本不符，請重新載入選項。")
    occupation = _shape(obj["occupation"], {"type", "keyword", "retrieval_profile_version"}, "職類")
    if occupation["type"] != "KEYWORD" or occupation["retrieval_profile_version"] != RETRIEVAL_VERSION:
        raise ReportError("CATALOG_STALE", "職類檢索版本不符，請重新載入選項。")
    keyword = _text(occupation["keyword"], "職類關鍵字", 60)
    observation = _shape(obj["observation"], {"mode", "month", "window_months", "knowledge_cutoff"}, "觀測期間")
    if observation["mode"] not in {"LATEST_AVAILABLE", "FIXED_MONTH"}:
        raise ReportError("INVALID_OBSERVATION", "請選擇最新資料或固定月份。")
    if type(observation["window_months"]) is not int or observation["window_months"] not in {3, 6, 12}:
        raise ReportError("INVALID_WINDOW", "區域觀察窗只提供 3、6、12 個月。")
    if observation["knowledge_cutoff"] is not None:
        raise ReportError("VINTAGE_NOT_SUPPORTED", "目前僅提供觀測期回看，尚不提供當時可知資訊重建。")
    if observation["mode"] == "LATEST_AVAILABLE":
        if observation["month"] is not None:
            raise ReportError("INVALID_OBSERVATION", "最新模式不可另指定觀測月。")
    else:
        month_index(observation["month"])
        if observation["month"] > datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m"):
            raise ReportError("FUTURE_OBSERVATION", "觀測月份不可在未來；未來招募請使用招募計畫。")
    plan = _shape(obj["hiring_plan"], {"net_hires", "start_month", "end_month"}, "招募計畫")
    if type(plan["net_hires"]) is not int or not 1 <= plan["net_hires"] <= 100000:
        raise ReportError("INVALID_HIRING_TARGET", "淨新增到職人數須為 1 至 100000 的整數。")
    start, end = month_index(plan["start_month"]), month_index(plan["end_month"])
    if not 0 <= end - start < 12:
        raise ReportError("INVALID_PLAN_PERIOD", "招募起月不可晚於迄月，且最多 12 個月。")
    return {
        "schema_version": SCHEMA_VERSION, "districts": regions,
        "manufacturing": {"division_code": code, "classification_version": CLASSIFICATION_VERSION},
        "occupation": {"type": "KEYWORD", "keyword": keyword, "retrieval_profile_version": RETRIEVAL_VERSION},
        "observation": dict(observation), "hiring_plan": dict(plan),
    }


def make_hiring_plan(scenario: dict) -> dict:
    plan = scenario["hiring_plan"]
    start, end = month_index(plan["start_month"]), month_index(plan["end_month"])
    base, remainder = divmod(plan["net_hires"], end - start + 1)
    return {
        **plan, "data_kind": "USER_PLAN", "formula": "H//M plus one in the first H%M months",
        "monthly_targets": [{"month": index_month(month), "people": base + (offset < remainder)} for offset, month in enumerate(range(start, end + 1))],
        "disclosure": "你的淨到職目標，不代表預測可招到的人數；未估計離職替補及到職延遲。",
    }
