# Recruitment Browser Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan task-by-task.

**Goal:** 展示可編輯需求、Agent 填表、人工預覽與確認後的模擬發布。
**Architecture:** 純狀態機管理不可自動跨越的發布關卡；獨立 UI 模組與 CSS 沿用現有模式切換。
**Tech Stack:** 原生 JS、CSS、Node test runner。
**Spec:** docs/superpowers/specs/2026-11-03-recruitment-browser-design.md

## Global Constraints
- 不呼叫真網站、模型或外部發布 API；只用模擬資料與固定腳本。
- 預覽後必須由使用者另行確認發布；編輯或退出使待處理流程失效。
- 不覆蓋既有未追蹤檔案，不推送或合併遠端。

## Review Focus
- 薪資倒置／空欄位不得開始。
- 計時器跑完不可自動發布。
- 重做後不可重用舊確認。
- 切換功能後不得繼續動畫或顯示發布。
- 輸入以 textContent 呈現，避免 HTML 插入。

### Task 1: 狀態機與工作台
**Files:** ui/static/recruitment-flow.js、recruitment.js、recruitment.css；ui/home.html、ui/static/radar-city.js；tests/frontend/recruitment-flow.test.cjs。
**Interfaces:** PostingFlow.start(draft)、advance()、publish(confirmed)、cancel()；window.recruitment.toggle()/deactivate()。
- [x] 撰寫並執行狀態機測試，先確認缺少實作失敗。
- [x] 實作狀態機與雙欄工作台，接上功能互斥切換。
- [x] 執行 node --test tests/frontend/recruitment-flow.test.cjs，預期全部通過。
- [x] 瀏覽器實測填表→預覽→確認發布、退出停止與切換，再截圖。
- [x] 檢查 JS 語法、差異與前端資源；記錄驗證結果。

## Execution record
Pre-flight: single task, no shared task interfaces.
Implementation follows approved local-only demonstration scope. Existing isolated local integration branch used; no additional worktree or remote push.
Review: independent reviewer identified comma-separated company-hires parsing; reproduced with failing assertion then fixed and verified 5/5 Node tests.
Verification details: docs/RECRUITMENT_BROWSER_DEMO.md.

## 第二版執行（已授權）
1. 新增狀態機測試：最小需求可開始、缺薪資必須停在審核、編輯後單次確認、暫停與略過動畫、退回草稿。
2. 更新狀態機支援薪資待補與來源；以需求卡片／來源節點／可編輯審核替換舊全欄必填表單。
3. 驗證 Node 測試與前端語法，瀏覽器操作整個流程與切換取消，保存截圖；不推送。

V2 completed: minimal brief/state tests RED→GREEN (8/8); browser verifies one review, missing salary, pause/skip and review edits retained. Independent review findings reproduced in browser then fixed: return draft preservation, provenance explanation; pause label resets too. Syntax/diff and assets verified. No real model/search/publishing calls.

## 第三版計畫
- 加入審核重點判定測試（無效值／待確認／範本；人工修改有效時不突出）。
- 分階段版面、明暗角色配色、進入審核標頭與篩選，游標移動／點擊／輸入／完成回饋。
- Node 測試、語法檢查及瀏覽器實測初始、作業、審核篩選、薪資攔截與單次完成；截圖保存。

V3 completed: focus helper RED→GREEN, 9 Node tests pass; Python 516 pass. Browser validated layout handoff, review filter returning salary/skills only, no active writing/cursor at review, hidden-field validation and inverted salaries blocked, single approval success. Independent read-only review found no important defects. Finished progress bar hidden on review to recover viewport space. No remote push.

## 第四版試作計畫
- 新增獨立 map-layout 樣式，地圖左右面板與中央工作／審核同座標，避免再動畫。
- FLIP 量測右側初始位置並放大／回彈到中央，取消或退出時清理 Web Animation；減少動態時直接切換。
- 接回地圖按鈕與同選點模擬成果標記；保留審核關卡和來源說明。
- 跑現有 9 項流程測試、語法與資產檢查；瀏覽器確認初始可見地圖、居中／審核位置不變、完成回收並保留標記。

V4 completed: map-overlay layout and 950ms FLIP, same working/review geometry, reduced-motion branch, success counter bound to captured coordinate. Node tests 9 pass; assets/syntax/diff pass. Browser confirmed initial map gap, centered review 860x473 at [104.5,181] on 1069x663 map, zero center offset, successful one-review publication, reset to brief and 1-count marker. Independent read-only review: no important defects. No external publishing or push.

## 第五版計畫
1. 導航狀態測試先失敗，加入輸入網址／載入完成後才可填表的控制。
2. 新增本機模擬站與瀏覽器外框，接導航→填寫、暫停恢復與略過。
3. 獨立 map-effects 模組接送出／審核／發布／退出；沿 map.project 更新示意線與端點、保存還原鏡頭。
4. Node 測試、語法資產檢查及瀏覽器驗證導航順序、訊號停止／回傳、退出清理與原審核規則。

V5 completed: navigation tests RED→GREEN, 11 pass. Local mock site HTTP 200 and inline JS checked. Browser confirms no entry signal, ordered navigation logs before first field, paused operation, review hides packet, completion return/wave, stop restores original pin x and clears signal. Independent reviewer identified standalone salary custom-validity dependency; reproduced then fixed and rechecked in browser (corrected minimum permits submit). No external API or push.
