"""Rate limiting, including that RATE_LIMIT_RPM is actually honoured."""

from __future__ import annotations

import importlib

from tests.conftest import API_KEY


def _invoke(client, caller="rl-caller", agent="test-standard"):
    return client.post(
        f"/api/v1/agents/{agent}/invoke",
        json={"prompt": "hello", "caller_id": caller},
        headers={"X-API-Key": API_KEY},
    )


class TestRateLimitConfig:
    def test_env_var_sets_the_limit(self, monkeypatch):
        """Regression: RATE_LIMIT_RPM used to be documented but never read."""
        import src.rate_limiter as rl

        monkeypatch.setenv("RATE_LIMIT_RPM", "7")
        importlib.reload(rl)
        assert rl.rate_limiter.max_requests == 7

    def test_default_is_60(self, monkeypatch):
        import src.rate_limiter as rl

        monkeypatch.delenv("RATE_LIMIT_RPM", raising=False)
        importlib.reload(rl)
        assert rl.rate_limiter.max_requests == 60

    def test_non_numeric_falls_back_to_default(self, monkeypatch):
        import src.rate_limiter as rl

        monkeypatch.setenv("RATE_LIMIT_RPM", "not-a-number")
        importlib.reload(rl)
        assert rl.rate_limiter.max_requests == 60

    def test_zero_falls_back_to_default(self, monkeypatch):
        """A limit of 0 would lock everyone out; refuse it."""
        import src.rate_limiter as rl

        monkeypatch.setenv("RATE_LIMIT_RPM", "0")
        importlib.reload(rl)
        assert rl.rate_limiter.max_requests == 60


class TestRateLimitEnforcement:
    def test_limit_is_enforced_at_the_configured_value(self, client):
        c = client(RATE_LIMIT_RPM="3")
        assert [_invoke(c).status_code for _ in range(3)] == [202, 202, 202]
        assert _invoke(c).status_code == 429

    def test_429_body_reports_the_limit(self, client):
        c = client(RATE_LIMIT_RPM="2")
        for _ in range(2):
            _invoke(c)
        r = _invoke(c)
        assert r.status_code == 429
        assert "2 requests" in r.json()["detail"]

    def test_limit_is_per_caller(self, client):
        c = client(RATE_LIMIT_RPM="2")
        for _ in range(2):
            assert _invoke(c, caller="caller-a").status_code == 202
        assert _invoke(c, caller="caller-a").status_code == 429
        # A different caller has its own budget.
        assert _invoke(c, caller="caller-b").status_code == 202


class TestSlidingWindow:
    def test_expired_timestamps_are_pruned(self, monkeypatch):
        import src.rate_limiter as rl

        limiter = rl.SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
        now = [1000.0]
        monkeypatch.setattr(rl.time, "monotonic", lambda: now[0])

        limiter.check("c")
        limiter.check("c")
        # Advance past the window; the earlier entries must age out.
        now[0] += 61
        limiter.check("c")
        assert len(limiter._requests["c"]) == 1
