"""Tests for group relational role detection, storage, and rendering."""

from __future__ import annotations

import unittest

from analyst.memory.relationship import (
    GroupRelationalRoleUpdate,
    _RELATIONAL_ROLE_VOCAB,
    _normalize_role,
    detect_group_relational_roles,
)


class TestNormalizeRole(unittest.TestCase):
    """Role vocabulary normalization."""

    def test_chinese_variants(self):
        self.assertEqual(_normalize_role("爸爸"), "爸爸")
        self.assertEqual(_normalize_role("爸"), "爸爸")
        self.assertEqual(_normalize_role("老爸"), "爸爸")
        self.assertEqual(_normalize_role("父亲"), "爸爸")
        self.assertEqual(_normalize_role("妈"), "妈妈")
        self.assertEqual(_normalize_role("母亲"), "妈妈")
        self.assertEqual(_normalize_role("大哥"), "哥哥")
        self.assertEqual(_normalize_role("弟"), "弟弟")

    def test_english_to_chinese(self):
        self.assertEqual(_normalize_role("dad"), "爸爸")
        self.assertEqual(_normalize_role("father"), "爸爸")
        self.assertEqual(_normalize_role("daddy"), "爸爸")
        self.assertEqual(_normalize_role("mom"), "妈妈")
        self.assertEqual(_normalize_role("mother"), "妈妈")
        self.assertEqual(_normalize_role("mum"), "妈妈")
        self.assertEqual(_normalize_role("bro"), "哥哥")
        self.assertEqual(_normalize_role("sis"), "姐姐")
        self.assertEqual(_normalize_role("child"), "孩子")
        self.assertEqual(_normalize_role("son"), "儿子")
        self.assertEqual(_normalize_role("daughter"), "女儿")

    def test_affectionate_and_social(self):
        self.assertEqual(_normalize_role("boss"), "老板")
        self.assertEqual(_normalize_role("老板"), "老板")
        self.assertEqual(_normalize_role("大佬"), "大佬")
        self.assertEqual(_normalize_role("dear"), "亲爱的")
        self.assertEqual(_normalize_role("darling"), "亲爱的")
        self.assertEqual(_normalize_role("honey"), "亲爱的")
        self.assertEqual(_normalize_role("sweetheart"), "亲爱的")
        self.assertEqual(_normalize_role("baby"), "宝贝")
        self.assertEqual(_normalize_role("宝贝"), "宝贝")
        self.assertEqual(_normalize_role("master"), "主人")
        self.assertEqual(_normalize_role("主人"), "主人")
        self.assertEqual(_normalize_role("teacher"), "老师")
        self.assertEqual(_normalize_role("老师"), "老师")
        self.assertEqual(_normalize_role("bestie"), "闺蜜")
        self.assertEqual(_normalize_role("buddy"), "兄弟")
        self.assertEqual(_normalize_role("师傅"), "师傅")
        self.assertEqual(_normalize_role("mentor"), "师傅")

    def test_case_insensitive(self):
        self.assertEqual(_normalize_role("Dad"), "爸爸")
        self.assertEqual(_normalize_role("MOM"), "妈妈")
        self.assertEqual(_normalize_role("Father"), "爸爸")
        self.assertEqual(_normalize_role("BOSS"), "老板")
        self.assertEqual(_normalize_role("Dear"), "亲爱的")

    def test_unknown_returns_none(self):
        self.assertIsNone(_normalize_role("朋友"))
        self.assertIsNone(_normalize_role("stranger"))
        self.assertIsNone(_normalize_role("enemy"))
        self.assertIsNone(_normalize_role(""))


class TestSpeakerRoleAssignment(unittest.TestCase):
    """Speaker assigns their own role."""

    def test_cn_wo_shi_ni_baba(self):
        r = detect_group_relational_roles("我是你爸爸", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "爸爸")

    def test_cn_wo_shi_ni_de_mama(self):
        r = detect_group_relational_roles("我是你的妈妈", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "妈妈")

    def test_cn_wo_shi_mama_without_ni(self):
        """'我是妈妈' without '你' should still match."""
        r = detect_group_relational_roles("我是妈妈", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "妈妈")

    def test_cn_wo_shi_mama_with_trailing_text(self):
        """'我是妈妈 那爸爸是谁' should match."""
        r = detect_group_relational_roles("我是妈妈 那爸爸是谁", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "妈妈")

    def test_en_i_am_the_boss(self):
        r = detect_group_relational_roles("I am the boss", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "老板")

    def test_cn_jiao_wo_gege(self):
        r = detect_group_relational_roles("叫我哥哥", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "哥哥")

    def test_cn_han_wo_jiejie(self):
        r = detect_group_relational_roles("你喊我姐姐吧", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "姐姐")

    def test_en_i_am_your_father(self):
        r = detect_group_relational_roles("I am your father", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "爸爸")

    def test_en_im_your_dad(self):
        r = detect_group_relational_roles("I'm your dad", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "爸爸")

    def test_en_call_me_mom(self):
        r = detect_group_relational_roles("call me mom", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "妈妈")

    def test_en_call_me_big_brother(self):
        r = detect_group_relational_roles("call me big brother", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "哥哥")

    def test_cn_wo_shi_ni_laoban(self):
        r = detect_group_relational_roles("我是你老板", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "老板")

    def test_en_i_am_your_boss(self):
        r = detect_group_relational_roles("I am your boss", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "老板")

    def test_cn_jiao_wo_shifu(self):
        r = detect_group_relational_roles("叫我师傅", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "师傅")

    def test_en_call_me_master(self):
        r = detect_group_relational_roles("call me master", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "主人")


class TestBotRoleAssignment(unittest.TestCase):
    """User assigns a role to the bot."""

    def test_cn_ni_shi_women_de_haizi(self):
        r = detect_group_relational_roles("你是我们的孩子", speaker_user_id="u1")
        self.assertEqual(r.bot_role, "孩子")

    def test_cn_ni_jiu_shi_wo_de_erzi(self):
        r = detect_group_relational_roles("你就是我的儿子", speaker_user_id="u1")
        self.assertEqual(r.bot_role, "儿子")

    def test_cn_ni_shi_meimei(self):
        r = detect_group_relational_roles("你是妹妹了", speaker_user_id="u1")
        self.assertEqual(r.bot_role, "妹妹")

    def test_en_you_are_our_child(self):
        r = detect_group_relational_roles("you are our child", speaker_user_id="u1")
        self.assertEqual(r.bot_role, "孩子")

    def test_en_youre_my_son(self):
        r = detect_group_relational_roles("you're my son", speaker_user_id="u1")
        self.assertEqual(r.bot_role, "儿子")

    def test_en_you_are_my_little_sister(self):
        r = detect_group_relational_roles("you are my little sister", speaker_user_id="u1")
        self.assertEqual(r.bot_role, "妹妹")

    def test_cn_ni_shi_baobei(self):
        r = detect_group_relational_roles("你是宝贝", speaker_user_id="u1")
        self.assertEqual(r.bot_role, "宝贝")

    def test_en_you_are_my_baby(self):
        r = detect_group_relational_roles("you are my baby", speaker_user_id="u1")
        self.assertEqual(r.bot_role, "宝贝")

    def test_en_you_are_my_dear(self):
        r = detect_group_relational_roles("you are my dear", speaker_user_id="u1")
        self.assertEqual(r.bot_role, "亲爱的")


class TestThirdPartyRoleAssignment(unittest.TestCase):
    """Speaker assigns role to another group member."""

    def test_cn_pronoun_via_reply(self):
        r = detect_group_relational_roles(
            "她是你妈妈",
            speaker_user_id="u1",
            reply_to_user_id="u2",
        )
        self.assertEqual(len(r.third_party_roles), 1)
        self.assertEqual(r.third_party_roles[0], ("u2", "妈妈"))

    def test_cn_zhe_shi_via_reply(self):
        r = detect_group_relational_roles(
            "这是你爸爸",
            speaker_user_id="u1",
            reply_to_user_id="u3",
        )
        self.assertEqual(r.third_party_roles[0], ("u3", "爸爸"))

    def test_en_she_is_your_mother_via_reply(self):
        r = detect_group_relational_roles(
            "she is your mother",
            speaker_user_id="u1",
            reply_to_user_id="u2",
        )
        self.assertEqual(r.third_party_roles[0], ("u2", "妈妈"))

    def test_cn_pronoun_no_reply_ignored(self):
        """Without reply context, pronoun-based assignment is ignored."""
        r = detect_group_relational_roles(
            "她是你妈妈",
            speaker_user_id="u1",
            reply_to_user_id=None,
        )
        self.assertEqual(len(r.third_party_roles), 0)

    def test_cn_mention_assignment(self):
        r = detect_group_relational_roles(
            "@Alice是你的妈妈",
            speaker_user_id="u1",
            mentioned_users={"alice": "u2"},
        )
        self.assertEqual(len(r.third_party_roles), 1)
        self.assertEqual(r.third_party_roles[0], ("u2", "妈妈"))

    def test_en_mention_assignment(self):
        r = detect_group_relational_roles(
            "@Bob is your dad",
            speaker_user_id="u1",
            mentioned_users={"bob": "u3"},
        )
        self.assertEqual(r.third_party_roles[0], ("u3", "爸爸"))

    def test_mention_not_found_ignored(self):
        """If mentioned name doesn't match any known user, ignore."""
        r = detect_group_relational_roles(
            "@Unknown是你的妈妈",
            speaker_user_id="u1",
            mentioned_users={"alice": "u2"},
        )
        self.assertEqual(len(r.third_party_roles), 0)


class TestMultiRoleInOneMessage(unittest.TestCase):
    """Multiple role assignments in a single message."""

    def test_speaker_and_bot_role(self):
        r = detect_group_relational_roles(
            "我是你爸爸，你是我们的孩子",
            speaker_user_id="u1",
        )
        self.assertEqual(r.speaker_role, "爸爸")
        self.assertEqual(r.bot_role, "孩子")

    def test_speaker_and_third_party(self):
        r = detect_group_relational_roles(
            "我是你爸爸，她是你妈妈",
            speaker_user_id="u1",
            reply_to_user_id="u2",
        )
        self.assertEqual(r.speaker_role, "爸爸")
        self.assertEqual(r.third_party_roles[0], ("u2", "妈妈"))


class TestRoleRevocation(unittest.TestCase):
    """Removal of relational roles."""

    def test_cn_speaker_revoke(self):
        r = detect_group_relational_roles("我不是你爸爸了", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "")

    def test_cn_bie_jiao_wo(self):
        r = detect_group_relational_roles("别叫我妈妈", speaker_user_id="u1")
        self.assertEqual(r.speaker_role, "")

    def test_en_speaker_revoke(self):
        r = detect_group_relational_roles(
            "I'm not your dad anymore", speaker_user_id="u1"
        )
        self.assertEqual(r.speaker_role, "")

    def test_en_dont_call_me(self):
        r = detect_group_relational_roles(
            "don't call me mom", speaker_user_id="u1"
        )
        self.assertEqual(r.speaker_role, "")

    def test_cn_bot_revoke(self):
        r = detect_group_relational_roles("你不是我孩子了", speaker_user_id="u1")
        self.assertEqual(r.bot_role, "")

    def test_en_bot_revoke(self):
        r = detect_group_relational_roles(
            "you're not my child anymore", speaker_user_id="u1"
        )
        self.assertEqual(r.bot_role, "")

    def test_revoke_takes_priority_over_assign(self):
        """If both revoke and assign match, revoke wins."""
        r = detect_group_relational_roles(
            "我不是你爸爸了，别叫我爸爸",
            speaker_user_id="u1",
        )
        self.assertEqual(r.speaker_role, "")


class TestNoFalsePositives(unittest.TestCase):
    """Non-role text should not trigger detection."""

    def test_random_chinese(self):
        r = detect_group_relational_roles("今天天气真好", speaker_user_id="u1")
        self.assertIsNone(r.speaker_role)
        self.assertIsNone(r.bot_role)
        self.assertEqual(len(r.third_party_roles), 0)

    def test_random_english(self):
        r = detect_group_relational_roles("what's for dinner?", speaker_user_id="u1")
        self.assertIsNone(r.speaker_role)
        self.assertIsNone(r.bot_role)

    def test_non_role_word(self):
        """Words not in vocab should not match."""
        r = detect_group_relational_roles("我是你朋友", speaker_user_id="u1")
        self.assertIsNone(r.speaker_role)

    def test_empty_text(self):
        r = detect_group_relational_roles("", speaker_user_id="u1")
        self.assertIsNone(r.speaker_role)
        self.assertIsNone(r.bot_role)


class TestStorageRoundTrip(unittest.TestCase):
    """Storage operations for relational roles."""

    def test_group_member_relational_role(self):
        import tempfile
        from pathlib import Path
        from analyst.storage.sqlite import SQLiteEngineStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEngineStore(db_path=Path(tmpdir) / "test.db")
            store.upsert_group_member(group_id="g1", user_id="u1", display_name="Alice")

            # Assign
            store.update_group_member_relational_role(
                group_id="g1", user_id="u1", relational_role="爸爸"
            )
            members = store.list_group_members("g1")
            self.assertEqual(len(members), 1)
            self.assertEqual(members[0].relational_role, "爸爸")

            # Clear
            store.update_group_member_relational_role(
                group_id="g1", user_id="u1", relational_role=""
            )
            members = store.list_group_members("g1")
            self.assertEqual(members[0].relational_role, "")

    def test_group_bot_relational_role(self):
        import tempfile
        from pathlib import Path
        from analyst.storage.sqlite import SQLiteEngineStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEngineStore(db_path=Path(tmpdir) / "test.db")
            store.upsert_group_profile(group_id="g1", group_name="Test Group")

            # Assign
            store.update_group_bot_relational_role(
                group_id="g1", bot_relational_role="孩子"
            )
            profile = store.get_group_profile("g1")
            self.assertEqual(profile.bot_relational_role, "孩子")

            # Clear
            store.update_group_bot_relational_role(
                group_id="g1", bot_relational_role=""
            )
            profile = store.get_group_profile("g1")
            self.assertEqual(profile.bot_relational_role, "")


class TestRendering(unittest.TestCase):
    """Participant model rendering includes relational roles."""

    def test_render_with_relational_role(self):
        from analyst.memory.service import _render_participant_model
        from analyst.storage.sqlite_records import GroupMemberRecord

        members = [
            GroupMemberRecord(
                group_id="g1",
                user_id="u1",
                display_name="Alice",
                role_in_group="leader",
                personality_notes="drives a lot of the chat",
                relational_role="爸爸",
                first_seen_at="2026-01-01",
                last_seen_at="2026-03-18",
                message_count=50,
            ),
            GroupMemberRecord(
                group_id="g1",
                user_id="u2",
                display_name="Bob",
                role_in_group="",
                personality_notes="",
                relational_role="",
                first_seen_at="2026-01-01",
                last_seen_at="2026-03-18",
                message_count=10,
            ),
        ]
        lines = _render_participant_model(
            members,
            current_speaker_id="u1",
            bot_relational_role="孩子",
        )
        # Alice should have 关系 tag
        self.assertIn("关系: 爸爸", lines[0])
        self.assertIn("(current speaker)", lines[0])
        # Bob should NOT have 关系 tag
        self.assertNotIn("关系", lines[1])
        # Bot role at end
        self.assertIn("你在这个群里的角色: 孩子", lines[-1])

    def test_render_no_relational_roles(self):
        from analyst.memory.service import _render_participant_model
        from analyst.storage.sqlite_records import GroupMemberRecord

        members = [
            GroupMemberRecord(
                group_id="g1",
                user_id="u1",
                display_name="Alice",
                role_in_group="",
                personality_notes="",
                relational_role="",
                first_seen_at="2026-01-01",
                last_seen_at="2026-03-18",
                message_count=5,
            ),
        ]
        lines = _render_participant_model(members)
        self.assertEqual(len(lines), 1)
        self.assertNotIn("关系", lines[0])
        self.assertNotIn("角色", lines[0])


if __name__ == "__main__":
    unittest.main()
