"""Public discovery content stays useful and safe without a session or a provider.

All upstream responses are synthetic. These tests never access Valve, Steam,
OpenAI, a database, or a production account.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from html import escape
import json
from threading import Event, Thread

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from narma_video import explore


NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No fixture or accidentally stale module cache may touch the network."""
    monkeypatch.setenv("NARMA_EXPLORE_REFRESH_ENABLED", "0")
    monkeypatch.setattr(explore, "_now", lambda: NOW)

    def forbidden(*args, **kwargs):
        pytest.fail("The explore tests must never access the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)


def heroes_payload():
    return {"result": {"data": {"heroes": [
        {"id": index + 1, "name": f"npc_dota_hero_fixture_{index}",
         "name_loc": f"Герой {index:03}", "name_english_loc": f"Hero {index}",
         "primary_attr": index % 4, "complexity": 1 + index % 3}
        for index in range(100)
    ]}}}


def rss_item(*, ident="123", title="Новости Dota 2", published=None,
             url=None, image=None, description=""):
    published = published or NOW - timedelta(days=1)
    url = url or f"https://store.steampowered.com/news/app/570/view/{ident}"
    enclosure = f'<enclosure url="{escape(image, quote=True)}" />' if image else ""
    return (f"<item><title>{escape(title)}</title><link>{escape(url)}</link>"
            f"<pubDate>{format_datetime(published)}</pubDate>{enclosure}"
            f"<description>{escape(description)}</description></item>")


def rss(*items):
    return ("<rss><channel>" + "".join(items or [rss_item()]) + "</channel></rss>").encode()


def patch_payload():
    return {"success": True, "patches": [
        {"patch_number": "7.9", "patch_timestamp": int((NOW - timedelta(days=10)).timestamp())},
        {"patch_number": "7.10a", "patch_timestamp": int((NOW - timedelta(days=1)).timestamp())},
        {"patch_number": "7.10", "patch_timestamp": int((NOW - timedelta(days=2)).timestamp())},
    ]}


@pytest.fixture
def snapshot():
    checked = (NOW - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    news = explore.parse_updates(rss())
    return {"schema_version": explore.SCHEMA,
        "heroes": {"checked_at": checked, "source_url": explore.HEROES_URL,
                   "source_published_at": None, "heroes": explore.parse_heroes(heroes_payload())},
        "updates": {"checked_at": checked, "source_url": explore.NEWS_URL,
                    "patch_source_url": explore.PATCHES_URL,
                    "source_published_at": news[0]["published_at"], "news": news,
                    "latest_patch": explore.parse_patch(patch_payload())}}


@pytest.mark.parametrize("url", [
    "http://www.dota2.com/datafeed/herolist?language=russian",
    "https://www.dota2.com.evil.example/datafeed/herolist?language=russian",
    "https://evil.example@www.dota2.com/datafeed/herolist?language=russian",
    "https://www.dota2.com:444/datafeed/herolist?language=russian",
    "https://127.0.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "file:///etc/passwd",
    "https://www.dota2.com/datafeed/herolist?language=russian&url=https://evil.example",
])
def test_fetch_rejects_untrusted_sources_before_opening_a_connection(url, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("An untrusted content URL reached the network")

    monkeypatch.setattr(explore.httpx, "Client", forbidden)
    with pytest.raises(explore.SourceError):
        explore.fetch_bytes(url)


def test_heroes_have_canonical_images_and_official_pages_without_upstream_html():
    raw = heroes_payload()
    raw["result"]["data"]["heroes"][0].update(
        name="npc_dota_hero_necrolyte", name_loc="Necrophos", name_english_loc="Necrophos",
        image_url="javascript:alert(1)", official_url="https://evil.example")
    before = deepcopy(raw)
    result = explore.parse_heroes(raw)
    necro = next(hero for hero in result if hero["name"] == "npc_dota_hero_necrolyte")
    assert necro["image_url"] == explore.HERO_IMAGE_BASE + "necrolyte.png"
    assert necro["official_url"] == "https://www.dota2.com/hero/necrophos"
    assert set(hero["attribute"] for hero in result) == set(explore.ATTRIBUTES)
    assert result == sorted(result, key=lambda hero: hero["display_name"].casefold())
    assert raw == before


@pytest.mark.parametrize("status", [0, True, "1"])
def test_heroes_accept_actual_statusless_feed_but_reject_explicit_failure(status):
    assert len(explore.parse_heroes(heroes_payload())) == 100
    raw = heroes_payload()
    raw["result"]["status"] = status
    with pytest.raises(explore.SourceError):
        explore.parse_heroes(raw)


@pytest.mark.parametrize("change", [
    {"id": True}, {"id": 0}, {"id": "1"}, {"id": 2},
    {"name": "npc_dota_hero_fixture_1"}, {"name": "npc_dota_hero_../../secrets"},
    {"name": 'npc_dota_hero_axe" onerror=alert(1)'},
    {"name_loc": "<img src=x onerror=alert(1)>"}, {"name_loc": "[url=javascript:alert(1)]"},
    {"primary_attr": True}, {"primary_attr": 4}, {"complexity": False}, {"complexity": 4},
])
def test_hero_parser_rejects_duplicates_unsafe_names_and_coerced_stats(change):
    raw = heroes_payload()
    raw["result"]["data"]["heroes"][0].update(change)
    with pytest.raises(explore.SourceError):
        explore.parse_heroes(raw)


@pytest.mark.parametrize("raw", [None, {}, {"result": {"data": {"heroes": []}}}])
def test_empty_or_partial_hero_feed_cannot_replace_catalog(raw):
    with pytest.raises(explore.SourceError):
        explore.parse_heroes(raw)


def test_news_dates_deduplication_images_and_categories_do_not_publish_article_html():
    official_image = "https://clan.fastly.steamstatic.com/images/3703047/" + "a" * 40 + ".png"
    result = explore.parse_updates(rss(
        rss_item(ident="1", title="Обновление 7.10a", image=official_image,
                 published=NOW - timedelta(days=2), description='<script>secretFullArticle()</script>'),
        rss_item(ident="2", title="The International", image="javascript:alert(1)"),
        rss_item(ident="2", title="Duplicate title"),
    ))
    assert len(result) == 2
    assert result[0]["category"] == "event" and result[0]["image_url"] is None
    assert result[1]["category"] == "patch" and result[1]["image_url"] == official_image
    assert result[0]["published_at"] == "2026-09-07T12:00:00Z"
    assert "secretFullArticle" not in json.dumps(result)
    assert "description" not in result[0]


@pytest.mark.parametrize("title", [
    "<b>News</b>", "[url=javascript:alert(1)]news[/url]", "news\x00text", "x" * 241,
])
def test_news_rejects_html_markup_controls_and_unbounded_titles(title):
    with pytest.raises(explore.SourceError):
        explore.parse_updates(rss(rss_item(title=title)))


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "https://evil.example/news/app/570/view/1",
    "https://store.steampowered.com/news/app/730/view/1",
    "https://store.steampowered.com/news/app/570/view/1?next=https://evil.example",
    "https://evil.example@store.steampowered.com/news/app/570/view/1",
])
def test_news_links_are_only_canonical_dota_official_articles(url):
    with pytest.raises(explore.SourceError):
        explore.parse_updates(rss(rss_item(url=url)))


@pytest.mark.parametrize("xml", [
    b'<!DOCTYPE rss [<!ENTITY news "malicious">]><rss><channel/></rss>',
    b'<!doctype rss SYSTEM "file:///etc/passwd"><rss><channel/></rss>',
    '<!DOCTYPE rss [<!ENTITY news "malicious">]><rss><channel/></rss>'.encode("utf-16"),
    b'<rss><channel><item></rss>', b'<html>Gateway error</html>',
])
def test_news_rejects_entity_documents_and_non_feeds(xml):
    with pytest.raises(explore.SourceError):
        explore.parse_updates(xml)


def test_future_news_and_patch_timestamps_cannot_be_labeled_current():
    future = NOW + timedelta(days=1)
    with pytest.raises(explore.SourceError):
        explore.parse_updates(rss(rss_item(published=future)))
    raw = patch_payload()
    raw["patches"][1]["patch_timestamp"] = int(future.timestamp())
    with pytest.raises(explore.SourceError):
        explore.parse_patch(raw)


def test_patch_uses_source_publication_time_not_array_or_string_order():
    result = explore.parse_patch(patch_payload())
    assert result == {"version": "7.10a", "published_at": "2026-09-07T12:00:00Z",
                      "url": "https://www.dota2.com/patches/7.10a"}


def test_patch_ties_use_numeric_versions_and_repeated_versions_are_invalid():
    raw = patch_payload()
    for row in raw["patches"]:
        row["patch_timestamp"] = int((NOW - timedelta(days=1)).timestamp())
    assert explore.parse_patch(raw)["version"] == "7.10a"
    raw["patches"].append(deepcopy(raw["patches"][0]))
    with pytest.raises(explore.SourceError):
        explore.parse_patch(raw)


@pytest.mark.parametrize("change", [
    {"patch_number": "7.10<script>"}, {"patch_number": "../../secrets"},
    {"patch_timestamp": True}, {"patch_timestamp": "2026-09-07T12:00:00"},
    {"patch_timestamp": -1},
])
def test_patch_rejects_unsafe_versions_or_untrusted_timestamps(change):
    raw = patch_payload()
    raw["patches"][0].update(change)
    with pytest.raises(explore.SourceError):
        explore.parse_patch(raw)


def install_http_response(monkeypatch, handler):
    original = httpx.Client
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(explore.httpx, "Client", client)
    return options


def test_fetch_accepts_bounded_json_without_redirects_or_ambient_proxy(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    options = install_http_response(monkeypatch, handler)
    assert json.loads(explore.fetch_bytes(explore.HEROES_URL)) == {"ok": True}
    assert options[0]["follow_redirects"] is False and options[0]["trust_env"] is False
    assert len(requests) == 1 and str(requests[0].url) == explore.HEROES_URL
    assert "authorization" not in requests[0].headers


def test_fetch_never_follows_redirect_to_another_origin(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    install_http_response(monkeypatch, handler)
    with pytest.raises(explore.SourceError) as error:
        explore.fetch_bytes(explore.HEROES_URL)
    assert error.value.code == "source_unavailable" and len(requests) == 1


@pytest.mark.parametrize("retry,expected", [
    (None, 3600), ("7200", 7200), ("Tue, 08 Sep 2026 15:00:00 GMT", 10800),
])
def test_rate_limits_have_a_bounded_safe_error_and_honor_server_retry_after(monkeypatch, retry, expected):
    headers = {"retry-after": retry} if retry is not None else {}
    install_http_response(monkeypatch, lambda request: httpx.Response(429, headers=headers))
    with pytest.raises(explore.SourceError) as error:
        explore.fetch_bytes(explore.HEROES_URL)
    assert error.value.code == "source_unavailable"
    assert error.value.retry_after == expected


def test_compressed_responses_are_rejected_before_decompression(monkeypatch):
    install_http_response(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type": "application/json", "content-encoding": "gzip"},
        stream=httpx.ByteStream(b"not a valid gzip stream")))
    with pytest.raises(explore.SourceError) as error:
        explore.fetch_bytes(explore.HEROES_URL)
    assert error.value.code == "invalid_source"


@pytest.mark.parametrize("headers,body,code", [
    ({"content-type": "text/html"}, b"<html>upstream unavailable</html>", "invalid_source"),
    ({"content-type": "application/json", "content-length": "9999999"}, b"{}", "source_too_large"),
    ({"content-type": "application/json"}, b"x" * (explore.MAX_BYTES + 1), "source_too_large"),
])
def test_fetch_rejects_wrong_media_type_and_excessive_payloads(monkeypatch, headers, body, code):
    install_http_response(monkeypatch, lambda request: httpx.Response(200, headers=headers, content=body))
    with pytest.raises(explore.SourceError) as error:
        explore.fetch_bytes(explore.HEROES_URL)
    assert error.value.code == code


def test_cache_returns_detached_snapshot_without_refresh_when_disabled(snapshot):
    cache = explore.PublicCache(snapshot)
    first = cache.get("heroes")
    first["heroes"][0]["display_name"] = "mutated"
    first["errors"].append("mutated")
    snapshot["heroes"]["heroes"][1]["display_name"] = "source mutated"
    second = cache.get("heroes")
    assert second["stale"] is True and second["refreshing"] is False
    assert second["errors"] == []
    assert "mutated" not in json.dumps(second)


def test_failed_refresh_retains_last_good_data_and_time_with_safe_errors(snapshot, monkeypatch):
    cache = explore.PublicCache(snapshot)

    def fail(url):
        raise RuntimeError("private-token upstream internal-host traceback")

    monkeypatch.setattr(explore, "fetch_bytes", fail)
    cache._refresh()
    for kind in ("heroes", "updates"):
        result = cache.get(kind)
        assert result["checked_at"] == snapshot[kind]["checked_at"]
        assert result["errors"] == ["invalid_source"] and result["stale"] is True
        assert result["refreshing"] is False
        assert "private-token" not in json.dumps(result)
        for field in snapshot[kind]:
            assert result[field] == snapshot[kind][field]


def test_successful_refresh_replaces_content_and_keeps_source_publication_distinct(snapshot, monkeypatch):
    cache = explore.PublicCache(snapshot)
    replies = {explore.HEROES_URL: json.dumps(heroes_payload()).encode(),
               explore.NEWS_URL: rss(rss_item(title="Новая новость")),
               explore.PATCHES_URL: json.dumps(patch_payload()).encode()}
    calls = []
    monkeypatch.setattr(explore, "fetch_bytes", lambda url: calls.append(url) or replies[url])
    cache._refresh()
    result = cache.get("updates")
    assert set(calls) == explore.SOURCE_URLS and len(calls) == 3
    assert result["news"][0]["title"] == "Новая новость"
    assert result["checked_at"] == "2026-09-08T12:00:00Z"
    assert result["source_published_at"] == "2026-09-07T12:00:00Z"
    assert result["stale"] is False and result["errors"] == []


@pytest.mark.parametrize("retry_hint", [None, 7200])
def test_refresh_is_nonblocking_single_flight_and_failures_observe_retry_delay(snapshot, monkeypatch, retry_hint):
    cache = explore.PublicCache(snapshot)
    monkeypatch.setenv("NARMA_EXPLORE_REFRESH_ENABLED", "1")
    clock = [1000.0]
    monkeypatch.setattr(explore.time, "monotonic", lambda: clock[0])
    entered, release, finished = Event(), Event(), Event()
    calls = []
    original_refresh = cache._refresh

    def fetch(url):
        calls.append(url)
        entered.set()
        assert release.wait(3), "The test failed to release its synthetic upstream"
        raise explore.SourceError("source_unavailable", retry_after=retry_hint)

    def refresh():
        try:
            original_refresh()
        finally:
            finished.set()

    monkeypatch.setattr(explore, "fetch_bytes", fetch)
    monkeypatch.setattr(cache, "_refresh", refresh)
    readers = []
    results = []
    try:
        first = cache.get("heroes")
        assert first["refreshing"] is True and entered.wait(1)
        for _ in range(8):
            reader = Thread(target=lambda: results.append(cache.get("updates")))
            readers.append(reader)
            reader.start()
        for reader in readers:
            reader.join(1)
            assert not reader.is_alive(), "A public read blocked on the upstream feed"
        assert len(results) == 8 and all(result["refreshing"] for result in results)
        assert calls == [explore.HEROES_URL]
    finally:
        release.set()
        assert finished.wait(3)
        for reader in readers:
            reader.join(1)
    assert len(calls) == 2
    clock[0] += (retry_hint or explore.RETRY_SECONDS) - 1
    assert cache.get("heroes")["refreshing"] is False
    assert len(calls) == 2
    finished.clear()
    clock[0] += 2
    cache.get("heroes")
    assert finished.wait(3) and len(calls) == 4


@pytest.fixture
def public_client(snapshot, monkeypatch):
    monkeypatch.setattr(explore, "_cache", explore.PublicCache(snapshot))
    app = FastAPI()
    app.include_router(explore.router)
    with TestClient(app) as client:
        yield client


def test_discovery_routes_work_without_owner_or_provider_credentials(public_client):
    for path in ("heroes", "updates", "learning"):
        response = public_client.get(f"/api/explore/{path}")
        assert response.status_code == 200
        assert response.headers["cache-control"].startswith("public,")
        assert "set-cookie" not in response.headers
        assert "owner_id" not in response.text and "api_key" not in response.text


@pytest.mark.parametrize("position", ["1", "2", "3", "4", "5"])
def test_public_learning_accepts_only_declared_positions(public_client, monkeypatch, position):
    calls = []
    monkeypatch.setattr(explore, "get_catalog", lambda role: calls.append(role) or {"position": role})
    response = public_client.get("/api/explore/learning", params={"position": position})
    assert response.status_code == 200
    assert calls == [int(position)]


@pytest.mark.parametrize("position", ["", "0", "6", "-1", "01", "+1", "1.0", " 1", "1 ", "true", "1\n"])
def test_public_learning_does_not_coerce_invalid_positions(public_client, monkeypatch, position):
    monkeypatch.setattr(explore, "get_catalog", lambda role: pytest.fail("Invalid position reached catalog"))
    assert public_client.get("/api/explore/learning", params={"position": position}).status_code == 422


def test_public_routes_do_not_offer_mutation_endpoints(public_client):
    for path in ("heroes", "updates", "learning"):
        assert public_client.post(f"/api/explore/{path}", json={"owner_id": "victim"}).status_code == 405


def test_missing_snapshot_is_explicitly_unavailable(public_client, monkeypatch):
    monkeypatch.setattr(explore, "_cache", None)
    response = public_client.get("/api/explore/heroes")
    assert response.status_code == 503
    assert "недоступны" in response.json()["detail"]


def test_shipped_snapshot_contains_real_catalog_and_source_dated_news():
    data = json.loads(explore.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert data["schema_version"] == explore.SCHEMA
    heroes = data["heroes"]["heroes"]
    assert 100 <= len(heroes) <= 300
    assert len({hero["id"] for hero in heroes}) == len(heroes)
    assert len({hero["name"] for hero in heroes}) == len(heroes)
    assert any(hero["name"] == "npc_dota_hero_axe" for hero in heroes)
    for hero in heroes:
        assert hero["image_url"] == explore.HERO_IMAGE_BASE + hero["slug"] + ".png"
        assert hero["official_url"].startswith("https://www.dota2.com/hero/")
    assert data["heroes"]["source_url"] == explore.HEROES_URL
    assert data["updates"]["source_url"] == explore.NEWS_URL
    assert data["updates"]["patch_source_url"] == explore.PATCHES_URL
    checked = datetime.fromisoformat(data["updates"]["checked_at"].replace("Z", "+00:00"))
    assert checked.utcoffset() == timedelta(0)
    assert 1 <= len(data["updates"]["news"]) <= 12
    for article in data["updates"]["news"]:
        published = datetime.fromisoformat(article["published_at"].replace("Z", "+00:00"))
        assert published <= checked
        assert article["url"].startswith("https://store.steampowered.com/news/app/570/view/")
        assert "<" not in article["title"] and ">" not in article["title"]
    patch = data["updates"]["latest_patch"]
    assert datetime.fromisoformat(patch["published_at"].replace("Z", "+00:00")) <= checked
    assert patch["url"] == "https://www.dota2.com/patches/" + patch["version"]
