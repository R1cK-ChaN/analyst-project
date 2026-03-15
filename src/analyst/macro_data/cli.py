from __future__ import annotations

import argparse
import json

from .server import main as serve_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Macro-data service CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--db-path", default=None)
    serve.add_argument("--api-token", default=None)

    refresh = subparsers.add_parser("refresh")
    refresh.add_argument("--db-path", default=None)

    subparsers.add_parser("schedule")

    news_refresh = subparsers.add_parser("news-refresh")
    news_refresh.add_argument("--category", default=None)
    news_refresh.add_argument("--db-path", default=None)

    rag_parser = subparsers.add_parser("rag")
    rag_sub = rag_parser.add_subparsers(dest="rag_command", required=True)
    rag_sub.add_parser("calibrate")
    rag_sub.add_parser("sync")
    rag_sub.add_parser("status")

    return parser


def _run_rag(args: argparse.Namespace) -> int:
    from analyst.rag.bridge import MacroIngestionBridge
    from analyst.rag.config import RAGConfig
    from analyst.rag.embeddings import Embedder
    from analyst.rag.vector_store import VectorStore

    cfg = RAGConfig.from_env()
    store = VectorStore(cfg)
    store.init_collection()
    embedder = Embedder(cfg)
    bridge = MacroIngestionBridge(store, embedder, cfg)
    if args.rag_command == "calibrate":
        print(json.dumps(bridge.calibrate(), ensure_ascii=False, indent=2))
        return 0
    if args.rag_command == "sync":
        print(json.dumps(bridge.sync(), ensure_ascii=False, indent=2))
        return 0
    if args.rag_command == "status":
        print(json.dumps(bridge.status(), ensure_ascii=False, indent=2))
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        serve_argv: list[str] = []
        if args.host is not None:
            serve_argv.extend(["--host", args.host])
        if args.port is not None:
            serve_argv.extend(["--port", str(args.port)])
        if args.db_path is not None:
            serve_argv.extend(["--db-path", args.db_path])
        if args.api_token is not None:
            serve_argv.extend(["--api-token", args.api_token])
        return serve_main(serve_argv)

    from analyst.app import build_local_macro_data_service
    from pathlib import Path

    service = build_local_macro_data_service(db_path=Path(args.db_path) if hasattr(args, "db_path") and args.db_path else None)

    if args.command == "refresh":
        print(json.dumps(service.invoke("refresh_all_sources", {}), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "schedule":
        service.invoke("run_schedule", {})
        return 0
    if args.command == "news-refresh":
        print(json.dumps(service.invoke("refresh_news", {"category": args.category}), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "rag":
        return _run_rag(args)
    parser.error("unknown command")
    return 2
