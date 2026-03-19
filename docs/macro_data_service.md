# Service Splits

## Macro Data Service

The macro-data service codebase now lives separately at:

```text
/home/rick/Desktop/analyst/macro-data-service
```

`analyst-project` consumes that service over HTTP when these env vars are set:

```text
ANALYST_MACRO_DATA_BASE_URL=http://127.0.0.1:8765
ANALYST_MACRO_DATA_API_TOKEN=
```

## Run the standalone service

```bash
cd /home/rick/Desktop/analyst/macro-data-service
python -m venv .venv
. .venv/bin/activate
pip install -e .
macro-data-service serve --host 127.0.0.1 --port 8765
```

Direct server entrypoint also works:

```bash
macro-data-api --host 127.0.0.1 --port 8765
```

## Agent side

Start `analyst-project` with:

```text
ANALYST_MACRO_DATA_BASE_URL=http://127.0.0.1:8765
ANALYST_MACRO_DATA_API_TOKEN=
```

If `ANALYST_MACRO_DATA_BASE_URL` is unset, `analyst-project` falls back to its local in-process adapter.

## HTTP contract

- `GET /health`
- `POST /v1/ops/<operation>`

Request shape:

```json
{
  "arguments": {}
}
```

Response shape:

```json
{
  "...": "operation-specific payload"
}
```

## Verified communication path

The current contract is verified by:

- `analyst-project/tests/test_macro_data_integration.py`
- `macro-data-service/tests/test_macro_data_cli.py`

The integration test starts the extracted service as a separate process, points `analyst-project` at it over localhost HTTP, verifies auth header handling, and checks that recent-release and news queries return seeded data through `HttpMacroDataClient`.

---

## Research Service

The research agent codebase now lives separately at:

```text
/home/rick/Desktop/analyst/research-service
GitHub: https://github.com/R1cK-ChaN/research-service
```

The companion agent calls the research service over HTTP when `ANALYST_RESEARCH_BASE_URL` is set. Without it, the companion runs without research capabilities (image/photo tools only).

### Run the research service

```bash
cd /home/rick/Desktop/analyst/research-service
OPENROUTER_API_KEY=<key> ANALYST_MACRO_DATA_BASE_URL=http://127.0.0.1:8765 \
  python3 -m research.server --port 8766
```

### Companion side

Set these env vars for `analyst-project`:

```text
ANALYST_RESEARCH_BASE_URL=http://127.0.0.1:8766
ANALYST_RESEARCH_API_TOKEN=           # optional
```

The companion's `build_research_delegate_tool()` (in `src/analyst/research/delegate.py`) creates a tool named `research_agent` with the same parameters and return shape as the old in-process sub-agent. The companion LLM sees no difference.

### HTTP contract

- `GET /healthz` — liveness probe
- `GET /health` — component health status
- `POST /v1/ops/investigate` — run research agent loop

Request:

```json
{
  "arguments": {
    "task": "What moved US equities today?",
    "goal": "Explain the move simply.",
    "analysis_type": "markets",
    "time_horizon": "today",
    "output_format": "summary",
    "context": "optional user-safe context"
  }
}
```

Response:

```json
{
  "status": "ok",
  "result": "S&P 500 rose 0.8% driven by...",
  "turns_used": 3
}
```

### What the research service contains

- 20 research tools (markets, macro, news, calendar, portfolio, analysis operators, artifact cache, Python sandbox, web search)
- 13 typed analysis operators (Series/Dataset/Metric/Signal)
- `PythonAgentLoop` (4-turn, 1400 tokens, temp 0.2)
- PLAN → ACQUIRE → COMPUTE → INTERPRET system prompt policy
- SQLite storage (artifact cache, regime snapshots, audit trail)
- Docker sandbox for Python code execution
- 26 tests

### Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `OPENROUTER_API_KEY` | yes | — | LLM API key |
| `ANALYST_MACRO_DATA_BASE_URL` | yes | — | macro-data-service URL |
| `ANALYST_RESEARCH_HOST` | no | `127.0.0.1` | Bind address |
| `ANALYST_RESEARCH_PORT` | no | `8766` | Listen port |
| `ANALYST_RESEARCH_API_TOKEN` | no | — | Bearer token auth |
| `ANALYST_RESEARCH_MODEL` | no | `google/gemini-3.1-flash-lite-preview` | LLM model |
