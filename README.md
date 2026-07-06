# Torrio

> A lightweight interactive torrent search and download tool for Android, built for Termux and powered by aria2.

![Python](https://img.shields.io/badge/Python-3.x-blue)
![Android](https://img.shields.io/badge/Android-Termux-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

Torrio provides a simple terminal interface for three common BitTorrent workflows on Android:

1. Paste a magnet link or `.torrent` URL.
2. Select a local `.torrent` file.
3. Search for a torrent interactively.

Search results are merged, ranked, deduplicated and displayed as numbered pages that are comfortable to use on a phone screen.

Torrio uses `aria2c` for downloads and automatically enables a Termux wake lock while aria2 is running, so the CPU does not go to sleep when the screen is turned off.

## Features

- Interactive torrent search from Termux
- Search query refinement by name, format/type and version/year/date
- Excluded words and excluded phrases
- Search across Knaben, FOSS Torrents and Internet Archive
- Result ranking and deduplication
- Paginated, numbered results designed for narrow terminal screens
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

For a regular Android device, the stable Termux build from F-Droid or the official Termux GitHub repository is recommended.

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

After this step, the Android `Download` directory is available in Termux as:

```text
~/storage/downloads
```

Torrio stores completed downloads in:

```text
Download/Torrio
```

Inside Termux, the same directory is:

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

Then start Torrio:

```bash
torrio
```

## Start menu

Torrio starts with a simple menu:

```text
Torrio 1.2

1) Вставить magnet или ссылку
2) Выбрать .torrent-файл
3) Найти раздачу
0) Выход

>
```

The current terminal interface is in Russian.

### 1 — Paste a magnet link or torrent URL

Choose:

```text
1
```

Paste either:

```text
magnet:?xt=urn:btih:...
```

or an HTTP/HTTPS URL pointing to a torrent resource.

Torrio passes the target directly to aria2.

### 2 — Select a local `.torrent` file

Choose:

```text
2
```

Torrio searches for `.torrent` files in commonly used locations, including:

- Android `Download`
- `Download/Torrio`
- `~/Torrio`
- the current working directory

Files are shown with numbers. Enter a number to select a file.

Example:

```text
  1) debian.iso.torrent
     /data/data/com.termux/files/home/storage/downloads

  2) example.torrent
     /data/data/com.termux/files/home/storage/downloads/Torrio
```

Available commands:

```text
number = select
n      = next page
p      = previous page
r      = enter a path manually
q      = quit
```

### 3 — Search for a torrent

Choose:

```text
3
```

Torrio asks four questions.

#### Name

Required.

Example:

```text
Debian
```

#### Format or type

Optional. Press Enter to skip.

Examples:

```text
netinst amd64
flac
book
linux x86_64
```

#### Version, year or date

Optional. Press Enter to skip.

Examples:

```text
13.5
2025
4.5
```

#### Excluded words

Optional. Press Enter to skip.

Examples:

```text
video course
```

or:

```text
-video -course
```

Quoted phrases are also supported:

```text
"linux mint" tutorial
```

Torrio treats excluded words as whole terms. For example, excluding `book` does not exclude `Bookworm`.

## Search examples

### Debian netinst image

```text
Что ищем: Debian
Формат / тип [Enter — любой]: netinst amd64
Версия / год / дата [Enter — любая]: 13.5
Исключить слова [Enter — нет]:
```

Generated query:

```text
Debian netinst amd64 13.5
```

### FLAC music search

```text
Что ищем: Enigma
Формат / тип [Enter — любой]: flac
Версия / год / дата [Enter — любая]:
Исключить слова [Enter — нет]:
```

Generated query:

```text
Enigma flac
```

### Software search with exclusions

```text
Что ищем: Blender
Формат / тип [Enter — любой]: linux x86_64
Версия / год / дата [Enter — любая]: 4.5
Исключить слова [Enter — нет]: tutorial course
```

## Search sources

Torrio currently combines results from:

- [Knaben](https://knaben.org/)
- [FOSS Torrents](https://fosstorrents.com/)
- [Internet Archive](https://archive.org/)

Torrio does not host torrent files or BitTorrent content itself.

Search availability and result quality depend on third-party sources and their current APIs or feeds.

## Search result navigation

Search results are shown as numbered pages.

Example:

```text
Результаты 1–8 из 74 загруженных · страница 1/10

   1) First torrent title
      [KN · сиды 84 · 10.9GB]

   2) A longer torrent title that automatically wraps
      onto another terminal line
      [KN · сиды 40 · 724.8MB]
```

Commands:

```text
number = select a result
n      = next page
p      = previous page
m      = load more remote results
q      = quit
```

When more results are loaded, Torrio merges, deduplicates and re-sorts the complete result list.

## Selected result menu

After selecting a result, Torrio displays its metadata and the following menu:

```text
[m] проверить метаданные
[d] скачать через aria2c
[c] скопировать magnet/.torrent URL
[o] открыть страницу источника
[q] выйти
```

### `m` — Fetch BitTorrent metadata

For magnet links, aria2 is started in metadata-only mode.

### `d` — Download

The selected magnet link, torrent URL or local torrent file is passed to aria2.

The download directory is displayed before aria2 starts.

### `c` — Copy the target

Copies the magnet link or torrent URL when `termux-clipboard-set` is available.

### `o` — Open the source page

Opens the result source page when `termux-open-url` is available.

## Wake lock and screen-off downloads

Before aria2 starts, Torrio calls:

```bash
termux-wake-lock
```

When the download process finishes or is interrupted, Torrio calls:

```bash
termux-wake-unlock
```

This prevents the CPU from going to sleep while aria2 is running and allows the screen to be turned off during a download.

Android vendors may still apply aggressive battery restrictions to background applications. If downloads are terminated after switching away from Termux, check the battery settings for Termux and allow unrestricted background activity where available.

## Direct command-line search

The interactive interface is the default, but Torrio also keeps a direct command-line mode for advanced users.

Example:

```bash
torrio Debian --format "netinst amd64" --fresh "13.5" --exclude "book mint"
```

Select a specific source:

```bash
torrio Debian --source knaben
torrio Debian --source foss
torrio Debian --source ia
```

Change the remote fetch batch size:

```bash
torrio Debian --batch-size 100
```

Change the number of displayed results per terminal page:

```bash
torrio Debian --page-size 5
```

## Updating Torrio

Download the current script again and reinstall it over the existing command:

```bash
curl -L https://raw.githubusercontent.com/Ayuemin/torrio/main/torrio.py -o ~/torrio.py
install -m 755 ~/torrio.py $PREFIX/bin/torrio
```

Start Torrio:

```bash
torrio
```

## Uninstall

Remove the installed command:

```bash
rm $PREFIX/bin/torrio
```

This does not remove downloaded files from `Download/Torrio`.

## Notes

- Torrio does not require root access.
- Torrio uses only the Python standard library.
- aria2 handles BitTorrent and other supported download protocols.
- Search sources are external services and may change or become temporarily unavailable.
- The current interactive UI is in Russian.

## Disclaimer

Torrio is a general-purpose search and download utility. It does not host, publish or distribute BitTorrent content.

Users are responsible for ensuring that their use of Torrio and BitTorrent complies with applicable laws, local regulations and the rights of content owners.

The authors and contributors do not endorse copyright infringement or any other unlawful use of the software.

## License

Torrio is released under the [MIT License](LICENSE).
