from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from analyst.delivery.sales_chat import build_sales_services, generate_sales_reply
from analyst.memory import build_sales_context, record_sales_interaction
from analyst.storage.sqlite import NewsArticleRecord, StoredEventRecord

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

    sales_chat = subparsers.add_parser("sales-chat")
    sales_chat.add_argument("--client-id", default="cli-demo")
    sales_chat.add_argument("--channel-id", default="cli:local")
    sales_chat.add_argument("--thread-id", default="main")
    sales_chat.add_argument("--focus", default="global")
    sales_chat.add_argument("--db-path", default=None)
    sales_chat.add_argument("--once", default=None, help="Run a single sales chat turn and exit.")
    sales_chat.add_argument(
        "--show-profile",
        action="store_true",
        help="Print the stored client profile after each assistant reply.",
    )

    return parser


def format_calendar_event(event: StoredEventRecord) -> str:
    stars = {"high": "***", "medium": "**", "low": "*"}.get(event.importance, "*")
    actual = event.actual or "-"
    forecast = event.forecast or "-"
    previous = event.previous or "-"
    dt = event.datetime_utc[:16].replace("T", " ")
    source = event.source.upper()
    return (
        f"{dt}  {event.country:>2} {stars:>3}  [{source:<12}]  "
        f"{event.indicator:<40}  A:{actual:<8} F:{forecast:<8} P:{previous}"
    )


def format_news_headline(article: NewsArticleRecord) -> str:
    dt = article.published_at[:16].replace("T", " ")
    impact = article.impact_level.upper()
    country = article.country or "--"
    subject = f"  [{article.subject}]" if article.subject else ""
    return (
        f"{dt}  {country:>2} [{impact:<8}]  [{article.source_feed:<20}]  "
        f"{article.title}{subject}"
    )


def _print_sales_profile(store, client_id: str) -> None:
    profile = store.get_client_profile(client_id)
    print("\n[profile]")
    print(json.dumps(asdict(profile), ensure_ascii=False, indent=2, sort_keys=True))


def _run_sales_chat(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path) if args.db_path else None
    agent_loop, tools, store = build_sales_services(db_path=db_path)
    history: list[dict[str, str]] = []

    def handle_turn(user_text: str) -> None:
        memory_context = build_sales_context(
            store=store,
            client_id=args.client_id,
            channel_id=args.channel_id,
            thread_id=args.thread_id,
            query=user_text,
        )
        reply = generate_sales_reply(
            user_text,
            history=history,
            agent_loop=agent_loop,
            tools=tools,
            memory_context=memory_context,
        )
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply.text})
        record_sales_interaction(
            store=store,
            client_id=args.client_id,
            channel_id=args.channel_id,
            thread_id=args.thread_id,
            user_text=user_text,
            assistant_text=reply.text,
            assistant_profile_update=reply.profile_update,
        )
        print(f"\nassistant> {reply.text}")
        if args.show_profile:
            _print_sales_profile(store, args.client_id)

    if args.once:
        handle_turn(args.once)
        return 0

    print("Interactive sales chat test")
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
    if args.command == "sales-chat":
        return _run_sales_chat(args)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
