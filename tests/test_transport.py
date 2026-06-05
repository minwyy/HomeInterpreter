from types import SimpleNamespace

import pytest

from app import config, transport


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _key_and_clear_cache(monkeypatch):
    monkeypatch.setattr(config, "NSW_TRANSPORT_API_KEY", "test-key")
    transport._stop_id_cache.clear()


def test_no_key_degrades(monkeypatch):
    monkeypatch.setattr(config, "NSW_TRANSPORT_API_KEY", "")
    out = transport.get_bus_departures("Underwood Rd before Powell St")
    assert "未配置" in out


def test_numeric_stop_skips_stop_finder(monkeypatch):
    """纯数字 stop 直接当 id 用，不该调 stop_finder。"""
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs["params"]
        return _FakeResp({
            "stopEvents": [
                {
                    "transportation": {"number": "526", "destination": {"name": "Strathfield"}},
                    "departureTimePlanned": "2099-01-01T00:00:00Z",
                    "departureTimeEstimated": "2099-01-01T00:05:00Z",
                }
            ]
        })

    monkeypatch.setattr(transport.httpx, "get", fake_get)
    out = transport.get_bus_departures("10118084", route="526")

    assert "departure_mon" in captured["url"]
    assert captured["params"]["name_dm"] == "10118084"
    assert "526" in out and "Strathfield" in out and "实时" in out


def test_name_resolved_via_stop_finder(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if "stop_finder" in url:
            return _FakeResp({"locations": [
                {"id": "10118084", "name": "Underwood Rd before Powell St", "type": "stop", "isBest": True},
            ]})
        assert kwargs["params"]["name_dm"] == "10118084"  # resolved id flows through
        return _FakeResp({"stopEvents": [
            {"transportation": {"number": "526", "destination": {"name": "Strathfield"}},
             "departureTimePlanned": "2099-01-01T00:10:00Z"},
        ]})

    monkeypatch.setattr(transport.httpx, "get", fake_get)
    out = transport.get_bus_departures("Underwood Rd before Powell St", route="526")

    assert any("stop_finder" in u for u in calls)
    assert any("departure_mon" in u for u in calls)
    assert "526" in out


def test_route_filter_excludes_other_lines(monkeypatch):
    def fake_get(url, **kwargs):
        return _FakeResp({"stopEvents": [
            {"transportation": {"number": "408", "destination": {"name": "Strathfield"}},
             "departureTimePlanned": "2099-01-01T00:02:00Z"},
            {"transportation": {"number": "526", "destination": {"name": "Strathfield"}},
             "departureTimePlanned": "2099-01-01T00:08:00Z"},
        ]})

    monkeypatch.setattr(transport.httpx, "get", fake_get)
    out = transport.get_bus_departures("10118084", route="526")

    assert "526" in out
    assert "408" not in out


def test_returns_next_two_by_default(monkeypatch):
    def fake_get(url, **kwargs):
        return _FakeResp({"stopEvents": [
            {"transportation": {"number": "526", "destination": {"name": "Strathfield"}},
             "departureTimePlanned": f"2099-01-01T00:0{i}:00Z"} for i in range(1, 6)
        ]})

    monkeypatch.setattr(transport.httpx, "get", fake_get)
    out = transport.get_bus_departures("10118084", route="526")

    # 默认两班：出现两条 526 班次行（不含表头）
    assert out.count("526 路（开往") == 2


def test_no_matching_departures(monkeypatch):
    monkeypatch.setattr(transport.httpx, "get", lambda url, **k: _FakeResp({"stopEvents": []}))
    out = transport.get_bus_departures("10118084", route="526")
    assert "暂无" in out
