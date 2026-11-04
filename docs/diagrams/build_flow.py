"""產生 docs/diagrams/talent-radar-flow.drawio：產業人才雷達全貌流程圖（含現有與規劃中功能）。

用法：python docs/diagrams/build_flow.py
座標全部寫死在程式裡，改圖就改這支程式再重跑；不要手改 .drawio 以免下次被覆蓋。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path(__file__).with_name("talent-radar-flow.drawio")

# 顏色代表狀態，形狀代表類型
STATUS = {
    "done": "fillColor=#d5e8d4;strokeColor=#82b366;",
    "pr": "fillColor=#fff2cc;strokeColor=#d6b656;",
    "plan": "fillColor=#ffffff;strokeColor=#6c8ebf;dashed=1;",
    "stop": "fillColor=#f8cecc;strokeColor=#b85450;",
    "ext": "fillColor=#f5f5f5;strokeColor=#666666;fontColor=#333333;",
    "head": "fillColor=#dae8fc;strokeColor=#6c8ebf;fontStyle=1;",
}
SHAPE = {
    "box": "rounded=1;whiteSpace=wrap;html=1;arcSize=12;",
    "gate": "rhombus;whiteSpace=wrap;html=1;",
    "db": "shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;size=10;",
    "end": "ellipse;whiteSpace=wrap;html=1;",
    "note": "text;html=1;align=left;verticalAlign=top;whiteSpace=wrap;fontColor=#555555;",
}
LANE = "swimlane;startSize=30;html=1;whiteSpace=wrap;rounded=1;arcSize=4;fillColor=#fbfbfb;strokeColor=#999999;fontStyle=1;"
EDGE = "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;endArrow=block;endSize=8;"
PORT = {"t": (0.5, 0), "b": (0.5, 1), "l": (0, 0.5), "r": (1, 0.5)}


class Page:
    def __init__(self, name: str):
        self.name = name
        self.cells: list[ET.Element] = []

    def node(self, id, label, x, y, w=180, h=60, *, status="done", shape="box", parent="1", style=""):
        s = SHAPE[shape] + ("" if shape == "note" else STATUS[status]) + style
        c = ET.Element("mxCell", id=id, value=label, style=s, vertex="1", parent=parent)
        ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), **{"as": "geometry"})
        self.cells.append(c)
        return c

    def lane(self, id, label, x, y, w, h, *, style=""):
        c = ET.Element("mxCell", id=id, value=label, style=LANE + style, vertex="1", parent="1")
        ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width=str(w), height=str(h), **{"as": "geometry"})
        self.cells.append(c)

    def edge(self, id, src, dst, label="", *, out=None, inn=None, style="", points=()):
        s = EDGE + style
        if out:
            ox, oy = PORT[out] if isinstance(out, str) else out
            s += f"exitX={ox};exitY={oy};exitDx=0;exitDy=0;"
        if inn:
            ix, iy = PORT[inn] if isinstance(inn, str) else inn
            s += f"entryX={ix};entryY={iy};entryDx=0;entryDy=0;"
        c = ET.Element("mxCell", id=id, value=label, style=s, edge="1", parent="1", source=src, target=dst)
        g = ET.SubElement(c, "mxGeometry", relative="1", **{"as": "geometry"})
        if points:
            arr = ET.SubElement(g, "Array", **{"as": "points"})
            for px, py in points:
                ET.SubElement(arr, "mxPoint", x=str(px), y=str(py))
        self.cells.append(c)

    def title(self, text, x=40, y=10, w=900):
        self.node(f"{self.name}-title", text, x, y, w, 40, shape="note",
                  style="fontSize=20;fontStyle=1;fontColor=#222222;")

    def legend(self, x, y, roles):
        labels = {
            "done": "已有", "pr": "開發中（PR）", "plan": "規劃中",
            "stop": "拒答／攔下／封鎖", "ext": "外部網站・資料來源",
        }
        lid = f"{self.name}-legend"
        h = 30 + 24 * len(roles)
        c = ET.Element("mxCell", id=lid, value="圖例", vertex="1", parent="1",
                       style="rounded=0;whiteSpace=wrap;html=1;fillColor=#ffffff;strokeColor=#999999;verticalAlign=top;fontStyle=1;")
        ET.SubElement(c, "mxGeometry", x=str(x), y=str(y), width="190", height=str(h), **{"as": "geometry"})
        self.cells.append(c)
        for i, role in enumerate(roles):
            self.node(f"{lid}-{role}", "", 10, 30 + 24 * i, 30, 16, status=role, parent=lid,
                      style="rounded=0;")
            self.node(f"{lid}-{role}-t", labels[role], 50, 28 + 24 * i, 130, 20, shape="note", parent=lid,
                      style="verticalAlign=middle;fontColor=#333333;")


# ---------------------------------------------------------------- 第 1 頁：全貌
def page_overview() -> Page:
    p = Page("overview")
    p.title("產業人才雷達：系統全貌（現有＋規劃）")
    p.node("user", "HR／工廠老闆", 520, 70, 200, 60, shape="end", status="head")

    p.lane("fe", "前端頁面", 80, 170, 1080, 120)
    p.node("fe-home", "首頁：直接問答＋擴廠情境", 60, 45, 300, 55, parent="fe")
    p.node("fe-cmp", "行政區徵才比較（PR #20）", 390, 45, 300, 55, status="pr", parent="fe")
    p.node("fe-src", "找人頁 /sourcing&#xa;（前端團隊做介面）", 720, 45, 300, 55, status="plan", parent="fe")

    p.node("api", "FastAPI 後端（api/main.py）", 500, 340, 240, 60)

    p.lane("gov", "共用治理層", 80, 450, 1080, 110)
    p.node("gov-scope", "範圍檢查&#xa;（規劃：改用 Jev）", 20, 42, 230, 55, parent="gov")
    p.node("gov-fair", "公平招募護欄&#xa;就服法第 5 條", 280, 42, 230, 55, parent="gov")
    p.node("gov-num", "數字核對", 540, 42, 230, 55, parent="gov")
    p.node("gov-audit", "稽核紀錄（只存雜湊值）", 800, 42, 230, 55, parent="gov")

    p.lane("qa", "招募環境問答 agent", 80, 610, 500, 130)
    p.node("qa-llm", "gpt-6-luna&#xa;function calling 選工具", 20, 45, 210, 60, parent="qa")
    p.node("qa-write", "撰寫回答＋查證紀錄", 270, 45, 210, 60, parent="qa")

    p.lane("sa", "找人 agent（computer use）", 660, 610, 500, 130, style="dashed=1;strokeColor=#6c8ebf;")
    p.node("sa-cu", "typesafe-computer-use&#xa;Jev 決定每一步", 20, 45, 210, 60, status="plan", parent="sa")
    p.node("sa-llm", "gpt-6-luna&#xa;打字、讀畫面、寫摘要", 270, 45, 210, 60, status="plan", parent="sa")

    p.node("tools", "官方資料工具 engine/&#xa;＋預測引擎 forecast/", 100, 800, 220, 70)
    p.node("data", "處理後資料表&#xa;data/processed", 360, 795, 180, 80, shape="db")
    p.node("router", "OpenRouter&#xa;gpt-6-luna、Jev", 520, 920, 200, 60, status="ext")
    p.node("gov-data", "政府開放資料&#xa;經濟部、勞動部、臺中市府…", 100, 920, 260, 60, status="ext")
    p.node("sites", "外部網站&#xa;GitHub、Stack Overflow、個人網站", 880, 800, 260, 70, status="ext")
    p.node("api-sites", "官方 API&#xa;GitHub、Stack Exchange、ORCID", 880, 920, 260, 60, status="ext")

    p.edge("o1", "user", "fe", out="b", inn="t")
    p.edge("o2", "fe", "api", out="b", inn="t")
    p.edge("o3", "api", "gov", out="b", inn="t")
    p.edge("o4", "gov", "qa", out=(0.25, 1), inn=(0.54, 0))
    p.edge("o5", "gov", "sa", out=(0.75, 1), inn=(0.46, 0))
    p.edge("o6", "qa", "tools", out=(0.2, 1), inn=(0.3636, 0))
    p.edge("o7", "tools", "data", out="r", inn="l")
    p.edge("o8", "gov-data", "tools", "ETL", out=(0.3, 0), inn=(0.3, 1))
    p.edge("o9", "qa", "router", out="r", inn=(0.45, 0))
    p.edge("o10", "sa", "router", out=(0.2, 1), inn=(0.75, 0))
    p.edge("o11", "sa", "sites", "瀏覽器操作", out=(0.8, 1), inn="t")
    p.edge("o12", "sites", "api-sites", "資料以 API 為準", out="b", inn="t", style="dashed=1;")
    p.legend(1200, 70, ["done", "pr", "plan", "ext"])
    return p


# ------------------------------------------------- 第 2 頁：公司招募流程 × 功能
def page_hiring() -> Page:
    p = Page("hiring")
    p.title("公司招募流程 × 功能（只做前四步＋合規，不碰候選人管理）", w=1300)
    steps = [
        ("第 0 步&#xa;決定在哪裡擴廠", [
            ("擴廠情境（四個官方數字）", "done"), ("行政區徵才比較", "pr"), ("行政區同業動態", "plan"),
            ("通勤圈範圍", "plan"), ("行政區長期就業趨勢", "plan"), ("趨勢預測區間", "plan"), ("地圖", "plan")]),
        ("第 1 步&#xa;規劃職類與時程", [
            ("職稱對照", "plan"), ("臺中職類求供倍數", "plan"), ("全國求才僱用率&#xa;（勞動部 146549）", "plan"),
            ("招募時機", "plan")]),
        ("第 2 步&#xa;設計職缺與薪資", [
            ("同區職缺開薪分布", "plan"), ("製造業職類薪資&#xa;（勞動部 41685）", "plan"), ("招募條件對照", "plan"),
            ("職缺文案健檢", "plan")]),
        ("第 3 步&#xa;決定去哪裡找人", [
            ("找人 agent&#xa;GitHub、Stack Overflow…", "plan"), ("附近職訓課程&#xa;（勞動部 6060）", "plan"),
            ("相關科系畢業生趨勢", "plan"), ("技能檢定發證數&#xa;（勞動部 166315）", "plan"),
            ("臺中移工總數&#xa;（勞動部 41881）", "plan")]),
        ("第 4 步&#xa;篩選與面試", [("公平招募護欄", "done"), ("職缺文案健檢（共用）", "plan")]),
        ("第 5–6 步&#xa;錄用後持續觀察", [("每日職缺快照", "plan"), ("變化通知&#xa;Email", "plan")]),
    ]
    col_w, gap, x0 = 200, 40, 40
    for i, (head, feats) in enumerate(steps):
        x = x0 + i * (col_w + gap)
        p.node(f"h{i}", head, x, 70, col_w, 60, status="head")
        if i:
            p.edge(f"he{i}", f"h{i - 1}", f"h{i}", out="r", inn="l")
        for j, (label, st) in enumerate(feats):
            p.node(f"h{i}-{j}", label, x, 160 + j * 70, col_w, 55, status=st)
    p.node("h-out", "不在範圍：履歷管理、面試排程、錄用作業（交給 ATS／人資）", 40 + 4 * 240, 330, 440, 50,
           status="ext", style="dashed=1;")
    p.lane("cross", "每一步都用得到", 40, 680, 1400, 100)
    for k, (label, st) in enumerate([("查證紀錄", "done"), ("數字核對", "done"), ("稽核紀錄", "done"),
                                     ("匯出查證報告", "plan"), ("多輪追問", "plan"), ("資料新鮮度頁", "plan")]):
        p.node(f"cx{k}", label, 20 + k * 228, 40, 200, 45, status=st, parent="cross")
    p.legend(1490, 70, ["done", "pr", "plan", "ext"])
    return p


# --------------------------------------------------- 第 3 頁：招募環境問答流程
def page_qa() -> Page:
    p = Page("qa")
    p.title("招募環境問答流程（數字由程式算，模型只負責理解和說明）")
    cx = 530
    p.node("q0", "HR／老闆提問", cx - 90, 70, 180, 60, shape="end", status="head")
    p.node("q-scope", "範圍檢查&#xa;（規劃：改用 Jev）", cx - 100, 170, 200, 90, shape="gate")
    p.node("q-fair", "公平招募護欄", cx - 100, 300, 200, 90, shape="gate")
    p.node("q-reject", "拒答&#xa;不呼叫模型", 820, 245, 160, 60, status="stop")
    p.node("q-pick", "gpt-6-luna 選工具&#xa;function calling", cx - 110, 430, 220, 60)

    p.lane("q-tools", "資料工具（程式查官方資料，回傳數值＋期別＋出處＋限制）", 120, 530, 820, 245)
    tools = [
        [("公開職缺需求&#xa;台灣就業通", "done"), ("全市新設公司趨勢&#xa;GCIS", "done"),
         ("平均投保薪資&#xa;勞保局", "done"), ("擴廠情境&#xa;四個口徑", "done")],
        [("行政區同業動態", "plan"), ("職缺開薪分布", "plan"), ("職類求供倍數", "plan"), ("附近職訓課程", "plan")],
        [("製造業職類薪資", "plan"), ("臺中移工總數", "plan"), ("趨勢預測區間", "plan")],
    ]
    for r, row in enumerate(tools):
        for c, (label, st) in enumerate(row):
            p.node(f"qt{r}{c}", label, 20 + c * 200, 42 + r * 66, 180, 52, status=st, parent="q-tools")

    p.node("q-write", "gpt-6-luna 撰寫回答", cx - 110, 815, 220, 60)
    p.node("q-num", "數字核對&#xa;每個數字都要對得上", cx - 100, 915, 200, 90, shape="gate")
    p.node("q-block", "整段攔下&#xa;不顯示模型說法", 820, 930, 160, 60, status="stop")
    p.node("q-ans", "回答＋查證紀錄&#xa;出處、期別、限制", cx - 110, 1050, 220, 70)
    p.node("q-show", "顯示給使用者", cx - 90, 1170, 180, 60, shape="end", status="head")
    p.node("q-audit", "稽核紀錄&#xa;只存雜湊值", 20, 920, 130, 80, shape="db")
    p.lane("q-next", "回答之後（規劃）", 800, 1020, 200, 155, style="dashed=1;strokeColor=#6c8ebf;")
    for k, label in enumerate(["多輪追問", "匯出查證報告 PDF"]):
        p.node(f"q-f{k + 1}", label, 20, 40 + k * 55, 160, 45, status="plan", parent="q-next")

    p.edge("qe1", "q0", "q-scope", out="b", inn="t")
    p.edge("qe2", "q-scope", "q-fair", "通過", out="b", inn="t")
    p.edge("qe3", "q-fair", "q-pick", "通過", out="b", inn="t")
    p.edge("qe4", "q-scope", "q-reject", "超出範圍", out="r", inn=(0, 0.3))
    p.edge("qe5", "q-fair", "q-reject", "歧視條件", out="r", inn=(0, 0.7))
    p.edge("qe6", "q-pick", "q-tools", out="b", inn="t")
    p.edge("qe7", "q-tools", "q-write", out="b", inn="t")
    p.edge("qe8", "q-write", "q-num", out="b", inn="t")
    p.edge("qe9", "q-num", "q-ans", "全部對上", out="b", inn="t")
    p.edge("qe10", "q-num", "q-block", "有數字對不上", out="r", inn="l")
    p.edge("qe11", "q-ans", "q-show", out="b", inn="t")
    audit = "dashed=1;strokeColor=#999999;endArrow=open;"
    p.edge("qa1", "q-scope", "q-audit", out="l", inn="t", style=audit, points=[(85, 215)])
    p.edge("qa2", "q-fair", "q-audit", out="l", inn="t", style=audit, points=[(85, 345)])
    p.edge("qa3", "q-num", "q-audit", out="l", inn="r", style=audit)
    p.edge("qf", "q-ans", "q-next", out="r", inn=(0, 0.4194), style="dashed=1;")
    p.legend(1000, 70, ["done", "plan", "stop"])
    return p


# ------------------------------------------- 第 4 頁：找人 agent（computer use）
def page_sourcing() -> Page:
    p = Page("sourcing")
    p.title("找人 agent 流程（computer use：typesafe-computer-use ＋ Jev ＋ gpt-6-luna）", w=1100)
    cx = 580
    p.node("s0", "HR 輸入找人需求&#xa;職缺、地點、技能", cx - 110, 70, 220, 60, shape="end", status="head")
    p.node("s-scope", "Jev 是非題&#xa;是不是找人需求？", cx - 110, 170, 220, 90, shape="gate", status="plan")
    p.node("s-fair", "公平招募護欄&#xa;排除性別、年齡、國籍條件", cx - 120, 300, 240, 100, shape="gate")
    p.node("s-reject", "拒絕並說明原因", 900, 255, 180, 60, status="stop")
    p.node("s-route", "Jev 選擇題：依職類挑網站&#xa;GitHub／Stack Overflow／ORCID…", cx - 160, 440, 320, 60, status="plan")
    p.node("s-block", "封鎖：LinkedIn、Google Scholar、&#xa;人力銀行履歷庫", 900, 440, 260, 60, status="stop")

    p.lane("s-api", "官方 API（資料以此為準）", 60, 550, 420, 280)
    for k, label in enumerate(["GitHub API&#xa;repo、語言、topics、活躍度", "Stack Exchange API&#xa;回答標籤、聲望",
                               "ORCID API&#xa;論文、研究領域", "Hugging Face API&#xa;模型、資料集"]):
        p.node(f"sa{k}", label, 30, 42 + k * 58, 360, 48, status="plan", parent="s-api")

    p.lane("s-cu", "瀏覽器 computer use（typesafe-computer-use 瀏覽器模式）", 560, 550, 600, 380,
           style="dashed=1;strokeColor=#6c8ebf;")
    p.node("cu1", "讀網頁元素（DOM）", 30, 50, 220, 55, status="plan", parent="s-cu")
    p.node("cu2", "Jev 決定下一步&#xa;點哪裡／打字／完成", 350, 50, 220, 55, status="plan", parent="s-cu")
    p.node("cu3", "執行點擊、輸入、捲動", 350, 170, 220, 55, status="plan", parent="s-cu")
    p.node("cu4", "截圖透過 SSE 推給前端", 30, 170, 220, 55, status="plan", parent="s-cu")
    p.node("cu5", "gpt-6-luna&#xa;需要打字、讀懂畫面、Jev 卡住時接手", 200, 290, 260, 60, status="plan", parent="s-cu")
    p.node("s-live", "HR 即時看到操作畫面", 1220, 690, 180, 60, status="plan")

    p.node("s-merge", "整理候選人資料&#xa;個人頁、代表作品、技能證據", cx - 160, 980, 320, 60, status="plan")
    p.node("s-score", "Jev 評分題：符合度排序", cx - 160, 1080, 320, 55, status="plan")
    p.node("s-sum", "gpt-6-luna：專長摘要＋證據連結", cx - 160, 1175, 320, 55, status="plan")
    p.node("s-out", "候選人名單給 HR&#xa;只給連結，不抓 Email", cx - 120, 1270, 240, 70, shape="end", status="head")
    p.node("s-audit", "稽核紀錄&#xa;只存雜湊；名單不入庫", 60, 1068, 170, 80, shape="db")

    p.edge("se1", "s0", "s-scope", out="b", inn="t")
    p.edge("se2", "s-scope", "s-fair", "是", out="b", inn="t")
    p.edge("se3", "s-fair", "s-route", "通過", out="b", inn="t")
    p.edge("se4", "s-scope", "s-reject", "否", out="r", inn=(0, 0.3))
    p.edge("se5", "s-fair", "s-reject", "歧視條件", out="r", inn=(0, 0.7))
    p.edge("se6", "s-route", "s-block", "不在白名單", out="r", inn="l", style="dashed=1;")
    p.edge("se7", "s-route", "s-api", out="l", inn="t")
    p.edge("se8", "s-route", "s-cu", out=(0.75, 1), inn=(0.1667, 0))
    p.edge("cl1", "cu1", "cu2", out="r", inn="l")
    p.edge("cl2", "cu2", "cu3", out="b", inn="t")
    p.edge("cl3", "cu3", "cu4", out="l", inn="r")
    p.edge("cl4", "cu4", "cu1", "下一步", out="t", inn="b")
    p.edge("cl5", "cu2", "cu5", out="r", inn="r", style="dashed=1;startArrow=block;startSize=6;",
           points=[(1145, 627), (1145, 870)])
    p.edge("se9", "s-cu", "s-live", out=(1, 0.4474), inn="l", style="dashed=1;")
    p.edge("se10", "s-api", "s-merge", out="b", inn=(0.25, 0))
    p.edge("se11", "s-cu", "s-merge", out=(0.1667, 1), inn=(0.75, 0))
    p.edge("se12", "s-merge", "s-score", out="b", inn="t")
    p.edge("se13", "s-score", "s-sum", out="b", inn="t")
    p.edge("se14", "s-sum", "s-out", out="b", inn="t")
    p.edge("se15", "s-score", "s-audit", out="l", inn="r", style="dashed=1;strokeColor=#999999;endArrow=open;")
    p.legend(60, 140, ["done", "plan", "stop"])
    return p


# ---------------------------------------------------------- 第 5 頁：資料管線
def page_data() -> Page:
    p = Page("data")
    p.title("資料管線（政府開放資料 → ETL → 資料表 → 工具 → API）", w=1100)
    p.lane("d-src", "已接入的資料來源", 40, 70, 300, 410)
    for k, label in enumerate(["經濟部 GCIS 商工登記", "台灣就業通 職缺快照", "勞保局 投保薪資", "臺中市府 工廠家數",
                               "臺中市勞工局 就業市場季報", "教育部 大專／高中職校務", "經濟部 EE520 工廠調查",
                               "財政部 稅籍登記"]):
        p.node(f"ds{k}", label, 20, 40 + k * 45, 260, 36, parent="d-src")
    p.lane("d-new", "規劃接入的資料來源", 40, 510, 300, 365, style="dashed=1;strokeColor=#6c8ebf;")
    for k, label in enumerate(["勞動部 職訓課程（6060）", "勞動部 職類薪資（41685）", "勞動部 移工人數（41881）",
                               "勞動部 求才僱用（146549）", "勞動部 技能檢定（166315）", "內政部 戶政人口",
                               "產發署 登記工廠名錄"]):
        p.node(f"dn{k}", label, 20, 40 + k * 45, 260, 36, status="plan", parent="d-new")

    p.node("etl", "etl.run_real_etl&#xa;下載＋整理＋品質報告", 420, 330, 220, 70)
    p.node("cron", "每日排程&#xa;GitHub Actions cron", 420, 470, 220, 60, status="plan")
    p.node("proc", "data/processed&#xa;處理後資料表", 720, 320, 180, 90, shape="db")
    p.node("manifest", "_manifest.csv（網址、時間、SHA-256）&#xa;DATA_QUALITY.md 品質報告", 680, 450, 260, 60)

    p.node("t-now", "官方資料工具（已有）&#xa;職缺需求、新設公司、投保薪資、擴廠情境", 1000, 160, 280, 70)
    p.node("t-fc", "預測引擎 forecast/&#xa;rolling-origin 回測、80% 區間", 1000, 260, 280, 60)
    p.node("t-new", "新工具（規劃）&#xa;同業動態、開薪分布、求供倍數、職訓、&#xa;職類薪資、移工、畢業生", 1000, 360, 280, 80,
           status="plan")

    p.node("c1", "/api/official/*、/api/demo/expansion", 1360, 160, 260, 50)
    p.node("c2", "AI 問答 agent", 1360, 230, 260, 50)
    p.node("c3", "/api/forecast", 1360, 300, 260, 50, status="plan")
    p.node("c4", "/api/data-status 資料新鮮度", 1360, 370, 260, 50, status="plan")
    p.node("c5", "變化通知 Email", 1360, 440, 260, 50, status="plan")

    p.edge("de1", "d-src", "etl", out="r", inn=(0, 0.35))
    p.edge("de2", "d-new", "etl", out="r", inn=(0, 0.75), style="dashed=1;")
    p.edge("de3", "cron", "etl", "觸發", out="t", inn="b", style="dashed=1;")
    p.edge("de4", "etl", "proc", out="r", inn="l")
    p.edge("de5", "etl", "manifest", out=(0.8, 1), inn=(0.2, 0))
    p.edge("de6", "proc", "t-now", out=(1, 0.3), inn="l")
    p.edge("de7", "proc", "t-fc", out=(1, 0.5), inn="l")
    p.edge("de8", "proc", "t-new", out=(1, 0.7), inn="l", style="dashed=1;")
    p.edge("de9", "t-now", "c1", out=(1, 0.3571), inn="l")
    p.edge("de10", "t-now", "c2", out=(1, 0.75), inn="l")
    p.edge("de11", "t-fc", "c3", out="r", inn="l", style="dashed=1;")
    p.edge("de12", "t-new", "c4", out=(1, 0.3), inn="l", style="dashed=1;")
    p.edge("de13", "t-new", "c5", out=(1, 0.75), inn="l", style="dashed=1;")
    p.legend(1360, 540, ["done", "plan"])
    return p


def build() -> None:
    mxfile = ET.Element("mxfile", host="drawio", version="26.0.0")
    for page in (page_overview(), page_hiring(), page_qa(), page_sourcing(), page_data()):
        names = {"overview": "1 全貌", "hiring": "2 招募流程×功能", "qa": "3 問答流程",
                 "sourcing": "4 找人 agent", "data": "5 資料管線"}
        d = ET.SubElement(mxfile, "diagram", id=page.name, name=names[page.name])
        model = ET.SubElement(d, "mxGraphModel", grid="1", gridSize="10", page="1", pageScale="1",
                              pageWidth="1700", pageHeight="1400", math="0", shadow="0")
        root = ET.SubElement(model, "root")
        ET.SubElement(root, "mxCell", id="0")
        ET.SubElement(root, "mxCell", id="1", parent="0")
        for c in page.cells:
            # 每頁 id 唯一即可；加頁名前綴避免跨頁重複
            for key in ("id", "parent", "source", "target"):
                v = c.get(key)
                if v and v not in ("0", "1") and not v.startswith(page.name + "-"):
                    c.set(key, f"{page.name}-{v}")
            root.append(c)
    ET.indent(mxfile)
    xml = ET.tostring(mxfile, encoding="unicode").replace("&amp;#xa;", "&#xa;")
    OUT.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
