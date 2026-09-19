#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DETAILS_URL = "https://games.roblox.com/v1/games"
ICONS_URL = "https://thumbnails.roblox.com/v1/games/icons"
THUMBNAILS_URL = "https://thumbnails.roblox.com/v1/games/multiget/thumbnails"
HEADERS = {"User-Agent": "RobloxGameWatcher/1.0", "Accept": "application/json"}


def chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def request_json(session: requests.Session, url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def load_targets(input_dir: Path) -> list[dict[str, Any]]:
    games = json.loads((input_dir / "games.json").read_text(encoding="utf-8"))
    return [game for game in games if game.get("universe_id")]


def fetch_snapshot(session: requests.Session, targets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    universe_ids = [int(game["universe_id"]) for game in targets]
    details: dict[str, dict[str, Any]] = {}
    icons: dict[str, str] = {}
    thumbnails: dict[str, list[str]] = {}
    for batch in chunks(universe_ids, 50):
        params = {"universeIds": ",".join(str(value) for value in batch)}
        for item in request_json(session, DETAILS_URL, params).get("data", []):
            details[str(item["id"])] = item
        icon_params = {**params, "size": "512x512", "format": "Png", "isCircular": "false"}
        for item in request_json(session, ICONS_URL, icon_params).get("data", []):
            if item.get("imageUrl"):
                icons[str(item["targetId"])] = item["imageUrl"]
        thumb_params = {**params, "size": "768x432", "format": "Png", "countPerUniverse": "10"}
        for item in request_json(session, THUMBNAILS_URL, thumb_params).get("data", []):
            urls = [entry["imageUrl"] for entry in item.get("thumbnails", []) if entry.get("imageUrl")]
            thumbnails[str(item["universeId"])] = urls
    snapshot = {}
    for target in targets:
        key = str(target["universe_id"])
        detail = details.get(key, {})
        snapshot[key] = {
            "universe_id": int(target["universe_id"]),
            "place_id": target.get("place_id"),
            "name": detail.get("name") or target.get("name") or "Unknown game",
            "description": detail.get("description") or "",
            "players": detail.get("playing") or 0,
            "updated": detail.get("updated"),
            "icon_url": icons.get(key),
            "thumbnail_urls": thumbnails.get(key, []),
        }
    return snapshot


def compare(previous: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    changes = []
    fields = ("name", "description", "players", "updated", "icon_url", "thumbnail_urls")
    for key, value in current.items():
        old = previous.get(key)
        if old is None:
            changes.append({"type": "new", "game": value, "fields": ["new game"]})
            continue
        changed_fields = [field for field in fields if old.get(field) != value.get(field)]
        if changed_fields:
            changes.append({"type": "changed", "game": value, "fields": changed_fields})
    return changes


def format_change(change: dict[str, Any]) -> str:
    game = change["game"]
    prefix = "New game" if change["type"] == "new" else "Changed"
    return f"{prefix}: {game['name']} ({', '.join(change['fields'])})"


def send_webhook(url: str, messages: list[str]) -> None:
    if not messages:
        return
    response = requests.post(url, json={"content": "\n".join(messages)}, timeout=30)
    response.raise_for_status()


def run_once(args: argparse.Namespace) -> int:
    input_dir = args.input.resolve()
    targets = load_targets(input_dir)
    state_path = args.state.resolve() if args.state else input_dir / "watcher-state.json"
    previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    session = requests.Session()
    session.headers.update(HEADERS)
    current = fetch_snapshot(session, targets)
    changes = compare(previous, current)
    if previous or args.notify_first_run:
        messages = [format_change(change) for change in changes]
    else:
        messages = []
    if messages:
        for message in messages:
            print(message)
        if args.webhook_url:
            send_webhook(args.webhook_url, messages)
    else:
        print(f"No changes detected across {len(current)} games.")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    (input_dir / "watcher-last-run.json").write_text(
        json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "changes": messages}, indent=2),
        encoding="utf-8",
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch Roblox game metadata and thumbnails for changes.")
    parser.add_argument("--input", type=Path, default=Path("output"), help="Scraper output folder.")
    parser.add_argument("--state", type=Path, help="Snapshot state file.")
    parser.add_argument("--interval", type=int, default=900, help="Seconds between checks (default: 900).")
    parser.add_argument("--once", action="store_true", help="Run one check and exit.")
    parser.add_argument("--webhook-url", help="Optional Discord-compatible webhook URL.")
    parser.add_argument("--notify-first-run", action="store_true", help="Report every game as new on the first run.")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING"), default="INFO")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.interval < 1:
        print("interval must be positive")
        return 2
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")
    while True:
        try:
            run_once(args)
        except (OSError, ValueError, requests.RequestException) as exc:
            logging.error("Watcher failed: %s", exc)
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
