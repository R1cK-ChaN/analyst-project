from __future__ import annotations

import argparse
import json

from analyst.storage.sqlite import StoredEventRecord

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

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
