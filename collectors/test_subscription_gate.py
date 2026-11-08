"""Synthetic HTML fixtures only; no network, article corpus or credentials."""
import unittest
from subscription_gate import detect_subscription_lock, assert_no_subscription_lock, SubscriptionLockDetected

class GateTests(unittest.TestCase):
    def test_lock_after_body(self):
        raw = '<div class="article-body">preview</div><div class="subscription__lock">订阅栏目查看完整内容</div>'.encode()
        result = detect_subscription_lock(raw)
        self.assertTrue(result["blocked"])
        with self.assertRaises(SubscriptionLockDetected):
            assert_no_subscription_lock(raw)
        for evidence in result["evidence"]:
            self.assertEqual(raw.decode()[evidence["start"]:evidence["end"]], evidence["quote"])

    def test_subscribe_navigation_is_not_a_lock(self):
        raw = '<nav>订阅</nav><div class="article-body">A complete public example.</div>'.encode()
        self.assertFalse(detect_subscription_lock(raw)["blocked"])

    def test_invalid_encoding_fails_closed(self):
        with self.assertRaises(UnicodeDecodeError):
            assert_no_subscription_lock(b"\xff")

if __name__ == "__main__":
    unittest.main()
