import httpx
import pytest

from achados.db import Database
from achados.fetch import Blocked, PoliteFetcher
from achados.scrape import run_search

PAGE = (__import__("pathlib").Path(__file__).parent / "fixtures" / "imovirtual_page.html").read_text()


def fetcher(handler):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    return PoliteFetcher(delay=0, client=client, sleep=lambda s: None)


def test_robots_disallow_blocks():
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /pt/")
        return httpx.Response(200, text="x")
    with pytest.raises(Blocked):
        fetcher(h).get("https://s.pt/pt/resultados")


def test_403_is_not_retried_or_bypassed():
    calls = []
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        return httpx.Response(403)
    with pytest.raises(Blocked):
        fetcher(h).get("https://s.pt/a")
    assert len(calls) == 1


def test_429_retries_then_succeeds():
    state = {"n": 0}
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        state["n"] += 1
        return httpx.Response(429 if state["n"] < 3 else 200, text="ok")
    assert fetcher(h).get("https://s.pt/a") == "ok"


def test_run_search_paginates_until_empty(tmp_path):
    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=PAGE if "page=" not in str(req.url) else "<html></html>")
    db = Database(str(tmp_path / "t.db"))
    st = run_search({"name": "n", "source": "imovirtual", "url": "https://s.pt/x"}, db, fetcher(h), 5)
    assert (st.new, st.pages, st.blocked) == (7, 1, False)
    st2 = run_search({"name": "n", "source": "imovirtual", "url": "https://s.pt/x"}, db, fetcher(h), 5)
    assert (st2.new, st2.seen) == (0, 7)
