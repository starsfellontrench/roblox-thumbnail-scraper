# Roblox Thumbnail Scraper v2

Downloads Roblox game icons and thumbnails, stores API responses in a local cache, retries transient failures, and builds a searchable HTML gallery. Optional visual search analyzes thumbnails locally on the computer running the scraper.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Windows download

1. Open the `downloads` folder in this repository.
2. Download `roblox_thumbnail_scraper.exe` to a normal folder on your computer.
3. Open PowerShell in that folder.
4. Run the scraper with visual search enabled:

```powershell
.\roblox_thumbnail_scraper.exe --limit 50 --visual-search
```

The first visual-search run downloads the local model once. Roblox still needs to be reachable while scraping, but the downloaded thumbnails and image analysis stay on the computer.

## Using visual search

1. Wait for the scraper to finish downloading the games and thumbnails.
2. Open `output\index.html` in your browser.
3. Type a search into the box labeled `Search`.
4. Use simple visual terms such as `gun`, `character`, `car`, `zombie`, `weapon`, `stealing`, or `explosion`.
5. Use multiple words when you want both ideas to match, such as `character stealing`.

The search uses visual tags generated locally for each thumbnail. It is better with concrete objects and scenes than with complicated actions or long sentences. If a specific phrase returns nothing, try shorter terms.

## Run

```powershell
python roblox_thumbnail_scraper.py
```

```powershell
python roblox_thumbnail_scraper.py --limit 100 --output data --workers 1
python roblox_thumbnail_scraper.py --limit 50 --count-per-universe 5 --output data
python roblox_thumbnail_scraper.py --no-download
python roblox_thumbnail_scraper.py --limit 50 --visual-search --output data
```

The default output contains `games.csv`, `games.json`, `manifest.json`, downloaded `icons`, downloaded `thumbnails`, and a searchable `index.html` gallery. With `--visual-search`, the first run downloads a local CLIP model to `%USERPROFILE%\.roblox_thumbnail_scraper\models`, analyzes the thumbnails locally, and adds visual tags to the gallery. The images are not uploaded to a vision service.

## Useful options

```powershell
python roblox_thumbnail_scraper.py --refresh-cache
python roblox_thumbnail_scraper.py --no-cache
python roblox_thumbnail_scraper.py --cache-ttl 3600
python roblox_thumbnail_scraper.py --no-gallery
python roblox_thumbnail_scraper.py --gallery-title "My Roblox Gallery"
python roblox_thumbnail_scraper.py --visual-search --model-dir "D:\\Models\\clip" --visual-tags-per-image 16
```

The API cache defaults to `.cache` and lasts 24 hours. Existing image files are reused unless `--refresh-cache` is set.
