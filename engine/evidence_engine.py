"""
Deterministic Engine: Evidence Engine & Traceability Builder (System Spec Section P4, 27)
Builds structured evidence objects guaranteeing complete audit trails:
Result -> Indicator -> Calculation -> Processed Table -> Source Data
"""
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def build_evidence_object(
    intent: str,
    indicator_name: str,
    calculation_steps: List[str],
    source_tables: List[str],
    official_sources: List[str],
    data_period: str = "109-117學年度/年度",
    geography: str = "台中市",
    verification_status: str = "VERIFIED",
    source_urls: Optional[List[str]] = None,
    dataset_ids: Optional[List[str]] = None,
    limitations: Optional[List[str]] = None,
    fetched_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Standard evidence schema required by Section 27.
    """
    evidence = {
        "intent": intent,
        "indicator": indicator_name,
        "geography": geography,
        "data_period": data_period,
        "calculation": calculation_steps,
        "processed_tables": source_tables,
        "source": official_sources,
        # Never substitute the current date for an unknown source timestamp.
        # A missing value is explicit and auditable; a guessed value is not.
        "last_updated": fetched_at,
        "timestamp_status": "SOURCE_TIMESTAMP" if fetched_at else "NOT_RECORDED",
        "verification_status": verification_status
    }
    if source_urls:
        evidence["source_urls"] = source_urls
    if dataset_ids:
        evidence["dataset_ids"] = dataset_ids
    if limitations:
        evidence["limitations"] = limitations
    return evidence
