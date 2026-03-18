"""End-to-end simulation tests for document handling through the Telegram handler.

Mirrors the patterns in test_telegram.py (TestGroupChat) to exercise:
- Private chat: PDF, text, docx, xlsx sent directly
- Private chat: document in reply-to message
- Private chat: document with caption text
- Private chat: document-only (no text)
- Private chat: unsupported document type → silently ignored
- Private chat: oversized document → silently ignored
- Private chat: document + image together → image wins, doc text not injected
- Group chat: document with @mention triggers reply
- Group chat: document without mention → buffered only
- Truncation marker appears when text exceeds limit
- History records [Document: filename] marker
- LLM receives injected document text block
"""

from __future__ import annotations

import sys
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.engine.live_types import AgentLoopResult, ConversationMessage
from analyst.delivery.bot_constants import MAX_DOCUMENT_TEXT_CHARS, MAX_DOCUMENT_FILE_SIZE


def _make_docx_bytes(text: str = "Hello from Word document") -> bytes:
    from docx import Document as DocxDocument

    doc = DocxDocument()
    doc.add_paragraph(text)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Product", "Revenue"])
    ws.append(["Widget", 1200])
    ws.append(["Gadget", 3400])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_pdf_bytes(text: str = "PDF content for testing") -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((50, 100), text)
    data = doc.tobytes()
    doc.close()
    return data


class TestDocumentSimulation(unittest.IsolatedAsyncioTestCase):
    """End-to-end handler simulation for document messages."""

    def setUp(self) -> None:
        self.mock_loop = MagicMock()
        self.mock_tools = []
        self.mock_store = MagicMock()

        async def run_inline(func, /, *args, **kwargs):
            return func(*args, **kwargs)

        self.to_thread_patcher = patch(
            "analyst.delivery.bot.asyncio.to_thread",
            new=AsyncMock(side_effect=run_inline),
        )
        self.to_thread_patcher.start()
        self.addCleanup(self.to_thread_patcher.stop)

        self.mock_store.get_client_profile.return_value = SimpleNamespace(
            preferred_language="zh",
            response_style="",
            current_mood="",
            emotional_trend="",
            stress_level="",
            confidence="",
            notes="",
            personal_facts=[],
            total_interactions=0,
            last_active_at="",
        )
        self.mock_store.list_group_messages.return_value = []
        self.mock_store.list_group_members.return_value = []
        self.mock_store.build_user_context = MagicMock(return_value="")

        self.mock_loop.run.return_value = AgentLoopResult(
            messages=[
                ConversationMessage(role="user", content="test"),
                ConversationMessage(role="assistant", content="reply text"),
            ],
            final_text="reply text",
            events=[],
        )

    def _make_update(
        self,
        text: str = "",
        caption: str | None = None,
        chat_type: str = "private",
        chat_id: int = 12345,
        user_id: int = 42,
        first_name: str = "Alice",
        entities: dict | None = None,
        caption_entities: dict | None = None,
        reply_to_bot: bool = False,
        bot_id: int = 999,
        with_photo: bool = False,
        doc_file_id: str | None = None,
        doc_mime_type: str | None = None,
        doc_file_name: str | None = None,
        doc_file_size: int = 500,
    ) -> tuple:
        update = MagicMock()
        update.effective_chat.type = chat_type
        update.effective_chat.id = chat_id
        update.effective_chat.send_action = AsyncMock()
        update.effective_message.text = text
        update.effective_message.caption = caption
        update.effective_message.message_thread_id = None
        update.effective_message.reply_text = AsyncMock()
        update.effective_message.reply_photo = AsyncMock()
        update.effective_message.reply_video = AsyncMock()
        update.effective_user.id = user_id
        update.effective_user.first_name = first_name
        update.effective_message.photo = []
        update.effective_message.document = None

        if entities is None:
            update.effective_message.parse_entities.return_value = {}
        else:
            update.effective_message.parse_entities.return_value = entities
        if caption_entities is None:
            update.effective_message.parse_caption_entities.return_value = {}
        else:
            update.effective_message.parse_caption_entities.return_value = caption_entities

        if with_photo:
            photo = MagicMock()
            photo.file_id = "photo-file-id"
            update.effective_message.photo = [photo]

        if doc_file_id is not None:
            document = MagicMock()
            document.file_id = doc_file_id
            document.file_name = doc_file_name or "document"
            document.mime_type = doc_mime_type or "text/plain"
            document.file_size = doc_file_size
            update.effective_message.document = document

        if reply_to_bot:
            reply_user = MagicMock()
            reply_user.id = bot_id
            update.effective_message.reply_to_message.from_user = reply_user
            update.effective_message.reply_to_message.text = None
            update.effective_message.reply_to_message.caption = None
            update.effective_message.reply_to_message.quote = None
            update.effective_message.reply_to_message.photo = []
            update.effective_message.reply_to_message.document = None
        else:
            update.effective_message.reply_to_message = None

        context = MagicMock()
        context.bot.username = "testbot"
        context.bot.id = bot_id
        context.bot.get_file = AsyncMock()
        context.user_data = {}
        context.chat_data = {}

        return update, context

    def _setup_file_download(self, context, raw_bytes: bytes):
        telegram_file = MagicMock()
        telegram_file.download_as_bytearray = AsyncMock(return_value=bytearray(raw_bytes))
        context.bot.get_file.return_value = telegram_file

    # ------------------------------------------------------------------
    # Private chat: plain text file
    # ------------------------------------------------------------------

    async def test_private_text_file_injects_content_into_llm(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="what does this say?",
            chat_type="private",
            doc_file_id="txt-file-1",
            doc_mime_type="text/plain",
            doc_file_name="notes.txt",
        )
        self._setup_file_download(context, b"These are my notes about the project.")

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        # Bot should have replied
        update.effective_message.reply_text.assert_called()
        # Verify the LLM received the document text
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIsInstance(user_prompt, str)
        self.assertIn("[Attached document: notes.txt]", user_prompt)
        self.assertIn("These are my notes about the project.", user_prompt)
        self.assertIn("what does this say?", user_prompt)

    # ------------------------------------------------------------------
    # Private chat: PDF file
    # ------------------------------------------------------------------

    async def test_private_pdf_file_extracts_and_injects(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        pdf_bytes = _make_pdf_bytes("Quarterly revenue increased by 15%")
        update, context = self._make_update(
            text="summarize this",
            chat_type="private",
            doc_file_id="pdf-file-1",
            doc_mime_type="application/pdf",
            doc_file_name="report.pdf",
        )
        self._setup_file_download(context, pdf_bytes)

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[Attached document: report.pdf]", user_prompt)
        self.assertIn("Quarterly revenue increased by 15%", user_prompt)

    # ------------------------------------------------------------------
    # Private chat: Word (.docx) file
    # ------------------------------------------------------------------

    async def test_private_docx_file_extracts_and_injects(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        docx_bytes = _make_docx_bytes("Meeting notes from Monday standup")
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        update, context = self._make_update(
            text="read this",
            chat_type="private",
            doc_file_id="docx-file-1",
            doc_mime_type=mime,
            doc_file_name="meeting.docx",
        )
        self._setup_file_download(context, docx_bytes)

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[Attached document: meeting.docx]", user_prompt)
        self.assertIn("Meeting notes from Monday standup", user_prompt)

    # ------------------------------------------------------------------
    # Private chat: Excel (.xlsx) file
    # ------------------------------------------------------------------

    async def test_private_xlsx_file_extracts_and_injects(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        xlsx_bytes = _make_xlsx_bytes()
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        update, context = self._make_update(
            text="analyze this spreadsheet",
            chat_type="private",
            doc_file_id="xlsx-file-1",
            doc_mime_type=mime,
            doc_file_name="sales.xlsx",
        )
        self._setup_file_download(context, xlsx_bytes)

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[Attached document: sales.xlsx]", user_prompt)
        self.assertIn("[Sheet: Sales]", user_prompt)
        self.assertIn("Widget", user_prompt)

    # ------------------------------------------------------------------
    # Private chat: JSON file
    # ------------------------------------------------------------------

    async def test_private_json_file_injects_content(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        import json
        raw = json.dumps({"status": "active", "count": 42}).encode("utf-8")
        update, context = self._make_update(
            text="what's in this config?",
            chat_type="private",
            doc_file_id="json-file-1",
            doc_mime_type="application/json",
            doc_file_name="config.json",
        )
        self._setup_file_download(context, raw)

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[Attached document: config.json]", user_prompt)
        self.assertIn('"status"', user_prompt)

    # ------------------------------------------------------------------
    # Private chat: document only (no caption text)
    # ------------------------------------------------------------------

    async def test_private_document_only_no_text(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="",
            caption=None,
            chat_type="private",
            doc_file_id="txt-only-1",
            doc_mime_type="text/plain",
            doc_file_name="data.txt",
        )
        self._setup_file_download(context, b"Just raw data here")

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        # Should still reply — document alone is enough
        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[Attached document: data.txt]", user_prompt)
        self.assertIn("Just raw data here", user_prompt)

    # ------------------------------------------------------------------
    # Private chat: unsupported MIME type → no reply
    # ------------------------------------------------------------------

    async def test_private_unsupported_mime_ignored(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="",
            chat_type="private",
            doc_file_id="zip-1",
            doc_mime_type="application/zip",
            doc_file_name="archive.zip",
        )

        await handler(update, context)

        # No text, no supported doc → early return, no reply
        update.effective_message.reply_text.assert_not_called()

    # ------------------------------------------------------------------
    # Private chat: oversized file → ignored
    # ------------------------------------------------------------------

    async def test_private_oversized_document_ignored(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="",
            chat_type="private",
            doc_file_id="big-pdf-1",
            doc_mime_type="application/pdf",
            doc_file_name="huge.pdf",
            doc_file_size=MAX_DOCUMENT_FILE_SIZE + 1,
        )

        await handler(update, context)

        update.effective_message.reply_text.assert_not_called()

    # ------------------------------------------------------------------
    # Private chat: document + image → image wins, no doc injection
    # ------------------------------------------------------------------

    async def test_private_document_plus_image_image_wins(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="look at both",
            chat_type="private",
            with_photo=True,
            doc_file_id="txt-with-img",
            doc_mime_type="text/plain",
            doc_file_name="notes.txt",
        )
        # The photo download takes priority; image extraction runs first
        telegram_file = MagicMock()
        telegram_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake image bytes"))
        context.bot.get_file.return_value = telegram_file

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        # Image produces multimodal list, not plain text with doc block
        self.assertIsInstance(user_prompt, list)
        # The document text should NOT be in the image prompt text
        text_parts = [p["text"] for p in user_prompt if p.get("type") == "text"]
        for t in text_parts:
            self.assertNotIn("[Attached document:", t)

    # ------------------------------------------------------------------
    # Private chat: document in reply-to message
    # ------------------------------------------------------------------

    async def test_private_document_from_reply(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="what is in that file?",
            chat_type="private",
            reply_to_bot=True,
        )
        # Attach document to the reply message instead of the direct message
        reply_doc = MagicMock()
        reply_doc.file_id = "reply-doc-file-id"
        reply_doc.file_name = "replied.csv"
        reply_doc.mime_type = "text/csv"
        reply_doc.file_size = 200
        update.effective_message.reply_to_message.document = reply_doc
        update.effective_message.reply_to_message.photo = []

        self._setup_file_download(context, b"name,value\nfoo,42\nbar,99")

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[Attached document: replied.csv]", user_prompt)
        self.assertIn("foo,42", user_prompt)

    # ------------------------------------------------------------------
    # History records [Document: filename] marker
    # ------------------------------------------------------------------

    async def test_history_records_document_marker(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="check this",
            chat_type="private",
            doc_file_id="txt-hist-1",
            doc_mime_type="text/plain",
            doc_file_name="log.txt",
        )
        self._setup_file_download(context, b"error on line 42")

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction") as mock_record:
            await handler(update, context)

        mock_record.assert_called_once()
        user_text_recorded = mock_record.call_args.kwargs["user_text"]
        self.assertIn("[Document: log.txt]", user_text_recorded)

    # ------------------------------------------------------------------
    # Truncation marker appears for large documents
    # ------------------------------------------------------------------

    async def test_truncation_marker_for_large_document(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        big_text = "A" * (MAX_DOCUMENT_TEXT_CHARS + 1000)
        update, context = self._make_update(
            text="read this huge file",
            chat_type="private",
            doc_file_id="big-txt-1",
            doc_mime_type="text/plain",
            doc_file_name="big.txt",
        )
        self._setup_file_download(context, big_text.encode("utf-8"))

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[... document truncated ...]", user_prompt)
        # The text should be capped
        doc_start = user_prompt.index("[Attached document: big.txt]")
        doc_content = user_prompt[doc_start:]
        # Should not contain the full text
        self.assertLess(len(doc_content), MAX_DOCUMENT_TEXT_CHARS + 500)

    # ------------------------------------------------------------------
    # Group chat: document with @mention triggers reply
    # ------------------------------------------------------------------

    async def test_group_document_with_mention_triggers_reply(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        mention_entity = MagicMock()
        mention_entity.type = "mention"
        entities = {mention_entity: "@testbot"}

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="@testbot check this file",
            chat_type="supergroup",
            chat_id=-100999,
            entities=entities,
            doc_file_id="group-doc-1",
            doc_mime_type="text/plain",
            doc_file_name="data.log",
        )
        self._setup_file_download(context, b"2026-03-18 ERROR connection timeout")

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[Attached document: data.log]", user_prompt)
        self.assertIn("ERROR connection timeout", user_prompt)

    # ------------------------------------------------------------------
    # Group chat: document without mention → buffered, no reply
    # ------------------------------------------------------------------

    async def test_group_document_without_mention_buffered(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="here's the log file",
            chat_type="supergroup",
            chat_id=-100999,
            doc_file_id="grp-doc-2",
            doc_mime_type="text/plain",
            doc_file_name="app.log",
        )
        self._setup_file_download(context, b"log content")

        await handler(update, context)

        # No mention → no reply
        update.effective_message.reply_text.assert_not_called()
        # But message should be buffered
        self.assertIn("group_buffers", context.chat_data)
        buf = context.chat_data["group_buffers"]["main"]
        self.assertEqual(len(buf), 1)
        self.assertIn("[Document: app.log]", buf[0]["text"])

    # ------------------------------------------------------------------
    # Group chat: document stored in group message history
    # ------------------------------------------------------------------

    async def test_group_document_appended_to_group_messages(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="look at this",
            chat_type="supergroup",
            chat_id=-100999,
            doc_file_id="grp-doc-3",
            doc_mime_type="application/pdf",
            doc_file_name="quarterly.pdf",
        )
        self._setup_file_download(context, _make_pdf_bytes("Q1 results"))

        await handler(update, context)

        # Verify store.append_group_message was called with the doc marker
        self.mock_store.append_group_message.assert_called_once()
        call_kwargs = self.mock_store.append_group_message.call_args.kwargs
        self.assertIn("[Document: quarterly.pdf]", call_kwargs["content"])

    # ------------------------------------------------------------------
    # CSV file handling
    # ------------------------------------------------------------------

    async def test_private_csv_file(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        csv_data = b"date,price\n2026-01-01,100\n2026-01-02,105\n"
        update, context = self._make_update(
            text="plot this data",
            chat_type="private",
            doc_file_id="csv-1",
            doc_mime_type="text/csv",
            doc_file_name="prices.csv",
        )
        self._setup_file_download(context, csv_data)

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[Attached document: prices.csv]", user_prompt)
        self.assertIn("2026-01-01", user_prompt)

    # ------------------------------------------------------------------
    # Python file handling
    # ------------------------------------------------------------------

    async def test_private_python_file(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        py_code = b"def hello():\n    print('Hello, world!')\n"
        update, context = self._make_update(
            text="review my code",
            chat_type="private",
            doc_file_id="py-1",
            doc_mime_type="text/x-python",
            doc_file_name="main.py",
        )
        self._setup_file_download(context, py_code)

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[Attached document: main.py]", user_prompt)
        self.assertIn("def hello():", user_prompt)

    # ------------------------------------------------------------------
    # Markdown file handling
    # ------------------------------------------------------------------

    async def test_private_markdown_file(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        md_data = b"# My Notes\n\n- Point one\n- Point two\n"
        update, context = self._make_update(
            text="",
            chat_type="private",
            doc_file_id="md-1",
            doc_mime_type="text/markdown",
            doc_file_name="notes.md",
        )
        self._setup_file_download(context, md_data)

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("# My Notes", user_prompt)

    # ------------------------------------------------------------------
    # Image document (e.g. image/png sent as file) goes to image path
    # ------------------------------------------------------------------

    async def test_image_document_goes_to_image_path_not_document(self) -> None:
        from analyst.delivery.bot import _make_message_handler
        from analyst.delivery.user_chat import UserChatReply
        from analyst.memory import ClientProfileUpdate

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="what's in this image?",
            chat_type="private",
            doc_file_id="img-doc-1",
            doc_mime_type="image/png",
            doc_file_name="screenshot.png",
        )
        telegram_file = MagicMock()
        telegram_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake image bytes"))
        context.bot.get_file.return_value = telegram_file

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"), \
             patch(
                 "analyst.delivery.bot._chat_reply",
                 new=AsyncMock(
                     return_value=UserChatReply(
                         text="I see an image",
                         profile_update=ClientProfileUpdate(),
                     )
                 ),
             ) as mock_chat_reply:
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = mock_chat_reply.call_args.kwargs
        user_content = call_kwargs["user_content"]
        # Should be multimodal (image path), not plain text with doc block
        self.assertIsInstance(user_content, list)
        self.assertEqual(user_content[1]["type"], "image_url")
        # The document text should NOT be in the image prompt text
        text_parts = [p["text"] for p in user_content if p.get("type") == "text"]
        for t in text_parts:
            self.assertNotIn("[Attached document:", t)

    # ------------------------------------------------------------------
    # Unsupported MIME with text → text still processed
    # ------------------------------------------------------------------

    async def test_unsupported_doc_with_text_still_processes_text(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="here's a file but also this question",
            chat_type="private",
            doc_file_id="zip-2",
            doc_mime_type="application/zip",
            doc_file_name="archive.zip",
        )

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        # The text should still be processed even though the doc is unsupported
        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("here's a file but also this question", user_prompt)
        self.assertNotIn("[Attached document:", user_prompt)

    # ------------------------------------------------------------------
    # Group chat: docx with @mention
    # ------------------------------------------------------------------

    async def test_group_docx_with_mention(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        mention_entity = MagicMock()
        mention_entity.type = "mention"
        entities = {mention_entity: "@testbot"}

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        docx_bytes = _make_docx_bytes("Action items from today's meeting")
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        update, context = self._make_update(
            text="@testbot summarize this doc",
            chat_type="supergroup",
            chat_id=-100999,
            entities=entities,
            doc_file_id="grp-docx-1",
            doc_mime_type=mime,
            doc_file_name="meeting_notes.docx",
        )
        self._setup_file_download(context, docx_bytes)

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()
        call_kwargs = self.mock_loop.run.call_args.kwargs
        user_prompt = call_kwargs["user_prompt"]
        self.assertIn("[Attached document: meeting_notes.docx]", user_prompt)
        self.assertIn("Action items from today's meeting", user_prompt)


if __name__ == "__main__":
    unittest.main()
