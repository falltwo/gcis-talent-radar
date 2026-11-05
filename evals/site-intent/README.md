# Site-intent eval

Ten siting sentences checked against `engine/site_intent.py`, the code behind `POST /api/site-intent`. The provider calls the real `parse()`, so the eval tests what ships, model included.

Each run makes one paid OpenRouter call per test (10 calls). It needs `OPENROUTER_API_KEY` in `.env`.

```bash
cd evals/site-intent
PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_PYTHON=/path/to/python npx promptfoo@0.125.1 eval --no-cache --no-share
```

`PROMPTFOO_PYTHON` must be a Python with the project requirements installed.

What the cases cover: industry, role, senior role and head count from one sentence; each of the four criteria; conditions the site scan has no data for (interchange, land price); a sentence with nothing to extract; and instructions written inside the text.

The preference chip is applied by code, not the model, and a role is kept only when the user wrote it, so neither depends on the model.
