import unittest

from main import _update_key


class WebhookKeyTests(unittest.TestCase):
    def test_message_key_uses_mid(self):
        payload = {"message": {"body": {"mid": "mid-123"}}}
        self.assertEqual(_update_key(payload), "message:mid-123")

    def test_callback_key_uses_callback_id(self):
        payload = {"callback": {"callback_id": "callback-123"}}
        self.assertEqual(_update_key(payload), "callback:callback-123")

    def test_fallback_key_is_stable(self):
        payload = {"timestamp": 1, "message": {"text": "test"}}
        self.assertEqual(_update_key(payload), _update_key(dict(reversed(list(payload.items())))))


if __name__ == "__main__":
    unittest.main()
