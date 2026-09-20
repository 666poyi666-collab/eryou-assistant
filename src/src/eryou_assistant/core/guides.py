from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse


@dataclass(slots=True)
class GuideEntry:
    title: str
    url: str
    visited_at: str


def normalize_url(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("地址不能为空")
    if "://" not in text and not text.startswith(("about:", "file:")):
        text = f"https://{text}"
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https", "file", "about"}:
        raise ValueError("仅支持 http、https、file 和 about 地址")
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise ValueError("地址缺少域名")
    return urlunparse(parsed._replace(fragment=""))


class GuideStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.bookmarks: list[GuideEntry] = []
        self.history: list[GuideEntry] = []
        self.last_url = ""
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self.bookmarks = [GuideEntry(**item) for item in payload.get("bookmarks", [])]
            self.history = [GuideEntry(**item) for item in payload.get("history", [])]
            self.last_url = str(payload.get("last_url", ""))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self.bookmarks = []
            self.history = []
            self.last_url = ""

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "bookmarks": [asdict(item) for item in self.bookmarks],
            "history": [asdict(item) for item in self.history[-1000:]],
            "last_url": self.last_url,
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def toggle_bookmark(self, title: str, url: str) -> bool:
        normalized = normalize_url(url)
        existing = next((item for item in self.bookmarks if item.url == normalized), None)
        if existing:
            self.bookmarks.remove(existing)
            added = False
        else:
            self.bookmarks.append(GuideEntry(title or normalized, normalized, _now()))
            added = True
        self.save()
        return added

    def is_bookmarked(self, url: str) -> bool:
        try:
            normalized = normalize_url(url)
        except ValueError:
            return False
        return any(item.url == normalized for item in self.bookmarks)

    def record_visit(self, title: str, url: str) -> None:
        normalized = normalize_url(url)
        self.last_url = normalized
        entry = GuideEntry(title or normalized, normalized, _now())
        if self.history and self.history[-1].url == normalized:
            self.history[-1] = entry
        else:
            self.history.append(entry)
        self.save()

    def search(self, query: str, *, bookmarks: bool = False) -> list[GuideEntry]:
        source = self.bookmarks if bookmarks else self.history
        needle = query.strip().casefold()
        return [item for item in source if needle in f"{item.title} {item.url}".casefold()]

    def update_last_title(self, url: str, title: str) -> None:
        if not self.history or not title.strip():
            return
        try:
            normalized = normalize_url(url)
        except ValueError:
            return
        if self.history[-1].url == normalized:
            self.history[-1].title = title.strip()
            self.save()

    def clear_history(self) -> None:
        self.history.clear()
        self.save()

    def remove_bookmark(self, url: str) -> None:
        normalized = normalize_url(url)
        self.bookmarks = [item for item in self.bookmarks if item.url != normalized]
        self.save()

    def remove_history(self, visited_at: str) -> None:
        self.history = [item for item in self.history if item.visited_at != visited_at]
        self.save()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
