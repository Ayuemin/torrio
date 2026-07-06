#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import shlex
import shutil
import subprocess
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
            print("Загрузка FOSS Torrents...", end=" ", flush=True)

            try:
                found = search_foss_all(self.spec)
                added = self._merge(found)
                print(f"{added}")
            except Exception as exc:
                print(f"ошибка: {type(exc).__name__}: {exc}")

            self.foss_done = True

        self.load_more(show_header=False)

    def load_more(self, *, show_header: bool = True) -> int:
        if show_header:
            print("\nЗагружаю следующую порцию...")

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

                self.knaben_offset += raw_count
                added = self._merge(found)
                added_total += added

                if raw_count < self.batch_size:
                    self.knaben_done = True

                suffix = " · конец" if self.knaben_done else ""
                print(f"+{added}{suffix}")

            except urllib.error.HTTPError as exc:
                print(f"HTTP {exc.code}")
                self.knaben_done = True
            except urllib.error.URLError as exc:
                print(f"сеть: {exc.reason}")
            except Exception as exc:
                print(f"{type(exc).__name__}: {exc}")
                self.knaben_done = True

        if not self.ia_done:
            print(
                f"Internet Archive [страница {self.ia_page}]...",
                end=" ",
                flush=True,
            )

            try:
                found, raw_count = search_internet_archive_page(
                    self.spec,
                    self.ia_page,
                    self.batch_size,
                )

                self.ia_page += 1
                added = self._merge(found)
                added_total += added

                if raw_count < self.batch_size:
                    self.ia_done = True

                suffix = " · конец" if self.ia_done else ""
                print(f"+{added}{suffix}")

            except urllib.error.HTTPError as exc:
                print(f"HTTP {exc.code}")
                self.ia_done = True
            except urllib.error.URLError as exc:
                print(f"сеть: {exc.reason}")
            except Exception as exc:
                print(f"{type(exc).__name__}: {exc}")
                self.ia_done = True

        return added_total

    @property
    def remote_done(self) -> bool:
        return self.knaben_done and self.ia_done


def terminal_width() -> int:
    width = shutil.get_terminal_size((80, 24)).columns
    return max(40, min(width, 120))


def metadata_text(item: Result) -> str:
    parts = [item.source]

    if item.seeders is not None:
        parts.append(f"сиды {item.seeders}")
    elif item.downloads is not None:
        parts.append(f"загрузки {item.downloads}")

    if item.size is not None:
        parts.append(human_size(item.size))

    return " · ".join(parts)


def print_wrapped_result(
    number: int,
    item: Result,
    width: int,
) -> None:
    prefix = f"{number:>4}) "
    indent = " " * len(prefix)
    title_width = max(20, width - len(prefix))

    wrapped = textwrap.wrap(
        item.title,
        width=title_width,
        break_long_words=True,
        break_on_hyphens=True,
    ) or [""]

    print(prefix + wrapped[0])

    for line in wrapped[1:]:
        print(indent + line)

    meta = f"[{metadata_text(item)}]"
    meta_lines = textwrap.wrap(
        meta,
        width=max(20, width - len(indent)),
        break_long_words=False,
        break_on_hyphens=False,
    ) or [meta]

    for line in meta_lines:
        print(indent + line)


def show_result_page(
    results: list[Result],
    page_index: int,
    page_size: int,
    remote_done: bool,
) -> None:
    width = terminal_width()
    total = len(results)

    if total == 0:
        print("\nНичего не найдено.")
        return

    total_pages = max(1, (total + page_size - 1) // page_size)
    page_index = min(page_index, total_pages - 1)

    start = page_index * page_size
    end = min(start + page_size, total)

    print("\n" + "─" * width)
    print(
        f"Результаты {start + 1}–{end} из {total} загруженных "
        f"· страница {page_index + 1}/{total_pages}"
    )
    print("─" * width)

    for index in range(start, end):
        print_wrapped_result(
            index + 1,
            results[index],
            width,
        )
        print()

    commands = "номер = выбрать · n = дальше · p = назад"
    if not remote_done:
        commands += " · m = загрузить ещё"
    commands += " · q = выход"

    print("─" * width)
    print(commands)


def select_result(
    session: SearchSession,
    page_size: int,
) -> Result | None:
    page_index = 0

    while True:
        results = session.results

        if not results:
            print("\nНичего не найдено.")
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
            command = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return None

        if command == "q":
            return None

        if command == "p":
            if page_index > 0:
                page_index -= 1
            else:
                print("Это первая страница.")
            continue

        if command == "n":
            if page_index + 1 < total_pages:
                page_index += 1
                continue

            if session.remote_done:
                print("Это последняя загруженная страница.")
                continue

            old_total = len(session.results)
            session.load_more()
            new_total = len(session.results)

            if new_total == old_total:
                print("Новых уникальных результатов нет.")
            else:
                # После пересортировки остаёмся на текущей странице.
                print(
                    f"Теперь загружено результатов: {new_total}. "
                    "Список пересортирован."
                )
            continue

        if command == "m":
            if session.remote_done:
                print("Удалённые источники больше результатов не отдают.")
                continue

            old_total = len(session.results)
            session.load_more()
            new_total = len(session.results)

            print(
                f"Загружено: {new_total} "
                f"(новых уникальных: {new_total - old_total})."
            )
            continue

        try:
            number = int(command)
        except ValueError:
            print("Введите номер результата, n, p, m или q.")
            continue

        if 1 <= number <= len(results):
            return results[number - 1]

        print(f"Номер должен быть от 1 до {len(results)}.")


def copy_target(value: str) -> None:
    clipboard = shutil.which("termux-clipboard-set")

    if clipboard:
        subprocess.run(
            [clipboard],
            input=value,
            text=True,
            check=False,
        )
        print("Ссылка скопирована в буфер Android.")
    else:
        print("\ntermux-clipboard-set не найден. Ссылка:")
        print(value)


def open_page(url: str) -> None:
    opener = shutil.which("termux-open-url")

    if opener:
        subprocess.run([opener, url], check=False)
    else:
        print(url)


def run_aria2(target: str, *, metadata_only: bool) -> None:
    aria2c = shutil.which("aria2c")

    if not aria2c:
        print("aria2c не найден. Установи: pkg install aria2")
        return

    destination, _ = get_download_dir()
    print(f"Папка: {destination}")

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
    subprocess.run(command, check=False)


def show_result(item: Result) -> None:
    width = terminal_width()

    print("\n" + "=" * width)

    for label, value in (
        ("Источник", item.source),
        ("Название", item.title),
        ("Размер", human_size(item.size)),
        ("Сиды", item.seeders if item.seeders is not None else "?"),
        ("Загрузки", item.downloads if item.downloads is not None else "?"),
        ("Infohash", item.infohash or "?"),
        ("Тип", "magnet" if item.magnet else ".torrent URL"),
        ("Страница", item.page_url or "—"),
    ):
        prefix = f"{label}: "
        wrapped = textwrap.wrap(
            str(value),
            width=max(20, width - len(prefix)),
            break_long_words=True,
            break_on_hyphens=True,
        ) or [""]

        print(prefix + wrapped[0])

        for line in wrapped[1:]:
            print(" " * len(prefix) + line)

    print("=" * width)


def action_menu(item: Result) -> None:
    target = item.target

    if not target:
        print("У результата нет magnet или .torrent URL.")
        return

    while True:
        print("\n[m] проверить метаданные")
        print("[d] скачать через aria2c")
        print("[c] скопировать magnet/.torrent URL")
        print("[o] открыть страницу источника")
        print("[q] выйти")

        try:
            action = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if action == "m":
            if item.magnet:
                run_aria2(item.magnet, metadata_only=True)
            else:
                print(
                    "У результата уже есть .torrent URL; "
                    "metadata-only для magnet здесь не нужен."
                )

        elif action == "d":
            run_aria2(target, metadata_only=False)

        elif action == "c":
            copy_target(target)

        elif action == "o":
            if item.page_url:
                open_page(item.page_url)
            else:
                print("Страница источника не указана.")

        elif action == "q":
            return

        else:
            print("Неизвестное действие.")


def prompt_spec() -> SearchSpec:
    print(f"{APP_NAME} {APP_VERSION} — поиск торрент-раздач\n")

    while True:
        try:
            name = input("Что ищем: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise SystemExit(130)

        if name:
            break

        print("Название обязательно.\n")

    try:
        format_hint = input(
            "Формат / тип [Enter — любой]: "
        ).strip()
        freshness = input(
            "Версия / год / дата [Enter — любая]: "
        ).strip()
        exclude_raw = input(
            "Исключить слова [Enter — нет]: "
        ).strip()
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
        description=f"{APP_NAME} — интерактивный поиск торрент-раздач в Termux."
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
        spec = SearchSpec(
            name=" ".join(args.query),
            format_hint=args.format_hint,
            freshness=args.fresh,
            exclude=parse_exclusions(args.exclude),
        )
    else:
        spec = prompt_spec()

    width = terminal_width()
    destination, shared_storage = get_download_dir()

    print(f"\nПапка загрузок: {destination}")
    if not shared_storage:
        print(
            "Внимание: общая память Android не подключена. "
            "Выполни termux-setup-storage, чтобы сохранять в Download/Torrio."
        )

    print("\n" + "─" * width)
    print(f"Запрос:     {spec.query}")

    if spec.exclude:
        print("Исключить:  " + ", ".join(spec.exclude))
    else:
        print("Исключить:  —")

    print("─" * width + "\n")

    batch_size = max(10, min(args.batch_size, 100))
    page_size = max(3, min(args.page_size, 20))

    session = SearchSession(
        spec=spec,
        source=args.source,
        batch_size=batch_size,
    )

    session.load_initial()

    if not session.results:
        print("\nНичего не найдено.")
        return 1

    print(f"\nВсего загружено результатов: {len(session.results)}")

    item = select_result(session, page_size)

    if item is None:
        return 0

    show_result(item)
    action_menu(item)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
