# SK Grabber <sup>mp3 version</sup>

A universal audio grabber with a glassmorphism interface. Paste a direct file
link, a normal web page, a streaming site, a DRM music service link, or a Tor
`.onion` address - SK Grabber finds the audio, converts it to MP3 and tags it.

<img width="662" height="660" alt="Screenshot 2026-10-21 005955" src="https://github.com/user-attachments/assets/7226461b-39e0-4b3c-adc1-c898a6c8176c" />

SK Grabber (mp3 version)

A modern Windows desktop utility designed to extract and convert audio from any direct link, streaming platform, web page, or Tor .onion site into high-quality MP3 files.

Quick Start

No Python installation required.
Simply download, extract the zip archive, and run SK Grabber.exe.
The app comes pre-bundled with yt-dlp, ffmpeg, curl_cffi, requests, PySocks, and all necessary certificates to run standalone.

Key Features

Glassmorphism Interface
Clean dark glass-style design with soft gradient glows, rounded borders, and custom fonts. Features simple action buttons for Download, Reset, and Open Folder upon completion, with keyboard shortcut support.

Universal Audio Extraction
Extracts and converts to all major audio formats including MP3, M4A, WAV, OGG, FLAC, AAC, OPUS, and WMA.
Supports YouTube, SoundCloud, TikTok, Instagram, Reddit, Audiomack, and thousands of other platforms.
Includes an automatic web scraper fallback that detects direct audio streams inside web pages if standard extractors fail.
Emulates real browser TLS fingerprints to bypass Cloudflare and bot checks.

Music Streaming Metadata Matching
Supports Spotify, Apple Music, TIDAL, Deezer, and Amazon Music links.
Reads track metadata (Title, Artist, Duration), searches public sources for the best match, downloads the audio, and applies clean ID3 tags automatically.

Native Tor Support (.onion)
Automatically detects .onion URLs and routes requests through your local Tor SOCKS5 proxy without leaking DNS queries.

Built-in Free Proxy Toggle
Easily bypass local network blocks or region restrictions using dynamically fetched public HTTP and SOCKS5 proxy pools with automatic fast-node selection.

Automatic Engine Updates

On startup, SK Grabber checks for new stable yt-dlp updates in the background and upgrades itself automatically to keep all supported sites working smoothly.

Limitations

Spotify and Apple Music downloads rely on best-match audio search rather than direct DRM decryption.
Tor links require a running or locally installed Tor service on your machine.
The free proxy pool is meant for unblocking content, not for high-privacy or sensitive data logins.
