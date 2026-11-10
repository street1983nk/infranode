"""Regressionstests für die Pfad-Begrenzung im MCP-Client und den Host-/Schema-Filter
für Upstream-GBFS-Feed-URLs."""

import httpx
import pytest

from infranode.adapters import gbfs
from infranode.mcp import client

DISCOVERY = "https://api.mobidata-bw.de/sharing/gbfs/v2/callabike/gbfs"


@pytest.mark.parametrize("slug", [".", "..", "...", "...."])
def test_dot_only_slug_rejected(slug: str) -> None:
    """Reine Punkt-Segmente dürfen den /cities/{slug}/-Pfad nicht verlassen."""
    with pytest.raises(ValueError, match="Punkt-Segment"):
        client._validate_slug(slug)


def test_dot_segment_would_escape_cities_path_without_guard() -> None:
    """Dokumentiert das httpx-Verhalten (RFC 3986 remove_dot_segments)."""
    collapsed = httpx.URL("http://localhost:8000/api/v1/cities/../weather")
    assert str(collapsed).endswith("/api/v1/weather")


@pytest.mark.parametrize(
    "slug",
    ["hamburg", "frankfurt-am-main", "st.-ingbert", "k%C3%B6ln"],
)
def test_regular_slugs_still_accepted(slug: str) -> None:
    """Reguläre Stadt-Slugs inklusive Punkt im Namen bleiben gültig."""
    assert client._validate_slug(slug)


async def test_get_resource_dot_slug_sends_no_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_resource lehnt '..' ab, bevor ein HTTP-Request ausgelöst wird."""
    called = False

    async def fake_request(*args: object, **kwargs: object) -> dict:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(ValueError, match="Punkt-Segment"):
        await client.get_resource("..", "weather")
    assert called is False


async def test_get_live_dot_slug_sends_no_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_live lehnt '..' ebenfalls vor jedem HTTP-Request ab."""
    called = False

    async def fake_request(*args: object, **kwargs: object) -> dict:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(ValueError, match="Punkt-Segment"):
        await client.get_live("..", "transit/departures")
    assert called is False


def test_safe_feeds_keeps_same_host_and_redirect_hosts() -> None:
    """Erlaubte Feed-URLs auf Discovery-Host oder _REDIRECT_HOSTS bleiben erhalten."""
    feeds = {
        "system_information": (
            "https://api.mobidata-bw.de/sharing/gbfs/v2/callabike/system_information"
        ),
        "station_status": (
            "https://gbfs2.nextbike.net/maps/gbfs/v2/x/station_status.json"
        ),
    }
    assert gbfs._safe_feeds(feeds, DISCOVERY) == feeds
    donkey_discovery = (
        "https://stables.donkey.bike/api/public/gbfs/3.0/donkey_kielsmile/gbfs.json"
    )
    donkey_feeds = {
        "system_information": (
            "https://stables.donkey.bike/api/public/gbfs/3.0/"
            "donkey_kielsmile/system_information.json"
        ),
    }
    assert gbfs._safe_feeds(donkey_feeds, donkey_discovery) == donkey_feeds


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://api.mobidata-bw.de/sharing/gbfs/v2/callabike/system_information",
        "https://127.0.0.1:8080/internal",
        "https://localhost/internal",
        "https://untrusted.example/feed.json",
        "https://acct@api.mobidata-bw.de/x",
        "https://api.mobidata-bw.de:8443/x",
        "https://api.mobidata-bw.de\\@untrusted.example/x",
        "file:///etc/hosts",
        "not a url \x00",
    ],
)
def test_safe_feeds_drops_untrusted_upstream_urls(bad_url: str) -> None:
    """Fremde Hosts, unverschlüsseltes HTTP, Userinfo und Sonderports fallen heraus."""
    assert gbfs._safe_feeds({"station_status": bad_url}, DISCOVERY) == {}


async def test_fetch_system_never_requests_foreign_feed_host() -> None:
    """_fetch_system ruft niemals fremde Feed-Hosts aus gbfs.json ab."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/gbfs"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "de": {
                            "feeds": [
                                {
                                    "name": "system_information",
                                    "url": "http://198.51.100.10/system_information.json",
                                },
                                {
                                    "name": "station_status",
                                    "url": "https://untrusted.example/s.json",
                                },
                                {
                                    "name": "station_information",
                                    "url": "https://untrusted.example/i.json",
                                },
                            ]
                        }
                    }
                },
            )
        return httpx.Response(404)

    spec = gbfs.GbfsSystem(
        system_id="callabike",
        base_url="https://api.mobidata-bw.de",
        discovery_path="/sharing/gbfs/v2/{system_id}/gbfs",
        license_override="DL-DE-BY-2.0",
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as http:
        await gbfs._fetch_system(http, spec=spec, lat=48.0, lon=9.0, radius=1000.0)
    assert seen == [DISCOVERY]
