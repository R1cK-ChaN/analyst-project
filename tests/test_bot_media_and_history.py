"""Tests for analyst.delivery.bot_media and analyst.delivery.bot_history."""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from PIL import Image

from analyst.delivery.bot_constants import (
    MANAGED_MEDIA_PREFIXES,
    MAX_HISTORY_TURNS,
    MAX_INBOUND_IMAGE_EDGE,
)
from analyst.delivery.bot_history import (
    _append_history,
    _get_history,
    _send_bot_bubbles,
)
from analyst.delivery.bot_media import (
    _cleanup_generated_media,
    _encode_image_data_uri,
    _image_file_ref,
    _image_summary_marker,
    _is_managed_generated_media,
    _render_image_instruction,
    _summarize_user_message,
)
from analyst.tools._request_context import RequestImageInput


def _make_jpeg_bytes(width: int = 100, height: int = 100) -> bytes:
    """Create minimal JPEG bytes of the given size."""
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _make_png_rgba_bytes(width: int = 80, height: int = 80) -> bytes:
    """Create PNG bytes with an alpha channel."""
    img = Image.new("RGBA", (width, height), color=(0, 128, 255, 128))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _run(coro):
    """Helper to run an async coroutine in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# bot_media tests
# ---------------------------------------------------------------------------


class TestEncodeImageDataUri(unittest.TestCase):
    """Tests for _encode_image_data_uri."""

    def test_jpeg_bytes_produce_valid_data_uri(self):
        raw = _make_jpeg_bytes(64, 64)
        result = _encode_image_data_uri(raw, "image/jpeg")

        self.assertIsInstance(result, RequestImageInput)
        self.assertTrue(result.data_uri.startswith("data:image/jpeg;base64,"))
        self.assertEqual(result.mime_type, "image/jpeg")

        # Decode the base64 portion and verify it is valid JPEG
        b64_part = result.data_uri.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        img = Image.open(BytesIO(decoded))
        self.assertEqual(img.format, "JPEG")

    def test_png_with_transparency_flattened_to_jpeg(self):
        raw = _make_png_rgba_bytes(50, 50)
        result = _encode_image_data_uri(raw, "image/png")

        # Even though the input was PNG/RGBA the output should be JPEG
        self.assertEqual(result.mime_type, "image/jpeg")
        self.assertTrue(result.data_uri.startswith("data:image/jpeg;base64,"))

        b64_part = result.data_uri.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        img = Image.open(BytesIO(decoded))
        self.assertEqual(img.mode, "RGB")

    def test_oversized_image_gets_resized(self):
        big = MAX_INBOUND_IMAGE_EDGE + 500
        raw = _make_jpeg_bytes(big, big)
        result = _encode_image_data_uri(raw, "image/jpeg")

        b64_part = result.data_uri.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        img = Image.open(BytesIO(decoded))
        self.assertLessEqual(max(img.size), MAX_INBOUND_IMAGE_EDGE)

    def test_small_image_not_resized(self):
        raw = _make_jpeg_bytes(200, 100)
        result = _encode_image_data_uri(raw, "image/jpeg")

        b64_part = result.data_uri.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        img = Image.open(BytesIO(decoded))
        # Should stay at original dimensions (after JPEG re-encode)
        self.assertEqual(img.size, (200, 100))

    def test_empty_mime_type_defaults_to_jpeg(self):
        raw = _make_jpeg_bytes(32, 32)
        result = _encode_image_data_uri(raw, "")

        self.assertEqual(result.mime_type, "image/jpeg")
        self.assertTrue(result.data_uri.startswith("data:image/jpeg;base64,"))

    def test_non_square_oversized_preserves_aspect_ratio(self):
        """A 3000x1500 image should be scaled so the longest edge is MAX_INBOUND_IMAGE_EDGE."""
        raw = _make_jpeg_bytes(3000, 1500)
        result = _encode_image_data_uri(raw, "image/jpeg")

        b64_part = result.data_uri.split(",", 1)[1]
        decoded = base64.b64decode(b64_part)
        img = Image.open(BytesIO(decoded))
        self.assertEqual(max(img.size), MAX_INBOUND_IMAGE_EDGE)
        # Aspect ratio should be roughly 2:1
        self.assertAlmostEqual(img.width / img.height, 2.0, delta=0.05)


class TestCleanupGeneratedMedia(unittest.TestCase):
    """Tests for _cleanup_generated_media and _is_managed_generated_media."""

    def test_managed_file_is_deleted(self):
        tmp_dir = tempfile.gettempdir()
        fd, path = tempfile.mkstemp(prefix=MANAGED_MEDIA_PREFIXES[0], dir=tmp_dir)
        os.close(fd)
        self.assertTrue(os.path.exists(path))

        _cleanup_generated_media(path)
        self.assertFalse(os.path.exists(path))

    def test_managed_directory_is_deleted(self):
        tmp_dir = tempfile.gettempdir()
        dir_path = tempfile.mkdtemp(prefix=MANAGED_MEDIA_PREFIXES[1], dir=tmp_dir)
        self.assertTrue(os.path.isdir(dir_path))

        _cleanup_generated_media(dir_path)
        self.assertFalse(os.path.exists(dir_path))

    def test_non_managed_prefix_not_deleted(self):
        tmp_dir = tempfile.gettempdir()
        fd, path = tempfile.mkstemp(prefix="other_prefix_", dir=tmp_dir)
        os.close(fd)

        _cleanup_generated_media(path)
        self.assertTrue(os.path.exists(path))
        os.remove(path)  # manual cleanup

    def test_file_outside_temp_dir_not_deleted(self):
        """Even with a managed prefix, files outside tempdir are not deleted."""
        # Create a temp directory to act as a non-tempdir parent
        parent = tempfile.mkdtemp()
        path = os.path.join(parent, f"{MANAGED_MEDIA_PREFIXES[0]}test.jpg")
        with open(path, "w") as f:
            f.write("data")

        _cleanup_generated_media(path)
        self.assertTrue(os.path.exists(path))
        os.remove(path)
        os.rmdir(parent)

    def test_empty_path_no_error(self):
        """Passing a nonexistent managed path should not raise."""
        tmp_dir = tempfile.gettempdir()
        fake_path = os.path.join(tmp_dir, f"{MANAGED_MEDIA_PREFIXES[0]}nonexistent_xyz")
        # Should not raise
        _cleanup_generated_media(fake_path)

    def test_is_managed_true_for_valid_prefix(self):
        tmp_dir = tempfile.gettempdir()
        path = os.path.join(tmp_dir, f"{MANAGED_MEDIA_PREFIXES[0]}abc.png")
        self.assertTrue(_is_managed_generated_media(path))

    def test_is_managed_false_for_wrong_prefix(self):
        tmp_dir = tempfile.gettempdir()
        path = os.path.join(tmp_dir, "random_file.png")
        self.assertFalse(_is_managed_generated_media(path))


class TestImageSummaryMarker(unittest.TestCase):
    """Tests for _image_summary_marker."""

    def test_none_returns_empty(self):
        self.assertEqual(_image_summary_marker(None), "")

    def test_reply_source_returns_referenced(self):
        img = RequestImageInput(data_uri="data:image/jpeg;base64,abc", mime_type="image/jpeg", source="reply")
        self.assertEqual(_image_summary_marker(img), "[Referenced image]")

    def test_message_source_returns_attached(self):
        img = RequestImageInput(data_uri="data:image/jpeg;base64,abc", mime_type="image/jpeg", source="message")
        self.assertEqual(_image_summary_marker(img), "[Image attached]")

    def test_other_source_returns_attached(self):
        img = RequestImageInput(data_uri="data:image/png;base64,abc", mime_type="image/png", source="forward")
        self.assertEqual(_image_summary_marker(img), "[Image attached]")


class TestSummarizeUserMessage(unittest.TestCase):
    """Tests for _summarize_user_message."""

    def test_text_only(self):
        self.assertEqual(_summarize_user_message("hello"), "hello")

    def test_image_only(self):
        img = RequestImageInput(data_uri="x", mime_type="image/jpeg", source="message")
        self.assertEqual(_summarize_user_message("", image=img), "[Image attached]")

    def test_text_and_image(self):
        img = RequestImageInput(data_uri="x", mime_type="image/jpeg", source="reply")
        result = _summarize_user_message("check this", image=img)
        self.assertEqual(result, "check this\n[Referenced image]")


class TestRenderImageInstruction(unittest.TestCase):
    """Tests for _render_image_instruction."""

    def test_attached_image_with_text(self):
        img = RequestImageInput(data_uri="x", mime_type="image/jpeg", source="message")
        result = _render_image_instruction("Describe this", image=img)
        self.assertIn("Describe this", result)
        self.assertIn("(attached)", result)

    def test_reply_image_with_text(self):
        img = RequestImageInput(data_uri="x", mime_type="image/jpeg", source="reply")
        result = _render_image_instruction("What is this?", image=img)
        self.assertIn("What is this?", result)
        self.assertIn("(referenced in the replied-to message)", result)

    def test_no_image_defaults_to_attached(self):
        result = _render_image_instruction("Look at this", image=None)
        self.assertIn("(attached)", result)

    def test_empty_text_uses_fallback(self):
        img = RequestImageInput(data_uri="x", mime_type="image/jpeg", source="message")
        result = _render_image_instruction("", image=img)
        self.assertIn("The user sent an image without caption", result)

    def test_whitespace_only_text_uses_fallback(self):
        img = RequestImageInput(data_uri="x", mime_type="image/jpeg", source="message")
        result = _render_image_instruction("   ", image=img)
        self.assertIn("The user sent an image without caption", result)

    def test_contains_tool_guidance(self):
        result = _render_image_instruction("test", image=None)
        self.assertIn("generate_image", result)
        self.assertIn("generate_live_photo", result)
        self.assertIn("use_attached_image=true", result)


class TestImageFileRef(unittest.TestCase):
    """Tests for _image_file_ref."""

    def test_photo_message(self):
        photo = MagicMock()
        photo.file_id = "photo_file_123"
        message = MagicMock()
        message.photo = [photo]
        message.document = None

        result = _image_file_ref(message)
        self.assertIsNotNone(result)
        file_id, mime_type, filename = result
        self.assertEqual(file_id, "photo_file_123")
        self.assertEqual(mime_type, "image/jpeg")
        self.assertEqual(filename, "photo_file_123.jpg")

    def test_document_image(self):
        doc = MagicMock()
        doc.file_id = "doc_123"
        doc.mime_type = "image/png"
        doc.file_name = "screenshot.png"
        message = MagicMock()
        message.photo = []
        message.document = doc

        result = _image_file_ref(message)
        self.assertIsNotNone(result)
        file_id, mime_type, filename = result
        self.assertEqual(file_id, "doc_123")
        self.assertEqual(mime_type, "image/png")
        self.assertEqual(filename, "screenshot.png")

    def test_non_image_document_returns_none(self):
        doc = MagicMock()
        doc.file_id = "doc_456"
        doc.mime_type = "application/pdf"
        doc.file_name = "report.pdf"
        message = MagicMock()
        message.photo = []
        message.document = doc

        result = _image_file_ref(message)
        self.assertIsNone(result)

    def test_no_photo_no_document_returns_none(self):
        message = MagicMock()
        message.photo = []
        message.document = None

        result = _image_file_ref(message)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# bot_history tests
# ---------------------------------------------------------------------------


class TestGetHistory(unittest.TestCase):
    """Tests for _get_history."""

    def _make_context(self, user_data=None, chat_data=None):
        ctx = MagicMock()
        ctx.user_data = user_data if user_data is not None else {}
        ctx.chat_data = chat_data if chat_data is not None else {}
        return ctx

    def test_private_chat_initializes_empty(self):
        ctx = self._make_context()
        history = _get_history(ctx, is_group=False)
        self.assertEqual(history, [])
        self.assertIn("history", ctx.user_data)

    def test_private_chat_returns_existing(self):
        existing = [{"role": "user", "content": "hi"}]
        ctx = self._make_context(user_data={"history": existing})
        history = _get_history(ctx, is_group=False)
        self.assertIs(history, existing)

    def test_group_chat_initializes_empty(self):
        ctx = self._make_context()
        history = _get_history(ctx, is_group=True, thread_id="topic_42")
        self.assertEqual(history, [])
        self.assertIn("agent_history", ctx.chat_data)
        self.assertIn("topic_42", ctx.chat_data["agent_history"])

    def test_group_chat_returns_existing(self):
        existing = [{"role": "assistant", "content": "hello"}]
        ctx = self._make_context(chat_data={"agent_history": {"main": existing}})
        history = _get_history(ctx, is_group=True, thread_id="main")
        self.assertIs(history, existing)

    def test_group_chat_different_threads_are_independent(self):
        ctx = self._make_context()
        h1 = _get_history(ctx, is_group=True, thread_id="t1")
        h2 = _get_history(ctx, is_group=True, thread_id="t2")
        h1.append({"role": "user", "content": "a"})
        self.assertEqual(len(h2), 0)

    def test_private_chat_ignores_thread_id(self):
        ctx = self._make_context()
        h1 = _get_history(ctx, is_group=False, thread_id="anything")
        h2 = _get_history(ctx, is_group=False, thread_id="other")
        self.assertIs(h1, h2)


class TestAppendHistory(unittest.TestCase):
    """Tests for _append_history."""

    def _make_context(self, user_data=None, chat_data=None):
        ctx = MagicMock()
        ctx.user_data = user_data if user_data is not None else {}
        ctx.chat_data = chat_data if chat_data is not None else {}
        return ctx

    def test_append_to_private(self):
        ctx = self._make_context()
        _append_history(ctx, "user", "hello")
        _append_history(ctx, "assistant", "hi there")
        self.assertEqual(len(ctx.user_data["history"]), 2)
        self.assertEqual(ctx.user_data["history"][0], {"role": "user", "content": "hello"})
        self.assertEqual(ctx.user_data["history"][1], {"role": "assistant", "content": "hi there"})

    def test_append_to_group(self):
        ctx = self._make_context()
        _append_history(ctx, "user", "group msg", is_group=True, thread_id="t1")
        history = ctx.chat_data["agent_history"]["t1"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "group msg")

    def test_trimming_at_max(self):
        ctx = self._make_context()
        max_messages = MAX_HISTORY_TURNS * 2
        # Fill beyond the limit
        for i in range(max_messages + 10):
            role = "user" if i % 2 == 0 else "assistant"
            _append_history(ctx, role, f"msg_{i}")

        history = ctx.user_data["history"]
        self.assertEqual(len(history), max_messages)
        # The oldest messages should have been trimmed; last message should be present
        self.assertEqual(history[-1]["content"], f"msg_{max_messages + 9}")
        # The first remaining message should be msg_10 (10 were trimmed)
        self.assertEqual(history[0]["content"], "msg_10")

    def test_trimming_preserves_recent(self):
        ctx = self._make_context()
        max_messages = MAX_HISTORY_TURNS * 2
        for i in range(max_messages):
            _append_history(ctx, "user", f"m{i}")
        # At exactly the limit, no trim yet
        self.assertEqual(len(ctx.user_data["history"]), max_messages)
        # One more triggers trim
        _append_history(ctx, "user", "overflow")
        self.assertEqual(len(ctx.user_data["history"]), max_messages)
        self.assertEqual(ctx.user_data["history"][-1]["content"], "overflow")


class TestSendBotBubbles(unittest.TestCase):
    """Tests for _send_bot_bubbles."""

    def test_single_bubble_no_sleep(self):
        bot = AsyncMock()
        _run(_send_bot_bubbles(bot, chat_id=123, bubbles=["Hello!"]))

        bot.send_chat_action.assert_called_once()
        bot.send_message.assert_called_once_with(chat_id=123, text="Hello!")

    def test_multiple_bubbles_sent_in_order(self):
        bot = AsyncMock()
        bubbles = ["First", "Second", "Third"]

        with patch("analyst.delivery.bot_history.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            _run(_send_bot_bubbles(bot, chat_id=42, bubbles=bubbles))

        self.assertEqual(bot.send_message.call_count, 3)
        sent_texts = [call.kwargs["text"] for call in bot.send_message.call_args_list]
        self.assertEqual(sent_texts, ["First", "Second", "Third"])

        # sleep should have been called for bubbles after the first
        self.assertEqual(mock_sleep.call_count, 2)

    def test_empty_bubbles_no_calls(self):
        bot = AsyncMock()
        _run(_send_bot_bubbles(bot, chat_id=1, bubbles=[]))
        bot.send_message.assert_not_called()
        bot.send_chat_action.assert_not_called()

    def test_delay_clamped_to_minimum(self):
        """Even for a very short bubble the delay should be >= 0.3."""
        bot = AsyncMock()
        bubbles = ["A", "B"]

        with patch("analyst.delivery.bot_history.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch("analyst.delivery.bot_history.random.uniform", return_value=-0.3):
                _run(_send_bot_bubbles(bot, chat_id=1, bubbles=bubbles))

        actual_delay = mock_sleep.call_args[0][0]
        self.assertGreaterEqual(actual_delay, 0.3)

    def test_delay_clamped_to_maximum(self):
        """For a very long bubble, the base delay should be capped at 2.5 (+ jitter)."""
        bot = AsyncMock()
        long_text = "x" * 10000
        bubbles = ["first", long_text]

        with patch("analyst.delivery.bot_history.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with patch("analyst.delivery.bot_history.random.uniform", return_value=0.3):
                _run(_send_bot_bubbles(bot, chat_id=1, bubbles=bubbles))

        actual_delay = mock_sleep.call_args[0][0]
        # max base is 2.5, plus jitter 0.3 => 2.8
        self.assertLessEqual(actual_delay, 2.8 + 0.01)

    def test_chat_action_sent_for_each_bubble(self):
        bot = AsyncMock()
        bubbles = ["a", "b", "c"]

        with patch("analyst.delivery.bot_history.asyncio.sleep", new_callable=AsyncMock):
            _run(_send_bot_bubbles(bot, chat_id=7, bubbles=bubbles))

        self.assertEqual(bot.send_chat_action.call_count, 3)


if __name__ == "__main__":
    unittest.main()
