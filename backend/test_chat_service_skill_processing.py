import unittest
from unittest.mock import AsyncMock, patch

from backend.services import chat_service


class ChatServiceSkillProcessingTests(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_reply_handles_action_before_strip(self):
        raw_reply = (
            "这是正常回答。\n"
            '<action>{"action":"update_profile","field":"sectors","value":["黄金"]}</action>'
        )
        fake_db = object()

        with patch.object(chat_service.settings, "enable_memory", True):
            with patch.object(
                chat_service,
                "_handle_profile_action_in_reply",
                new=AsyncMock(),
            ) as handle_mock:
                cleaned = await chat_service._prepare_reply_for_user(
                    raw_reply,
                    user_id="user-1",
                    db=fake_db,
                )

        handle_mock.assert_awaited_once_with(raw_reply, "user-1", fake_db)
        self.assertIn("这是正常回答", cleaned)
        self.assertNotIn("<action>", cleaned)


if __name__ == "__main__":
    unittest.main()
