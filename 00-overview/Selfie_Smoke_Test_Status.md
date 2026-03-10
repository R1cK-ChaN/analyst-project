# Selfie Smoke Test — Status

**Date:** 2026-03-10
**Commit:** 619394b (Add companion persona mode and selfie scene system)

---

## What was tested

### Unit tests (all passing — 354 total)

- `test_cli.py` — 7 tests covering:
  - generic image CLI (`media-gen image --prompt ...`)
  - selfie mode CLI (`media-gen image --mode selfie --scene-key coffee_shop`)
  - `--json` flag manifest output
  - selfie with `--scene-prompt` override
  - live-photo CLI
  - sales-chat `--once` flow
- `test_image_gen.py` — 10 tests: handler routing, base64/URL responses, selfie delegation, timeout fallback, attached image context, watermark flag, retry logic
- `test_selfie_persona.py` — 3 tests: bootstrap + state persistence, selfie request detection, transient retry behavior
- `test_live_photo.py` — 14 tests: SeedDance polling, selfie-to-motion two-stage flow, fallback chains, Live Photo packaging, tool availability gating

All mocked — no live API calls.

### Live endpoint verification

**API connectivity: CONFIRMED**

Direct curl to `https://ark.cn-beijing.volces.com/api/v3/images/generations` with the production `VOLCENGINE_API_KEY` succeeds:

```
curl POST /images/generations
  model: doubao-seedream-5-0-260128
  prompt: "a red circle on white background"
  size: 2048x2048
  response_format: url
  watermark: false

Result: 200 OK — returned image URL, 16384 output tokens
```

The Volcengine Ark API is live, auth works, and Seedream image generation returns valid results.

**CLI selfie smoke test: PARTIAL (fallback path exercised)**

```
python3 -m analyst media-gen image --mode selfie --scene-key coffee_shop \
  --output-dir /tmp/selfie-smoke-test --json
```

Result:
- Selfie bootstrap (4 anchor images) timed out — Python `requests.Session` hit `TimeoutError` on repeated POST calls (`('Connection aborted.', TimeoutError('The write operation timed out'))`)
- Fallback path triggered correctly: produced a generic coffee_shop scene image via single Seedream call
- Output: `status: "ok"`, `fallback_kind: "generic_image"`, valid `image_url` pointing to a real Volcengine TOS-signed JPEG
- Scene metadata preserved: `scene_key: "coffee_shop"`, `scene_prompt` and `negative_prompt_used` populated correctly

---

## Root cause of bootstrap timeout

The selfie bootstrap needs 4 sequential Seedream generations (each ~10-20s at the API). From this machine, the Python `requests` session loses its TCP connection after the first successful response, causing subsequent POSTs to fail with `ConnectionAborted / write timeout`.

Curl (single-shot) works fine. The issue is likely:

1. **Connection keep-alive mismatch** — the Volcengine load balancer may close idle connections faster than Python's `requests.Session` connection pool expects
2. **Network path instability** — the route from this machine to `101.126.13.31` (Beijing) has high latency; sustained connections degrade
3. **Rate limiting** — sequential rapid-fire image generations may trigger per-key throttling

The 120s per-request timeout is generous, but the session reuse + sequential pattern makes the bootstrap fragile from high-latency locations.

---

## What needs to happen next

### Must fix

1. **Connection resilience for bootstrap** — either:
   - Create a fresh `requests.Session` per generation call during bootstrap (avoid stale pooled connections)
   - Add explicit `Connection: close` header to force no keep-alive
   - Add a short delay between bootstrap calls (e.g., 2s) to avoid thundering the same TCP socket
2. **Re-run the full selfie smoke test** from a lower-latency location (production Contabo VPS is closer to China endpoints)

### Should verify

3. **Selfie bootstrap on production server** — the Contabo VPS in Germany may have better routing to Volcengine Beijing than this machine
4. **SeedDance motion video endpoint** — `media-gen live-photo --mode selfie` not yet tested live (same connectivity concern)
5. **Image download reliability** — the first run also showed a download timeout (`ark-acg-cn-beijing.tos-cn-beijing.volces.com` read timeout), suggesting TOS object storage has the same latency issue

### Nice to have

6. **Pytest marker for live tests** — add `@pytest.mark.live` to a real integration test that can be run with `pytest -m live` when network access is available
