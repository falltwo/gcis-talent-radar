[繁體中文](README.md) | **English**

# Industry Talent Radar

Before a factory expands and starts hiring, the owner wants to know a few things. Are competitors nearby opening up or shutting down? How many job openings are in the district right now? What is the wage level? Industry Talent Radar answers these questions from Taiwan government open data. Every number comes with its source and data period. When the data doesn't cover something, the system says so.

This is an entry in the 2026 InnoServe Awards, Business Governance AI Innovation track (GCIS-OD). Taichung manufacturing is the demo scope.

The app UI and the data are in Traditional Chinese.

![Home page Q&A: manufacturing openings in Daya District](docs/images/answer.png)

## What it answers

| Question | Data | Granularity |
|---|---|---|
| Are firms in my industry opening, raising capital, or dissolving in this district? | MOEA company registration and change records, mapped to manufacturing sub-sectors via tax industry codes | Taichung district × manufacturing sub-sector × month |
| How many factories are in this district? | Taichung Economic Development Bureau factory counts ([data.gov.tw 174209](https://data.gov.tw/dataset/174209)) | District × factory category × month |
| How many public job openings are in this district now? | Taiwan Jobs vacancy list ([data.gov.tw 44062](https://data.gov.tw/dataset/44062)) | District, daily snapshot |
| What is the citywide trend in new manufacturing companies? | MOEA open data: new company statistics by industry and county | Taichung citywide × industry section × month |
| What is the wage level? | Bureau of Labor Insurance insured-salary statistics ([data.gov.tw 100999](https://data.gov.tw/dataset/100999)) | Taichung citywide × industry section × year-end |

Data at different levels of detail is never combined. City-level figures are not broken down to districts. Openings are not the same as labor shortage, and insured salary is not take-home pay.

## How every number gets a source

```
question → scope check → fair-hiring check → model picks tools → code queries official data → model writes answer → number check → answer + audit trail
                           │ rejected: refuse, no model call                                       │ any mismatch: block the whole answer
                           └──────────── every step is logged (hashes only) ─────────────────────────┘
```

1. **Code computes, the model explains.** The model calls read-only data tools through function calling. Each tool returns values together with the data period, source URL, and limitations.
2. **Every number is checked before the answer goes out.** `agent/numeric_verifier.py` matches each number and date in the answer against the tool results. If any of them fails, the whole answer is blocked and the model's text is not shown.
3. **Fair-hiring guard.** Article 5 of Taiwan's Employment Service Act bans hiring discrimination. Requests that screen or rank candidates by age, sex, nationality, disability, religion, or similar traits are refused before any model call (`agent/prompt_guard.py`). Questions such as "how do I avoid age discrimination in hiring" pass.
4. **Audit log stores hashes only.** Each question is appended to `reports/agent_audit.jsonl`. An entry holds the question's SHA-256, its length, the rule outcomes, the tools used, and the check status. Question text, answers, and keys are never written. If the log cannot be written, the request stops and the API returns 503.
5. **The audit trail is visible.** Under each answer, users can expand what was queried, how it was computed, and what the limits are.

![Audit trail](docs/images/trace.png)

## Forecasts are ranges

The forecast engine lives in `forecast/`. Every series runs simple baselines first, then complex models. Models are picked by rolling-origin backtest. Only 80% intervals are published, never a single number.

| Series | Span | Backtest origins | Selected model | MAE | Seasonal Naive MAE |
|---|---|---:|---|---:|---:|
| New manufacturing companies, Taichung | 2012-06 to 2026-08 (171 months) | 45 | Chronos-Bolt-tiny | 24.1 | 27.9 |
| New job vacancies, public employment service | 2022-01 to 2026-06 (54 months) | 6 | Seasonal Naive | 917.5 | — |

The newer model does not always win. On job vacancies, Seasonal Naive beats Chronos. The 80% interval for new manufacturing companies citywide in 2026-09 is 61 to 95. Backtest method, metrics, and how missing official months were recovered are in [docs/FORECAST_ENGINE.md](docs/FORECAST_ENGINE.md) (Chinese).

## Quick start

You need Python 3.10 or later. AI Q&A needs an OpenRouter API key.

```bash
git clone https://github.com/falltwo/gcis-talent-radar.git
cd gcis-talent-radar
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn pandas numpy requests xlrd openpyxl statsmodels pytest

cp .env.example .env      # put OPENROUTER_API_KEY in .env
python server.py
```

Open `http://127.0.0.1:8888/`. If port 8888 is taken, `server.py` picks another port and prints the URL.

- Only the backend reads the key. Keep it out of `ui/`, frontend environment variables, and Git. `.env` is already in `.gitignore`.
- The default model is `openai/gpt-6-luna`. Override it with `OPENROUTER_MODEL`.
- The server also starts without a key. The expansion-scenario cards on the home page and the `/api/official/*` endpoints still work.

### Refresh the data

```bash
python -m etl.run_real_etl                     # download (skips existing) + build tables + quality report
python -m etl.run_real_etl --only taiwanjobs   # today's Taiwan Jobs snapshot only
python -m forecast.run_real --series gcis --horizon 12 --step 3
```

Each run updates the following:

- `data/raw/_manifest.csv`: source URL, time, and SHA-256 of each raw file
- `data/processed/_catalog.json`
- `reports/DATA_QUALITY.md`

See [docs/04-ETL.md](docs/04-ETL.md) (Chinese).

### Tests

```bash
python -m pytest tests -q
```

There are 345 tests covering ETL, data tools, forecasting, guards, and audit logging. GitHub Actions runs them on every PR and on pushes to `main`.

## Pages and API

| Path | What it is |
|---|---|
| `/` | Home: Q&A plus the expansion scenario (defaults to Daya District, hiring 10) |
| `/demo` | Single-page version of the expansion scenario |
| `/docs` | FastAPI auto-generated API docs |
| `POST /api/agent/chat` | AI Q&A |
| `GET /api/demo/expansion` | The four official figures behind the expansion scenario |
| `GET /api/official/job-demand`, `company-trend`, `wage-baseline` | The three official-data tools |
| `/legacy` | Old prototype with simulated data; not part of the demo |

## Layout

```
agent/      Q&A pipeline: scope check, fair-hiring guard, tool calls, number check, audit
engine/     data tools (official-data queries)
etl/        real-data download and cleaning (one module per source in etl/sources/)
forecast/   forecast engine and backtests
api/        FastAPI routes
ui/         frontend pages
data/       raw files and processed tables
reports/    data-quality report, forecast outputs, audit log
tests/      pytest
docs/       design and data docs (Chinese)
```

## Limitations

- **Older tables still hold simulated data.** This repo grew out of an early prototype. Some tables are still simulated or imputed, including industry momentum, supply–demand mismatch, and parts of the higher-education projections. The list is in [docs/SIMULATED_DATA.md](docs/SIMULATED_DATA.md). When the assistant uses those tools, the answer labels the values as simulated. Every figure on the home page comes from the official sources above.
- **Job snapshots are capped.** The Taiwan Jobs API returns at most 1,000 rows per query, so totals for districts that hit the cap run low. Job industry is matched by keywords in job titles and categories, not by the employer's registered industry.
- **The guards are rules, not models.** The scope check and the fair-hiring guard are local keyword and regex rules. They can miss cases or misfire, and they are not legal compliance certification. A second gate, a safety model judging against a custom policy, is still on a development branch and not merged.
- **The number check covers values only.** It confirms each number in an answer appears in the tool results. It does not confirm that meaning or units are right.

## Docs (Chinese)

- [docs/04-初賽展示主線.md](docs/04-初賽展示主線.md): demo walkthrough and where each number comes from
- [docs/05-三項官方資料工具實作.md](docs/05-三項官方資料工具實作.md): scope and acceptance of the three official-data tools
- [docs/GOVERNANCE.md](docs/GOVERNANCE.md): guard order and audit fields
- [docs/FORECAST_ENGINE.md](docs/FORECAST_ENGINE.md): models, backtests, recovery of missing official months
- [docs/04-ETL.md](docs/04-ETL.md): table list and how to run ETL
- [docs/SIMULATED_DATA.md](docs/SIMULATED_DATA.md): simulated data not yet replaced

## Data sources and license

Government data is used under the [Open Government Data License, version 1.0](https://data.gov.tw/license). Sources:

- MOEA Commerce Industrial Services open data platform
- data.gov.tw
- Taichung City Economic Development Bureau
- Workforce Development Agency, Ministry of Labor
- Bureau of Labor Insurance, Ministry of Labor

This project has no open-source license yet. All rights reserved by the authors.

Adapted from [DrChunChihChen/taichung-industry-talent-radar](https://github.com/DrChunChihChen/taichung-industry-talent-radar).
