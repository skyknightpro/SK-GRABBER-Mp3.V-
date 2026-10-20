# SK Grabber <sup>mp3 version</sup>

A universal audio grabber with a glassmorphism interface. Paste a direct file
link, a normal web page, a streaming site, a DRM music service link, or a Tor
`.onion` address - SK Grabber finds the audio, converts it to MP3 and tags it.

<img width="662" height="660" alt="Screenshot 2026-10-21 005955" src="https://github.com/user-attachments/assets/7226461b-39e0-4b3c-adc1-c898a6c8176c" />

## Ready to use

Run **`dist\SK Grabber.exe`**. No Python installation is needed.

The exe bundles yt-dlp, ffmpeg, CA certificates, curl_cffi, requests and
PySocks, so it can download, convert, impersonate a browser and use Tor by
itself.

## Interface

- Dark glass-style cards with soft gradient glows, rounded borders and the
  Poppins font family bundled inside the exe.
- A custom SK Grabber icon is used for the window and the compiled executable.
- Title badge shows the **mp3 version** label; the subtitle is kept short:
  *Extract and convert audio from any link into MP3.*
- The main action button is simply **Download**. **Reset** returns the window
  to its launch state while keeping the selected **SAVE TO** folder and the
  proxy preference unchanged.
- When a download finishes, an **Open Folder** button appears under the
  completion message and opens the output folder with the file selected.
- Micro-animations: a breathing accent glow in the header, animated status
  colours, a sliding and fading **Supported Platforms** page, and a faded
  file-picker dialog.
- **Platforms** button opens an in-app page with every supported category,
  a scrollable list and a smooth Back button.
- Internal engine, proxy and Tor diagnostics are written to the log file
  rather than shown in the interface; the status line uses plain language.
- Press **Enter** in the link field to start; **Escape** closes the Platforms
  page or the file chooser.

## What it supports

- Direct audio links (MP3, M4A, WAV, OGG, FLAC, AAC, OPUS, WMA)
- SoundCloud, YouTube / YouTube Music, Bandcamp, Mixcloud, Vimeo,
  TikTok, Instagram, Reddit and thousands of other sites supported by yt-dlp
- Audiomack songs: the app reads the page and asks Audiomack's public API for
  the signed stream, which fixes the "Failed to parse JSON" error from the old
  extractor. Region-locked or premium-only songs are matched on
  YouTube/SoundCloud instead
- Universal webpage fallback: if yt-dlp fails with an unsupported URL, parser
  error or JSON error, the app fetches the raw HTML and scans it for
  `<audio>`, `<video>`, `<source>`, `og:audio`, HLS (`.m3u8`), DASH (`.mpd`),
  common player JSON keys, player `data-*` attributes, and embedded YouTube,
  SoundCloud, Vimeo and Dailymotion players
- Direct ffmpeg fallback for clearnet audio/HLS/DASH URLs when yt-dlp's
  extractor fails but ffmpeg can still read the stream
- Cloudflare-protected direct media files: after an HTTP 401/403/429, the file
  is retried with curl_cffi's Chrome TLS fingerprint before proxy retries
- Spotify track, album and playlist links (up to 50 tracks per link)
- Apple Music song, album and playlist links
- Best-effort metadata matching for TIDAL, Deezer and Amazon Music links
- Tor `.onion` pages. Onion URLs never go through yt-dlp's site-specific
  extractors: the raw HTML is fetched through the local Tor SOCKS5 proxy,
  scanned for embedded media, and the found MP3/M4A/etc. is downloaded
  directly through Tor. HLS/DASH links use yt-dlp's generic extractor with
  native segment downloading inside Tor
- Built-in free VPN / proxy toggle for sites that are blocked on your network

Everything is saved as MP3. Spotify and matched music tracks get clean
title/artist ID3 tags.

## Browser impersonation and bot protection

Every yt-dlp request uses normal Chrome headers (User-Agent, Accept,
Accept-Language) and yt-dlp's Chrome TLS/browser impersonation through
`curl_cffi`. The same global browser fingerprint is applied to every
extraction and search, and page scraping prefers a real browser fingerprint
too, then falls back to the standard library. This gets through many
Cloudflare and bot-protection checks that reject plain Python requests.

If impersonation is unavailable for any reason, the app retries without it
instead of failing the download.

When a site still returns a bot-check, region block or JSON/parser error, the
app retries the page (and the download) through the free proxy pool described
below.

## Free VPN / Proxy toggle

The **Free VPN / Proxy** switch routes restricted or blocked requests through
free public proxies - no external software, accounts or paid service needed.

How it works:

- Every time the switch is turned **ON** (including OFF -> ON again), the app
  throws away the previous pool and starts a completely fresh search. It
  downloads public HTTP/SOCKS5 lists from TheSpeedX, monosans, proxifly,
  ProxyScrape, GeoNode and OpenProxyList, then validates candidates against a
  neutral endpoint.
- Up to three search/validation rounds are run automatically when a list is
  full of dead entries. Each candidate is checked for a real, different exit
  IP, so private, loopback, LAN and transparent proxies are rejected.
- Working proxies are sorted by measured latency. The **fastest validated
  proxy is always tried first**, then the rest rotate for later attempts.
  The switch itself only shows ON/OFF; proxy counts and latency stay out of
  the interface.
- Turning the switch **OFF** clears the pool. The pool also refreshes itself
  after 15 minutes and keeps up to 10 working proxies in memory only.
- Normal downloads still try the direct connection first. Only when that
  fails with a network, geo-block, Cloudflare/captcha, timeout or parser error
  does the app retry through free proxies, showing a simple retry message
  instead of technical details.
- The toggle applies to page scraping, metadata fetching and yt-dlp
  downloads/searches. HTTP proxies can also be passed to ffmpeg's
  `-http_proxy` for HLS/DASH streams through the same pool.
- Onion links always use Tor; the free proxy pool is never used for `.onion`
  traffic.
- The choice is saved in `~/.sk_grabber.json`, so the switch keeps its state
  between launches. Existing settings from `.mp3_grabber.json` are migrated
  automatically.

Free public proxies are slow, change constantly and are shared by many
people. They can also inspect unencrypted traffic, so avoid enabling the
toggle for logins or private data - leave it off for ordinary downloads and
turn it on when a specific site refuses to load.

## DRM and metadata matching

Spotify and Apple Music streams are DRM-protected, so no downloader can save
their raw audio. For those links the app reads the public page/API metadata
(title, artist, duration), searches YouTube, tries several best matches, then
falls back to SoundCloud. The best audio is downloaded, converted to MP3 and
tagged with the original title/artist.

TIDAL, Deezer and Amazon Music use the same best-effort metadata path. A few
tracks may not be available, may be region-locked, or may match a different
live/cover version. Playlists and albums are capped at 50 tracks per link.

## Tor and .onion links

A `.onion` URL is detected automatically. The app looks for a local Tor SOCKS5
proxy on:

- `127.0.0.1:9050` - Tor daemon / Tor service
- `127.0.0.1:9150` - Tor Browser

If neither port is open, SK Grabber looks for a local `tor.exe` (Tor Browser,
the Tor Expert Bundle, or `tor` in `PATH`) and tries to start it automatically
with a private data directory under `%LOCALAPPDATA%\SK Grabber\tor`. It then
waits for the SOCKS port to open. Start Tor Browser manually if no Tor
installation is found.

Tor circuits can be slow or drop a connection. Page fetching retries each
onion target three times with a fresh session, and HTTP and HTTPS onion
variants are both attempted. If a direct media transfer is cut, try the link
again.

The app uses remote DNS through `socks5h`, so `.onion` hostnames are never
sent to your normal DNS resolver. Page fetching, direct media downloads,
generic yt-dlp extraction and HLS/DASH fragments all use the same Tor proxy.

Onion pages are never passed to yt-dlp's site-specific extractors. The app
reads the raw page source, then follows onion player iframes and looks for
`<audio>`, `<video>`, `<source>`, `og:audio`, media extensions, HLS/DASH
manifests, player JSON keys and common `data-*` attributes. A found direct
file is streamed to disk through Tor and converted to MP3 locally.

To use a different proxy, set `SK_GRABBER_TOR_PROXY` (the old
`MP3_GRABBER_TOR_PROXY` is also read), for example:

```
set SK_GRABBER_TOR_PROXY=socks5h://127.0.0.1:9050
```

To point at a specific Tor executable:

```
set SK_GRABBER_TOR_EXE=C:\Program Files\Tor Browser\Browser\TorBrowser\Tor\tor.exe
```

Only onion links (and media requested with an onion page as referer) are sent
through Tor. Ordinary clearnet downloads are not routed through Tor unless you
configure a proxy yourself.

Onion services are usually plain HTTP. If you paste an HTTPS onion URL, page
fetching tries HTTP first and falls back to HTTPS when needed. Direct media
links are normalized the same way.

## Browser-only `blob:` players

Some sites create a `blob:` URL inside JavaScript. A blob only exists in that
browser tab, so yt-dlp cannot fetch it directly. The scanner detects these
players and still searches the surrounding scripts for the real HLS/DASH
manifest. If the stream is completely hidden inside JavaScript, the app shows
a clear message instead of downloading an invalid blob link.

## Automatic updates

On startup the app checks PyPI for a newer stable yt-dlp release. When one is
available it updates automatically, so new or changed sites keep working:

- Running from source: it uses `pip install --upgrade yt-dlp`.
- Running the exe: it downloads the official wheel from PyPI, verifies its
  SHA-256 checksum and loads it from
  `%LOCALAPPDATA%\SK Grabber\yt-dlp`. The bundled copy is used if the update
  cannot be downloaded (for example, when offline).

The check runs in the background and is cached for six hours. A log is kept at
`%LOCALAPPDATA%\SK Grabber\yt-dlp-update.log`. The updater follows stable
PyPI releases, the same ones `pip install -U yt-dlp` installs. An existing
`%LOCALAPPDATA%\MP3 GRABBER` folder is renamed automatically on first launch.

## Run from source

```
pip install customtkinter yt-dlp certifi imageio-ffmpeg mutagen curl_cffi requests PySocks
python sk_grabber.py
```

Bundled fonts and the app icon live in `assets/`. On this machine the Python
3.15 standard library is split into
`%LOCALAPPDATA%\Programs\Python\Python315`, so `PYTHONHOME` may need to point
there for imports/pip to work.

## Rebuild the exe

Run `build_exe.bat`. It installs the dependencies and rebuilds
`dist\SK Grabber.exe` using `SK Grabber.spec`. The spec bundles curl_cffi,
requests and PySocks along with yt-dlp, ffmpeg, certifi and mutagen, plus the
`assets` folder (Poppins fonts and the custom icon).

## Diagnostics

Run this from a command prompt:

```
"dist\SK Grabber.exe" --selftest
```

The result is written to `%TEMP%\sk_grabber_selftest.txt` and checks
impersonation, page scanning, yt-dlp, certificates, ffmpeg, bundled assets and
a real test download.

To test Tor as well (Tor must be running or installed):

```
"dist\SK Grabber.exe" --selftest --tor
```

To test the free proxy pool (downloads and validates public proxies):

```
"dist\SK Grabber.exe" --selftest --proxy
```

To test the Audiomack API signing path:

```
"dist\SK Grabber.exe" --selftest --audiomack
```

The flags can be combined, for example
`"dist\SK Grabber.exe" --selftest --tor --proxy --audiomack`.

To also download and load the latest yt-dlp update during the test:

```
"dist\SK Grabber.exe" --selftest --update
```

To reset the automatic updater, delete
`%LOCALAPPDATA%\SK Grabber\yt-dlp` and `yt-dlp-check.json`.

## Limitations

- Spotify/Apple Music/TIDAL/Deezer/Amazon Music are metadata matches, not DRM
  extraction.
- Audiomack region-locked or premium-only songs are matched on other services,
  so the audio may differ from Audiomack's own stream.
- Login-protected and age-restricted pages may still fail.
- A browser-only `blob:` stream cannot be downloaded without running the
  site's JavaScript.
- ffmpeg's direct URL fallback is used only for clearnet URLs because ffmpeg
  has no SOCKS support. Onion files are downloaded through Tor by the app, and
  onion HLS/DASH uses yt-dlp's native downloader through Tor.
- Tor must be running locally (or installable) for onion links.
- Free public proxies are best-effort: some are slow or short-lived, and a
  blocked site may still fail after trying several of them. The toggle is a
  convenience proxy rotation, not a privacy VPN.

## Files

- `sk_grabber.py` - current source
- `SK Grabber.spec` / `build_exe.bat` - packaging files
- `assets\sk_grabber.ico` - window and executable icon
- `assets\fonts\Poppins-*.ttf` - bundled UI fonts (SIL Open Font License)
- `make_icon.py` - development helper that regenerates the icon
- `mp3_grabber (1).py.bak` - backup of the original version
- `mp3_grabber.py` - older version, kept for reference
- `dist\SK Grabber.exe` - ready-to-run program
