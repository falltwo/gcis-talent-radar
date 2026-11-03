"""產生 docs/diagrams/sourcing-flow.drawio：HR 透過 agent 找人才的流程（泳道圖，依職類找不同網站）。

用法：python docs/diagrams/build_sourcing_flow.py
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from build_flow import Page

OUT = Path(__file__).with_name("sourcing-flow.drawio")

LANE_H = "swimlane;horizontal=0;startSize=44;html=1;whiteSpace=wrap;fillColor=#fbfbfb;strokeColor=#999999;fontStyle=1;fontSize=14;"
HR = "fillColor=#dae8fc;strokeColor=#6c8ebf;"
AGENT = "fillColor=#d5e8d4;strokeColor=#82b366;"
CU = "fillColor=#ffe6cc;strokeColor=#d79b00;"
SITE = "fillColor=#f5f5f5;strokeColor=#666666;fontColor=#333333;"
SCREEN = "fillColor=#fff2cc;strokeColor=#d6b656;"
BLOCK = "fillColor=#f8cecc;strokeColor=#b85450;"
ROW = "align=left;spacingLeft=10;"

# 職類 → 適合找人的網站（都要有公開作品或公開檔案）
SITES = [
    ("軟體開發", "GitHub、Stack Overflow"),
    ("AI／資料", "Hugging Face、Kaggle"),
    ("設計", "Dribbble"),
    ("研究", "ORCID、OpenAlex"),
    ("所有職類", "個人網站、部落格、作品集"),
]


def lane(p: Page, id, label, y, h, w=2520):
    c = ET.Element("mxCell", id=id, value=label, style=LANE_H, vertex="1", parent="1")
    ET.SubElement(c, "mxGeometry", x="40", y=str(y), width=str(w), height=str(h), **{"as": "geometry"})
    p.cells.append(c)


def build() -> None:
    p = Page("src")
    p.title("HR 透過 agent 找人才（依職類到不同網站找）", w=1400)

    # 泳道：HR／Agent／網站／操作畫面。節點座標相對於泳道左上角
    lane(p, "l-hr", "HR", 70, 170)
    lane(p, "l-ag", "Agent", 260, 280)
    lane(p, "l-web", "網站", 560, 260)
    lane(p, "l-scr", "操作畫面", 840, 150)

    col = lambda i: 60 + i * 240  # noqa: E731

    p.node("h1", "輸入需求&#xa;職缺、技能、地點&#xa;（例：軟體工程師、設計師）", col(0), 40, 210, 90,
           shape="end", status="head", parent="l-hr", style=HR)
    p.node("hn", "收到建議：這類職缺網路上&#xa;少有公開作品，改用其他管道&#xa;（職缺刊登、職訓單位…）", 500, 40, 230, 90,
           parent="l-hr", style=HR)
    p.node("h3", "收到候選人名單&#xa;每人的專長摘要＋連結", col(8) + 40, 45, 210, 80, parent="l-hr", style=HR)
    p.node("h4", "點連結查看&#xa;個人頁、作品", col(9) + 40, 45, 210, 80, shape="end", status="head",
           parent="l-hr", style=HR)

    p.node("a1", "理解需求，轉成搜尋條件&#xa;技能標籤、工具、地點", col(1), 130, 190, 80, parent="l-ag", style=AGENT)
    p.node("d0", "這個職類網路上&#xa;有公開作品嗎？", 515, 120, 200, 100, shape="gate", parent="l-ag", style=AGENT)
    p.node("a2", "依職類挑網站", col(3), 130, 210, 80, parent="l-ag", style=AGENT)
    p.lane("cu", "computer use：像人一樣操作瀏覽器", 1040, 280, 960, 240, style="fillColor=#fffaf3;strokeColor=#d79b00;")
    p.node("a3", "開啟網站並搜尋&#xa;用標籤、技能、地點篩選", 20, 110, 200, 80, parent="cu", style=CU)
    p.node("a4", "點進候選人個人頁", 260, 110, 200, 80, parent="cu", style=CU)
    p.node("a5", "讀取專業&#xa;作品、技能標籤、經歷、活躍度", 500, 110, 200, 80, parent="cu", style=CU)
    p.node("d1", "人數夠了？", 740, 100, 200, 100, shape="gate", parent="cu", style=CU)
    p.node("a6", "整理每人的&#xa;專長摘要＋連結", col(8) + 40, 130, 210, 80, parent="l-ag", style=AGENT)

    # 網站對照表：一列一個職類，最後一列是不碰的網站
    p.lane("cat", "職類 → 網站", 520, 585, 450, 226, style="fillColor=#ffffff;strokeColor=#666666;")
    for k, (job, sites) in enumerate(SITES):
        p.node(f"cat{k}", f"{job}：{sites}", 10, 36 + k * 26, 430, 22, parent="cat", style=SITE + ROW + "rounded=0;")
    p.node("cat-x", "不碰：LinkedIn、Google Scholar、人力銀行履歷庫", 10, 36 + len(SITES) * 26, 430, 22,
           status="stop", parent="cat", style=ROW + "rounded=0;")
    p.node("cat-bot", "會擋機器人，跳過：GitLab、Behance", 10, 36 + (len(SITES) + 1) * 26, 430, 22,
           status="stop", parent="cat", style=ROW + "rounded=0;")
    p.node("w1", "搜尋結果頁", 1020, 75, 200, 80, parent="l-web", style=SITE)
    p.node("w2", "候選人個人頁、作品集", 1300, 75, 360, 80, parent="l-web", style=SITE)
    p.node("s1", "即時操作畫面：每一步截圖推給 HR 看&#xa;開網頁 → 輸入搜尋 → 點擊 → 讀內容", 1000, 35, 920, 80,
           parent="l-scr", style=SCREEN)

    both = "startArrow=block;startSize=6;"
    p.edge("e1", "h1", "a1", out="r", inn="t")
    p.edge("e2", "a1", "d0", out="r", inn="l")
    p.edge("e3", "d0", "hn", "否", out="t", inn="b")
    p.edge("e4", "d0", "a2", "是", out="r", inn="l")
    p.edge("e5", "a2", "cat", "查表", out="b", inn=(0.9, 0), style=both)
    p.edge("e6", "a2", "a3", out="r", inn="l")
    p.edge("e7", "a3", "a4", out="r", inn="l")
    p.edge("e8", "a4", "a5", out="r", inn="l")
    p.edge("e9", "a5", "d1", out="r", inn="l")
    p.edge("e10", "d1", "a4", "還不夠：下一位，或換下一個網站", out="t", inn="t", points=[(1880, 330), (1400, 330)])
    p.edge("e11", "d1", "a6", "夠了", out="r", inn="l")
    p.edge("e12", "a6", "h3", out="t", inn="b")
    p.edge("e13", "h3", "h4", out="r", inn="l")
    p.edge("w-e1", "a3", "w1", "搜尋", out="b", inn="t", style=both)
    p.edge("w-e2", "a4", "w2", "開啟", out="b", inn=(0.1667, 0))
    p.edge("w-e3", "w2", "a5", "讀內容", out=(0.8333, 0), inn="b")
    p.edge("s-e1", "cu", "s1", "每一步截圖", out=(0.875, 1), inn=(0.913, 0), style="dashed=1;")

    mxfile = ET.Element("mxfile", host="drawio", version="26.0.0")
    d = ET.SubElement(mxfile, "diagram", id=p.name, name="找人流程")
    model = ET.SubElement(d, "mxGraphModel", grid="1", gridSize="10", page="1", pageScale="1",
                          pageWidth="2620", pageHeight="1030", math="0", shadow="0")
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")
    for c in p.cells:
        root.append(c)
    ET.indent(mxfile)
    xml = ET.tostring(mxfile, encoding="unicode").replace("&amp;#xa;", "&#xa;")
    OUT.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
