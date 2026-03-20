from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import json
import mimetypes
from pathlib import Path
import shutil
import sys
from urllib.parse import urlparse

from analyst.delivery.companion_schedule import (
    apply_companion_schedule_update,
    build_companion_schedule_context,
)
from analyst.delivery.companion_reminders import apply_companion_reminder_update
from analyst.memory import build_chat_context, record_chat_interaction
from analyst.runtime.chat import build_companion_services, generate_chat_reply, split_into_bubbles
from analyst.runtime.conversation_service import persist_companion_turn_for_input, run_companion_turn_for_input
from analyst.runtime.environment_adapter import build_cli_conversation_input
from analyst.tools import build_image_gen_tool, build_live_photo_tool
from analyst.tools._image_gen import GeneratedImage, ImageGenConfig, SeedreamImageClient
from analyst.tools._request_context import RequestImageInput, bind_request_image


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyst companion agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    companion_chat = subparsers.add_parser("companion-chat")
    companion_chat.add_argument("--client-id", default="cli-demo")
    companion_chat.add_argument("--channel-id", default="cli:local")
    companion_chat.add_argument("--thread-id", default="main")
    companion_chat.add_argument("--db-path", default=None)
    companion_chat.add_argument("--once", default=None, help="Run a single companion chat turn and exit.")
    companion_chat.add_argument(
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


def _print_user_profile(store, client_id: str) -> None:
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


def _run_companion_chat(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path) if args.db_path else None
    agent_loop, tools, store = build_companion_services(db_path=db_path)
    history: list[dict[str, str]] = []

    def handle_turn(user_text: str) -> None:
        conversation = build_cli_conversation_input(
            user_id=args.client_id,
            channel_id=args.channel_id,
            thread_id=args.thread_id,
            message=user_text,
            history=history,
            companion_local_context=build_companion_schedule_context(store, client_id=args.client_id),
        )
        reply = run_companion_turn_for_input(
            conversation=conversation,
            store=store,
            agent_loop=agent_loop,
            tools=tools,
            memory_context_builder=build_chat_context,
            reply_generator=generate_chat_reply,
        )
        persist_companion_turn_for_input(
            conversation=conversation,
            store=store,
            assistant_text=reply.text,
            reply=reply,
            schedule_updater=apply_companion_schedule_update,
            reminder_updater=apply_companion_reminder_update,
            interaction_recorder=record_chat_interaction,
        )
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply.text})
        bubbles = split_into_bubbles(reply.text)
        for bubble in bubbles:
            print(f"\nassistant> {bubble}")
        if args.show_profile:
            _print_user_profile(store, args.client_id)

    if args.once:
        handle_turn(args.once)
        return 0

    print("Interactive companion chat test")
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
            _print_user_profile(store, args.client_id)
            continue
        if user_text == "/memory":
            memory_context = build_chat_context(
                store=store,
                client_id=args.client_id,
                channel_id=args.channel_id,
                thread_id=args.thread_id,
                query="",
                current_user_text="",
                persona_mode="companion",
            )
            print("\n[memory]")
            print(memory_context or "(empty)")
            continue

        handle_turn(user_text)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "companion-chat":
        return _run_companion_chat(args)
    if args.command == "media-gen":
        return _run_media_gen(args)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
