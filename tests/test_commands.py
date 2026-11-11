"""Offline command decoding regressions; no Host or Telegram connection required."""

from copy import deepcopy
from itertools import product
import unittest

from codec import decode_message, utf16_length


def payload(text, entities, *, caption=False, chat_type="private"):
    return {
        "message_id": 42,
        "date": 1791504000,
        "chat": {"id": 123 if chat_type == "private" else -123, "type": chat_type, "title": "Synthetic group"},
        "from": {"id": 123, "first_name": "Synthetic user"},
        "caption" if caption else "text": text,
        "caption_entities" if caption else "entities": entities,
    }


class CommandTests(unittest.TestCase):
    def test_addressing_preserves_arguments(self):
        cases = [
            ("/draw@Test_Bot", "Test_Bot", "/draw", True),
            ("/draw@tEsT_bOt", "TEST_BOT", "/draw", True),
            ("/draw@Other_Bot", "Test_Bot", "/draw@Other_Bot", False),
            ("/draw@Test_Bot_extra", "Test_Bot", "/draw@Test_Bot_extra", False),
            ("/draw@Test_Bot", "", "/draw@Test_Bot", False),
            ("/draw@", "Test_Bot", "/draw@", False),
            ("/draw@Teſt_Bot", "Test_Bot", "/draw@Teſt_Bot", False),
            ("/draw", "Test_Bot", "/draw", True),
            ("/help@Test_Bot", "Test_Bot", "/help", True),
            ("/HELP@Test_Bot", "Test_Bot", "/HELP", True),
            ("/help", "Test_Bot", "/help", True),
        ]
        for caption, (command, username, expected, is_command) in product((False, True), cases):
            with self.subTest(caption=caption, command=command, username=username):
                arguments = "  猫😀\n/draw@Other_Bot user@example.com  "
                message = payload(
                    command + arguments,
                    [{"type": "bot_command", "offset": 0, "length": utf16_length(command)}],
                    caption=caption,
                )
                original = deepcopy(message)

                result = decode_message(message, "999", username, [])

                self.assertEqual(result["raw_message"], [{"type": "text", "data": expected + arguments}])
                self.assertIs(result["is_command"], is_command)
                self.assertFalse(result["is_at"])
                self.assertFalse(result["is_mentioned"])
                self.assertEqual(message, original)

    def test_utf16_mentions_media_reply_and_chat_identity(self):
        chats = [("private", False), ("group", False), ("supergroup", False), ("supergroup", True)]
        for caption, (chat_type, topic) in product((False, True), chats):
            with self.subTest(caption=caption, chat_type=chat_type, topic=topic):
                command = "/draw@Test_Bot"
                prefix = command + " 😀猫 "
                text = prefix + "@Other_Bot 与 @Test_Bot"
                entities = [
                    {"type": "bot_command", "offset": 0, "length": utf16_length(command)},
                    {"type": "mention", "offset": utf16_length(prefix), "length": len("@Other_Bot")},
                    {"type": "mention", "offset": utf16_length(prefix + "@Other_Bot 与 "), "length": len("@Test_Bot")},
                ]
                message = payload(text, entities, caption=caption, chat_type=chat_type)
                message["reply_to_message"] = {
                    "message_id": 41,
                    "text": "/draw@Test_Bot original",
                    "from": {"id": 456, "first_name": "Author"},
                }
                if topic:
                    message.update(is_topic_message=True, message_thread_id=7)
                    message["chat"]["is_forum"] = True
                original = deepcopy(message)
                media = [{"type": "image", "data": "synthetic image"}]

                result = decode_message(message, "999", "Test_Bot", media, "Art")

                self.assertEqual(result["raw_message"][0]["data"]["target_message_content"], "/draw@Test_Bot original")
                self.assertEqual(result["raw_message"][1:], [
                    {"type": "text", "data": "/draw 😀猫 "},
                    {"type": "at", "data": {"target_user_id": "@Other_Bot", "target_user_nickname": "@Other_Bot"}},
                    {"type": "text", "data": " 与 "},
                    {"type": "at", "data": {"target_user_id": "999", "target_user_nickname": "@Test_Bot"}},
                    *media,
                ])
                self.assertTrue(result["is_command"])
                self.assertTrue(result["is_picture"])
                self.assertTrue(result["is_mentioned"])
                self.assertEqual(result["account_id"], "999")
                self.assertEqual(result["message_id"], "123:42" if chat_type == "private" else "-123:42")
                info = result["message_info"]
                self.assertEqual(info["user_info"]["user_id"], "123")
                if chat_type == "private":
                    self.assertNotIn("group_info", info)
                else:
                    self.assertEqual(info["group_info"], {
                        "group_id": "-123:7" if topic else "-123",
                        "group_name": "Synthetic group / Art" if topic else "Synthetic group",
                    })
                if topic:
                    self.assertEqual(info["additional_config"]["telegram_message_thread_id"], 7)
                else:
                    self.assertNotIn("telegram_message_thread_id", info["additional_config"])
                self.assertEqual(message, original)

    def test_non_command_text_is_not_rewritten(self):
        cases = [
            ("/draw@Test_Bot", []),
            ("普通正文 /draw@Test_Bot", []),
            ("😀 /draw@Test_Bot", [{"type": "bot_command", "offset": 3, "length": len("/draw@Test_Bot")}]),
            ("/draw@Test_Bot", [{"type": "code", "offset": 0, "length": len("/draw@Test_Bot")}]),
        ]
        for caption, (text, entities) in product((False, True), cases):
            with self.subTest(caption=caption, text=text, entities=entities):
                result = decode_message(payload(text, entities, caption=caption), "999", "Test_Bot", [])
                self.assertEqual(result["raw_message"], [{"type": "text", "data": text}])
                self.assertFalse(result["is_command"])

    def test_command_only_and_wrong_bot_with_actual_mention(self):
        command = "/draw@Test_Bot"
        result = decode_message(
            payload(command, [{"type": "bot_command", "offset": 0, "length": utf16_length(command)}]),
            "999", "Test_Bot", [],
        )
        self.assertEqual(result["raw_message"], [{"type": "text", "data": "/draw"}])
        self.assertTrue(result["is_command"])
        text = "/draw@Other_Bot @Test_Bot"
        entities = [
            {"type": "bot_command", "offset": 0, "length": len("/draw@Other_Bot")},
            {"type": "mention", "offset": len("/draw@Other_Bot "), "length": len("@Test_Bot")},
        ]
        result = decode_message(payload(text, entities), "999", "Test_Bot", [])
        self.assertEqual(result["raw_message"][0], {"type": "text", "data": "/draw@Other_Bot "})
        self.assertFalse(result["is_command"])
        self.assertTrue(result["is_mentioned"])

    def test_overlapping_command_and_mention_is_rejected(self):
        text = "/draw@Test_Bot"
        entities = [
            {"type": "bot_command", "offset": 0, "length": utf16_length(text)},
            {"type": "mention", "offset": len("/draw"), "length": len("@Test_Bot")},
        ]
        with self.assertRaises(ValueError):
            decode_message(payload(text, entities), "999", "Test_Bot", [])


if __name__ == "__main__":
    unittest.main()
