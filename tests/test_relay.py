import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from analyst.delivery.relay import _append_transcript_event, _forward_message
from analyst.delivery.relay_scenarios import resolve_relay_scenario


class RelayForwardMessageTest(unittest.IsolatedAsyncioTestCase):
    async def test_text_only_message_uses_send_message(self) -> None:
        client = AsyncMock()
        message = SimpleNamespace(text="hello", media=None)

        forwarded = await _forward_message(client, "target", message)

        self.assertTrue(forwarded)
        client.send_message.assert_awaited_once_with("target", "hello")
        client.send_file.assert_not_awaited()

    async def test_media_with_caption_uses_send_file_with_caption(self) -> None:
        client = AsyncMock()
        media = object()
        message = SimpleNamespace(text="caption", media=media)

        forwarded = await _forward_message(client, "target", message)

        self.assertTrue(forwarded)
        client.send_file.assert_awaited_once_with("target", media, caption="caption")
        client.send_message.assert_not_awaited()

    async def test_media_without_caption_uses_send_file_without_caption(self) -> None:
        client = AsyncMock()
        media = object()
        message = SimpleNamespace(text="", media=media)

        forwarded = await _forward_message(client, "target", message)

        self.assertTrue(forwarded)
        client.send_file.assert_awaited_once_with("target", media)
        client.send_message.assert_not_awaited()

    async def test_empty_message_returns_false(self) -> None:
        client = AsyncMock()
        message = SimpleNamespace(text="", media=None)

        forwarded = await _forward_message(client, "target", message)

        self.assertFalse(forwarded)
        client.send_file.assert_not_awaited()
        client.send_message.assert_not_awaited()


class RelayTranscriptTest(unittest.TestCase):
    def test_append_transcript_event_writes_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "transcript.jsonl"
            _append_transcript_event(path, {"event_type": "turn", "turn": 1, "text": "hello"})
            rows = path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0])["text"], "hello")

    def test_resolve_relay_scenario_returns_named_preset(self) -> None:
        scenario = resolve_relay_scenario("opinion_brunch")

        self.assertEqual(scenario.name, "opinion_brunch")
        self.assertGreaterEqual(scenario.max_turns, 20)

    def test_resolve_relay_scenario_rejects_unknown_name(self) -> None:
        with self.assertRaises(ValueError):
            resolve_relay_scenario("missing_scenario")


if __name__ == "__main__":
    unittest.main()
