import unittest

from app.services.reference.fallback_lookup import (
    FallbackReferenceLookup,
    LookupState,
    ReferenceAttempt,
)


class FakeProvider:
    def __init__(self, name: str, attempts: list[ReferenceAttempt]):
        self.name = name
        self.attempts = attempts
        self.calls = 0

    def lookup(self, ncm: str) -> ReferenceAttempt:
        result = self.attempts[min(self.calls, len(self.attempts) - 1)]
        self.calls += 1
        return result


class FallbackReferenceLookupTests(unittest.TestCase):
    def test_uses_first_source_when_it_returns_a_reference(self) -> None:
        primary = FakeProvider(
            "tabelas",
            [ReferenceAttempt("tabelas", LookupState.FOUND, cest_codes=("03.002.00",))],
        )
        fallback = FakeProvider("ncm_api", [ReferenceAttempt("ncm_api", LookupState.UNAVAILABLE)])
        router = FallbackReferenceLookup((primary, fallback), sleep_fn=lambda _: None)

        result = router.lookup("2203.00.00")

        self.assertEqual(result.attempt.source, "tabelas")
        self.assertEqual(result.attempt.cest_codes, ("03.002.00",))
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)

    def test_restarts_from_first_source_after_seventy_seconds_when_all_fail(self) -> None:
        providers = tuple(
            FakeProvider(name, [ReferenceAttempt(name, LookupState.UNAVAILABLE)])
            for name in ("tabelas", "ncm_api", "azx", "local")
        )
        waits: list[float] = []
        router = FallbackReferenceLookup(
            providers,
            retry_seconds=70,
            max_cycles=2,
            sleep_fn=waits.append,
            clock_fn=lambda: 0,
        )

        result = router.lookup("22030000")

        self.assertEqual(waits, [70, 120, 70])
        self.assertEqual(result.attempt.state, LookupState.UNAVAILABLE)
        self.assertEqual([provider.calls for provider in providers], [4, 4, 2, 2])

    def test_keeps_partial_ncm_result_when_cest_is_not_available(self) -> None:
        primary = FakeProvider("tabelas", [ReferenceAttempt("tabelas", LookupState.UNAVAILABLE)])
        ncm_api = FakeProvider("ncm_api", [ReferenceAttempt("ncm_api", LookupState.PARTIAL)])
        local = FakeProvider("local", [ReferenceAttempt("local", LookupState.NOT_FOUND)])
        router = FallbackReferenceLookup((primary, ncm_api, local), sleep_fn=lambda _: None)

        result = router.lookup("22030000")

        self.assertEqual(result.attempt.source, "ncm_api")
        self.assertEqual(result.attempt.state, LookupState.PARTIAL)

    def test_uses_ncm_result_without_waiting_when_the_secondary_api_responds(self) -> None:
        primary = FakeProvider("tabelas", [ReferenceAttempt("tabelas", LookupState.UNAVAILABLE)])
        ncm_api = FakeProvider("ncm_api", [ReferenceAttempt("ncm_api", LookupState.PARTIAL)])
        waits: list[float] = []
        router = FallbackReferenceLookup((primary, ncm_api), retry_seconds=70, max_cycles=2, sleep_fn=waits.append)

        result = router.lookup("22030000")

        self.assertEqual(result.attempt.state, LookupState.PARTIAL)
        self.assertEqual(waits, [])

    def test_uses_full_fallback_only_after_two_consecutive_api_failures(self) -> None:
        primary = FakeProvider(
            "tabelas",
            [
                ReferenceAttempt("tabelas", LookupState.UNAVAILABLE),
                ReferenceAttempt("tabelas", LookupState.UNAVAILABLE),
                ReferenceAttempt("tabelas", LookupState.FOUND, cest_codes=("03.002.00",)),
            ],
        )
        ncm_api = FakeProvider("ncm_api", [ReferenceAttempt("ncm_api", LookupState.UNAVAILABLE)])
        azx = FakeProvider("azx", [ReferenceAttempt("azx", LookupState.MANUAL_REVIEW)])
        local = FakeProvider("local", [ReferenceAttempt("local", LookupState.UNAVAILABLE)])
        waits: list[float] = []
        router = FallbackReferenceLookup(
            (primary, ncm_api, azx, local), max_cycles=2, sleep_fn=waits.append, clock_fn=lambda: 0
        )

        result = router.lookup("22030000")

        self.assertEqual(result.attempt.source, "tabelas")
        self.assertEqual(result.attempt.cest_codes, ("03.002.00",))
        self.assertEqual(waits, [70, 120])
        self.assertEqual([primary.calls, ncm_api.calls, azx.calls, local.calls], [3, 2, 1, 1])
