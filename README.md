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

## Thumbnail organizer

The organizer runs locally in a browser and works with an existing scraper output folder. It groups near-duplicate images, saves favorites in the output folder, filters by game, tag, resolution, and duplicate group, creates contact sheets, and exports selected images to ZIP files.

```powershell
python thumbnail_organizer.py --input output
```

Use the `Search` box for game names, visual tags, or descriptions. Use the filter controls to narrow the results, click `Favorite` on images you want to keep, then use `Export favorites ZIP` or `Create contact sheet`.

## Roblox game update watcher

The watcher uses the games already saved by the scraper and keeps a local snapshot of Roblox metadata. It can report changes to player count, descriptions, icons, thumbnails, names, and update timestamps.

Run one check:

```powershell
python roblox_game_watcher.py --input output --once
```

Keep checking every 15 minutes:

```powershell
python roblox_game_watcher.py --input output --interval 900
```

The state is saved as `output\watcher-state.json`. For Discord-compatible notifications, add `--webhook-url "https://discord.com/api/webhooks/..."`.

## Windows launcher

The repository also includes a Windows Forms launcher in `launcher/`. It runs the scraper without requiring command-line options and can open the generated HTML gallery when the scrape finishes.

### Download setup

1. Download `RobloxToolLauncher.exe` and `roblox_thumbnail_scraper.exe` from the [latest release](https://github.com/starsfellontrench/roblox-thumbnail-scraper/releases/latest).
2. Keep both files in the same folder.
3. Double-click `RobloxToolLauncher.exe`.
4. If it does not find the scraper automatically, use Browse to select `roblox_thumbnail_scraper.exe`.
5. Choose the game count, workers, thumbnail count, and output folder.
6. Enable local visual search if you want to search thumbnails by image content.
7. Click `Run scraper`, then click `Open gallery` when it finishes.

The launcher also supports saved profiles, recent output folders, a scrape history, a progress bar, cancellation, automatic HTML gallery opening, and one daily scheduled run.

The first visual-search run downloads the local model once. Images stay on the computer and are not sent to a vision service.

### Build the launcher

Install the .NET 8 SDK, then run these commands from the repository folder:

```powershell
dotnet build launcher\RobloxToolLauncher\RobloxToolLauncher.csproj -c Release
dotnet publish launcher\RobloxToolLauncher\RobloxToolLauncher.csproj -c Release -r win-x64 --self-contained true /p:PublishSingleFile=true /p:IncludeNativeLibrariesForSelfExtract=true -o launcher\publish
```

Copy `downloads\roblox_thumbnail_scraper.exe` beside the published launcher before running it.

### Launcher controls

- `Games to scrape` controls the number of Roblox games collected.
- `Workers` controls how many requests and image downloads happen at the same time. Use `1` or `2` for safer API usage.
- `Thumbnails per game` controls how many thumbnails are requested for each game.
- `Enable local visual search` adds locally generated image-content tags to the gallery.
