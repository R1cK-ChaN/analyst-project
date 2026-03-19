import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from analyst.delivery.relay import _forward_message


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


if __name__ == "__main__":
    unittest.main()
