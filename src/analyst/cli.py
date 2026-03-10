from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import json
import mimetypes
from pathlib import Path
import shutil
from urllib.parse import urlparse

from analyst.contracts import format_epoch
from analyst.delivery.sales_chat import (
    ChatPersonaMode,
    build_chat_services,
    build_sales_services,
    generate_chat_reply,
    generate_sales_reply,
    resolve_chat_persona_mode,
    split_into_bubbles,
)
from analyst.memory import build_chat_context, build_sales_context, record_chat_interaction, record_sales_interaction
from analyst.storage.sqlite import NewsArticleRecord, StoredEventRecord
from analyst.tools import build_image_gen_tool, build_live_photo_tool
from analyst.tools._image_gen import GeneratedImage, ImageGenConfig, SeedreamImageClient
from analyst.tools._request_context import RequestImageInput, bind_request_image

from .app import build_demo_app, build_live_engine_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone Analyst product demo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask = subparsers.add_parser("ask")
    ask.add_argument("question")

    draft = subparsers.add_parser("draft")
    draft.add_argument("request")

    prep = subparsers.add_parser("meeting-prep")
    prep.add_argument("request")

    route = subparsers.add_parser("route")
    route.add_argument("message")

    regime = subparsers.add_parser("regime")
    regime.add_argument("--focus", default="global")

    calendar = subparsers.add_parser("calendar")
    calendar.add_argument("--limit", type=int, default=5)

    premarket = subparsers.add_parser("premarket")
    premarket.add_argument("--focus", default="global")

    refresh = subparsers.add_parser("refresh")
    refresh.add_argument("--once", action="store_true", help="Refresh all WS1 sources once")

    live_cal = subparsers.add_parser("live-calendar")
    live_cal.add_argument("--scope", choices=["today", "upcoming", "recent", "week"], default="today")
    live_cal.add_argument("--country", default=None)
    live_cal.add_argument("--category", default=None)
    live_cal.add_argument("--importance", default=None)
    live_cal.add_argument("--limit", type=int, default=20)

    subparsers.add_parser("schedule")

    flash = subparsers.add_parser("flash")
    flash.add_argument("--indicator")

    subparsers.add_parser("briefing")
    subparsers.add_parser("wrap")
    subparsers.add_parser("regime-refresh")

    news_refresh = subparsers.add_parser("news-refresh")
    news_refresh.add_argument("--category", default=None)

    news_latest = subparsers.add_parser("news-latest")
    news_latest.add_argument("--limit", type=int, default=20)
    news_latest.add_argument("--impact", default=None)
    news_latest.add_argument("--category", default=None)

    news_search = subparsers.add_parser("news-search")
    news_search.add_argument("query")
    news_search.add_argument("--limit", type=int, default=20)

    news_feeds_parser = subparsers.add_parser("news-feeds")
    news_feeds_parser.add_argument("--category", default=None)

    portfolio_import = subparsers.add_parser("portfolio-import")
    portfolio_import.add_argument("csv_path", help="Path to CSV file with holdings")
    portfolio_import.add_argument("--portfolio-id", default="default")
    portfolio_import.add_argument("--db-path", default=None)

    portfolio_sync = subparsers.add_parser("portfolio-sync")
    portfolio_sync.add_argument("--broker", default="ibkr", help="Broker adapter (default: ibkr)")
    portfolio_sync.add_argument("--account", default="", help="Broker account ID (auto-detect if omitted)")
    portfolio_sync.add_argument("--gateway-url", default="", help="Override gateway URL")
    portfolio_sync.add_argument("--portfolio-id", default="default")
    portfolio_sync.add_argument("--db-path", default=None)
    portfolio_sync.add_argument("--dry-run", action="store_true", help="Show positions without persisting")

    portfolio_risk = subparsers.add_parser("portfolio-risk")
    portfolio_risk.add_argument("--portfolio-id", default="default")
    portfolio_risk.add_argument("--json", action="store_true", dest="as_json")
    portfolio_risk.add_argument("--db-path", default=None)

    sales_chat = subparsers.add_parser("sales-chat")
    sales_chat.add_argument("--client-id", default="cli-demo")
    sales_chat.add_argument("--channel-id", default="cli:local")
    sales_chat.add_argument("--thread-id", default="main")
    sales_chat.add_argument("--focus", default="global")
    sales_chat.add_argument("--db-path", default=None)
    sales_chat.add_argument(
        "--persona-mode",
        choices=[ChatPersonaMode.SALES.value, ChatPersonaMode.COMPANION.value],
        default=ChatPersonaMode.SALES.value,
    )
    sales_chat.add_argument("--once", default=None, help="Run a single sales chat turn and exit.")
    sales_chat.add_argument(
        "--show-profile",
        action="store_true",
        help="Print the stored client profile after each assistant reply.",
    )

    media_gen = subparsers.add_parser("media-gen")
    media_gen.add_argument("kind", choices=["image", "live-photo"])
    media_gen.add_argument("--prompt", default="", help="English prompt for generic image/video generation.")
    media_gen.add_argument("--mode", default="", help="Use 'selfie' for persona-consistent selfie generation.")
    media_gen.add_argument("--scene-key", default="", help="Optional predefined selfie scene key.")
    media_gen.add_argument("--scene-prompt", default="", help="Optional extra scene detail.")
    media_gen.add_argument("--duration-seconds", type=int, default=3, help="Motion duration for live-photo mode.")
    media_gen.add_argument("--attached-image", default=None, help="Optional local image path for image-to-image or image-to-video.")
    media_gen.add_argument("--output-dir", required=True, help="Directory to store generated media artifacts.")
    media_gen.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Print the final saved-artifact manifest as JSON.",
    )

    return parser


def format_calendar_event(event: StoredEventRecord) -> str:
    stars = {"high": "***", "medium": "**", "low": "*"}.get(event.importance, "*")
    actual = event.actual or "-"
    forecast = event.forecast or "-"
    previous = event.previous or "-"
    dt = format_epoch(event.timestamp)
    source = event.source.upper()
    return (
        f"{dt}  {event.country:>2} {stars:>3}  [{source:<12}]  "
        f"{event.indicator:<40}  A:{actual:<8} F:{forecast:<8} P:{previous}"
    )


def format_news_headline(article: NewsArticleRecord) -> str:
    dt = format_epoch(article.timestamp)
    impact = article.impact_level.upper()
    country = article.country or "--"
    subject = f"  [{article.subject}]" if article.subject else ""
    return (
        f"{dt}  {country:>2} [{impact:<8}]  [{article.source_feed:<20}]  "
        f"{article.title}{subject}"
    )


def _run_portfolio_sync(args: argparse.Namespace) -> int:
    from analyst.portfolio import create_broker_adapter, validate_holdings
    from analyst.portfolio.brokers import BrokerAuthError, BrokerConnectionError
    from analyst.storage import SQLiteEngineStore

    try:
        adapter = create_broker_adapter(
            args.broker,
            gateway_url=args.gateway_url,
            account_id=args.account,
        )
        result = adapter.fetch_positions(account_id=args.account)
    except BrokerAuthError as exc:
        print(f"AUTH ERROR: {exc}")
        return 1
    except BrokerConnectionError as exc:
        print(f"CONNECTION ERROR: {exc}")
        return 1
    except ValueError as exc:
        print(f"CONFIG ERROR: {exc}")
        return 1

    if not result.holdings:
        print(f"No positions found in {args.broker} account {result.account_id}.")
        for s in result.skipped:
            print(f"  SKIPPED: {s}")
        return 0

    warnings = validate_holdings(result.holdings)
    warnings.extend(result.warnings)
    for w in warnings:
        print(f"WARNING: {w}")

    print(f"\n{len(result.holdings)} positions from {result.broker} account {result.account_id}:")
    for h in result.holdings:
        print(f"  {h.symbol:>8}  {h.weight:>6.1%}  ${h.notional:>12,.0f}  {h.asset_class:<14} {h.name}")
    if result.skipped:
        print(f"\nSkipped {len(result.skipped)} positions:")
        for s in result.skipped:
            print(f"  {s}")

    if args.dry_run:
        print("\n[dry-run] No changes written.")
        return 0

    db_path = Path(args.db_path) if args.db_path else None
    store = SQLiteEngineStore(db_path=db_path)
    store.replace_portfolio_holdings(
        [
            {
                "symbol": h.symbol,
                "name": h.name,
                "asset_class": h.asset_class,
                "weight": h.weight,
                "notional": h.notional,
            }
            for h in result.holdings
        ],
        portfolio_id=args.portfolio_id,
    )
    print(f"\nImported {len(result.holdings)} holdings into portfolio '{args.portfolio_id}'.")
    return 0


def _run_portfolio_import(args: argparse.Namespace) -> int:
    from analyst.portfolio import load_holdings_from_csv, validate_holdings
    from analyst.storage import SQLiteEngineStore

    db_path = Path(args.db_path) if args.db_path else None
    store = SQLiteEngineStore(db_path=db_path)
    holdings = load_holdings_from_csv(args.csv_path)
    warnings = validate_holdings(holdings)
    for w in warnings:
        print(f"WARNING: {w}")
    store.replace_portfolio_holdings(
        [
            {
                "symbol": h.symbol,
                "name": h.name,
                "asset_class": h.asset_class,
                "weight": h.weight,
                "notional": h.notional,
            }
            for h in holdings
        ],
        portfolio_id=args.portfolio_id,
    )
    print(f"Imported {len(holdings)} holdings into portfolio '{args.portfolio_id}'.")
    for h in holdings:
        print(f"  {h.symbol:>8}  {h.weight:>6.1%}  ${h.notional:>10,.0f}  {h.name}")
    return 0


def _run_portfolio_risk(args: argparse.Namespace) -> int:
    from analyst.portfolio import compute_portfolio_snapshot, load_portfolio_config
    from analyst.storage import SQLiteEngineStore

    db_path = Path(args.db_path) if args.db_path else None
    store = SQLiteEngineStore(db_path=db_path)
    config = load_portfolio_config()
    snapshot = compute_portfolio_snapshot(store, args.portfolio_id, config)
    if args.as_json:
        print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Portfolio Risk Snapshot  ({snapshot.as_of.strftime('%Y-%m-%d %H:%M UTC')})")
        print(f"  Annualized Vol : {snapshot.portfolio_vol_annualized:.1%}")
        print(f"  Daily Vol      : {snapshot.portfolio_vol_daily:.4f}")
        print(f"  Target Vol     : {snapshot.target_vol:.1%}")
        print(f"  Scale Factor   : {snapshot.scale_factor:.2f}")
        print(f"  VIX            : {snapshot.vix_level:.1f}  (P{snapshot.vix_percentile:.0f}, {snapshot.vix_regime})")
        print()
        print("  Risk Contributions:")
        for rc in snapshot.risk_contributions:
            print(f"    {rc.symbol:>8}  weight {rc.weight:>5.0%}  risk {rc.marginal_contribution:>5.0%}  standalone {rc.standalone_vol:>5.1%}")
        if snapshot.alerts:
            print()
            print("  Alerts:")
            for a in snapshot.alerts:
                print(f"    [{a.severity.upper():>7}] {a.message}")
    return 0


def _print_sales_profile(store, client_id: str) -> None:
    profile = store.get_client_profile(client_id)
    print("\n[profile]")
    print(json.dumps(asdict(profile), ensure_ascii=False, indent=2, sort_keys=True))


def _load_request_image(path_str: str) -> RequestImageInput:
    path = Path(path_str).expanduser().resolve()
    raw_bytes = path.read_bytes()
    mime_type, _ = mimetypes.guess_type(path.name)
    normalized_mime_type = mime_type if mime_type and mime_type.startswith("image/") else "image/jpeg"
    encoded = base64.b64encode(raw_bytes).decode("ascii")
    return RequestImageInput(
        data_uri=f"data:{normalized_mime_type};base64,{encoded}",
        mime_type=normalized_mime_type,
        filename=path.name,
    )


def _artifact_output_path(output_dir: Path, field_name: str, source: str = "") -> Path:
    suffix = Path(urlparse(source).path).suffix or Path(source).suffix
    fallback_suffix = {
        "image_path": ".png",
        "image_url": ".png",
        "delivery_video_path": ".mp4",
        "delivery_video_url": ".mp4",
        "live_photo_image_path": ".jpg",
        "live_photo_video_path": ".mov",
        "live_photo_manifest_path": ".json",
    }.get(field_name, ".bin")
    filename = {
        "image_path": "image",
        "image_url": "image",
        "delivery_video_path": "motion",
        "delivery_video_url": "motion",
        "live_photo_image_path": "live_photo",
        "live_photo_video_path": "live_photo_video",
        "live_photo_manifest_path": "live_photo_manifest",
    }.get(field_name, f"artifact_{field_name}")
    return output_dir / f"{filename}{suffix or fallback_suffix}"


def _materialize_media_result(output_dir: Path, result: dict[str, object]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str] = {}

    for field_name in ("image_path", "delivery_video_path", "live_photo_image_path", "live_photo_video_path", "live_photo_manifest_path"):
        raw_value = result.get(field_name)
        if not isinstance(raw_value, str) or not raw_value:
            continue
        source = Path(raw_value)
        if not source.is_file():
            continue
        target = _artifact_output_path(output_dir, field_name, raw_value)
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        saved[field_name] = str(target)

    image_url = result.get("image_url")
    if isinstance(image_url, str) and image_url and "image_path" not in saved:
        image_client = SeedreamImageClient(ImageGenConfig.from_env())
        target = _artifact_output_path(output_dir, "image_url", image_url)
        image_client.materialize_image(GeneratedImage(image_url=image_url), target)
        saved["image_path"] = str(target)

    delivery_video_url = result.get("delivery_video_url")
    if isinstance(delivery_video_url, str) and delivery_video_url:
        saved["delivery_video_url"] = delivery_video_url

    manifest_path = output_dir / "result.json"
    manifest = {
        "saved_artifacts": saved,
        "result": result,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    saved["result_json"] = str(manifest_path)
    return saved


def _build_media_arguments(args: argparse.Namespace) -> dict[str, object]:
    arguments: dict[str, object] = {}
    if args.prompt:
        arguments["prompt"] = args.prompt
    if args.mode:
        arguments["mode"] = args.mode
    if args.scene_key:
        arguments["scene_key"] = args.scene_key
    if args.scene_prompt:
        arguments["scene_prompt"] = args.scene_prompt
    if args.kind == "live-photo":
        arguments["duration_seconds"] = args.duration_seconds
    if args.attached_image:
        arguments["use_attached_image"] = True
    return arguments


def _run_media_gen(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir).expanduser().resolve()
    request_image = _load_request_image(args.attached_image) if args.attached_image else None
    arguments = _build_media_arguments(args)
    tool = build_image_gen_tool() if args.kind == "image" else build_live_photo_tool()

    with bind_request_image(request_image):
        result = tool.handler(arguments)

    if not isinstance(result, dict):
        print("ERROR: invalid tool result")
        return 1

    try:
        saved_artifacts = _materialize_media_result(output_dir, result)
    except Exception as exc:
        print(f"ERROR: failed to save generated media locally: {exc}")
        return 1

    if args.as_json:
        print(
            json.dumps(
                {"output_dir": str(output_dir), "saved_artifacts": saved_artifacts, "result": result},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"Generated {args.kind} artifacts in {output_dir}")
        print(json.dumps(saved_artifacts, ensure_ascii=False, indent=2, sort_keys=True))

    return 0 if result.get("status") == "ok" else 1


def _run_sales_chat(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path) if args.db_path else None
    persona_mode = resolve_chat_persona_mode(args.persona_mode)
    if persona_mode is ChatPersonaMode.SALES:
        agent_loop, tools, store = build_sales_services(db_path=db_path)
    else:
        agent_loop, tools, store = build_chat_services(db_path=db_path, persona_mode=persona_mode)
    history: list[dict[str, str]] = []

    def handle_turn(user_text: str) -> None:
        if persona_mode is ChatPersonaMode.COMPANION:
            memory_context = build_chat_context(
                store=store,
                client_id=args.client_id,
                channel_id=args.channel_id,
                thread_id=args.thread_id,
                query=user_text,
                persona_mode=persona_mode.value,
            )
        else:
            memory_context = build_sales_context(
                store=store,
                client_id=args.client_id,
                channel_id=args.channel_id,
                thread_id=args.thread_id,
                query=user_text,
            )
        profile = store.get_client_profile(args.client_id)
        if persona_mode is ChatPersonaMode.SALES:
            reply = generate_sales_reply(
                user_text,
                history=history,
                agent_loop=agent_loop,
                tools=tools,
                memory_context=memory_context,
                preferred_language=profile.preferred_language,
            )
        else:
            reply = generate_chat_reply(
                user_text,
                history=history,
                agent_loop=agent_loop,
                tools=tools,
                memory_context=memory_context,
                preferred_language=profile.preferred_language,
                persona_mode=persona_mode,
            )
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply.text})
        if persona_mode is ChatPersonaMode.COMPANION:
            record_chat_interaction(
                store=store,
                client_id=args.client_id,
                channel_id=args.channel_id,
                thread_id=args.thread_id,
                user_text=user_text,
                assistant_text=reply.text,
                assistant_profile_update=reply.profile_update,
                tool_audit=reply.tool_audit,
                persona_mode=persona_mode.value,
            )
        else:
            record_sales_interaction(
                store=store,
                client_id=args.client_id,
                channel_id=args.channel_id,
                thread_id=args.thread_id,
                user_text=user_text,
                assistant_text=reply.text,
                assistant_profile_update=reply.profile_update,
                tool_audit=reply.tool_audit,
            )
        bubbles = split_into_bubbles(reply.text)
        for bubble in bubbles:
            print(f"\nassistant> {bubble}")
        if args.show_profile:
            _print_sales_profile(store, args.client_id)

    if args.once:
        handle_turn(args.once)
        return 0

    print("Interactive companion chat test" if persona_mode is ChatPersonaMode.COMPANION else "Interactive sales chat test")
    print("Type /exit to quit, /memory to inspect current memory, /profile to inspect stored profile, /reset to clear in-memory history.")
    while True:
        try:
            user_text = input("\nyou> ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 130

        if not user_text:
            continue
        if user_text in {"/exit", "/quit"}:
            return 0
        if user_text == "/reset":
            history.clear()
            print("history cleared")
            continue
        if user_text == "/profile":
            _print_sales_profile(store, args.client_id)
            continue
        if user_text == "/memory":
            memory_context = build_sales_context(
                store=store,
                client_id=args.client_id,
                channel_id=args.channel_id,
                thread_id=args.thread_id,
                query="",
            )
            print("\n[memory]")
            print(memory_context or "(empty)")
            continue

        handle_turn(user_text)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "ask":
        app = build_demo_app()
        print(app.ask(args.question).markdown)
        return 0
    if args.command == "draft":
        app = build_demo_app()
        print(app.draft(args.request).markdown)
        return 0
    if args.command == "meeting-prep":
        app = build_demo_app()
        print(app.meeting_prep(args.request).markdown)
        return 0
    if args.command == "route":
        app = build_demo_app()
        print(app.route(args.message).markdown)
        return 0
    if args.command == "regime":
        app = build_demo_app()
        print(app.regime(focus=args.focus).markdown)
        return 0
    if args.command == "calendar":
        app = build_demo_app()
        print(app.calendar(limit=args.limit).markdown)
        return 0
    if args.command == "premarket":
        app = build_demo_app()
        print(app.premarket(focus=args.focus).body_markdown)
        return 0
    if args.command == "live-calendar":
        app = build_live_engine_app()
        events = app.live_calendar(
            scope=args.scope,
            country=args.country,
            category=args.category,
            importance=args.importance,
            limit=args.limit,
        )
        if not events:
            print("No events found.")
        else:
            for event in events:
                print(format_calendar_event(event))
        return 0
    if args.command == "refresh":
        if not args.once:
            parser.error("refresh requires --once; use schedule for continuous refresh")
        app = build_live_engine_app()
        print(json.dumps(app.refresh(), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "schedule":
        app = build_live_engine_app()
        app.schedule()
        return 0
    if args.command == "flash":
        app = build_live_engine_app()
        print(app.flash(indicator_keyword=args.indicator).body_markdown)
        return 0
    if args.command == "briefing":
        app = build_live_engine_app()
        print(app.briefing().body_markdown)
        return 0
    if args.command == "wrap":
        app = build_live_engine_app()
        print(app.wrap().body_markdown)
        return 0
    if args.command == "regime-refresh":
        app = build_live_engine_app()
        state = app.regime_refresh()
        print(state.summary)
        for score in state.scores:
            print(f"- {score.axis}: {score.label} ({score.score:.0f})")
        return 0
    if args.command == "news-refresh":
        app = build_live_engine_app()
        result = app.engine.ingestion.refresh_news(category=args.category)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "news-latest":
        app = build_live_engine_app()
        articles = app.engine.store.list_recent_news(
            limit=args.limit,
            impact_level=args.impact,
            feed_category=args.category,
        )
        if not articles:
            print("No news articles found.")
        else:
            for article in articles:
                print(format_news_headline(article))
        return 0
    if args.command == "news-search":
        app = build_live_engine_app()
        articles = app.engine.store.search_news(args.query, limit=args.limit)
        if not articles:
            print("No matching news articles found.")
        else:
            for article in articles:
                print(format_news_headline(article))
        return 0
    if args.command == "news-feeds":
        from analyst.ingestion.news_feeds import get_feeds
        feeds = get_feeds(args.category)
        for feed in feeds:
            print(f"[{feed.category:<16}] {feed.name}")
        print(f"\nTotal: {len(feeds)} feeds")
        return 0
    if args.command == "portfolio-sync":
        return _run_portfolio_sync(args)
    if args.command == "portfolio-import":
        return _run_portfolio_import(args)
    if args.command == "portfolio-risk":
        return _run_portfolio_risk(args)
    if args.command == "sales-chat":
        return _run_sales_chat(args)
    if args.command == "media-gen":
        return _run_media_gen(args)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
