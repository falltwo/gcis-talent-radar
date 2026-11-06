"""Official definitions of the manufacturing divisions, keyed by the EE520 category names.

Source: 行政院主計總處《行業統計分類（第 11 次修正）》, in force from 2021-01-01, section C
(PDF pages 35-78). The EE520 factory survey the site scan counts uses this revision.
Each record keeps the division code(s), the official name and definition, and the names of
its groups and classes, which serve as the "activities included" list the model reads.

Needs `pip install pypdf` and the PDF downloaded locally:
    python etl/build_industry_divisions.py path/to/行業統計分類-第11次修正.pdf
Writes data/reference/industry_divisions_rev11.json.
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/reference/industry_divisions_rev11.json"
SOURCE_URL = "https://www.dbas.taichung.gov.tw/media/689925/行業統計分類-第11次修正.pdf"
CODE = r"(\d(?:\s?\d){1,3})"
HEAD = re.compile(r"^\s*" + CODE + r"((?:\s+\d(?:\s?\d){1,3}){0,2})\s+([^\s\d]\S*業)\s*(.*)$")


def divisions(pdf: Path) -> list[dict]:
    from pypdf import PdfReader  # only needed to rebuild the file
    reader = PdfReader(str(pdf))
    # The PDF uses CJK compatibility code points; NFKC turns them into the usual characters.
    text = unicodedata.normalize("NFKC", "\n".join(reader.pages[i].extract_text() for i in range(39, 84)))
    out, cur, mode = [], None, None
    for line in text.splitlines():
        if "行業名稱及定義" in line or re.fullmatch(r"\s*(分類編號|大類\s*中類\s*小類\s*細類)\s*", line):
            continue
        m = HEAD.match(line)
        if m:
            first = m.group(1).replace(" ", "")
            if len(first) == 2 and 8 <= int(first) <= 34:
                cur = {"code": first, "name": m.group(3), "definition": m.group(4).strip(), "groups": []}
                out.append(cur)
                mode = "definition"
                continue
            if cur and len(first) in (3, 4) and first[:2] == cur["code"]:
                if m.group(3) not in cur["groups"]:
                    cur["groups"].append(m.group(3))
                mode = "skip"
                continue
        if cur is None:
            continue
        stripped = line.strip()
        if mode == "definition":
            if stripped.startswith("不包括"):
                mode = "skip"
            elif stripped and not stripped.isdigit():
                cur["definition"] += stripped
    return out


def by_ee520(records: list[dict]) -> dict:
    ee520 = list(next(iter(json.loads((ROOT / "ui/static/district-stats.json").read_text(encoding="utf-8"))
                           ["factories"]["districts"].values())).keys())
    squash = lambda s: re.sub(r"[、及其製造業]", "", s)
    result = {}
    for name in ee520:
        # EE520 merges divisions 09 (beverages) and 10 (tobacco) into one category.
        matched = [r for r in records if r["code"] in ("09", "10")] if name == "飲料及菸草業" \
            else [r for r in records if squash(r["name"]) == squash(name)]
        if not matched:
            raise SystemExit(f"no division for EE520 category {name}")
        result[name] = {"codes": [r["code"] for r in matched], "official_names": [r["name"] for r in matched],
                        "definition": "".join(r["definition"] for r in matched),
                        "groups": [g for r in matched for g in r["groups"]]}
    return result


if __name__ == "__main__":
    records = divisions(Path(sys.argv[1]))
    assert len(records) == 27, f"expected divisions 08-34, got {len(records)}"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "行政院主計總處《行業統計分類（第 11 次修正）》C 大類製造業",
                               "source_url": SOURCE_URL, "pages": "35-78", "effective": "2021-01-01",
                               "categories": by_ee520(records)}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(OUT, len(records), "divisions")
