"""Local type stubs for `protego`.

protego ships no ``py.typed``, so under mypy ``strict`` +
``disallow_any_unimported`` every value flowing out of it would be ``Any`` and
would silently erase type checking in neptiq_robots — the package that decides
whether we are allowed to fetch a URL at all. Vendoring a minimal stub keeps
strict mode meaningful there.

Only the surface neptiq_robots actually uses is declared. If a future change
needs more of protego's API, extend this file; do not relax mypy.
"""

from collections.abc import Iterable

class Protego:
    @classmethod
    def parse(cls, content: str) -> Protego: ...
    def can_fetch(self, url: str, user_agent: str) -> bool: ...
    def crawl_delay(self, user_agent: str) -> float | None: ...
    def request_rate(self, user_agent: str) -> object | None: ...
    @property
    def sitemaps(self) -> Iterable[str]: ...
    @property
    def preferred_host(self) -> str | None: ...
