# Macro Data Service Split

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
