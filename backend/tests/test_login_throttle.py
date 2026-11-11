"""Regras do limite de tentativas de login, com relógio controlado."""

import unittest

from app.core.login_throttle import LoginThrottle


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class LoginThrottleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.throttle = LoginThrottle(max_failures=3, window_seconds=60, lockout_seconds=120, clock=self.clock)

    def fail(self, times: int, username: str = "admin") -> None:
        for _ in range(times):
            self.throttle.record_failure(username)

    def test_blocks_after_the_limit_and_releases_after_the_lockout(self) -> None:
        self.fail(2)
        self.assertEqual(self.throttle.retry_after("admin"), 0)

        self.fail(1)
        self.assertEqual(self.throttle.retry_after("admin"), 120)

        self.clock.now += 119.5
        self.assertEqual(self.throttle.retry_after("admin"), 1)
        self.clock.now += 1
        self.assertEqual(self.throttle.retry_after("admin"), 0)

    def test_failures_outside_the_window_do_not_count(self) -> None:
        self.fail(2)
        self.clock.now += 61
        self.fail(1)

        self.assertEqual(self.throttle.retry_after("admin"), 0)

    def test_username_is_compared_without_case_or_surrounding_spaces(self) -> None:
        self.fail(1, "Admin")
        self.fail(1, " admin ")
        self.fail(1, "ADMIN")

        self.assertGreater(self.throttle.retry_after("admin"), 0)
        self.assertEqual(self.throttle.retry_after("outro"), 0)

    def test_reset_clears_failures_and_lockout(self) -> None:
        self.fail(3)
        self.throttle.reset("admin")
        self.fail(2)

        self.assertEqual(self.throttle.retry_after("admin"), 0)

    def test_stale_entries_are_pruned_when_too_many_usernames_are_tracked(self) -> None:
        throttle = LoginThrottle(max_failures=3, window_seconds=60, lockout_seconds=120, clock=self.clock, max_tracked_keys=3)
        for name in ("a", "b", "c"):
            throttle.record_failure(name)
        self.clock.now += 61
        throttle.record_failure("d")

        self.assertEqual(set(throttle._failures), {"d"})


if __name__ == "__main__":
    unittest.main()
