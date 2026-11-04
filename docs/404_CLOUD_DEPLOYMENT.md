# 404徵才網：上雲端

名稱已更新於獨立展示頁與人才雷達的招募視窗。已發布 GitHub Pages 靜態展示站，以下保留其他平台的部署參考。

## 已發布：GitHub Pages（2026-11-04）

- 公開網站：https://evaeva12021202-sys.github.io/404-jobs/
- 獨立儲存庫：https://github.com/evaeva12021202-sys/404-jobs
- 發布來源：`main` 分支根目錄，入口為 `index.html`。
- 已驗證公開網址 HTTP 200，頁面名稱為「404徵才網」。
- 僅發布前端展示，未上傳 API key、分析資料庫、履歷或原專案其他檔案。
- 此版仍為模擬填表與刊登，不會啟用 AI 或永久保存資料。
- 日後在獨立儲存庫更新 `index.html` 並提交，GitHub Pages 會重新部署。
- 原專案 `scripts/build-404-site.mjs` 只建置本機檔案，**不會自動同步至這個獨立儲存庫**。先執行 `node scripts/build-404-site.mjs`，再將產出的 `dist/404-jobs/index.html` 更新到獨立儲存庫根目錄。

## 其他選擇：Render Static Site

這是最少步驟的方式，不需要雲端資料庫或 AI key。網站可以填表、驗證欄位及顯示模擬刊登成功；不會永久保存職缺，也不會呼叫 AI。

1. 將這次修改提交並推送到你自己的 GitHub 儲存庫。不要加入 `.env`、本機資料庫或私人履歷。
2. 到 Render 控制台選 New → Static Site，連接該 GitHub 儲存庫及包含這次修改的分支。
3. 專案根目錄維持儲存庫根目錄。設定：

| 欄位 | 值 |
| --- | --- |
| Name | jobs-404（或其他可用名稱） |
| Build Command | `node scripts/build-404-site.mjs` |
| Publish Directory | `dist/404-jobs` |
| Environment Variable | `SKIP_INSTALL_DEPS=true` |

4. 選 Create Static Site。建置成功後，Render 會給你可公開分享的 HTTPS `.onrender.com` 網址；實際名稱依可用性決定。
5. 開啟公開首頁，確認顯示「404徵才網」，填表測試薪資上下限與模擬刊登。

建置程式只輸出 `index.html`，不會把後端、金鑰、資料庫或人才雷達其他功能放進網站。若改用支援直接上傳資料夾的靜態平台，執行 `node scripts/build-404-site.mjs`，上傳 `dist/404-jobs` 內容即可。Render 上述流程使用 Git 儲存庫部署。

Render 靜態站目前可免費部署，但有平台用量限制；取得自訂網域需自行註冊網域並設定 DNS。

## 要上線完整 AI 招募功能

目前前端仍是模擬，尚未改接 `/api/recruitment/mvp`；單純部署 HTML 不會啟用 AI 或資料保存。完整上線需要：

1. 把前端接上註冊／登入、批次草稿、編輯、確認與刊登 API；只有 HR 確認後才可正式寫入。
2. 用 Render Web Service 或其他支援 Python 的平台部署 FastAPI 後端。
3. 使用 PostgreSQL 保存招募資料，設定 `RECRUITMENT_DATABASE_URL=postgresql+psycopg://...`。
4. 在平台後端環境設定 `OPENROUTER_API_KEY`、支援 structured outputs 的 `OPENROUTER_MODEL` 及 `LLM_MODE=auto`；不可把 key 放到 HTML。
5. 首批 HR 帳號建立後，可將 `ALLOW_REGISTRATION=false` 關閉開放註冊。

若只部署招募後端，而不部署整個人才雷達，可使用：

- Build Command：`pip install -r requirements-recruitment.txt`
- Start Command：`uvicorn recruitment.backend.main:create_app --factory --host 0.0.0.0 --port $PORT`
- API 文件：`https://你的後端網址/docs`（這個獨立啟動方式沒有 `/api/recruitment/mvp` 前綴）。
- 前後端不同網域時，需在後端加入限定前端網址的 CORS 設定。

不要直接用 `server.py` 當雲端啟動指令：它目前綁定本機位址與固定候選埠。完整人才雷達若要同時上線，還需準備其分析資料庫、報告儲存與其他依賴，不能只裝招募套件。

Render 免費 Web Service 會閒置休眠，本機檔案會在重啟或重新部署等情況消失，因此不能依賴本機 SQLite 保存正式職缺。免費 Render PostgreSQL 目前建立後 30 天到期；正式服務請選可持續保存資料的方案，費用另計。

## 官方說明

- 靜態站：https://render.com/docs/static-sites
- FastAPI：https://render.com/docs/deploy-fastapi
- 免費方案限制：https://render.com/docs/free
