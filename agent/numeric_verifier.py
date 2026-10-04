"""Conservative numeric-overlap check for generated text.

This is only a lexical guardrail: it checks whether each extracted number
appears in the tool payload. It cannot verify claim-to-value relationships,
units, meaning, or source provenance, and must not be presented as semantic
fact-checking.
"""
import re
from typing import Dict, Any, List, Set

def extract_numbers_from_text(text: str) -> List[float]:
    """Extracts all numerical quantities from text, normalizing commas and units."""
    # First handle "X 萬" or "X 萬人" -> X * 10000
    expanded_text = re.sub(r"(\d+\.?\d*)\s*萬", lambda m: f" {float(m.group(1))*10000} ", text)
    # Remove commas between digits like 188,000
    cleaned = re.sub(r"(?<=\d),(?=\d)", "", expanded_text)
    
    # Match standard numbers: integers, decimals, negatives
    raw_matches = re.findall(r"[-+]?\d*\.?\d+", cleaned)
    nums = []
    for m in raw_matches:
        try:
            val = float(m)
            nums.append(val)
        except ValueError:
            pass
    return nums

def flatten_structured_numbers(data: Any) -> Set[float]:
    """Collect numeric values explicitly present in tool data.

    Do not synthesize rounded integers, absolute values, or alternate units here:
    those transformations made unrelated numbers (and arbitrary constants) look
    supported by the evidence.
    """
    nums = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ["tax_id", "company_id"]:
                try:
                    nums.add(float(v))
                except (ValueError, TypeError):
                    pass
            nums.update(flatten_structured_numbers(v))
    elif isinstance(data, list):
        for item in data:
            nums.update(flatten_structured_numbers(item))
    elif isinstance(data, (int, float)):
        nums.add(float(data))
    return nums

def verify_explanation_numbers(
    explanation_text: str,
    structured_data: Dict[str, Any],
    tolerance: float = 0.05
) -> Dict[str, Any]:
    """
    Compares numbers in text against structured truth.
    Returns status: VERIFIED / WARNING / FAILED.
    """
    text_nums = extract_numbers_from_text(explanation_text)
    truth_nums = flatten_structured_numbers(structured_data)

    if not structured_data or not truth_nums:
        return {
            "status": "FAILED",
            "matched_count": 0,
            "total_extracted": len(text_nums),
            "accuracy_pct": 0.0 if text_nums else None,
            "audit_details": ["沒有可供核對的工具數值；不能驗證模型回答。"],
        }

    if not text_nums:
        return {
            "status": "NOT_APPLICABLE",
            "matched_count": 0,
            "total_extracted": 0,
            "accuracy_pct": None,
            "audit_details": ["回答沒有可比對的數值；本檢查不代表語意或來源已驗證。"],
        }

    audit_details = []
    matched_count = 0
    unmatched_nums = []

    for num in text_nums:
        found = any(abs(num - t) <= tolerance for t in truth_nums)

        if found:
            matched_count += 1
        else:
            unmatched_nums.append(num)

    total = len(text_nums)
    accuracy = round((matched_count / total) * 100.0, 1) if total > 0 else 100.0

    if accuracy == 100.0:
        status = "VERIFIED"
    elif accuracy >= 80.0:
        status = "WARNING"
    else:
        status = "FAILED"

    audit_details.append(f"數值比對完成：{matched_count}/{total} 個數值符合工具資料 (符合率 {accuracy}%)；此結果不核驗數值與敘述的語意關係")
    if unmatched_nums:
        audit_details.append(f"未完全比對數值：{unmatched_nums[:5]}")

    return {
        "status": status,
        "matched_count": matched_count,
        "total_extracted": total,
        "accuracy_pct": accuracy,
        "audit_details": audit_details
    }
