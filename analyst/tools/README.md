# tools/

Tool implementations used by the companion agent.

## Files

| File | Status | Notes |
|------|--------|-------|
| `_image_gen.py` | Active | Image generation via SeedDream API |
| `_live_photo.py` | Active | Live photo (image + motion video) generation |
| `_web_search.py` | Active | Web search via OpenRouter plugins API |
| `_search_router.py` | Active | Smart search router: keyword-routes to Places/Weather/web |
| `_places.py` | Active | Google Places API (Text Search) handler |
| `_weather.py` | Active | OpenWeatherMap API handler with 1hr cache |
| `_selfie_persona.py` | Active | Selfie persona consistency engine |
| `_ffmpeg.py` | Active | FFmpeg subprocess wrapper |
| `_request_context.py` | Active | Request-local image binding |
| `_registry.py` | Active | ToolKit builder class |

No legacy files in this module.
