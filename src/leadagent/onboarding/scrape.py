"""Polite scraper for a company's public website.

Respects robots.txt, stays on one host, refuses private addresses (no SSRF into your network),
and returns clean text plus the hints the drafter needs: links, logo candidates, brand color,
structured data. Page text is untrusted data and is never treated as instructions.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "leadagent-draft/0.1 (company onboarding helper)"
MAX_BYTES = 2_000_000
SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe"}
BLOCK_TAGS = {
    "p",
    "div",
    "li",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "tr",
    "section",
    "article",
    "address",
    "footer",
    "header",
    "ul",
    "ol",
    "table",
    "dt",
    "dd",
    "blockquote",
    "details",
    "summary",
    "nav",
    "main",
    "form",
    "td",
    "th",
}
LINK_HINTS = {
    "about": 3,
    "service": 4,
    "solution": 3,
    "product": 2,
    "faq": 4,
    "question": 3,
    "financ": 4,
    "pricing": 4,
    "price": 3,
    "cost": 3,
    "warrant": 4,
    "guarantee": 2,
    "contact": 4,
    "location": 4,
    "office": 4,
    "area": 3,
    "process": 3,
    "how-it-works": 3,
    "why": 2,
    "install": 2,
    "hours": 3,
    "team": 1,
}
NON_HTML_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|mp4|mov|docx?|xlsx?|css|js)$", re.I)
_CSS_COLOR = re.compile(
    r"--(?:primary|brand|main|accent|theme)[\w-]*\s*:\s*(#[0-9a-fA-F]{6})\b", re.I
)


class BlockedHost(Exception):
    pass


def is_public_host(host: str, resolver: Callable[..., list] = socket.getaddrinfo) -> bool:
    """False for loopback, private, link-local and other non-public addresses."""
    try:
        infos = resolver(host, None)
    except OSError:
        return True  # unresolvable: the request itself will fail with a clearer error
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            return False
    return True


@dataclass
class Page:
    url: str
    title: str = ""
    text: str = ""
    description: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)
    logo_candidates: list[str] = field(default_factory=list)
    theme_colors: list[str] = field(default_factory=list)
    jsonld: list[dict] = field(default_factory=list)


@dataclass
class Site:
    root_url: str
    pages: list[Page] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # "url: reason"

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    def page_for(self, url: str) -> Page | None:
        return next((p for p in self.pages if p.url.rstrip("/") == url.rstrip("/")), None)


class _PageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.page = Page(url=base_url)
        self._skip = 0
        self._line: list[str] = []
        self._lines: list[str] = []
        self._in_title = False
        self._title: list[str] = []
        self._in_style = False
        self._in_jsonld = False
        self._jsonld: list[str] = []
        self._href: str | None = None
        self._anchor: list[str] = []

    # -- helpers
    def _flush(self) -> None:
        line = re.sub(r"\s+", " ", "".join(self._line)).strip()
        if line:
            self._lines.append(line)
        self._line = []

    def _abs(self, href: str) -> str:
        return urljoin(self.base, href.strip())

    # -- parser callbacks
    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        if tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").lower()
            content = attrs.get("content", "")
            if name == "theme-color" and re.fullmatch(r"#[0-9a-fA-F]{6}", content.strip()):
                self.page.theme_colors.append(content.strip().upper())
            elif name in ("description", "og:description") and not self.page.description:
                self.page.description = content.strip()
            elif name == "og:image" and content:
                self.page.logo_candidates.append(self._abs(content))
        elif tag == "link":
            rel = attrs.get("rel", "").lower()
            if "apple-touch-icon" in rel or rel == "icon" or "shortcut" in rel:
                if attrs.get("href"):
                    self.page.logo_candidates.append(self._abs(attrs["href"]))
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and "ld+json" in attrs.get("type", "").lower():
            self._in_jsonld = True
        elif tag == "style":
            self._in_style = True
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if tag == "img":
            blob = " ".join(attrs.get(k, "") for k in ("src", "alt", "class", "id")).lower()
            if "logo" in blob and attrs.get("src"):
                # real logos beat favicons and social images
                self.page.logo_candidates.insert(0, self._abs(attrs["src"]))
        if tag == "a" and attrs.get("href"):
            href = attrs["href"].strip()
            if href.lower().startswith("mailto:"):
                self._line.append(f" Email: {href[7:].split('?')[0]} ")
            elif href.lower().startswith("tel:"):
                self._line.append(f" Phone: {href[4:]} ")
            elif not href.startswith(("#", "javascript:")):
                self._href = self._abs(href)
                self._anchor = []
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "style":
            self._in_style = False
        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            raw = "".join(self._jsonld).strip()
            self._jsonld = []
            try:
                data = json.loads(raw)
                self.page.jsonld.extend(data if isinstance(data, list) else [data])
            except ValueError:
                pass
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
            return
        if tag == "a" and self._href:
            text = re.sub(r"\s+", " ", "".join(self._anchor)).strip()
            self.page.links.append((self._href, text))
            self._href = None
        if tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)
        if self._in_jsonld:
            self._jsonld.append(data)
            return
        if self._in_style:
            self.page.theme_colors.extend(c.upper() for c in _CSS_COLOR.findall(data))
            return
        if self._skip:
            return
        self._line.append(data)
        if self._href is not None:
            self._anchor.append(data)

    def result(self, max_chars: int) -> Page:
        self._flush()
        self.page.title = re.sub(r"\s+", " ", "".join(self._title)).strip()
        seen: set[str] = set()
        kept: list[str] = []
        for line in self._lines:
            if line not in seen:
                seen.add(line)
                kept.append(line)
        self.page.text = "\n".join(kept)[:max_chars]
        return self.page


def parse_html(url: str, html: str, max_chars: int = 12000) -> Page:
    parser = _PageParser(url)
    parser.feed(html)
    return parser.result(max_chars)


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h.removeprefix("www.")


def _clean(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path.rstrip("/") or "/", "", "", ""))


def _score(url: str, anchor: str) -> int:
    blob = f"{urlparse(url).path} {anchor}".lower()
    return sum(w for hint, w in LINK_HINTS.items() if hint in blob)


def fetch_site(
    url: str,
    *,
    client: httpx.Client | None = None,
    max_pages: int = 12,
    delay: float = 0.3,
    allow_private: bool = False,
    resolver: Callable[..., list] = socket.getaddrinfo,
    max_chars_per_page: int = 12000,
) -> Site:
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://")
    site = Site(root_url=url)
    host_cache: dict[str, bool] = {}

    def guard(request: httpx.Request) -> None:
        host = request.url.host
        if allow_private:
            return
        if host not in host_cache:
            host_cache[host] = is_public_host(host, resolver)
        if not host_cache[host]:
            raise BlockedHost(f"{host} is a private or local address (use --allow-private)")

    own = client is None
    client = client or httpx.Client(
        follow_redirects=True, timeout=15, headers={"User-Agent": USER_AGENT}
    )
    client.event_hooks.setdefault("request", []).append(guard)

    robots = RobotFileParser()
    try:
        r = client.get(urljoin(url, "/robots.txt"))
        robots.parse(r.text.splitlines() if r.status_code == 200 else [])
    except (httpx.HTTPError, BlockedHost):
        robots.parse([])

    def get_page(u: str) -> Page | None:
        if not robots.can_fetch(USER_AGENT, u):
            site.skipped.append(f"{u}: disallowed by robots.txt")
            return None
        try:
            resp = client.get(u)
        except BlockedHost as e:
            site.skipped.append(f"{u}: {e}")
            return None
        except httpx.HTTPError as e:
            site.skipped.append(f"{u}: {type(e).__name__}")
            return None
        if resp.status_code != 200:
            site.skipped.append(f"{u}: HTTP {resp.status_code}")
            return None
        if "html" not in resp.headers.get("content-type", "html").lower():
            site.skipped.append(f"{u}: not HTML")
            return None
        page = parse_html(
            str(resp.url),
            resp.content[:MAX_BYTES].decode(resp.encoding or "utf-8", "replace"),
            max_chars_per_page,
        )
        return page

    try:
        home = get_page(url)
        if home is None:
            return site
        site.pages.append(home)
        root_host = _host(str(url))
        candidates: dict[str, int] = {}
        for href, anchor in home.links:
            href = _clean(href)
            if _host(href) != root_host or NON_HTML_EXT.search(href):
                continue
            if _clean(href) == _clean(home.url):
                continue
            candidates[href] = max(candidates.get(href, 0), _score(href, anchor))
        ranked = [u for u, s in sorted(candidates.items(), key=lambda kv: -kv[1]) if s > 0]
        for u in ranked[: max_pages - 1]:
            time.sleep(delay)
            page = get_page(u)
            if page:
                site.pages.append(page)
    finally:
        if own:
            client.close()
    return site
