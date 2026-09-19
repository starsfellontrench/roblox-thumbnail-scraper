#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import logging
import mimetypes
import os
import threading
import webbrowser
import zipfile
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse

from PIL import Image, ImageDraw, ImageOps


def normalize_path(value: str) -> str:
    return value.replace(chr(92), "/").lstrip("/")


def relative_file(root: Path, value: str) -> Path:
    candidate = (root / normalize_path(value)).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError("file is outside the organizer folder")
    return candidate


def image_hash(path: Path) -> str:
    with Image.open(path) as image:
        grayscale = ImageOps.fit(image.convert("L"), (16, 16), method=Image.Resampling.BILINEAR)
        pixels = list(grayscale.getdata())
    average = sum(pixels) / len(pixels)
    return "".join("1" if pixel >= average else "0" for pixel in pixels)


def load_items(root: Path) -> list[dict]:
    games_path = root / "games.json"
    games = json.loads(games_path.read_text(encoding="utf-8")) if games_path.exists() else []
    items: list[dict] = []
    for game in games:
        files = game.get("thumbnail_files") or []
        tags = game.get("thumbnail_tags") or []
        for index, value in enumerate(files):
            try:
                path = relative_file(root, value)
                with Image.open(path) as image:
                    width, height = image.size
                digest = image_hash(path)
            except (OSError, ValueError):
                continue
            item_tags = tags[index] if index < len(tags) else []
            items.append(
                {
                    "path": normalize_path(value),
                    "name": game.get("name") or "Unknown game",
                    "rank": game.get("rank") or 0,
                    "players": game.get("players") or 0,
                    "place_id": game.get("place_id"),
                    "tags": item_tags,
                    "width": width,
                    "height": height,
                    "resolution": f"{width}x{height}",
                    "hash": digest,
                }
            )
    groups: defaultdict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        groups[item["hash"]].append(index)
    for item in items:
        group = groups[item["hash"]]
        item["duplicate"] = len(group) > 1
        item["duplicate_count"] = len(group)
    return items


def organizer_html(items: list[dict], title: str) -> str:
    payload = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    title_text = html.escape(title)
    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{{color-scheme:dark;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#0d1117;color:#e6edf3}}
*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1500px;margin:auto;padding:24px}}
header{{display:flex;gap:16px;align-items:end;justify-content:space-between;flex-wrap:wrap;margin-bottom:18px}}
h1{{margin:0;font-size:30px}}p{{color:#9da7b3}}.controls{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
input,select,button{{border:1px solid #30363d;border-radius:6px;background:#161b22;color:#e6edf3;padding:9px 11px;font:inherit}}
button{{cursor:pointer}}button:hover{{border-color:#58a6ff}}input{{min-width:240px}}.stats{{color:#8b949e;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}}.card{{position:relative;border:1px solid #30363d;border-radius:8px;background:#161b22;padding:10px}}
.card.hidden{{display:none}}.thumb{{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:5px;background:#21262d;cursor:pointer}}
.card h2{{font-size:15px;margin:9px 0 2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.meta,.tags{{font-size:12px;color:#8b949e;margin:3px 0}}
.tags{{line-height:1.35;min-height:32px}}.favorite{{position:absolute;top:16px;right:16px;border:0;background:#0d1117cc;font-size:22px;padding:3px 8px}}
.favorite.active{{color:#ffd33d}}.duplicate{{color:#ff7b72}}.empty{{padding:40px;text-align:center;color:#8b949e}}
</style></head><body><main><header><div><h1>{title_text}</h1><p>Local organizer. Images never leave this computer.</p></div>
<div class="controls"><input id="search" placeholder="Search"><select id="game"><option value="">All games</option></select><select id="tag"><option value="">All tags</option></select><select id="resolution"><option value="">All resolutions</option></select><select id="duplicate"><option value="">All thumbnails</option><option value="duplicates">Duplicates only</option><option value="unique">Unique only</option></select><button id="favorites">Favorites only</button><button id="contact">Contact sheet</button><button id="export">Export favorites ZIP</button><span id="stats" class="stats"></span></div></header><section id="grid" class="grid"></section></main>
<script>
const items=__ITEMS__;
const state={{favorites:new Set(JSON.parse(localStorage.getItem('thumbnail-organizer-favorites')||'[]')}};
const $=id=>document.getElementById(id);const normalize=value=>value.toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
const values=(key)=>[...new Set(items.map(item=>item[key]).filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b)));
values('name').forEach(value=>$('game').insertAdjacentHTML('beforeend',`<option value="${{encodeURIComponent(value)}}">${{value}}</option>`));
values('resolution').forEach(value=>$('resolution').insertAdjacentHTML('beforeend',`<option>${{value}}</option>`));
[...new Set(items.flatMap(item=>item.tags||[]))].sort().forEach(value=>$('tag').insertAdjacentHTML('beforeend',`<option value="${{encodeURIComponent(value)}}">${{value}}</option>`));
function save(){{localStorage.setItem('thumbnail-organizer-favorites',JSON.stringify([...state.favorites]));}}
function render(){{const query=normalize($('search').value);const game=decodeURIComponent($('game').value);const tag=decodeURIComponent($('tag').value);const resolution=$('resolution').value;const duplicate=$('duplicate').value;const favoriteOnly=$('favorites').classList.contains('active');let visible=0;const grid=$('grid');grid.innerHTML='';items.forEach((item,index)=>{{const text=normalize(`${{item.name}} ${{(item.tags||[]).join(' ')}} ${{item.path}}`);const matches=(!query||text.includes(query))&&(!game||item.name===game)&&(!tag||(item.tags||[]).includes(tag))&&(!resolution||item.resolution===resolution)&&(!duplicate||(duplicate==='duplicates'?item.duplicate:!item.duplicate))&&(!favoriteOnly||state.favorites.has(item.path));if(!matches)return;visible+=1;const card=document.createElement('article');card.className='card';const active=state.favorites.has(item.path);card.innerHTML=`<button class="favorite ${{active?'active':''}}">${{active?'★':'☆'}}</button><img class="thumb" src="${{encodeURI(item.path)} }" alt="${{item.name}} thumbnail"><h2 title="${{item.name}}">${{item.name}}</h2><p class="meta">#${{item.rank}} · ${{item.resolution}} · ${{item.players.toLocaleString()}} players</p><p class="tags">${{(item.tags||[]).join(', ')||'No visual tags'}}${{item.duplicate?`<br><span class="duplicate">Duplicate group: ${{item.duplicate_count}}</span>`:''}}</p>`;card.querySelector('.favorite').onclick=()=>{{if(state.favorites.has(item.path))state.favorites.delete(item.path);else state.favorites.add(item.path);save();render();}};card.querySelector('.thumb').onclick=()=>window.open(item.path,'_blank');grid.appendChild(card);}});$('stats').textContent=`${{visible}} of ${{items.length}} thumbnails`;}}
['search','game','tag','resolution','duplicate'].forEach(id=>$(id).addEventListener('input',render));$('favorites').onclick=()=>{{ $('favorites').classList.toggle('active');render(); }};
async function send(path){{const chosen=[...state.favorites];if(!chosen.length){{alert('Favorite some thumbnails first.');return;}}const response=await fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{files:chosen}})}});const data=await response.json();if(data.url)window.open(data.url,'_blank');else alert(data.message||'Done');}}
$('export').onclick=()=>send('/api/export');$('contact').onclick=()=>send('/api/contact-sheet');render();
</script></body></html>'''.replace("{{", "{").replace("}}", "}").replace("__TITLE__", title_text).replace("__ITEMS__", payload)


class OrganizerHandler(BaseHTTPRequestHandler):
    root: Path
    page: str

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            data = self.page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        path = relative_file(self.root, parsed.path)
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            files = [relative_file(self.root, value) for value in body.get("files", [])]
            files = [path for path in files if path.exists() and path.is_file()]
            if self.path == "/api/export":
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target = self.root / f"favorites_{stamp}.zip"
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in files:
                        archive.write(path, path.relative_to(self.root))
                self.respond_json({"url": "/" + target.name, "message": f"Exported {len(files)} files"})
                return
            if self.path == "/api/contact-sheet":
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target = self.root / f"contact_sheet_{stamp}.png"
                create_contact_sheet(files, target)
                self.respond_json({"url": "/" + target.name, "message": f"Created contact sheet for {len(files)} files"})
                return
            self.send_error(404)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.respond_json({"message": str(exc)}, status=400)

    def respond_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        logging.info("organizer %s", format % args)


def create_contact_sheet(files: list[Path], target: Path) -> None:
    if not files:
        raise ValueError("no files selected")
    tile_width, tile_height = 240, 150
    columns = 4
    rows = (len(files) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), "#161b22")
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(files):
        with Image.open(path) as image:
            thumb = ImageOps.contain(image.convert("RGB"), (tile_width - 12, tile_height - 30))
        x = (index % columns) * tile_width + (tile_width - thumb.width) // 2
        y = (index // columns) * tile_height + 6
        sheet.paste(thumb, (x, y))
        draw.text(((index % columns) * tile_width + 6, (index // columns + 1) * tile_height - 20), path.name[:34], fill="white")
    sheet.save(target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Organize and export Roblox thumbnails locally.")
    parser.add_argument("--input", type=Path, default=Path("output"), help="Scraper output folder.")
    parser.add_argument("--port", type=int, default=8766, help="Local organizer port.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the organizer automatically.")
    parser.add_argument("--title", default="Roblox Thumbnail Organizer", help="Organizer window title.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.input.resolve()
    if not root.exists():
        print(f"Input folder does not exist: {root}")
        return 2
    items = load_items(root)
    page = organizer_html(items, args.title)
    OrganizerHandler.root = root
    OrganizerHandler.page = page
    server = ThreadingHTTPServer(("127.0.0.1", args.port), OrganizerHandler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Organizer ready at {url}")
    print(f"Found {len(items)} thumbnails and {sum(item['duplicate'] for item in items)} duplicate entries")
    if not args.no_open:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
