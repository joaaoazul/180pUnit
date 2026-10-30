from __future__ import annotations

import logging
import random
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 achados/0.1 (uso pessoal)"
)


class Blocked(Exception):
    """O site recusou o acesso (403/robots.txt). Não tentamos contornar."""


class PoliteFetcher:
    """Cliente HTTP com robots.txt, pausa entre pedidos e backoff em 429/5xx."""

    def __init__(self, delay: float = 4.0, retries: int = 3,
                 client: httpx.Client | None = None, sleep=time.sleep):
        self.delay = delay
        self.retries = retries
        self._sleep = sleep
        self._last = 0.0
        self._robots: dict[str, RobotFileParser | None] = {}
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-PT,pt;q=0.9"},
            timeout=30, follow_redirects=True,
        )

    def _wait(self) -> None:
        gap = self.delay * random.uniform(0.75, 1.5)
        elapsed = time.monotonic() - self._last
        if elapsed < gap:
            self._sleep(gap - elapsed)
        self._last = time.monotonic()

    def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = RobotFileParser()
            try:
                resp = self.client.get(f"{origin}/robots.txt")
                if resp.status_code == 200:
                    rp.parse(resp.text.splitlines())
                    self._robots[origin] = rp
                else:  # sem robots.txt -> permitido
                    self._robots[origin] = None
            except httpx.HTTPError:
                self._robots[origin] = None
        rp = self._robots[origin]
        return rp is None or rp.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> str:
        if not self._allowed(url):
            raise Blocked(f"robots.txt não permite: {url}")
        for attempt in range(self.retries + 1):
            self._wait()
            try:
                resp = self.client.get(url)
            except httpx.TransportError as exc:
                log.warning("erro de rede (%s), tentativa %d", exc, attempt + 1)
                self._sleep(2 ** attempt * 5)
                continue
            if resp.status_code in (401, 403):
                raise Blocked(f"{resp.status_code} em {url} (anti-bot?)")
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = int(resp.headers.get("Retry-After", 0) or 0) or 2 ** attempt * 10
                log.warning("%d em %s, a esperar %ds", resp.status_code, url, wait)
                self._sleep(wait)
                continue
            resp.raise_for_status()
            return resp.text
        raise httpx.HTTPError(f"falhou após {self.retries + 1} tentativas: {url}")
