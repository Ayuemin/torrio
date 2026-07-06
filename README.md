# Torrio

> A lightweight interactive torrent search and download tool for Android, built for Termux and powered by aria2.

![Python](https://img.shields.io/badge/Python-3.x-blue)
![Android](https://img.shields.io/badge/Android-Termux-green)
![Version](https://img.shields.io/badge/Torrio-1.3-cyan)
![License](https://img.shields.io/badge/License-MIT-yellow)

Torrio gives Android users a simple terminal interface for three common BitTorrent workflows:

1. Paste a magnet link or `.torrent` URL.
2. Select a local `.torrent` file.
3. Search for torrents interactively.

Search results are merged, ranked, deduplicated and displayed as numbered pages designed for narrow phone screens.

Torrio uses `aria2c` for downloads and automatically enables a Termux wake lock while aria2 is running, helping downloads continue when the screen is turned off.

## Features

- English interactive terminal UI
- Lightweight ANSI colors with automatic fallback to plain text
- `NO_COLOR` support
- Interactive torrent search from Termux
- Query refinement by name, format/type and version/year/date
- Excluded words and quoted excluded phrases
- Search across Knaben, FOSS Torrents and Internet Archive
- Result ranking and deduplication
- Numbered, paginated results for mobile terminals
- Magnet link support
- Remote `.torrent` URL support
- Local `.torrent` file discovery and selection
- aria2 download integration
- Android shared storage support
- Automatic `termux-wake-lock` during downloads
- No root required
- No third-party Python packages required

## Requirements

- Android 7 or newer
- [Termux](https://github.com/termux/termux-app)
- Python 3
- aria2
- curl for the installation command below

For a regular Android device, use the stable Termux build from F-Droid or the official Termux GitHub repository.

## Installation on a new Android device

### 1. Install Termux

Install Termux from:

- [F-Droid](https://f-droid.org/packages/com.termux/)
- or the [official Termux GitHub repository](https://github.com/termux/termux-app)

Open Termux after installation.

### 2. Update Termux packages

```bash
pkg update && pkg upgrade -y
```

### 3. Grant access to Android shared storage

```bash
termux-setup-storage
```

Approve the Android storage permission request.

The Android `Download` directory will then be available in Termux as:

```text
~/storage/downloads
```

Torrio stores downloads in:

```text
Download/Torrio
```

The same directory inside Termux is:

```text
~/storage/downloads/Torrio
```

If shared storage is not configured, Torrio falls back to:

```text
~/Torrio
```

### 4. Install the required packages

```bash
pkg install python aria2 curl -y
```

### 5. Download and install Torrio

```bash
curl -L https://raw.githubusercontent.com/Ayuemin/torrio/main/torrio.py -o ~/torrio.py
install -m 755 ~/torrio.py $PREFIX/bin/torrio
```

Verify the installation:

```bash
which torrio
```

Start Torrio:

```bash
torrio
```

## Start menu

```text
Torrio 1.3
Android torrent search & download for Termux

 [1] Paste magnet link or .torrent URL
 [2] Select a local .torrent file
 [3] Search torrents
 [0] Exit
>
```

### 1 — Paste a magnet link or torrent URL

Choose `1` and paste either a magnet link:

```text
magnet:?xt=urn:btih:...
```

or an HTTP/HTTPS URL.

Torrio passes the target to aria2.

### 2 — Select a local `.torrent` file

Choose `2`.

Torrio searches for `.torrent` files in common locations, including:

- Android `Download`
- `Download/Torrio`
- `~/Torrio`
- the current working directory

Files are displayed with global numbers.

```text
  1) debian.iso.torrent
     /data/data/com.termux/files/home/storage/downloads

  2) example.torrent
     /data/data/com.termux/files/home/storage/downloads/Torrio
```

Commands:

```text
number = select
n      = next page
p      = previous page
r      = enter a path manually
q      = quit
```

### 3 — Search torrents

Choose `3`.

Torrio asks four questions:

```text
What are you looking for?
Format / type [Enter = any]:
Version / year / date [Enter = any]:
Exclude words or phrases [Enter = none]:
```

Only the first field is required.

## Search examples

### Debian netinst image

```text
What are you looking for? Debian
Format / type [Enter = any]: netinst amd64
Version / year / date [Enter = any]: 13.5
Exclude words or phrases [Enter = none]:
```

Generated query:

```text
Debian netinst amd64 13.5
```

### FLAC music search

```text
What are you looking for? Enigma
Format / type [Enter = any]: flac
Version / year / date [Enter = any]:
Exclude words or phrases [Enter = none]:
```

Generated query:

```text
Enigma flac
```

### Software search with exclusions

```text
What are you looking for? Blender
Format / type [Enter = any]: linux x86_64
Version / year / date [Enter = any]: 4.5
Exclude words or phrases [Enter = none]: tutorial course
```

Excluded terms can also be written with a leading minus sign:

```text
-video -course
```

Quoted phrases are supported:

```text
"linux mint" tutorial
```

Torrio treats a single excluded word as a whole term. For example, excluding `book` does not exclude `Bookworm`.

## Search sources

Torrio currently combines results from:

- [Knaben](https://knaben.org/)
- [FOSS Torrents](https://fosstorrents.com/)
- [Internet Archive](https://archive.org/)

Torrio does not host torrent files or BitTorrent content itself.

Search availability and result quality depend on third-party sources and their current APIs or feeds.

## Search result navigation

Results are displayed as numbered pages. Long titles wrap instead of being truncated.

```text
Results 1–8 of 74 loaded · page 1/10

   1) A long torrent title that automatically wraps onto
      another terminal line
      [KN · seeders 84 · 10.9GB]

   2) Another result
      [IA · downloads 1200 · 762.9MB]
```

Commands:

```text
number = select
n      = next
p      = previous
m      = load more
q      = quit
```

When additional results are loaded, Torrio merges, deduplicates and re-sorts the complete list.

## Selected result menu

After selecting a result, Torrio displays a result card:

```text
 SELECTED RESULT ───────────────────────────────────────────
Source: KN
Title: Example torrent title
Size: 464.3MB
Seeders: 13
Downloads: ?
Infohash: ...
Type: magnet
Page: ...
```

Available actions:

```text
 [m] Fetch BitTorrent metadata
 [d] Download with aria2c
 [c] Copy magnet/.torrent URL
 [o] Open source page
 [q] Quit
```

### `m` — Fetch BitTorrent metadata

For magnet links, aria2 is started in metadata-only mode.

### `d` — Download

The selected magnet link, torrent URL or local torrent file is passed to aria2.

Torrio displays the download directory and enables a wake lock before aria2 starts.

### `c` — Copy the target

Copies the magnet link or torrent URL when `termux-clipboard-set` is available.

### `o` — Open the source page

Opens the source page when `termux-open-url` is available.

## Wake lock and screen-off downloads

Before aria2 starts, Torrio calls:

```bash
termux-wake-lock
```

When aria2 finishes or is interrupted, Torrio calls:

```bash
termux-wake-unlock
```

This prevents the CPU from going to sleep while aria2 is running and lets the screen be turned off during a download.

Android vendors may still apply aggressive battery restrictions to background applications. If downloads are terminated after switching away from Termux, check Android battery settings for Termux and allow unrestricted background activity where available.

## Colors and `NO_COLOR`

Torrio uses a small ANSI color palette for headings, menu keys and status labels such as:

```text
[OK]
[INFO]
[WARN]
[ERROR]
```

Colors are automatically disabled when output is not connected to an interactive terminal or when `TERM=dumb`.

Torrio also respects the `NO_COLOR` environment variable:

```bash
NO_COLOR=1 torrio
```

## Direct command-line search

Interactive mode is the default, but direct CLI search is also available.

```bash
torrio Debian --format "netinst amd64" --fresh "13.5" --exclude "book mint"
```

Select a source:

```bash
torrio Debian --source knaben
torrio Debian --source foss
torrio Debian --source ia
```

Change the remote batch size:

```bash
torrio Debian --batch-size 100
```

Change the number of results displayed per terminal page:

```bash
torrio Debian --page-size 5
```

## Updating Torrio

Download the current script and reinstall it over the existing command:

```bash
curl -L https://raw.githubusercontent.com/Ayuemin/torrio/main/torrio.py -o ~/torrio.py
install -m 755 ~/torrio.py $PREFIX/bin/torrio
```

Then run:

```bash
torrio
```

## Uninstall

Remove the installed command:

```bash
rm $PREFIX/bin/torrio
```

This does not remove files from `Download/Torrio`.

## Notes

- Torrio does not require root access.
- Torrio uses only the Python standard library.
- aria2 handles BitTorrent and other supported download protocols.
- Search sources are external services and may change or become temporarily unavailable.
- Search matching keeps Unicode/Cyrillic support even though the interface is in English.

## Disclaimer

Torrio is a general-purpose search and download utility. It does not host, publish or distribute BitTorrent content.

Users are responsible for ensuring that their use of Torrio and BitTorrent complies with applicable laws, local regulations and the rights of content owners.

The authors and contributors do not endorse copyright infringement or any other unlawful use of the software.

## License

Torrio is released under the [MIT License](LICENSE).
