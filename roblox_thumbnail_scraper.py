#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import logging
import random
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
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
VISION_MODEL_REPO = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main"
VISION_MODEL_FILES = {
    "vision_model_quantized.onnx": "onnx/vision_model_quantized.onnx",
    "text_model_quantized.onnx": "onnx/text_model_quantized.onnx",
    "tokenizer.json": "tokenizer.json",
    "preprocessor_config.json": "preprocessor_config.json",
}
VISION_LABELS = [
    "a person",
    "a character",
    "a group of characters",
    "a cartoon character",
    "a weapon",
    "a gun",
    "a sword",
    "a knife",
    "a person holding a gun",
    "a person holding a weapon",
    "a car",
    "a vehicle",
    "a motorcycle",
    "an airplane",
    "a spaceship",
    "a building",
    "a house",
    "a city",
    "a landscape",
    "a forest",
    "an ocean",
    "an animal",
    "a dog",
    "a cat",
    "a monster",
    "a robot",
    "a zombie",
    "a dragon",
    "a fantasy scene",
    "a horror scene",
    "a fight",
    "an explosion",
    "fire",
    "smoke",
    "a game menu",
    "text",
    "a logo",
    "a map",
    "a sports scene",
    "a racing scene",
    "a military scene",
    "a police scene",
    "a robbery",
    "someone stealing",
    "a treasure",
    "coins",
    "money",
    "a colorful scene",
    "a dark scene",
    "a funny scene",
    "an anime style scene",
]

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
    description: str = ""
    icon_url: str | None = None
    thumbnail_urls: list[str] | None = None
    icon_file: str | None = None
    thumbnail_files: list[str] | None = None
    thumbnail_tags: list[list[str]] | None = None
    error: str | None = None


def chunks(values: list[int], size: int) -> Iterable[list[int]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def cache_path(cache_dir: Path, kind: str, url: str, params: dict[str, Any] | None) -> Path:
    query = json.dumps(params or {}, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(f"{url}\n{query}".encode("utf-8")).hexdigest()
    return cache_dir / kind / f"{digest}.json"


def read_cache(
    cache_dir: Path | None,
    kind: str,
    url: str,
    params: dict[str, Any] | None,
    *,
    ttl: float,
    refresh: bool,
) -> Any | None:
    if cache_dir is None or refresh:
        return None
    path = cache_path(cache_dir, kind, url, params)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        cached_at = float(cached["cached_at"])
        if time.time() - cached_at <= ttl:
            return cached["value"]
    except (OSError, TypeError, ValueError, KeyError):
        return None
    return None


def write_cache(
    cache_dir: Path | None,
    kind: str,
    url: str,
    params: dict[str, Any] | None,
    value: Any,
) -> None:
    if cache_dir is None:
        return
    path = cache_path(cache_dir, kind, url, params)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"cached_at": time.time(), "value": value}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def retry_wait(response: requests.Response | None, attempt: int) -> float:
    retry_after = 0.0
    if response is not None:
        header = response.headers.get("Retry-After")
        try:
            retry_after = float(header) if header else 0.0
        except ValueError:
            retry_after = 0.0
    return min(120.0, max(retry_after, 1.5 * (2**attempt))) + random.uniform(0, 0.25)


def request_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float,
    retries: int = 3,
    cache_dir: Path | None = None,
    cache_ttl: float = 86400,
    refresh_cache: bool = False,
) -> dict[str, Any]:
    cached = read_cache(
        cache_dir,
        "json",
        url,
        params,
        ttl=cache_ttl,
        refresh=refresh_cache,
    )
    if isinstance(cached, dict):
        return cached
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < retries:
                wait_seconds = retry_wait(response, attempt)
                logging.warning(
                    "Request returned %s; retrying in %.1f seconds (%s)",
                    response.status_code,
                    wait_seconds,
                    url,
                )
                time.sleep(wait_seconds)
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("API returned a JSON value that was not an object")
            write_cache(cache_dir, "json", url, params, payload)
            return payload
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_wait(None, attempt))
    raise RuntimeError(f"GET failed: {url}: {last_error}") from last_error


def request_text(
    session: requests.Session,
    url: str,
    *,
    timeout: float,
    retries: int,
    cache_dir: Path | None,
    cache_ttl: float,
    refresh_cache: bool,
) -> str:
    cached = read_cache(
        cache_dir,
        "text",
        url,
        None,
        ttl=cache_ttl,
        refresh=refresh_cache,
    )
    if isinstance(cached, str):
        return cached
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < retries:
                wait_seconds = retry_wait(response, attempt)
                logging.warning(
                    "Request returned %s; retrying in %.1f seconds (%s)",
                    response.status_code,
                    wait_seconds,
                    url,
                )
                time.sleep(wait_seconds)
                continue
            response.raise_for_status()
            write_cache(cache_dir, "text", url, None, response.text)
            return response.text
        except requests.RequestException as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_wait(None, attempt))
    raise RuntimeError(f"GET failed: {url}: {last_error}") from last_error


def get_top_candidates(
    session: requests.Session,
    *,
    limit: int,
    timeout: float,
    retries: int,
    cache_dir: Path | None,
    cache_ttl: float,
    refresh_cache: bool,
) -> list[tuple[int, str, int]]:
    payload = request_json(
        session,
        SOURCE_URL,
        timeout=timeout,
        retries=retries,
        cache_dir=cache_dir,
        cache_ttl=cache_ttl,
        refresh_cache=refresh_cache,
    )
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
    place_id: int,
    *,
    timeout: float,
    retries: int,
    cache_dir: Path | None,
    cache_ttl: float,
    refresh_cache: bool,
) -> tuple[int, int | None, str | None]:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    page_url = GAME_PAGE_URL.format(place_id=place_id)
    try:
        page_text = request_text(
            session,
            page_url,
            timeout=timeout,
            retries=retries,
            cache_dir=cache_dir,
            cache_ttl=cache_ttl,
            refresh_cache=refresh_cache,
        )
        match = re.search(
            r'data-universe-id=["\'](\d+)["\']',
            html.unescape(page_text),
            flags=re.IGNORECASE,
        )
        if match:
            return place_id, int(match.group(1)), None
        raise RuntimeError("game page did not contain a universe ID")
    except (requests.RequestException, ValueError, RuntimeError) as exc:
        url = UNIVERSE_FROM_PLACE_URL.format(place_id=place_id)
        try:
            payload = request_json(
                session,
                url,
                timeout=timeout,
                retries=retries,
                cache_dir=cache_dir,
                cache_ttl=cache_ttl,
                refresh_cache=refresh_cache,
            )
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
    cache_dir: Path | None,
    cache_ttl: float,
    refresh_cache: bool,
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
                    cache_dir=cache_dir,
                    cache_ttl=cache_ttl,
                    refresh_cache=refresh_cache,
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
    cache_dir: Path | None,
    cache_ttl: float,
    refresh_cache: bool,
) -> dict[int, dict[str, Any]]:
    details: dict[int, dict[str, Any]] = {}
    for batch in chunks(universe_ids, 50):
        payload = request_json(
            session,
            GAME_DETAILS_URL,
            params={"universeIds": ",".join(map(str, batch))},
            timeout=timeout,
            retries=retries,
            cache_dir=cache_dir,
            cache_ttl=cache_ttl,
            refresh_cache=refresh_cache,
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
    count_per_universe: int,
    cache_dir: Path | None,
    cache_ttl: float,
    refresh_cache: bool,
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
            cache_dir=cache_dir,
            cache_ttl=cache_ttl,
            refresh_cache=refresh_cache,
        )
        for item in icon_payload.get("data", []):
            if item.get("state") == "Completed" and item.get("imageUrl"):
                icons[int(item["targetId"])] = item["imageUrl"]

        thumbnail_payload = request_json(
            session,
            THUMBNAILS_URL,
            params={
                "universeIds": ids,
                "countPerUniverse": str(count_per_universe),
                "defaults": "true",
                "size": "768x432",
                "format": "Png",
            },
            timeout=timeout,
            retries=retries,
            cache_dir=cache_dir,
            cache_ttl=cache_ttl,
            refresh_cache=refresh_cache,
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
    refresh: bool,
) -> None:
    if not refresh and destination.exists() and destination.stat().st_size > 0:
        return
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < retries:
                wait_seconds = retry_wait(response, attempt)
                logging.warning(
                    "Image request returned %s; retrying in %.1f seconds (%s)",
                    response.status_code,
                    wait_seconds,
                    url,
                )
                time.sleep(wait_seconds)
                continue
            response.raise_for_status()
            if not response.content or not response.headers.get("content-type", "").startswith("image/"):
                raise ValueError("response was not an image")
            destination.write_bytes(response.content)
            return
        except (requests.RequestException, OSError, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(retry_wait(None, attempt))
    raise RuntimeError(f"download failed for {url}: {last_error}") from last_error


def download_record_images(
    record: GameRecord,
    output_dir: Path,
    *,
    timeout: float,
    retries: int,
    refresh: bool,
) -> GameRecord:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    prefix = f"{record.rank:04d}_{record.place_id}_{safe_name(record.name)}"
    try:
        if record.icon_url:
            icon_path = output_dir / "icons" / f"{prefix}.png"
            download_image(
                session,
                record.icon_url,
                icon_path,
                timeout=timeout,
                retries=retries,
                refresh=refresh,
            )
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
                refresh=refresh,
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
            for field in ("thumbnail_urls", "thumbnail_files", "thumbnail_tags"):
                row[field] = json.dumps(row[field] or [], ensure_ascii=False)
            writer.writerow(row)
    (output_dir / "games.json").write_text(
        json.dumps([asdict(record) for record in records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def ensure_vision_model(model_dir: Path, timeout: float) -> None:
    model_dir.mkdir(parents=True, exist_ok=True)
    for local_name, remote_name in VISION_MODEL_FILES.items():
        target = model_dir / local_name
        if target.exists() and target.stat().st_size > 0:
            continue
        temporary = target.with_suffix(target.suffix + ".tmp")
        logging.info("Downloading local vision model file %s", local_name)
        with requests.get(
            f"{VISION_MODEL_REPO}/{remote_name}",
            headers=DEFAULT_HEADERS,
            stream=True,
            timeout=max(timeout, 120),
        ) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        temporary.replace(target)


class LocalVisionTagger:
    def __init__(self, model_dir: Path, timeout: float, tags_per_image: int) -> None:
        try:
            import numpy as np
            import onnxruntime as ort
            from PIL import Image
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Visual search needs numpy, Pillow, onnxruntime, and tokenizers. "
                "Install them with: python -m pip install -r requirements.txt"
            ) from exc
        ensure_vision_model(model_dir, timeout)
        self.np = np
        self.Image = Image
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=77)
        self.tokenizer.enable_padding(length=77, pad_id=49407, pad_token="<|endoftext|>")
        self.vision = ort.InferenceSession(
            str(model_dir / "vision_model_quantized.onnx"),
            providers=["CPUExecutionProvider"],
        )
        self.text = ort.InferenceSession(
            str(model_dir / "text_model_quantized.onnx"),
            providers=["CPUExecutionProvider"],
        )
        self.tags_per_image = max(1, min(tags_per_image, len(VISION_LABELS)))
        self.text_embeddings = self._encode_text(
            [f"a photo of {label}" for label in VISION_LABELS]
        )

    def _encode_text(self, prompts: list[str]) -> Any:
        encodings = self.tokenizer.encode_batch(prompts)
        input_ids = self.np.asarray([encoding.ids for encoding in encodings], dtype=self.np.int64)
        embeddings = self.text.run(None, {"input_ids": input_ids})[0].astype(self.np.float32)
        norms = self.np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / self.np.maximum(norms, 1e-12)

    def _image_array(self, path: Path) -> Any:
        image = self.Image.open(path).convert("RGB")
        width, height = image.size
        scale = 224 / min(width, height)
        resized = image.resize((round(width * scale), round(height * scale)), self.Image.Resampling.BICUBIC)
        left = (resized.width - 224) // 2
        top = (resized.height - 224) // 2
        cropped = resized.crop((left, top, left + 224, top + 224))
        pixels = self.np.asarray(cropped, dtype=self.np.float32) / 255.0
        pixels = (pixels - self.np.asarray([0.48145466, 0.4578275, 0.40821073])) / self.np.asarray(
            [0.26862954, 0.26130258, 0.27577711]
        )
        return self.np.transpose(pixels, (2, 0, 1))

    def _encode_images(self, arrays: list[Any]) -> Any:
        batch = self.np.asarray(arrays, dtype=self.np.float32)
        embeddings = self.vision.run(None, {"pixel_values": batch})[0].astype(self.np.float32)
        norms = self.np.linalg.norm(embeddings, axis=1, keepdims=True)
        return embeddings / self.np.maximum(norms, 1e-12)

    def tag_records(self, output_dir: Path, records: list[GameRecord]) -> None:
        paths: list[tuple[GameRecord, int, Path]] = []
        for record in records:
            record.thumbnail_tags = [[] for _ in record.thumbnail_files or []]
            for index, relative_path in enumerate(record.thumbnail_files or []):
                paths.append((record, index, output_dir / relative_path))
        total = len(paths)
        completed = 0
        for start in range(0, total, 16):
            batch_paths = paths[start : start + 16]
            arrays = []
            valid = []
            for item in batch_paths:
                try:
                    arrays.append(self._image_array(item[2]))
                    valid.append(item)
                except (OSError, ValueError) as exc:
                    logging.debug("Could not analyze %s: %s", item[2], exc)
            if arrays:
                scores = self._encode_images(arrays) @ self.text_embeddings.T
                for row, item in zip(scores, valid):
                    best = self.np.argsort(row)[::-1][: self.tags_per_image]
                    item[0].thumbnail_tags[item[1]] = [VISION_LABELS[int(index)] for index in best]
            completed += len(batch_paths)
            if completed == total or completed % 50 == 0:
                logging.info("Analyzed %d/%d thumbnails locally", completed, total)


def write_gallery(output_dir: Path, records: list[GameRecord], title: str) -> Path:
    cards: list[str] = []
    for record in records:
        name = html.escape(record.name)
        description = html.escape(record.description or "No description available")
        visual_tags = [tag for tags in record.thumbnail_tags or [] for tag in tags]
        search_blob = re.sub(
            r"[^a-z0-9]+",
            " ",
            f"{record.name} {record.description} {record.place_id} {record.universe_id or ''} {' '.join(visual_tags)}".lower(),
        ).strip()
        search_text = html.escape(search_blob, quote=True)
        if record.icon_file:
            icon = (
                f'<img class="icon" loading="lazy" src="{html.escape(record.icon_file.replace(chr(92), "/"), quote=True)}" '
                f'alt="{name} icon">'
            )
        else:
            icon = '<div class="icon missing">No icon</div>'
        thumbnails = []
        for number, thumbnail_file in enumerate(record.thumbnail_files or [], start=1):
            source = html.escape(thumbnail_file.replace(chr(92), "/"), quote=True)
            tag_groups = record.thumbnail_tags or []
            tags = tag_groups[number - 1] if number - 1 < len(tag_groups) else []
            tag_text = html.escape(", ".join(tags)) if tags else ""
            thumbnails.append(
                f'<figure><img loading="lazy" src="{source}" alt="{name} thumbnail {number}">'
                f'<figcaption>{tag_text}</figcaption></figure>'
            )
        thumbnail_markup = "".join(thumbnails) or '<div class="empty">No thumbnails</div>'
        error = f'<p class="error">{html.escape(record.error)}</p>' if record.error else ""
        cards.append(
            f'<article class="card" data-search="{search_text}">'
            f'<div class="card-top">{icon}<div><div class="rank">#{record.rank}</div>'
            f'<h2>{name}</h2><p class="meta">{record.players:,} players · place {record.place_id}</p>'
            f'<a href="https://www.roblox.com/games/{record.place_id}" target="_blank" rel="noopener">Open on Roblox</a>'
            f'</div></div><p class="description">{description}</p>'
            f'<div class="thumbs">{thumbnail_markup}</div>{error}</article>'
        )

    css = """
    :root{color-scheme:dark;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#0d1117;color:#e6edf3}
    *{box-sizing:border-box}body{margin:0}main{max-width:1400px;margin:0 auto;padding:32px 20px 64px}
    header{display:flex;gap:20px;justify-content:space-between;align-items:end;flex-wrap:wrap;margin-bottom:24px}
    h1{margin:0;font-size:clamp(24px,4vw,42px)}p{margin:6px 0;color:#9da7b3}.controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
    input{width:min(360px,80vw);padding:10px 12px;border:1px solid #30363d;border-radius:6px;background:#161b22;color:#e6edf3;font:inherit}
    .stats{font-size:13px;color:#8b949e}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:18px}
    .card{border:1px solid #30363d;border-radius:10px;background:#161b22;padding:16px;overflow:hidden}.card[hidden]{display:none}
    .card-top{display:flex;gap:14px;align-items:center}.icon{width:88px;height:88px;border-radius:8px;object-fit:cover;background:#21262d;flex:none}.missing{display:grid;place-items:center;color:#8b949e;font-size:12px}
    .rank{color:#8b949e;font-size:12px}.card h2{margin:2px 0;font-size:19px;line-height:1.2}.meta{font-size:13px}.card a{color:#58a6ff;font-size:13px}.description{font-size:13px;line-height:1.45;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden}
    .thumbs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:16px}.thumbs figure{margin:0;min-width:0}.thumbs img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:5px;background:#21262d}.thumbs figcaption{margin-top:4px;color:#8b949e;font-size:11px;line-height:1.25}.empty{padding:20px;text-align:center;color:#8b949e;background:#21262d;border-radius:5px}.error{color:#ff7b72;font-size:12px}
    """
    script = r"""
    const input=document.querySelector('#search');
    const resultCount=document.querySelector('#result-count');
    const cards=[...document.querySelectorAll('.card')];
    const normalize=value=>value.toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
    const variants=term=>[term,term.replace(/ies$/,'y'),term.replace(/ing$/,''),term.replace(/s$/,'')].filter(Boolean);
    const applySearch=()=>{const query=normalize(input.value);const terms=query.split(/\s+/).filter(Boolean);let visible=0;cards.forEach(card=>{const text=card.dataset.search;const matches=!terms.length||terms.every(term=>variants(term).some(variant=>text.includes(variant)));card.hidden=!matches;if(matches)visible+=1;});resultCount.textContent=query?`${visible} matches`:`${cards.length} games`;};
    input.addEventListener('input',applySearch);
    applySearch();
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    gallery = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{html.escape(title)}</title><style>{css}</style></head><body><main>"
        f"<header><div><h1>{html.escape(title)}</h1><p>Generated {generated_at}</p></div>"
        f"<div class=\"controls\"><input id=\"search\" type=\"search\" placeholder=\"Search names or what is in the image...\" aria-label=\"Search names or what is in the image\">"
        f"<span id=\"result-count\" class=\"stats\">{len(records)} games</span></div></header>"
        f"<section class=\"grid\">{''.join(cards)}</section></main><script>{script}</script></body></html>"
    )
    gallery_path = output_dir / "index.html"
    gallery_path.write_text(gallery, encoding="utf-8")
    return gallery_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download icons and thumbnails for the top Roblox experiences."
    )
    parser.add_argument("--limit", type=int, default=500, help="Number of games to collect (default: 500).")
    parser.add_argument("--output", type=Path, default=Path("output"), help="Output directory (default: output).")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent API/download workers (default: 2).")
    parser.add_argument("--timeout", type=float, default=30, help="Per-request timeout in seconds (default: 30).")
    parser.add_argument("--retries", type=int, default=3, help="Retries for transient failures (default: 3).")
    parser.add_argument("--count-per-universe", type=int, default=10, help="Thumbnails to request per game (default: 10).")
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache"), help="API cache directory (default: .cache).")
    parser.add_argument("--cache-ttl", type=float, default=86400, help="Cache lifetime in seconds (default: 86400).")
    parser.add_argument("--refresh-cache", action="store_true", help="Ignore cached API responses and redownload images.")
    parser.add_argument("--no-cache", action="store_true", help="Disable API response caching.")
    parser.add_argument("--no-download", action="store_true", help="Only write metadata and image URLs.")
    parser.add_argument("--no-gallery", action="store_true", help="Skip generating output/index.html.")
    parser.add_argument("--gallery-title", default="Roblox Thumbnail Gallery", help="Gallery page title.")
    parser.add_argument("--visual-search", action="store_true", help="Analyze downloaded thumbnails locally for visual search.")
    parser.add_argument("--model-dir", type=Path, default=Path.home() / ".roblox_thumbnail_scraper" / "models" / "clip-vit-base-patch32", help="Local visual-search model directory.")
    parser.add_argument("--visual-tags-per-image", type=int, default=12, help="Visual tags to save per thumbnail (default: 12).")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING"), default="INFO")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (
        args.limit < 1
        or args.workers < 1
        or args.retries < 0
        or args.count_per_universe < 1
        or args.count_per_universe > 10
        or args.timeout <= 0
        or args.cache_ttl < 0
        or args.visual_tags_per_image < 1
    ):
        print("invalid limits, workers, retries, timeout, thumbnail count, or cache TTL", file=sys.stderr)
        return 2
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s: %(message)s")
    args.output.mkdir(parents=True, exist_ok=True)
    cache_dir = None if args.no_cache else args.cache_dir
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    if not args.no_download:
        (args.output / "icons").mkdir(exist_ok=True)
        (args.output / "thumbnails").mkdir(exist_ok=True)

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    try:
        logging.info("Loading the current public game list")
        candidates = get_top_candidates(
            session,
            limit=args.limit,
            timeout=args.timeout,
            retries=args.retries,
            cache_dir=cache_dir,
            cache_ttl=args.cache_ttl,
            refresh_cache=args.refresh_cache,
        )
        resolved = resolve_universes(
            candidates,
            target_count=args.limit,
            workers=args.workers,
            timeout=args.timeout,
            retries=args.retries,
            cache_dir=cache_dir,
            cache_ttl=args.cache_ttl,
            refresh_cache=args.refresh_cache,
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
                session,
                universe_ids,
                timeout=args.timeout,
                retries=args.retries,
                cache_dir=cache_dir,
                cache_ttl=args.cache_ttl,
                refresh_cache=args.refresh_cache,
            )
        except RuntimeError as exc:
            logging.warning("Could not refresh official game details: %s", exc)
            details = {}
        icons, thumbnails = fetch_thumbnail_urls(
            session,
            universe_ids,
            timeout=args.timeout,
            retries=args.retries,
            count_per_universe=args.count_per_universe,
            cache_dir=cache_dir,
            cache_ttl=args.cache_ttl,
            refresh_cache=args.refresh_cache,
        )
        for record in records:
            assert record.universe_id is not None
            official = details.get(record.universe_id)
            if official and official.get("name"):
                record.name = official["name"]
            if official and isinstance(official.get("description"), str):
                record.description = official["description"].strip()
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
                        refresh=args.refresh_cache,
                    ): record
                    for record in records
                }
                completed: list[GameRecord] = []
                for index, future in enumerate(as_completed(futures), start=1):
                    completed.append(future.result())
                    if index % 50 == 0 or index == len(futures):
                        logging.info("Downloaded %d/%d games", index, len(futures))
                records = sorted(completed, key=lambda item: item.rank)

        if args.visual_search:
            if args.no_download:
                raise RuntimeError("--visual-search requires downloaded thumbnails; remove --no-download")
            logging.info("Preparing local visual search")
            tagger = LocalVisionTagger(args.model_dir, args.timeout, args.visual_tags_per_image)
            tagger.tag_records(args.output, records)

        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_url": SOURCE_URL,
            "thumbnail_api": THUMBNAILS_URL,
            "icon_api": ICONS_URL,
            "requested": args.limit,
            "collected": len(records),
            "cache_enabled": cache_dir is not None,
            "cache_ttl_seconds": args.cache_ttl if cache_dir is not None else None,
            "count_per_universe": args.count_per_universe,
            "downloaded_icons": sum(record.icon_file is not None for record in records),
            "downloaded_thumbnails": sum(len(record.thumbnail_files or []) for record in records),
            "visual_search": args.visual_search,
            "visual_model": "Xenova/clip-vit-base-patch32" if args.visual_search else None,
        }
        (args.output / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        write_indexes(args.output, records)
        if not args.no_gallery:
            gallery_path = write_gallery(args.output, records, args.gallery_title)
            manifest["gallery"] = str(gallery_path.relative_to(args.output))
            (args.output / "manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
        logging.info("Done. Results are in %s", args.output.resolve())
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
