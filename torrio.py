#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass
from typing import Callable

APP_NAME = "Torrio"
APP_VERSION = "1.3"
USER_AGENT = f"{APP_NAME}/{APP_VERSION} (Termux torrent search)"
TIMEOUT = 20

KNABEN_URL = "https://api.knaben.org/v1"
IA_URL = "https://archive.org/advancedsearch.php"
FOSS_FEED_URL = "https://fosstorrents.com/feed/torrents.xml"


class Style:
    def __init__(self) -> None:
        no_color = os.environ.get("NO_COLOR") is not None
        dumb_term = os.environ.get("TERM", "").casefold() == "dumb"
        self.enabled = sys.stdout.isatty() and not no_color and not dumb_term

    def wrap(self, text: str, code: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def cyan(self, text: str) -> str:
        return self.wrap(text, "36")

    def green(self, text: str) -> str:
        return self.wrap(text, "32")

    def yellow(self, text: str) -> str:
        return self.wrap(text, "33")

    def red(self, text: str) -> str:
        return self.wrap(text, "31")

    def bold(self, text: str) -> str:
        return self.wrap(text, "1")

    def dim(self, text: str) -> str:
        return self.wrap(text, "2")


STYLE = Style()


def status(kind: str, message: str) -> None:
    labels = {
        "ok": STYLE.green("[OK]"),
        "info": STYLE.cyan("[INFO]"),
        "warn": STYLE.yellow("[WARN]"),
        "error": STYLE.red("[ERROR]"),
    }
    print(f"{labels.get(kind, '[INFO]')} {message}")


def terminal_width() -> int:
    return max(40, min(shutil.get_terminal_size((80, 24)).columns, 120))


def section(title: str) -> None:
    width = terminal_width()
    label = f" {title} "
    line = "─" * max(1, width - len(label))
    print("\n" + STYLE.cyan(label + line))


def prompt_value(label: str) -> str:
    return input(STYLE.cyan(label)).strip()


def get_download_dir() -> tuple[Path, bool]:
    """Return download directory and whether Android shared storage is active."""
    shared_downloads = Path.home() / "storage" / "downloads"

    if shared_downloads.is_dir():
        destination = shared_downloads / APP_NAME
        shared_storage = True
    else:
        destination = Path.home() / APP_NAME
        shared_storage = False

    destination.mkdir(parents=True, exist_ok=True)
    return destination, shared_storage


@dataclass
class SearchSpec:
    name: str
    format_hint: str = ""
    freshness: str = ""
    exclude: tuple[str, ...] = ()

    @property
    def query(self) -> str:
        return " ".join(
            part.strip()
            for part in (self.name, self.format_hint, self.freshness)
            if part.strip()
        )

    @property
    def positive_terms(self) -> list[str]:
        terms: list[str] = []
        for part in (self.name, self.format_hint, self.freshness):
            terms.extend(split_terms(part))
        return terms


@dataclass
class Result:
    source: str
    title: str
    size: int | None = None
    seeders: int | None = None
    downloads: int | None = None
    infohash: str | None = None
    magnet: str | None = None
    torrent_url: str | None = None
    page_url: str | None = None
    score: int = 0

    @property
    def target(self) -> str | None:
        return self.magnet or self.torrent_url

    @property
    def dedup_key(self) -> str:
        if self.infohash:
            return f"hash:{self.infohash}"
        normalized = re.sub(r"[^a-zа-я0-9]+", "", self.title.casefold())
        return f"title:{normalized}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(html.unescape(value).split())


def normalize_text(value: str) -> str:
    value = value.casefold().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9._+-]+", " ", value).strip()


def split_terms(value: str) -> list[str]:
    return [term for term in normalize_text(value).split() if term]


def parse_exclusions(value: str) -> tuple[str, ...]:
    value = value.strip()
    if not value:
        return ()

    try:
        raw = shlex.split(value)
    except ValueError:
        raw = value.split()

    result: list[str] = []
    for item in raw:
        item = item.strip().lstrip("-").strip()
        if item:
            result.append(item.casefold().replace("ё", "е"))
    return tuple(result)


def contains_term(text: str, term: str) -> bool:
    text_n = normalize_text(text)
    term_n = normalize_text(term)

    if not term_n:
        return False

    if " " in term_n:
        return term_n in text_n

    pattern = rf"(?<![a-zа-я0-9]){re.escape(term_n)}(?![a-zа-я0-9])"
    return re.search(pattern, text_n) is not None


def is_excluded(title: str, exclusions: tuple[str, ...]) -> bool:
    return any(contains_term(title, term) for term in exclusions)


def relevance(title: str, spec: SearchSpec) -> int:
    title_n = normalize_text(title)
    score = 0

    name_n = normalize_text(spec.name)
    fmt_n = normalize_text(spec.format_hint)
    fresh_n = normalize_text(spec.freshness)

    name_terms = split_terms(spec.name)
    fmt_terms = split_terms(spec.format_hint)
    fresh_terms = split_terms(spec.freshness)
    all_terms = name_terms + fmt_terms + fresh_terms

    if name_n and name_n in title_n:
        score += 1000
    if name_terms and all(contains_term(title, term) for term in name_terms):
        score += 500
    score += sum(80 for term in name_terms if contains_term(title, term))

    if fmt_n and fmt_n in title_n:
        score += 500
    score += sum(180 for term in fmt_terms if contains_term(title, term))

    if fresh_n and fresh_n in title_n:
        score += 600
    score += sum(220 for term in fresh_terms if contains_term(title, term))

    if all_terms and all(contains_term(title, term) for term in all_terms):
        score += 700

    return score


def human_size(size: int | None) -> str:
    if size is None or size < 0:
        return "?"

    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024

    return "?"


def request_bytes(
    url: str,
    *,
    payload: dict | None = None,
    accept: str = "*/*",
) -> bytes:
    data = None
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    method = "GET"

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def normalize_hash(value: object) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    if re.fullmatch(r"[A-Fa-f0-9]{40}", text):
        return text.upper()

    if re.fullmatch(r"[A-Z2-7]{32}", text, flags=re.I):
        return text.upper()

    return None


def make_magnet(infohash: str | None, title: str) -> str | None:
    if not infohash:
        return None

    return (
        "magnet:?xt=urn:btih:"
        + urllib.parse.quote(infohash)
        + "&dn="
        + urllib.parse.quote(title)
    )


def search_knaben_page(
    spec: SearchSpec,
    offset: int,
    batch_size: int,
) -> tuple[list[Result], int]:
    payload = {
        "search_type": "100%",
        "search_field": "title",
        "query": spec.query,
        "order_by": "seeders",
        "order_direction": "desc",
        "from": offset,
        "size": batch_size,
        "hide_unsafe": True,
        "hide_xxx": True,
    }

    data = json.loads(
        request_bytes(
            KNABEN_URL,
            payload=payload,
            accept="application/json",
        )
    )

    hits = data.get("hits", [])
    results: list[Result] = []

    for item in hits:
        title = clean_text(str(item.get("title", "")))

        if not title or is_excluded(title, spec.exclude):
            continue

        infohash = normalize_hash(item.get("hash"))
        magnet = clean_text(item.get("magnetUrl")) or make_magnet(
            infohash,
            title,
        )

        try:
            size = int(item["bytes"]) if item.get("bytes") is not None else None
        except (TypeError, ValueError):
            size = None

        try:
            seeders = (
                int(item["seeders"])
                if item.get("seeders") is not None
                else None
            )
        except (TypeError, ValueError):
            seeders = None

        results.append(
            Result(
                source="KN",
                title=title,
                size=size,
                seeders=seeders,
                infohash=infohash,
                magnet=magnet or None,
                page_url=clean_text(item.get("details")) or None,
                score=relevance(title, spec),
            )
        )

    return results, len(hits)


def search_internet_archive_page(
    spec: SearchSpec,
    page: int,
    batch_size: int,
) -> tuple[list[Result], int]:
    terms = spec.positive_terms

    if not terms:
        return [], 0

    expr = " AND ".join(
        re.sub(r"[^A-Za-zА-Яа-яЁё0-9._+-]+", "", term)
        for term in terms
    )

    ia_query = (
        f"(title:({expr}) OR subject:({expr}) "
        f"OR description:({expr})) AND btih:*"
    )

    params = [
        ("q", ia_query),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "btih"),
        ("fl[]", "item_size"),
        ("fl[]", "downloads"),
        ("sort[]", "downloads desc"),
        ("rows", str(batch_size)),
        ("page", str(page)),
        ("output", "json"),
    ]

    url = IA_URL + "?" + urllib.parse.urlencode(params)
    data = json.loads(request_bytes(url, accept="application/json"))

    docs = data.get("response", {}).get("docs", [])
    results: list[Result] = []

    for item in docs:
        title = clean_text(str(item.get("title", "")))

        if not title or is_excluded(title, spec.exclude):
            continue

        identifier = clean_text(str(item.get("identifier", "")))
        infohash = normalize_hash(item.get("btih"))

        if not infohash:
            continue

        try:
            size = (
                int(item["item_size"])
                if item.get("item_size") is not None
                else None
            )
        except (TypeError, ValueError):
            size = None

        try:
            downloads = (
                int(item["downloads"])
                if item.get("downloads") is not None
                else None
            )
        except (TypeError, ValueError):
            downloads = None

        results.append(
            Result(
                source="IA",
                title=title,
                size=size,
                downloads=downloads,
                infohash=infohash,
                magnet=make_magnet(infohash, title),
                page_url=(
                    "https://archive.org/details/"
                    + urllib.parse.quote(identifier)
                    if identifier
                    else None
                ),
                score=relevance(title, spec),
            )
        )

    return results, len(docs)


def extract_torrent_url(item: ET.Element) -> str | None:
    candidates: list[str] = []

    for element in item.iter():
        if element.text:
            candidates.append(element.text)

        candidates.extend(str(value) for value in element.attrib.values())

    joined = html.unescape("\n".join(candidates))
    matches = re.findall(
        r'https?://[^"\'<>\s]+\.torrent(?:\?[^"\'<>\s]*)?',
        joined,
        flags=re.I,
    )

    return matches[0] if matches else None


def search_foss_all(spec: SearchSpec) -> list[Result]:
    root = ET.fromstring(
        request_bytes(
            FOSS_FEED_URL,
            accept="text/xml,application/xml",
        )
    )

    terms = spec.positive_terms
    results: list[Result] = []

    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title"))

        if not title:
            continue

        if terms and not all(contains_term(title, term) for term in terms):
            continue

        if is_excluded(title, spec.exclude):
            continue

        torrent_url = extract_torrent_url(item)

        if not torrent_url:
            continue

        results.append(
            Result(
                source="FOSS",
                title=title,
                torrent_url=torrent_url,
                page_url=clean_text(item.findtext("link")) or None,
                score=relevance(title, spec),
            )
        )

    return results


def result_metric(item: Result) -> tuple[int, int, int]:
    return (
        item.score,
        item.seeders if item.seeders is not None else -1,
        item.downloads if item.downloads is not None else -1,
    )


def merge_and_sort(
    current: list[Result],
    incoming: list[Result],
) -> list[Result]:
    chosen: dict[str, Result] = {
        item.dedup_key: item
        for item in current
    }

    for item in incoming:
        existing = chosen.get(item.dedup_key)

        if existing is None or result_metric(item) > result_metric(existing):
            chosen[item.dedup_key] = item

    return sorted(
        chosen.values(),
        key=lambda item: (
            -item.score,
            -(item.seeders if item.seeders is not None else -1),
            -(item.downloads if item.downloads is not None else -1),
            item.title.casefold(),
        ),
    )


class SearchSession:
    def __init__(
        self,
        spec: SearchSpec,
        source: str,
        batch_size: int,
    ) -> None:
        self.spec = spec
        self.source = source
        self.batch_size = batch_size

        self.results: list[Result] = []

        self.knaben_offset = 0
        self.knaben_done = source not in ("all", "knaben")

        self.ia_page = 1
        self.ia_done = source not in ("all", "ia")

        self.foss_done = source not in ("all", "foss")

    def _merge(self, incoming: list[Result]) -> int:
        before = len(self.results)
        self.results = merge_and_sort(self.results, incoming)
        return len(self.results) - before

    def load_initial(self) -> None:
        if not self.foss_done:
            print("Loading FOSS Torrents...", end=" ", flush=True)

            try:
                found = search_foss_all(self.spec)
                added = self._merge(found)
                print(STYLE.green(str(added)))
            except Exception as exc:
                print(STYLE.red(f"error: {type(exc).__name__}: {exc}"))

            self.foss_done = True

        self.load_more(show_header=False)

    def load_more(self, *, show_header: bool = True) -> int:
        if show_header:
            print("\nLoading the next batch...")

        added_total = 0

        if not self.knaben_done:
            print(
                f"Knaben [{self.knaben_offset}.."
                f"{self.knaben_offset + self.batch_size - 1}]...",
                end=" ",
                flush=True,
            )

            try:
                found, raw_count = search_knaben_page(
                    self.spec,
                    self.knaben_offset,
                    self.batch_size,
                )
                added = self._merge(found)
                added_total += added
                self.knaben_offset += raw_count

                if raw_count < self.batch_size:
                    self.knaben_done = True
                    print(STYLE.green(f"+{added} · end"))
                else:
                    print(STYLE.green(f"+{added}"))

            except urllib.error.HTTPError as exc:
                print(STYLE.red(f"HTTP {exc.code}"))
                self.knaben_done = True
            except urllib.error.URLError as exc:
                print(STYLE.yellow(f"network error: {exc.reason}"))
            except Exception as exc:
                print(STYLE.red(f"error: {type(exc).__name__}: {exc}"))
                self.knaben_done = True

        if not self.ia_done:
            print(
                f"Internet Archive [page {self.ia_page}]...",
                end=" ",
                flush=True,
            )

            try:
                found, raw_count = search_internet_archive_page(
                    self.spec,
                    self.ia_page,
                    self.batch_size,
                )
                added = self._merge(found)
                added_total += added
                self.ia_page += 1

                if raw_count < self.batch_size:
                    self.ia_done = True
                    print(STYLE.green(f"+{added} · end"))
                else:
                    print(STYLE.green(f"+{added}"))

            except urllib.error.HTTPError as exc:
                print(STYLE.red(f"HTTP {exc.code}"))
                self.ia_done = True
            except urllib.error.URLError as exc:
                print(STYLE.yellow(f"network error: {exc.reason}"))
            except Exception as exc:
                print(STYLE.red(f"error: {type(exc).__name__}: {exc}"))
                self.ia_done = True

        return added_total

    @property
    def remote_done(self) -> bool:
        return self.knaben_done and self.ia_done


def build_metric(item: Result) -> str:
    parts = [item.source]

    if item.seeders is not None:
        parts.append(f"seeders {item.seeders}")
    elif item.downloads is not None:
        parts.append(f"downloads {item.downloads}")

    if item.size is not None:
        parts.append(human_size(item.size))

    return " · ".join(parts)


def print_result_item(
    number: int,
    item: Result,
    width: int,
) -> None:
    prefix = f"{number:>4}) "
    indent = " " * len(prefix)
    title_width = max(20, width - len(prefix))

    wrapped_title = textwrap.wrap(
        item.title,
        width=title_width,
        break_long_words=True,
        break_on_hyphens=True,
    ) or [""]

    print(STYLE.bold(prefix + wrapped_title[0]))

    for line in wrapped_title[1:]:
        print(indent + line)

    metadata = f"[{build_metric(item)}]"
    wrapped_meta = textwrap.wrap(
        metadata,
        width=max(20, width - len(indent)),
        break_long_words=True,
        break_on_hyphens=True,
    ) or [metadata]

    for line in wrapped_meta:
        print(indent + STYLE.dim(line))


def show_result_page(
    results: list[Result],
    page_index: int,
    page_size: int,
    remote_done: bool,
) -> None:
    width = terminal_width()
    total = len(results)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = page_index * page_size
    end = min(start + page_size, total)

    print("\n" + STYLE.cyan("─" * width))
    print(
        STYLE.bold(
            f"Results {start + 1}–{end} of {total} loaded "
            f"· page {page_index + 1}/{total_pages}"
        )
    )
    print(STYLE.cyan("─" * width))

    for index in range(start, end):
        print_result_item(index + 1, results[index], width)
        print()

    print(STYLE.cyan("─" * width))
    commands = "number = select · n = next · p = previous"
    if not remote_done:
        commands += " · m = load more"
    commands += " · q = quit"
    print(STYLE.dim(commands))


def select_result(
    session: SearchSession,
    page_size: int,
) -> Result | None:
    page_index = 0

    while True:
        results = session.results

        if not results:
            status("warn", "No results found.")
            return None

        total_pages = max(1, (len(results) + page_size - 1) // page_size)
        page_index = min(page_index, total_pages - 1)

        show_result_page(
            results,
            page_index,
            page_size,
            session.remote_done,
        )

        try:
            command = prompt_value("> ").lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if command == "q":
            return None

        if command == "p":
            if page_index > 0:
                page_index -= 1
            else:
                status("info", "This is the first page.")
            continue

        if command == "n":
            if page_index + 1 < total_pages:
                page_index += 1
                continue

            if session.remote_done:
                status("info", "This is the last loaded page.")
                continue

            old_total = len(session.results)
            session.load_more()
            new_total = len(session.results)

            if new_total == old_total:
                status("info", "No new unique results were found.")
            else:
                status(
                    "ok",
                    f"{new_total} results loaded. The list was re-sorted.",
                )
            continue

        if command == "m":
            if session.remote_done:
                status("info", "Remote sources have no more results.")
                continue

            old_total = len(session.results)
            session.load_more()
            new_total = len(session.results)

            status(
                "ok",
                f"{new_total} results loaded "
                f"({new_total - old_total} new unique).",
            )
            continue

        try:
            number = int(command)
        except ValueError:
            status("warn", "Enter a result number, n, p, m or q.")
            continue

        if 1 <= number <= len(results):
            return results[number - 1]

        status("warn", f"The number must be between 1 and {len(results)}.")


def copy_target(value: str) -> None:
    clipboard = shutil.which("termux-clipboard-set")

    if clipboard:
        subprocess.run(
            [clipboard],
            input=value,
            text=True,
            check=False,
        )
        status("ok", "Target copied to the Android clipboard.")
    else:
        status("warn", "termux-clipboard-set was not found. Target:")
        print(value)


def open_page(url: str) -> None:
    opener = shutil.which("termux-open-url")

    if opener:
        subprocess.run([opener, url], check=False)
    else:
        print(url)


def set_wake_lock(enabled: bool) -> bool:
    command_name = "termux-wake-lock" if enabled else "termux-wake-unlock"
    command = shutil.which(command_name)

    if not command:
        if enabled:
            status(
                "warn",
                "termux-wake-lock was not found. Android may pause the "
                "download when the screen is off.",
            )
        return False

    try:
        completed = subprocess.run(
            [command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.returncode == 0
    except OSError:
        return False


def run_aria2(target: str, *, metadata_only: bool) -> int:
    aria2c = shutil.which("aria2c")

    if not aria2c:
        status("error", "aria2c was not found. Install it with: pkg install aria2")
        return 127

    destination, _ = get_download_dir()
    status("info", f"Download directory: {destination}")

    command = [
        aria2c,
        f"--dir={destination}",
    ]

    if metadata_only and target.startswith("magnet:"):
        command.extend(
            [
                "--bt-metadata-only=true",
                "--bt-save-metadata=true",
            ]
        )

    command.append(target)

    wake_lock_acquired = set_wake_lock(True)

    if wake_lock_acquired:
        status("ok", "Wake lock enabled — the screen can be turned off.")

    try:
        completed = subprocess.run(command, check=False)
        return completed.returncode
    except KeyboardInterrupt:
        return 130
    finally:
        if wake_lock_acquired:
            set_wake_lock(False)


def show_result(item: Result) -> None:
    section("SELECTED RESULT")
    width = terminal_width()

    for label, value in (
        ("Source", item.source),
        ("Title", item.title),
        ("Size", human_size(item.size)),
        ("Seeders", item.seeders if item.seeders is not None else "?"),
        ("Downloads", item.downloads if item.downloads is not None else "?"),
        ("Infohash", item.infohash or "?"),
        ("Type", "magnet" if item.magnet else ".torrent URL"),
        ("Page", item.page_url or "—"),
    ):
        prefix = f"{label}: "
        wrapped = textwrap.wrap(
            str(value),
            width=max(20, width - len(prefix)),
            break_long_words=True,
            break_on_hyphens=True,
        ) or [""]

        print(STYLE.bold(prefix) + wrapped[0])

        for line in wrapped[1:]:
            print(" " * len(prefix) + line)


def action_menu(item: Result) -> None:
    target = item.target

    if not target:
        status("error", "This result has no magnet link or .torrent URL.")
        return

    while True:
        print()
        print(f" {STYLE.cyan('[m]')} Fetch BitTorrent metadata")
        print(f" {STYLE.cyan('[d]')} Download with aria2c")
        print(f" {STYLE.cyan('[c]')} Copy magnet/.torrent URL")
        print(f" {STYLE.cyan('[o]')} Open source page")
        print(f" {STYLE.cyan('[q]')} Quit")

        try:
            action = prompt_value("> ").lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if action == "m":
            if item.magnet:
                run_aria2(item.magnet, metadata_only=True)
            else:
                status(
                    "info",
                    "This result already has a .torrent URL; magnet metadata-only "
                    "mode is not needed.",
                )

        elif action == "d":
            run_aria2(target, metadata_only=False)
            return

        elif action == "c":
            copy_target(target)

        elif action == "o":
            if item.page_url:
                open_page(item.page_url)
            else:
                status("info", "No source page is available for this result.")

        elif action == "q":
            return

        else:
            status("warn", "Unknown action.")


def prompt_start_mode() -> str:
    print()
    print(STYLE.bold(STYLE.cyan(f"{APP_NAME} {APP_VERSION}")))
    print(STYLE.dim("Android torrent search & download for Termux"))
    print()
    print(f" {STYLE.cyan('[1]')} Paste magnet link or .torrent URL")
    print(f" {STYLE.cyan('[2]')} Select a local .torrent file")
    print(f" {STYLE.cyan('[3]')} Search torrents")
    print(f" {STYLE.cyan('[0]')} Exit")

    while True:
        try:
            choice = prompt_value("> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return "exit"

        modes = {
            "0": "exit",
            "1": "link",
            "2": "file",
            "3": "search",
        }

        if choice in modes:
            return modes[choice]

        status("warn", "Enter 0, 1, 2 or 3.")


def prompt_link() -> str | None:
    section("PASTE LINK")
    print("Paste a magnet link or a .torrent URL:")

    try:
        value = prompt_value("> ")
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if not value:
        return None

    lower = value.casefold()
    if lower.startswith("magnet:?"):
        return value

    if lower.startswith(("http://", "https://")):
        return value

    status("error", "The value does not look like a magnet or HTTP/HTTPS URL.")
    return None


def torrent_search_roots() -> list[Path]:
    roots: list[Path] = []
    home = Path.home()
    shared_downloads = home / "storage" / "downloads"

    for candidate in (
        shared_downloads,
        shared_downloads / APP_NAME,
        home / APP_NAME,
        Path.cwd(),
    ):
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate

        if candidate.is_dir() and resolved not in roots:
            roots.append(resolved)

    return roots


def find_torrent_files() -> list[Path]:
    found: dict[str, Path] = {}

    for root in torrent_search_roots():
        try:
            for path in root.rglob("*.torrent"):
                if not path.is_file():
                    continue

                try:
                    resolved = path.resolve()
                except OSError:
                    resolved = path

                found[str(resolved)] = resolved
        except (OSError, PermissionError):
            continue

    def sort_key(path: Path) -> tuple[float, str]:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        return (-mtime, path.name.casefold())

    return sorted(found.values(), key=sort_key)


def print_torrent_file(number: int, path: Path, width: int) -> None:
    prefix = f"{number:>3}) "
    indent = " " * len(prefix)
    name_width = max(20, width - len(prefix))

    wrapped_name = textwrap.wrap(
        path.name,
        width=name_width,
        break_long_words=True,
        break_on_hyphens=True,
    ) or [""]

    print(STYLE.bold(prefix + wrapped_name[0]))
    for line in wrapped_name[1:]:
        print(indent + line)

    display_path = str(path.parent)
    wrapped_path = textwrap.wrap(
        display_path,
        width=max(20, width - len(indent)),
        break_long_words=True,
        break_on_hyphens=True,
    ) or [display_path]

    for line in wrapped_path:
        print(indent + STYLE.dim(line))


def prompt_torrent_path() -> Path | None:
    section("TORRENT PATH")
    print("Enter the full path to a .torrent file:")

    try:
        value = prompt_value("> ")
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if not value:
        return None

    path = Path(value).expanduser()

    if not path.is_file():
        status("error", "File not found.")
        return None

    if path.suffix.casefold() != ".torrent":
        status("error", "The selected file is not a .torrent file.")
        return None

    return path


def choose_torrent_file(page_size: int = 8) -> Path | None:
    files = find_torrent_files()
    width = terminal_width()

    if not files:
        status("info", "No .torrent files were found in Download or Torrio folders.")
        return prompt_torrent_path()

    page = 0

    while True:
        total_pages = max(1, (len(files) + page_size - 1) // page_size)
        page = min(page, total_pages - 1)
        start = page * page_size
        end = min(start + page_size, len(files))

        print("\n" + STYLE.cyan("─" * width))
        print(
            STYLE.bold(
                f".torrent files {start + 1}–{end} of {len(files)} "
                f"· page {page + 1}/{total_pages}"
            )
        )
        print(STYLE.cyan("─" * width))

        for index in range(start, end):
            print_torrent_file(index + 1, files[index], width)
            print()

        print(
            STYLE.dim(
                "number = select · n = next · p = previous · "
                "r = manual path · q = quit"
            )
        )

        try:
            command = prompt_value("> ").lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if command == "q":
            return None
        if command == "r":
            return prompt_torrent_path()
        if command == "n":
            if page + 1 < total_pages:
                page += 1
            else:
                status("info", "This is the last page.")
            continue
        if command == "p":
            if page > 0:
                page -= 1
            else:
                status("info", "This is the first page.")
            continue

        try:
            number = int(command)
        except ValueError:
            status("warn", "Enter a number, n, p, r or q.")
            continue

        if 1 <= number <= len(files):
            return files[number - 1]

        status("warn", f"The number must be between 1 and {len(files)}.")


def prompt_spec() -> SearchSpec:
    section("SEARCH")

    while True:
        try:
            name = prompt_value("What are you looking for? ")
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit(130)

        if name:
            break

        status("warn", "A search name is required.")

    try:
        format_hint = prompt_value("Format / type [Enter = any]: ")
        freshness = prompt_value("Version / year / date [Enter = any]: ")
        exclude_raw = prompt_value("Exclude words or phrases [Enter = none]: ")
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(130)

    return SearchSpec(
        name=name,
        format_hint=format_hint,
        freshness=freshness,
        exclude=parse_exclusions(exclude_raw),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} — interactive torrent search for Termux."
    )

    parser.add_argument(
        "query",
        nargs="*",
        help="optional direct query; without it interactive mode starts",
    )
    parser.add_argument(
        "--format",
        dest="format_hint",
        default="",
        help="format/type refinement",
    )
    parser.add_argument(
        "--fresh",
        default="",
        help="version/year/date refinement",
    )
    parser.add_argument(
        "--exclude",
        default="",
        help='excluded words, e.g. "book mint"',
    )
    parser.add_argument(
        "--source",
        choices=("all", "knaben", "foss", "ia"),
        default="all",
        help="all = Knaben + FOSS + Internet Archive",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="remote results loaded per source per batch",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=8,
        help="results shown on one terminal page",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.query:
        mode = "search"
        spec = SearchSpec(
            name=" ".join(args.query),
            format_hint=args.format_hint,
            freshness=args.fresh,
            exclude=parse_exclusions(args.exclude),
        )
    else:
        mode = prompt_start_mode()

        if mode == "exit":
            return 0

        if mode == "link":
            target = prompt_link()
            if target:
                run_aria2(target, metadata_only=False)
            return 0

        if mode == "file":
            torrent_file = choose_torrent_file(
                page_size=max(3, min(args.page_size, 20))
            )
            if torrent_file:
                run_aria2(str(torrent_file), metadata_only=False)
            return 0

        spec = prompt_spec()

    destination, shared_storage = get_download_dir()
    section("SEARCH QUERY")
    print(STYLE.bold("Query:     ") + spec.query)
    print(
        STYLE.bold("Exclude:   ")
        + (", ".join(spec.exclude) if spec.exclude else "—")
    )
    print(STYLE.dim(f"Downloads: {destination}"))

    if not shared_storage:
        status(
            "warn",
            "Android shared storage is not configured. Run termux-setup-storage "
            "to save files in Download/Torrio.",
        )

    print()

    batch_size = max(10, min(args.batch_size, 100))
    page_size = max(3, min(args.page_size, 20))

    session = SearchSession(
        spec=spec,
        source=args.source,
        batch_size=batch_size,
    )

    session.load_initial()

    if not session.results:
        status("warn", "No results found.")
        return 1

    status("ok", f"{len(session.results)} results loaded.")

    item = select_result(session, page_size)

    if item is None:
        return 0

    show_result(item)
    action_menu(item)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
