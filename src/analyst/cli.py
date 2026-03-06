from __future__ import annotations

import argparse

from .app import build_demo_app


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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    app = build_demo_app()

    if args.command == "ask":
        print(app.ask(args.question).markdown)
        return 0
    if args.command == "draft":
        print(app.draft(args.request).markdown)
        return 0
    if args.command == "meeting-prep":
        print(app.meeting_prep(args.request).markdown)
        return 0
    if args.command == "route":
        print(app.route(args.message).markdown)
        return 0
    if args.command == "regime":
        print(app.regime(focus=args.focus).markdown)
        return 0
    if args.command == "calendar":
        print(app.calendar(limit=args.limit).markdown)
        return 0
    if args.command == "premarket":
        print(app.premarket(focus=args.focus).body_markdown)
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
