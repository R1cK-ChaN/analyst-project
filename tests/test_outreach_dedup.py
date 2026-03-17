from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.delivery.outreach_dedup import (
    normalize_outreach_text,
    char_ngram_tfidf_similarity,
    is_duplicate_outreach,
)
from analyst.storage import SQLiteEngineStore


def _make_store() -> SQLiteEngineStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return SQLiteEngineStore(db_path=Path(tmp.name))


# ---------------------------------------------------------------------------
# normalize_outreach_text
# ---------------------------------------------------------------------------

class TestNormalizeOutreachText(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(normalize_outreach_text("Hello WORLD"), "hello world")

    def test_strip_punctuation(self):
        self.assertEqual(normalize_outreach_text("你好！今天怎么样？"), "你好今天怎么样")

    def test_collapse_whitespace(self):
        self.assertEqual(normalize_outreach_text("hello   world"), "hello world")

    def test_cjk_preserved(self):
        self.assertEqual(normalize_outreach_text("今天看到一只猫好可爱"), "今天看到一只猫好可爱")

    def test_empty_string(self):
        self.assertEqual(normalize_outreach_text(""), "")

    def test_mixed_language(self):
        result = normalize_outreach_text("Hello 你好！world")
        self.assertEqual(result, "hello 你好world")

    def test_only_punctuation(self):
        self.assertEqual(normalize_outreach_text("...!!!???"), "")


# ---------------------------------------------------------------------------
# char_ngram_tfidf_similarity
# ---------------------------------------------------------------------------

class TestCharNgramTfidfSimilarity(unittest.TestCase):
    def test_identical_strings(self):
        sim = char_ngram_tfidf_similarity("今天怎么没来找我", "今天怎么没来找我")
        self.assertAlmostEqual(sim, 1.0, places=3)

    def test_completely_different(self):
        sim = char_ngram_tfidf_similarity("abcdef", "xyz123")
        self.assertLess(sim, 0.2)

    def test_very_similar_chinese(self):
        """'你今天怎么没来找我呀' vs '今天怎么没来找我' should be highly similar."""
        sim = char_ngram_tfidf_similarity("你今天怎么没来找我呀", "今天怎么没来找我")
        self.assertGreater(sim, 0.75)

    def test_different_topics(self):
        """'刚听了一首歌好好听' vs '今天看到一只猫好可爱' should be dissimilar."""
        sim = char_ngram_tfidf_similarity("刚听了一首歌好好听", "今天看到一只猫好可爱")
        self.assertLess(sim, 0.75)

    def test_empty_both(self):
        self.assertAlmostEqual(char_ngram_tfidf_similarity("", ""), 1.0)

    def test_empty_one(self):
        self.assertAlmostEqual(char_ngram_tfidf_similarity("hello", ""), 0.0)

    def test_short_strings(self):
        # Strings shorter than n=3 produce no trigrams → similarity 0
        sim = char_ngram_tfidf_similarity("ab", "ab")
        self.assertAlmostEqual(sim, 0.0)
        # But 3+ chars work fine
        sim2 = char_ngram_tfidf_similarity("abc", "abc")
        self.assertAlmostEqual(sim2, 1.0, places=3)

    def test_english_similar(self):
        sim = char_ngram_tfidf_similarity(
            "How are you doing today?",
            "How are you doing today",
        )
        self.assertGreater(sim, 0.9)

    def test_english_different(self):
        sim = char_ngram_tfidf_similarity(
            "The weather is nice today",
            "I just finished a great book",
        )
        self.assertLess(sim, 0.5)


# ---------------------------------------------------------------------------
# is_duplicate_outreach
# ---------------------------------------------------------------------------

class TestIsDuplicateOutreach(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(is_duplicate_outreach("今天怎么样", ["今天怎么样"]))

    def test_exact_match_with_punctuation_diff(self):
        self.assertTrue(is_duplicate_outreach("今天怎么样？", ["今天怎么样"]))

    def test_similar_above_threshold(self):
        self.assertTrue(is_duplicate_outreach(
            "你今天怎么没来找我呀",
            ["今天怎么没来找我"],
        ))

    def test_different_below_threshold(self):
        self.assertFalse(is_duplicate_outreach(
            "刚听了一首歌好好听",
            ["今天看到一只猫好可爱"],
        ))

    def test_empty_recent(self):
        self.assertFalse(is_duplicate_outreach("hello", []))

    def test_empty_candidate(self):
        self.assertFalse(is_duplicate_outreach("", ["hello"]))

    def test_multiple_recent_one_match(self):
        self.assertTrue(is_duplicate_outreach(
            "今天天气真好",
            ["昨天下雨了", "今天天气真好啊", "明天有约吗"],
        ))

    def test_multiple_recent_no_match(self):
        self.assertFalse(is_duplicate_outreach(
            "刚看了部电影好好看",
            ["今天天气真好", "你吃饭了吗", "最近在忙什么"],
        ))


# ---------------------------------------------------------------------------
# Storage CRUD
# ---------------------------------------------------------------------------

class TestOutreachLogStorage(unittest.TestCase):
    def setUp(self):
        self.store = _make_store()
        self.now = datetime.now(timezone.utc)

    def test_log_and_list(self):
        self.store.log_companion_outreach(
            client_id="u1",
            channel="telegram:123",
            thread_id="main",
            kind="streak_save",
            content_raw="今天怎么没来找我",
            sent_at=self.now.isoformat(),
        )
        records = self.store.list_recent_companion_outreach(client_id="u1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].kind, "streak_save")
        self.assertEqual(records[0].client_id, "u1")
        self.assertFalse(records[0].user_replied)

    def test_list_filters_by_client(self):
        self.store.log_companion_outreach(
            client_id="u1", channel="telegram:123", thread_id="main",
            kind="morning", content_raw="早上好", sent_at=self.now.isoformat(),
        )
        self.store.log_companion_outreach(
            client_id="u2", channel="telegram:456", thread_id="main",
            kind="morning", content_raw="早上好", sent_at=self.now.isoformat(),
        )
        records = self.store.list_recent_companion_outreach(client_id="u1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].client_id, "u1")

    def test_mark_replied(self):
        sent_at = self.now.isoformat()
        self.store.log_companion_outreach(
            client_id="u1", channel="telegram:123", thread_id="main",
            kind="streak_save", content_raw="想你了", sent_at=sent_at,
        )
        replied_at = (self.now + timedelta(hours=1)).isoformat()
        self.store.mark_outreach_replied(
            client_id="u1", channel="telegram:123", thread_id="main",
            replied_at=replied_at,
        )
        records = self.store.list_recent_companion_outreach(client_id="u1")
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].user_replied)
        self.assertEqual(records[0].user_replied_at, replied_at)

    def test_mark_replied_outside_4h_window(self):
        """Reply after 4h should not be attributed."""
        sent_at = self.now.isoformat()
        self.store.log_companion_outreach(
            client_id="u1", channel="telegram:123", thread_id="main",
            kind="streak_save", content_raw="你好", sent_at=sent_at,
        )
        replied_at = (self.now + timedelta(hours=5)).isoformat()
        self.store.mark_outreach_replied(
            client_id="u1", channel="telegram:123", thread_id="main",
            replied_at=replied_at,
        )
        records = self.store.list_recent_companion_outreach(client_id="u1")
        self.assertFalse(records[0].user_replied)

    def test_mark_replied_scoped_to_channel_thread(self):
        """Reply attribution should scope to same channel+thread."""
        sent_at = self.now.isoformat()
        self.store.log_companion_outreach(
            client_id="u1", channel="telegram:123", thread_id="main",
            kind="streak_save", content_raw="你好", sent_at=sent_at,
        )
        replied_at = (self.now + timedelta(hours=1)).isoformat()
        # Reply in a different thread
        self.store.mark_outreach_replied(
            client_id="u1", channel="telegram:123", thread_id="other",
            replied_at=replied_at,
        )
        records = self.store.list_recent_companion_outreach(client_id="u1")
        self.assertFalse(records[0].user_replied)

    def test_count_outreach_today(self):
        self.store.log_companion_outreach(
            client_id="u1", channel="telegram:123", thread_id="main",
            kind="morning", content_raw="早上好", sent_at=self.now.isoformat(),
        )
        self.store.log_companion_outreach(
            client_id="u1", channel="telegram:123", thread_id="main",
            kind="evening", content_raw="晚上好", sent_at=self.now.isoformat(),
        )
        count = self.store.count_outreach_sent_today(
            client_id="u1", channel="telegram:123", thread_id="main",
        )
        self.assertEqual(count, 2)

    def test_get_last_outreach_sent_at(self):
        t1 = self.now.isoformat()
        t2 = (self.now + timedelta(hours=2)).isoformat()
        self.store.log_companion_outreach(
            client_id="u1", channel="telegram:123", thread_id="main",
            kind="morning", content_raw="早上好", sent_at=t1,
        )
        self.store.log_companion_outreach(
            client_id="u1", channel="telegram:123", thread_id="main",
            kind="evening", content_raw="晚上好", sent_at=t2,
        )
        last = self.store.get_last_outreach_sent_at(
            client_id="u1", channel="telegram:123", thread_id="main",
        )
        self.assertEqual(last, t2)

    def test_get_last_outreach_sent_at_none(self):
        last = self.store.get_last_outreach_sent_at(
            client_id="u1", channel="telegram:123", thread_id="main",
        )
        self.assertIsNone(last)


if __name__ == "__main__":
    unittest.main()
