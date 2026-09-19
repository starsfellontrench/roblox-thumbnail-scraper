#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests


SOURCE_URL = "https://api.rolimons.com/games/v1/gamelist"
UNIVERSE_FROM_PLACE_URL = "https://apis.roblox.com/universes/v1/places/{place_id}/universe"
GAME_PAGE_URL = "https://www.roblox.com/games/{place_id}"
GAME_DETAILS_URL = "https://games.roblox.com/v1/games"
ICONS_URL = "https://thumbnails.roblox.com/v1/games/icons"
THUMBNAILS_URL = "https://thumbnails.roblox.com/v1/games/multiget/thumbnails"

DEFAULT_HEADERS = {
    "User-Agent": "RobloxThumbnailScraper/1.0 (+https://www.roblox.com/)",
    "Accept": "application/json",
}


@dataclass
class GameRecord:
    rank: int
    place_id: int
    universe_id: int | None
    name: str
    players: int
    icon_url: str | None = None
    thumbnail_urls: list[str] | None = None
    icon_file: str | None = None
    thumbnail_files: list[str] | None = None
    error: str | None = None


def chunks(values: list[int], size: int) -> Iterable[list[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def request_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float,
    retries: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = float(retry_after_header) if retry_after_header else 0
                except ValueError:
                    retry_after = 0
                wait_seconds = min(60.0, max(retry_after, 1.5 * (2**attempt)))
                if attempt < retries:
                    logging.warning(
                        "Rate limited by Roblox; retrying in %.1f seconds (%s)",
                        wait_seconds,
                        url,
                    )
                    time.sleep(wait_seconds)
                    continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("API returned a JSON value that was not an object")
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.75 * (2**attempt))
    raise RuntimeError(f"GET failed: {url}: {last_error}") from last_error


def get_top_candidates(
    session: requests.Session, *, limit: int, timeout: float
) -> list[tuple[int, str, int]]:
    payload = request_json(session, SOURCE_URL, timeout=timeout)
    games = payload.get("games")
    if not isinstance(games, dict):
        raise RuntimeError("The game-list response did not contain a 'games' object")

    candidates: list[tuple[int, str, int]] = []
    for raw_place_id, value in games.items():
        try:
            place_id = int(raw_place_id)
            name = str(value[0]).strip()
            players = max(0, int(value[1]))
        except (TypeError, ValueError, IndexError):
            continue
        if place_id > 0 and name:
            candidates.append((place_id, name, players))

    candidates.sort(key=lambda item: (-item[2], item[0]))
    return candidates[: max(limit * 2, limit + 25)]


def place_to_universe(
    place_id: int, *, timeout: float, retries: int
) -> tuple[int, int | None, str | None]:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    page_url = GAME_PAGE_URL.format(place_id=place_id)
    try:
        for attempt in range(retries + 1):
            response = session.get(page_url, timeout=timeout)
            if response.status_code == 429:
                wait_seconds = min(60.0, 1.5 * (2**attempt))
                if attempt < retries:
                    logging.warning(
                        "Rate limited by Roblox game page; retrying in %.1f seconds (%s)",
                        wait_seconds,
                        page_url,
                    )
                    time.sleep(wait_seconds)
                    continue
            response.raise_for_status()
            match = re.search(
                r'data-universe-id=["\'](\d+)["\']',
                html.unescape(response.text),
                flags=re.IGNORECASE,
            )
            if match:
                return place_id, int(match.group(1)), None
            raise RuntimeError("game page did not contain a universe ID")
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        url = UNIVERSE_FROM_PLACE_URL.format(place_id=place_id)
        try:
            payload = request_json(session, url, timeout=timeout, retries=retries)
            return place_id, int(payload["universeId"]), None
        except (KeyError, TypeError, ValueError, RuntimeError) as fallback_exc:
            return place_id, None, f"page: {exc}; API fallback: {fallback_exc}"
    finally:
        session.close()


def resolve_universes(
    candidates: list[tuple[int, str, int]],
    *,
    target_count: int,
    workers: int,
    timeout: float,
    retries: int,
) -> dict[int, tuple[int | None, str | None]]:
    resolved: dict[int, tuple[int | None, str | None]] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        resolved_count = 0
        for start in range(0, len(candidates), 100):
            batch = candidates[start : start + 100]
            futures = {
                executor.submit(
                    place_to_universe,
                    place_id,
                    timeout=timeout,
                    retries=retries,
                ): place_id
                for place_id, _, _ in batch
            }
            for future in as_completed(futures):
                place_id, universe_id, error = future.result()
                resolved[place_id] = (universe_id, error)
                resolved_count += 1
            valid_count = sum(universe_id is not None for universe_id, _ in resolved.values())
            logging.info(
                "Resolved %d place IDs (%d valid)", resolved_count, valid_count
            )
            if valid_count >= target_count:
                break
    return resolved


def fetch_official_details(
    session: requests.Session,
    universe_ids: list[int],
    *,
    timeout: float,
    retries: int,
) -> dict[int, dict[str, Any]]:
    details: dict[int, dict[str, Any]] = {}
    for batch in chunks(universe_ids, 50):
        payload = request_json(
            session,
            GAME_DETAILS_URL,
            params={"universeIds": ",".join(map(str, batch))},
            timeout=timeout,
            retries=retries,
        )
        for item in payload.get("data", []):
            try:
                details[int(item["id"])] = item
            except (KeyError, TypeError, ValueError):
                continue
    return details


def fetch_thumbnail_urls(
    session: requests.Session,
    universe_ids: list[int],
    *,
    timeout: float,
    retries: int,
) -> tuple[dict[int, str], dict[int, list[str]]]:
    icons: dict[int, str] = {}
    thumbnails: dict[int, list[str]] = {}
    for batch in chunks(universe_ids, 50):
        ids = ",".join(map(str, batch))
        icon_payload = request_json(
            session,
            ICONS_URL,
            params={
                "universeIds": ids,
                "returnPolicy": "PlaceHolder",
                "size": "512x512",
                "format": "Png",
                "isCircular": "false",
            },
            timeout=timeout,
            retries=retries,
        )
        for item in icon_payload.get("data", []):
            if item.get("state") == "Completed" and item.get("imageUrl"):
                icons[int(item["targetId"])] = item["imageUrl"]

        thumbnail_payload = request_json(
            session,
            THUMBNAILS_URL,
            params={
                "universeIds": ids,
                "countPerUniverse": "10",
                "defaults": "true",
                "size": "768x432",
                "format": "Png",
            },
            timeout=timeout,
            retries=retries,
        )
        for item in thumbnail_payload.get("data", []):
            try:
                media = item.get("thumbnails") or []
                thumbnails[int(item["universeId"])] = [
                    thumbnail["imageUrl"]
                    for thumbnail in media
                    if thumbnail.get("state") == "Completed" and thumbnail.get("imageUrl")
                ]
            except (TypeError, ValueError, KeyError):
                continue
    return icons, thumbnails


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._")
    return value[:80] or "game"


def download_image(
    session: requests.Session,
    url: str,
    destination: Path,
    *,
    timeout: float,
    retries: int,
) -> None:
    if destination.exists() and destination.stat().st_size > 0:
        return
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            if not response.content or not response.headers.get("content-type", "").startswith("image/"):
                raise ValueError("response was not an image")
            destination.write_bytes(response.content)
            return
        except (requests.RequestException, OSError, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.75 * (2**attempt))
    raise RuntimeError(f"download failed for {url}: {last_error}") from last_error


def download_record_images(
    record: GameRecord,
    output_dir: Path,
    *,
    timeout: float,
    retries: int,
) -> GameRecord:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    prefix = f"{record.rank:04d}_{record.place_id}_{safe_name(record.name)}"
    try:
        if record.icon_url:
            icon_path = output_dir / "icons" / f"{prefix}.png"
            download_image(session, record.icon_url, icon_path, timeout=timeout, retries=retries)
            record.icon_file = str(icon_path.relative_to(output_dir))
        record.thumbnail_files = []
        for thumbnail_number, thumbnail_url in enumerate(record.thumbnail_urls or [], start=1):
            thumbnail_path = output_dir / "thumbnails" / f"{prefix}_thumb_{thumbnail_number:02d}.png"
            download_image(
                session,
                thumbnail_url,
                thumbnail_path,
                timeout=timeout,
                retries=retries,
            )
            record.thumbnail_files.append(str(thumbnail_path.relative_to(output_dir)))
    except RuntimeError as exc:
        record.error = str(exc)
    finally:
        session.close()
    return record


def write_indexes(output_dir: Path, records: list[GameRecord]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(records[0]).keys()) if records else list(GameRecord.__dataclass_fields__)
    with (output_dir / "games.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = asdict(record)
            for field in ("thumbnail_urls", "thumbnail_files"):
                row[field] = json.dumps(row[field] or [], ensure_ascii=False)
            writer.writerow(row)
    (output_dir / "games.json").write_text(
        json.dumps([asdict(record) for record in records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download icons and thumbnails for the top Roblox experiences."
    )
    parser.add_argument("--limit", type=int, default=500, help="Number of games to collect (default: 500).")
    parser.add_argument("--output", type=Path, default=Path("output"), help="Output directory (default: output).")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent API/download workers (default: 4).")
    parser.add_argument("--timeout", type=float, default=30, help="Per-request timeout in seconds (default: 30).")
    parser.add_argument("--retries", type=int, default=3, help="Retries for transient failures (default: 3).")
    parser.add_argument("--no-download", action="store_true", help="Only write metadata and image URLs.")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING"), default="INFO")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.limit < 1 or args.workers < 1 or args.retries < 0:
        print("--limit and --workers must be positive; --retries cannot be negative", file=sys.stderr)
        return 2
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")
    args.output.mkdir(parents=True, exist_ok=True)
    if not args.no_download:
        (args.output / "icons").mkdir(exist_ok=True)
        (args.output / "thumbnails").mkdir(exist_ok=True)

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    try:
        logging.info("Loading the current public game list")
        candidates = get_top_candidates(session, limit=args.limit, timeout=args.timeout)
        resolved = resolve_universes(
            candidates,
            target_count=args.limit,
            workers=args.workers,
            timeout=args.timeout,
            retries=args.retries,
        )

        records: list[GameRecord] = []
        for place_id, source_name, players in candidates:
            universe_id, error = resolved.get(place_id, (None, "place was not resolved"))
            if universe_id is None:
                logging.debug("Skipping place %s: %s", place_id, error)
                continue
            records.append(
                GameRecord(
                    rank=len(records) + 1,
                    place_id=place_id,
                    universe_id=universe_id,
                    name=source_name,
                    players=players,
                    error=error,
                )
            )
            if len(records) >= args.limit:
                break

        if not records:
            raise RuntimeError("No valid Roblox places could be resolved")

        logging.info("Resolved %d games; fetching official metadata and image URLs", len(records))
        universe_ids = [record.universe_id for record in records if record.universe_id is not None]
        try:
            details = fetch_official_details(
                session, universe_ids, timeout=args.timeout, retries=args.retries
            )
        except RuntimeError as exc:
            logging.warning("Could not refresh official game details: %s", exc)
            details = {}
        icons, thumbnails = fetch_thumbnail_urls(
            session, universe_ids, timeout=args.timeout, retries=args.retries
        )
        for record in records:
            assert record.universe_id is not None
            official = details.get(record.universe_id)
            if official and official.get("name"):
                record.name = official["name"]
            record.icon_url = icons.get(record.universe_id)
            record.thumbnail_urls = thumbnails.get(record.universe_id, [])

        if not args.no_download:
            logging.info("Downloading images")
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(
                        download_record_images,
                        record,
                        args.output,
                        timeout=args.timeout,
                        retries=args.retries,
                    ): record
                    for record in records
                }
                completed: list[GameRecord] = []
                for index, future in enumerate(as_completed(futures), start=1):
                    completed.append(future.result())
                    if index % 50 == 0 or index == len(futures):
                        logging.info("Downloaded %d/%d games", index, len(futures))
                records = sorted(completed, key=lambda item: item.rank)

        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_url": SOURCE_URL,
            "thumbnail_api": THUMBNAILS_URL,
            "icon_api": ICONS_URL,
            "requested": args.limit,
            "collected": len(records),
            "downloaded_icons": sum(record.icon_file is not None for record in records),
            "downloaded_thumbnails": sum(len(record.thumbnail_files or []) for record in records),
        }
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        write_indexes(args.output, records)
        logging.info("Done. Results are in %s", args.output.resolve())
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
