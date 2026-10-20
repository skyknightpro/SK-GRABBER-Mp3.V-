"""SK Grabber - desktop audio downloader and MP3 converter."""
from __future__ import annotations

import base64
import concurrent.futures
import ctypes
import glob
import hashlib
import hmac
import html
import importlib.abc
import importlib.metadata
import importlib.util
import json
import os
import queue
import random
import re
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from tkinter import filedialog
from tkinter import font as tkfont

import customtkinter as ctk

from skgrabber.config import AppConfig, ProxyMode, load_config
from skgrabber.errors import DownloadCancelled, FriendlyError
from skgrabber.net import (
    BROWSER_HEADERS,
    USER_AGENT,
    disable_insecure_warnings as _disable_insecure_warnings,
    load_requests as _load_requests,
    urlopen_ctx,
)
from skgrabber.paths import (
    SELFTEST_LOG,
    app_data_directory,
    asset_path,
    ensure_proxies_file,
    migrate_legacy_data,
)
from skgrabber.proxy import (
    parse_custom_proxy_lines,
    parse_proxy_lines,
    proxy_manager,
)
from skgrabber.version import (
    APP_NAME,
    APP_SLOGAN,
    APP_TAGLINE,
    APP_VERSION,
)

APP_DATA_DIR = str(app_data_directory())
UPDATE_ROOT = os.path.join(APP_DATA_DIR, "yt-dlp")
UPDATE_VERSIONS_DIR = os.path.join(UPDATE_ROOT, "versions")
UPDATE_CACHE_PATH = os.path.join(APP_DATA_DIR, "yt-dlp-check.json")
UPDATE_LOG_PATH = os.path.join(APP_DATA_DIR, "yt-dlp-update.log")
UPDATE_CHECK_INTERVAL = 6 * 60 * 60
PYPI_SIMPLE_URL = "https://pypi.org/simple/yt-dlp/"
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus", ".wma"}
CTYPE_TO_EXT = {
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
    "audio/mp4": ".m4a", "audio/x-m4a": ".m4a", "audio/m4a": ".m4a",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
    "audio/ogg": ".ogg", "application/ogg": ".ogg",
    "audio/flac": ".flac", "audio/x-flac": ".flac",
    "audio/aac": ".aac", "audio/opus": ".opus",
}
SPOTIFY_URL_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z-]+/)?(?:embed/)?"
    r"(track|album|playlist|episode|show|artist)/([A-Za-z0-9]+)",
    re.I,
)
SPOTIFY_SHORT_RE = re.compile(
    r"https?://(?:open\.)?(?:spotify\.link|spotify\.app\.link)/",
    re.I,
)
SPOTIFY_MAX_TRACKS = 50
APPLE_MUSIC_RE = re.compile(r"^https?://music\.apple\.com/", re.I)
DRM_METADATA_RE = re.compile(
    r"^https?://(?:[^/]+\.)?(?:tidal\.com|deezer\.com|music\.amazon\.[a-z.]+)/",
    re.I,
)
AUDIOMACK_RE = re.compile(r"^https?://(?:www\.)?audiomack\.com/", re.I)
AUDIOMACK_API_URL = "https://api.audiomack.com/v1"
AUDIOMACK_CONSUMER_KEY = "audiomack-web"
AUDIOMACK_CONSUMER_SECRET = "bd8a07e9f23fbe9d808646b730f89b8e"
TOR_HOST = "127.0.0.1"
TOR_PORTS = (9050, 9150)
TOR_PROXY_ENV = "MP3_GRABBER_TOR_PROXY"
TOR_PROXY_ENV_NEW = "SK_GRABBER_TOR_PROXY"
TOR_EXE_ENV = "SK_GRABBER_TOR_EXE"
TOR_BROWSER_PATHS = (
    r"C:\Program Files\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
    r"C:\Program Files (x86)\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
    os.path.join(os.environ.get("LOCALAPPDATA") or "", "Tor Browser",
                 "Browser", "TorBrowser", "Tor", "tor.exe"),
    r"C:\Program Files\Tor\tor.exe",
    r"C:\Program Files (x86)\Tor\tor.exe",
)
ONION_TEST_URL = (
    "http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/"
)
ONION_TEST_FALLBACK = (
    "http://2gzyxa5ihm7nsggfxnu52rck2vv4rvmdlkiu3zzui5du4xyclen53wid.onion/"
)
MAX_METADATA_TRACKS = 50
_STOPWORDS = {
    "the", "and", "feat", "ft", "official", "video", "audio", "lyrics",
    "remaster", "remastered", "version", "with",
}


def _register_bundled_fonts() -> None:
    if not sys.platform.startswith("win"):
        return
    for name in ("Poppins-Regular.ttf", "Poppins-Medium.ttf",
                 "Poppins-SemiBold.ttf", "Poppins-Bold.ttf"):
        path = asset_path("fonts", name)
        try:
            if path.exists():
                ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0)
        except OSError:
            continue


def _best_font_family(root):
    """Prefer the bundled modern font, then Windows' newest UI fonts."""
    try:
        from tkinter import font as tkfont
        families = set(tkfont.families(root))
    except Exception:
        families = set()
    for name in ("Poppins", "Segoe UI Variable Display", "Segoe UI",
                 "Helvetica Neue", "Arial"):
        if name in families:
            return name
    return "TkDefaultFont"


def _mix_hex(start, end, t):
    """Blend two #rrggbb colors; used for micro-animations."""
    try:
        a = tuple(int(start[i:i + 2], 16) for i in (1, 3, 5))
        b = tuple(int(end[i:i + 2], 16) for i in (1, 3, 5))
        rgb = tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))
        return "#%02x%02x%02x" % rgb
    except Exception:
        return end


def fmt_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def fmt_time(sec):
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def clean_filename(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "audio"


def filename_from_headers(headers):
    cd = headers.get("Content-Disposition", "")
    m = re.search(r"filename\*\s*=\s*[\w-]+''([^;]+)", cd, re.I)
    if m:
        return urllib.parse.unquote(m.group(1).strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
    return m.group(1).strip() if m else None


def unique_path(folder, name):
    base, ext = os.path.splitext(name)
    path = os.path.join(folder, name)
    i = 1
    while os.path.exists(path) or os.path.exists(path + ".part"):
        path = os.path.join(folder, f"{base} ({i}){ext}")
        i += 1
    return path


def friendly_http_error(code):
    if code == 404:
        return "File not found (404). The link is broken or the file was removed."
    if code == 410:
        return "This file has been removed (410)."
    if code in (401, 403):
        return f"Access denied ({code}). The server refuses to share this file."
    if code == 429:
        return "Too many requests (429). Try again in a little while."
    if 500 <= code < 600:
        return f"The server has a problem ({code}). Try again later."
    return f"The server returned an error ({code})."


def is_direct_audio_url(url):
    """True when the URL clearly points at an audio file (fast path)."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    path = urllib.parse.unquote(parsed.path or "")
    if os.path.splitext(path)[1].lower() in AUDIO_EXTS:
        return True
    for values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).values():
        for value in values:
            if "/" not in value and os.path.splitext(value)[1].lower() in AUDIO_EXTS:
                return True
    return False


def is_spotify_url(url):
    return bool(SPOTIFY_URL_RE.search(url) or SPOTIFY_SHORT_RE.search(url))


def is_apple_music_url(url):
    return bool(APPLE_MUSIC_RE.search(url or ""))


def is_drm_metadata_url(url):
    """True for services whose streams are DRM-protected but whose public
    metadata can be matched to a playable copy elsewhere."""
    return bool(is_spotify_url(url) or is_apple_music_url(url)
                or DRM_METADATA_RE.search(url or ""))


def is_onion_url(url):
    """True when the host is an onion service (case-insensitive)."""
    if not url:
        return False
    try:
        host = (urllib.parse.urlparse(str(url)).hostname or "").strip(".").lower()
    except ValueError:
        return False
    return host == "onion" or host.endswith(".onion")


_TOR_CACHE = {"url": None, "checked": 0.0}


def _port_open(host, port, timeout=0.7):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def tor_proxy():
    """Return the local Tor SOCKS5 proxy, preferring system Tor then Tor Browser."""
    override = os.environ.get(TOR_PROXY_ENV_NEW, "").strip() or \
        os.environ.get(TOR_PROXY_ENV, "").strip()
    if override:
        return override if "://" in override else "socks5h://" + override

    now = time.time()
    cached = _TOR_CACHE.get("url")
    if cached and now - float(_TOR_CACHE.get("checked") or 0) < 30:
        try:
            port = urllib.parse.urlparse(cached).port
        except ValueError:
            port = None
        if port and _port_open(TOR_HOST, port):
            return cached
        _TOR_CACHE["url"] = None

    for port in TOR_PORTS:
        if _port_open(TOR_HOST, port):
            proxy = f"socks5h://{TOR_HOST}:{port}"
            _TOR_CACHE.update(url=proxy, checked=now)
            return proxy

    raise FriendlyError(
        "This .onion link needs Tor.\n"
        "Open Tor Browser, wait for it to connect, then try again."
    )


_TOR_PROCESS = {"proc": None}


def _find_local_tor():
    """Look for a tor.exe installed on this machine."""
    override = os.environ.get(TOR_EXE_ENV, "").strip().strip('"')
    candidates = []
    if override:
        candidates.append(override)
    found = shutil.which("tor")
    if found:
        candidates.append(found)
    candidates.extend(TOR_BROWSER_PATHS)
    for path in candidates:
        try:
            if path and os.path.isfile(path):
                return path
        except Exception:
            continue
    return None


def _start_local_tor():
    """Best-effort start of a local Tor SOCKS service; returns True when it
    believes a start was attempted successfully."""
    exe = _find_local_tor()
    if not exe:
        _update_log("tor: no local tor.exe found to start automatically")
        return False
    if _TOR_PROCESS.get("proc") is not None and _TOR_PROCESS["proc"].poll() is None:
        return True
    flags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW
    args = [exe, "--SocksPort", str(TOR_PORTS[0])]
    data_dir = os.path.join(APP_DATA_DIR, "tor")
    try:
        os.makedirs(data_dir, exist_ok=True)
        args += ["--DataDirectory", data_dir]
    except Exception:
        pass
    try:
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=flags)
        _TOR_PROCESS["proc"] = proc
        _update_log(f"tor: started {exe} (pid {proc.pid}) on port {TOR_PORTS[0]}")
        return True
    except Exception as exc:
        _update_log("tor: could not start " + exe + ": " + _error_text(exc))
        return False


def ensure_tor(timeout=25):
    """Return a working Tor proxy, trying to start a local tor.exe if the
    usual ports are closed. Raises FriendlyError when Tor cannot be reached."""
    try:
        return tor_proxy()
    except FriendlyError as first_exc:
        if not _start_local_tor():
            raise
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1.0)
        try:
            _TOR_CACHE["url"] = None
            return tor_proxy()
        except FriendlyError:
            continue
    raise FriendlyError(
        "Tor is taking too long to connect.\n"
        "Open Tor Browser, wait for it to connect, then try again."
    ) from first_exc


def _onion_http_url(url):
    """Most onion services speak plain HTTP. Keep an explicit non-80/443 port."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return url
    if parsed.scheme.lower() == "https" and parsed.port in (None, 80):
        parsed = parsed._replace(scheme="http")
        return urllib.parse.urlunparse(parsed)
    return url


def _load_requests():
    try:
        import requests
        import socks
        if not hasattr(socks, "SOCKS5"):
            raise ImportError("PySocks is incomplete")
        return requests
    except Exception as exc:
        raise FriendlyError(
            "Private .onion links aren't available in this build.\n"
            "Reinstall SK Grabber and try again."
        ) from exc


def _disable_insecure_warnings():
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass


def _proxy_mode() -> ProxyMode:
    return proxy_manager.mode


def _proxy_enabled() -> bool:
    return proxy_manager.enabled


def _set_proxy_mode(mode: ProxyMode) -> None:
    proxy_manager.set_mode(mode)


def _set_proxy_enabled(value: bool) -> None:
    proxy_manager.set_mode(ProxyMode.FREE if value else ProxyMode.NONE)


def _proxy_candidates(count: int = 3, q: object | None = None) -> list[str]:
    return proxy_manager.candidates(count, q=q)


def _warm_proxy_pool(force: bool = False) -> list[str]:
    return proxy_manager.warm(force=force)


def _fetch_page_via_proxies(url, headers, timeout, limit, count=3):
    try:
        requests = _load_requests()
    except FriendlyError:
        return None
    _disable_insecure_warnings()
    for proxy in _proxy_candidates(count):
        try:
            with requests.get(
                url, headers=headers,
                proxies={"http": proxy, "https": proxy},
                timeout=min(timeout, 30), verify=False,
                allow_redirects=True, stream=True,
            ) as resp:
                if resp.status_code >= 400:
                    continue
                chunks = []
                size = 0
                for chunk in resp.iter_content(128 * 1024):
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= limit:
                        break
                raw = b"".join(chunks)
                if raw:
                    return _decode_page(raw, resp.encoding, limit), str(resp.url)
        except Exception:
            continue
    return None


def _decode_page(raw, charset, limit):
    raw = raw[:limit]
    try:
        return raw.decode(charset or "utf-8", errors="ignore")
    except LookupError:
        return raw.decode("utf-8", errors="ignore")


def _fetch_page_impersonated(url, headers, timeout, limit):
    """Fetch a normal page with Chrome's TLS/browser fingerprint when possible."""
    from curl_cffi import requests as curl_requests
    resp = curl_requests.get(
        url, headers=headers, impersonate="chrome", timeout=timeout,
        allow_redirects=True,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}")
    return _decode_page(resp.content, resp.encoding, limit), str(resp.url)


def _fetch_page_tor(url, headers, timeout, limit):
    """Fetch a page through Tor; used for .onion and onion-referred downloads."""
    requests = _load_requests()
    _disable_insecure_warnings()
    proxy = ensure_tor()
    proxies = {"http": proxy, "https": proxy}
    targets = [_onion_http_url(url)] if is_onion_url(url) else [url]
    if targets[0] != url:
        targets.append(url)

    last_exc = None
    # Tor circuits are unreliable: fresh connections can fail for a minute
    # and then succeed instantly on a new circuit. Retry each target.
    timeout = max(20, min(int(timeout or 20), 30))
    for target in targets:
        for attempt in range(3):
            session = requests.Session()
            try:
                with session.get(
                    target, headers=headers, proxies=proxies, timeout=timeout,
                    verify=not is_onion_url(url), allow_redirects=True,
                    stream=True,
                ) as resp:
                    if resp.status_code >= 400:
                        raise FriendlyError(friendly_http_error(resp.status_code))
                    chunks = []
                    size = 0
                    for chunk in resp.iter_content(128 * 1024):
                        if not chunk:
                            continue
                        chunks.append(chunk)
                        size += len(chunk)
                        if size >= limit:
                            break
                    raw = b"".join(chunks)
                    return _decode_page(raw, resp.encoding, limit), resp.url
            except FriendlyError as exc:
                last_exc = exc
            except Exception as exc:
                last_exc = exc
            finally:
                try:
                    session.close()
                except Exception:
                    pass
            if attempt < 2:
                time.sleep(1.5)

    if isinstance(last_exc, FriendlyError):
        raise last_exc
    detail = _error_text(last_exc) if last_exc else "connection failed"
    _update_log("tor fetch failed: " + detail[:500])
    raise FriendlyError(
        "Could not reach this site privately.\n"
        "Make sure Tor Browser is open and connected, then try again."
    ) from last_exc


def fetch_page(url, referer=None, timeout=20, limit=4 * 1024 * 1024):
    headers = dict(BROWSER_HEADERS)
    if referer:
        headers["Referer"] = referer

    # Onion pages, and any clearnet asset requested with an onion referer,
    # must go through Tor so DNS/requests never leak outside the circuit.
    if is_onion_url(url) or is_onion_url(referer):
        return _fetch_page_tor(url, headers, timeout, limit)

    # Prefer a real browser fingerprint for stubborn/Cloudflare-protected
    # pages, then fall back to the standard library, and finally to the
    # free proxy pool when the site is blocked on this network.
    try:
        return _fetch_page_impersonated(url, headers, timeout, limit)
    except Exception:
        pass

    try:
        req = urllib.request.Request(url, headers=headers)
        with urlopen_ctx(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            text = resp.read(limit).decode(charset, errors="ignore")
            return text, resp.geturl()
    except Exception as direct_exc:
        if _proxy_enabled():
            proxied = _fetch_page_via_proxies(url, headers, timeout, limit)
            if proxied is not None:
                return proxied
        raise direct_exc


def fetch_json(url, referer=None, timeout=20, limit=2 * 1024 * 1024):
    text, _ = fetch_page(url, referer=referer, timeout=timeout, limit=limit)
    return json.loads(text)


# ---------------------------------------------------------------- audiomack
def is_audiomack_url(url):
    return bool(AUDIOMACK_RE.match(url or ""))


def _oauth1_signature(method, url, params, consumer_secret, token_secret=""):
    """OAuth 1.0a HMAC-SHA1 signature used by Audiomack's public API."""

    def enc(value):
        return urllib.parse.quote(str(value), safe="~") \
            .replace("!", "%21").replace("'", "%27") \
            .replace("(", "%28").replace(")", "%29").replace("*", "%2A")

    pairs = sorted((enc(k), enc(v)) for k, v in params.items())
    param_string = "&".join(f"{key}={value}" for key, value in pairs)
    base = "&".join([method.upper(), enc(url), enc(param_string)])
    key = enc(consumer_secret) + "&" + enc(token_secret)
    digest = hmac.new(key.encode("utf-8"), base.encode("utf-8"),
                      hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def _audiomack_api(path, params=None, proxy=None, timeout=25):
    """Signed GET against api.audiomack.com; returns parsed JSON."""
    base_url = f"{AUDIOMACK_API_URL}/{str(path).lstrip('/')}"
    signed = dict(params or {})
    signed.update({
        "oauth_consumer_key": AUDIOMACK_CONSUMER_KEY,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_nonce": "".join(random.choice(string.ascii_letters + string.digits)
                               for _ in range(32)),
        "oauth_version": "1.0",
    })
    signed["oauth_signature"] = _oauth1_signature(
        "GET", base_url, signed, AUDIOMACK_CONSUMER_SECRET)
    full_url = base_url + "?" + urllib.parse.urlencode(signed)

    headers = dict(BROWSER_HEADERS)
    headers["Accept"] = "application/json, text/plain, */*"
    status = 0
    text = ""
    if proxy:
        requests = _load_requests()
        _disable_insecure_warnings()
        resp = requests.get(full_url, headers=headers,
                            proxies={"http": proxy, "https": proxy},
                            timeout=timeout, verify=False)
        status, text = resp.status_code, resp.text
    else:
        try:
            with urlopen_ctx(urllib.request.Request(full_url, headers=headers),
                             timeout=timeout) as resp:
                status = resp.status
                text = resp.read(1024 * 1024).decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as exc:
            status = exc.code
            text = exc.read(1024 * 1024).decode("utf-8", errors="ignore")
        except Exception:
            from curl_cffi import requests as curl_requests
            resp = curl_requests.get(full_url, headers=headers,
                                     impersonate="chrome", timeout=timeout)
            status, text = resp.status_code, resp.text

    try:
        data = json.loads(text)
    except Exception as exc:
        raise FriendlyError(
            "Audiomack returned an unexpected response.\n"
            "Try again in a moment.") from exc
    if isinstance(data, dict) and data.get("errorcode"):
        message = str(data.get("message") or "request refused")
        _update_log("audiomack api error: " + message)
        if status in (401, 403) or "authoriz" in message.lower():
            raise FriendlyError(
                "This song isn't available directly.\n"
                "Finding another source...")
        raise FriendlyError("This song isn't available right now.")
    if status >= 400:
        raise FriendlyError(friendly_http_error(status))
    return data


def audiomack_info(url):
    """Return {'id', 'title', 'artist'} parsed from an Audiomack song page."""
    page, final_url = fetch_page(url, limit=2 * 1024 * 1024)
    text = html.unescape(page.replace("\\/", "/")).replace('\\"', '"')
    info = {"id": None, "title": "", "artist": "", "page_url": final_url}
    match = re.search(r'"music"\s*:\s*\{\s*"id"\s*:\s*(\d+)', text)
    if match:
        info["id"] = match.group(1)
        chunk = text[match.start():match.start() + 40000]
        title = re.search(r'"title"\s*:\s*"([^"]{1,200})"', chunk)
        artist = re.search(
            r'"uploader"\s*:\s*\{[^{}]*?"name"\s*:\s*"([^"]{1,160})"', chunk)
        if title:
            info["title"] = html.unescape(title.group(1)).strip()
        if artist:
            info["artist"] = html.unescape(artist.group(1)).strip()
    if not info["title"]:
        og = re.search(r'property="og:title"\s+content="([^"]+)"', page)
        if og:
            label = html.unescape(og.group(1)).strip()
            label = re.sub(r":\s*Listen on Audiomack$", "", label, flags=re.I)
            parts = re.split(r"\s+by\s+", label, maxsplit=1, flags=re.I)
            info["title"] = parts[0].strip()
            if len(parts) > 1 and not info["artist"]:
                info["artist"] = parts[1].strip()
    return info


def audiomack_stream_url(url):
    """Ask Audiomack's public API for the signed stream of a song page."""
    info = audiomack_info(url)
    if not info.get("id"):
        raise FriendlyError(
            "Could not read this Audiomack page. Make sure the link points "
            "to a public song.")
    data = _audiomack_api(f"music/play/{info['id']}",
                          {"environment": "desktop-web", "hq": "true"})
    signed = (data or {}).get("signedUrl") or (data or {}).get("signed_url")
    if not signed:
        raise FriendlyError(
            "Audiomack did not return a stream for this song "
            "(region-locked or premium-only). Searching for it elsewhere...")
    return str(signed), info


class PageFound(Exception):
    """Raised when the link was a web page; carries audio links found in it."""

    def __init__(self, candidates):
        super().__init__("page")
        self.candidates = candidates


_EXT = r"(?:mp3|m4a|wav|ogg|flac|aac|opus|wma)"
_STREAM_EXT = r"(?:m3u8|mpd)"


_VARIANT_PREF = (".mp3", ".m4a", ".flac", ".wav", ".ogg", ".opus", ".aac",
                 ".m3u8", ".mpd", ".webm", ".mp4")


def best_audio_variant(urls):
    """Pick the most useful URL when a page offers the same file in several formats."""
    def key(url):
        path = urllib.parse.urlparse(url).path.lower()
        ext = os.path.splitext(path)[1]
        try:
            rank = _VARIANT_PREF.index(ext)
        except ValueError:
            rank = len(_VARIANT_PREF)
        return rank, urls.index(url)

    return min(urls, key=key)


def collapse_candidates(candidates):
    """Turn <source> format variants of one track into a single choice."""
    groups = {}
    for url in candidates:
        parsed = urllib.parse.urlparse(url)
        stem, ext = os.path.splitext(os.path.basename(parsed.path))
        key = (parsed.netloc.lower(), stem.lower()) if stem and ext else url
        groups.setdefault(key, []).append(url)
    if len(groups) == 1:
        variants = next(iter(groups.values()))
        if len(variants) > 1:
            return [best_audio_variant(variants)]
    return candidates


def _normalize_scan_text(page_html):
    """Normalize common HTML/JS escaping before searching a page source."""
    text = html.unescape(str(page_html or ""))
    text = text.replace("\\/", "/").replace('\\"', '"')
    text = re.sub(r"\\u002[fF]", "/", text)
    text = re.sub(r"\\x2[fF]", "/", text)
    return text


def _collect_audio_links(page_html, base_url):
    """Return (media_links, generic_links) found in a page.

    media_links are trustworthy audio/stream sources (media tags, extensions,
    og:audio and absolute media URLs). generic_links are extension-less player
    endpoints and data-attribute values that may need another page scan.
    """
    text = _normalize_scan_text(page_html)
    found = []
    generic = []
    seen = set()

    def add(u, bucket):
        u = html.unescape(str(u or "")).strip()
        if not u or u.lower().startswith(("data:", "javascript:", "blob:")):
            return
        full = urllib.parse.urljoin(base_url, u)
        if not full.lower().startswith(("http://", "https://")):
            return
        if full not in seen:
            seen.add(full)
            bucket.append(full)

    ext = "(?:" + _EXT + "|" + _STREAM_EXT + ")"

    # <audio>/<video>/<source src=...> (may have no extension)
    for m in re.finditer(
            r"""<(?:audio|video|source)\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""",
            text, re.I):
        add(m.group(1), found)
    # og:audio / og:video meta tags
    for m in re.finditer(
            r"""<meta[^>]+(?:property|name)\s*=\s*["']og:(?:audio|video)[^"']*["']"""
            r"""[^>]*content\s*=\s*["']([^"']+)["']""",
            text, re.I):
        add(m.group(1), found)
    # attribute values ending in an audio/HLS extension (relative or absolute)
    for m in re.finditer(
            r"""(?:src|href|content|data-[\w-]+)\s*=\s*["']([^"'\s]+?\."""
            + ext + r"""(?:\?[^"'\s]*)?)["']""", text, re.I):
        add(m.group(1), found)
    # absolute audio/HLS URLs anywhere in the page (scripts, JSON, etc.)
    for m in re.finditer(r"""https?://[^\s"'<>\\)]+?\.""" + ext
                         + r"""(?:\?[^\s"'<>\\)]*)?""", text, re.I):
        add(m.group(0), found)
    # protocol-relative media URLs in scripts or JSON
    for m in re.finditer(r"""(?<!:)//[^\s"'<>\\)]+?\.""" + ext
                         + r"""(?:\?[^\s"'<>\\)]*)?""", text, re.I):
        add(m.group(0), found)
    # relative media paths (new Audio("/audio/x.mp3"), JSON, markup)
    for m in re.finditer(
            r"""(?:["'(\s=])((?:\.{0,2}/|/)?[A-Za-z0-9_%+~\-./]+?\."""
            + ext + r"""(?:\?[^"'\\\s<>]*)?)""", text, re.I):
        add(m.group(1), found)

    # Player data attributes often hold extension-less stream URLs.
    for m in re.finditer(
            r"""\b(?:data-src|data-url|data-audio(?:-src)?|data-stream(?:-url)?"""
            r"""|data-hls(?:-url)?|data-media(?:-url)?|data-file)\s*=\s*"""
            r"""["']([^"']+)["']""", text, re.I):
        value = m.group(1).strip()
        if value.lower().startswith(("http://", "https://", "//", "/", "./", "../")):
            add(value, generic)
    # Common JSON/JS keys used by unknown players. Only used as a last resort
    # so unrelated URLs on the page do not pollute the result.
    for m in re.finditer(
            r"""["'](?:audio|audio_url|audioUrl|audioURL|stream|stream_url|"""
            r"""streamUrl|streamURL|hls|hls_url|hlsUrl|hlsURL|playlist|"""
            r"""playlist_url|playlistUrl|media|media_url|mediaUrl|file|"""
            r"""contentUrl|contentURL|embedUrl|embedURL|src)["']"""
            r"""\s*[:=]\s*["']((?:https?://|//|/|\./|\.\./)[^"']+)["']""",
            text, re.I):
        add(m.group(1), generic)

    return found, generic


def find_audio_links(page_html, base_url):
    found, generic = _collect_audio_links(page_html, base_url)
    if not found:
        found.extend(generic)
    return found


def find_blob_links(page_html):
    """Collect browser-only blob: media URLs for diagnostics.

    A blob URL only exists inside the page's JavaScript session, so it cannot
    be fetched by yt-dlp. Seeing one tells us the page uses a MediaSource /
    MSE player; the real manifest is usually in the nearby scripts and is
    found by find_audio_links().
    """
    text = _normalize_scan_text(page_html)
    found = []
    for m in re.finditer(r"""blob:(?:https?://|null/)[^\s"'<>]+""", text, re.I):
        value = m.group(0).rstrip("),;")
        if value not in found:
            found.append(value)
    return found[:20]


def _canonical_embed(url):
    """Turn a known player/embed URL into a canonical page URL for yt-dlp."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    host = parsed.netloc.lower()
    path = parsed.path or ""

    if "youtube.com" in host or "youtube-nocookie.com" in host:
        m = re.search(r"/embed/([A-Za-z0-9_-]{6,})", path)
        if m:
            return "https://www.youtube.com/watch?v=" + m.group(1)
    if "youtu.be" in host:
        m = re.search(r"/([A-Za-z0-9_-]{6,})", path)
        if m:
            return "https://www.youtube.com/watch?v=" + m.group(1)
    if "soundcloud.com" in host and "/player" in path:
        params = urllib.parse.parse_qs(parsed.query)
        for value in params.get("url") or []:
            if value.startswith(("http://", "https://")):
                return value
    if "vimeo.com" in host:
        m = re.search(r"/(?:video/)?(\d+)", path)
        if m:
            return "https://vimeo.com/" + m.group(1)
    if "dailymotion.com" in host:
        m = re.search(r"/(?:embed/)?video/([A-Za-z0-9]+)", path)
        if m:
            return "https://www.dailymotion.com/video/" + m.group(1)
    return None


def find_embed_links(page_html, base_url):
    """Collect known embedded players (YouTube, SoundCloud, Vimeo, ...)."""
    text = _normalize_scan_text(page_html)
    found = []

    def add(u):
        full = urllib.parse.urljoin(base_url, u)
        if full.lower().startswith(("http://", "https://")) and full not in found:
            found.append(full)

    for m in re.finditer(
            r"""<(?:iframe|embed)\b[^>]*?\b(?:src|data-src)\s*=\s*["']([^"']+)["']""",
            text, re.I):
        canonical = _canonical_embed(m.group(1))
        if canonical:
            add(canonical)
    for m in re.finditer(
            r"""https?://(?:www\.|w\.)?(?:youtube(?:-nocookie)?\.com/embed/|"""
            r"""youtu\.be/|soundcloud\.com/player/|vimeo\.com/video/|"""
            r"""dailymotion\.com/embed/video/)[^\s"'<>\\)]+""",
            text, re.I):
        canonical = _canonical_embed(m.group(0))
        if canonical:
            add(canonical)
    return found[:10]


def _looks_like_audio_endpoint(url):
    """True for extension-less URLs that look like a player or media endpoint."""
    if is_direct_audio_url(url) or is_media_stream_url(url):
        return True
    try:
        parsed = urllib.parse.urlparse(url or "")
    except ValueError:
        return False
    haystack = urllib.parse.unquote(
        (parsed.path or "") + "?" + (parsed.query or "")).lower()
    return any(token in haystack for token in (
        "audio", "stream", "play", "listen", "download", "media",
        "song", "track", "radio", "mp3", "m4a",
    ))


def find_onion_containers(page_html, base_url):
    """Collect .onion player/iframe pages that may hold the real media URL."""
    text = _normalize_scan_text(page_html)
    found = []

    def add(u):
        full = urllib.parse.urljoin(base_url, html.unescape(str(u or "")).strip())
        if not is_onion_url(full):
            return
        if is_media_stream_url(full):
            return
        if full not in found:
            found.append(full)

    for m in re.finditer(
            r"""<(?:iframe|frame|embed)\b[^>]*?\b(?:src|data-src)\s*=\s*["']([^"']+)["']""",
            text, re.I):
        add(m.group(1))

    # Player links on onion pages are often plain <a> links rather than iframes.
    for m in re.finditer(
            r"""<a\b([^>]*)>(.*?)</a>""", text, re.I | re.S):
        attrs, label = m.group(1), m.group(2)
        label = re.sub(r"<[^>]+>", " ", label).lower()
        hint = (attrs + " " + label).lower()
        if any(word in hint for word in ("play", "listen", "stream",
                                         "download", "audio", "media")):
            match = re.search(r"""\bhref\s*=\s*["']([^"']+)["']""", attrs, re.I)
            if match:
                add(match.group(1))

    # Script-generated player/iframe URLs.
    for m in re.finditer(r"""https?://[^\s"'<>\\)]+?\.onion[^\s"'<>\\)]*""",
                         text, re.I):
        candidate = m.group(0)
        if _looks_like_audio_endpoint(candidate) and not is_media_stream_url(candidate):
            add(candidate)

    return found[:8]


class _YTDLPLogger:
    def __init__(self):
        self.lines = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        self.lines.append(str(msg))

    def error(self, msg):
        self.lines.append(str(msg))


# --------------------------------------------------------- yt-dlp updater
_UPDATE_THREAD = None
_UPDATE_LOCK = threading.Lock()
_UPDATE_FINDER = None


def _version_key(text):
    parts = re.findall(r"\d+", str(text or ""))
    return tuple(int(p) for p in parts[:4])


def _update_log(message: str) -> None:
    try:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        with open(UPDATE_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(message) + "\n")
    except OSError:
        return


proxy_manager.set_logger(_update_log)


def bundled_ytdlp_version():
    try:
        return importlib.metadata.version("yt-dlp")
    except Exception:
        pass
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:
        return "0"


def _latest_ytdlp_wheel(force=False):
    """Return (version, wheel_url, sha256) for the newest stable release."""
    if not force:
        try:
            with open(UPDATE_CACHE_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
            age = time.time() - float(cached.get("ts") or 0)
            if age < UPDATE_CHECK_INTERVAL:
                cached_url = cached.get("url") or ""
                cached_sha = cached.get("sha256") or ""
                parsed = urllib.parse.urlparse(cached_url)
                if (cached.get("version") and len(cached_sha) == 64
                        and parsed.scheme == "https"
                        and parsed.netloc == "files.pythonhosted.org"):
                    return cached["version"], cached_url, cached_sha
        except Exception:
            pass

    req = urllib.request.Request(
        PYPI_SIMPLE_URL,
        headers={**BROWSER_HEADERS,
                 "Accept": "application/vnd.pypi.simple.v1+json"},
    )
    with urlopen_ctx(req, timeout=30) as resp:
        data = json.load(resp)

    best = None
    python_version = sys.version_info[:2]
    for item in data.get("files") or []:
        if item.get("yanked"):
            continue
        name = item.get("filename") or ""
        match = re.match(r"yt_dlp-([0-9][^-]*)-py3-none-any\.whl$", name)
        if not match:
            continue
        version = match.group(1)
        low = version.lower()
        if any(tag in low for tag in (".dev", "a", "b", "rc")):
            continue
        requires = item.get("requires-python") or ""
        required = re.search(r">=\s*(\d+)\.(\d+)", requires)
        if required and python_version < (int(required.group(1)),
                                          int(required.group(2))):
            continue
        url = item.get("url") or ""
        sha = (item.get("hashes") or {}).get("sha256") or ""
        parsed = urllib.parse.urlparse(url)
        if (parsed.scheme != "https"
                or parsed.netloc != "files.pythonhosted.org" or not sha):
            continue
        key = _version_key(version)
        if best is None or key > best[0]:
            best = (key, version, url, sha)

    if not best:
        raise RuntimeError("No compatible stable yt-dlp wheel found on PyPI.")
    _, version, url, sha = best
    try:
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        with open(UPDATE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "version": version,
                       "url": url, "sha256": sha}, f)
    except Exception:
        pass
    return version, url, sha


def _prune_old_updates():
    """Keep the two newest unpacked versions and remove older leftovers."""
    try:
        names = []
        for name in os.listdir(UPDATE_VERSIONS_DIR):
            root = os.path.join(UPDATE_VERSIONS_DIR, name)
            if os.path.isfile(os.path.join(root, "yt_dlp", "__init__.py")):
                names.append(name)
        names.sort(key=_version_key, reverse=True)
        for name in names[2:]:
            shutil.rmtree(os.path.join(UPDATE_VERSIONS_DIR, name),
                          ignore_errors=True)
    except Exception:
        pass


def _install_ytdlp_wheel(version, url, sha256):
    """Download and unpack a pure-Python yt-dlp wheel into user data."""
    target = os.path.join(UPDATE_VERSIONS_DIR, version)
    if os.path.isfile(os.path.join(target, "yt_dlp", "__init__.py")):
        return target
    os.makedirs(UPDATE_VERSIONS_DIR, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".download-", dir=UPDATE_VERSIONS_DIR)
    try:
        wheel = os.path.join(tmp, "yt_dlp.whl")
        digest = hashlib.sha256()
        req = urllib.request.Request(
            url, headers={**BROWSER_HEADERS, "Accept": "*/*"})
        with urlopen_ctx(req, timeout=120) as resp, open(wheel, "wb") as f:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
        if digest.hexdigest().lower() != sha256.lower():
            raise RuntimeError("The downloaded yt-dlp update failed its checksum.")

        extract_dir = os.path.join(tmp, "package")
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(wheel) as archive:
            try:
                archive.extractall(extract_dir, filter="data")
            except TypeError:
                archive.extractall(extract_dir)
        if not os.path.isfile(os.path.join(extract_dir, "yt_dlp", "__init__.py")):
            raise RuntimeError("The downloaded yt-dlp update is incomplete.")

        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        os.replace(extract_dir, target)
        _update_log("installed yt-dlp " + version)
        _prune_old_updates()
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _latest_installed_update():
    try:
        names = os.listdir(UPDATE_VERSIONS_DIR)
    except OSError:
        return None
    best = None
    for name in names:
        root = os.path.join(UPDATE_VERSIONS_DIR, name)
        if not os.path.isfile(os.path.join(root, "yt_dlp", "__init__.py")):
            continue
        key = _version_key(name)
        if best is None or key > best[0]:
            best = (key, name, root)
    return best


class _YTDLPUpdateFinder(importlib.abc.MetaPathFinder):
    """Load yt_dlp.* from an unpacked update instead of the bundled copy."""

    def __init__(self, root):
        self.root = os.path.abspath(root)

    def find_spec(self, fullname, path=None, target=None):
        if fullname != "yt_dlp" and not fullname.startswith("yt_dlp."):
            return None
        base = os.path.join(self.root, *fullname.split("."))
        init = os.path.join(base, "__init__.py")
        if os.path.isfile(init):
            return importlib.util.spec_from_file_location(
                fullname, init, submodule_search_locations=[base])
        module = base + ".py"
        if os.path.isfile(module):
            return importlib.util.spec_from_file_location(fullname, module)
        return None


def _load_updated_ytdlp(root):
    global _UPDATE_FINDER
    old_finder = _UPDATE_FINDER
    for name in [n for n in list(sys.modules)
                 if n == "yt_dlp" or n.startswith("yt_dlp.")]:
        del sys.modules[name]
    if old_finder is not None:
        try:
            sys.meta_path.remove(old_finder)
        except ValueError:
            pass
    finder = _YTDLPUpdateFinder(root)
    sys.meta_path.insert(0, finder)
    try:
        import yt_dlp
    except Exception:
        try:
            sys.meta_path.remove(finder)
        except ValueError:
            pass
        for name in [n for n in list(sys.modules)
                     if n == "yt_dlp" or n.startswith("yt_dlp.")]:
            sys.modules.pop(name, None)
        _UPDATE_FINDER = old_finder
        if old_finder is not None:
            sys.meta_path.insert(0, old_finder)
        raise
    _UPDATE_FINDER = finder
    _update_log("loaded yt-dlp update from " + root)
    return yt_dlp


def _pip_update_ytdlp(version):
    """Use pip when running from source; frozen builds use the wheel path."""
    if getattr(sys, "frozen", False):
        return False
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade",
           "--disable-pip-version-check", "yt-dlp==" + version]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=180, creationflags=flags)
    except Exception as exc:
        _update_log("pip update failed: " + _error_text(exc))
        return False
    if proc.returncode == 0:
        _update_log("pip installed yt-dlp " + version)
        return True
    _update_log("pip update failed: "
                + (proc.stderr or proc.stdout or "")[-500:])
    return False


def _auto_update_worker():
    try:
        _update_log("checking for yt-dlp updates")
        force = os.environ.get("MP3_GRABBER_FORCE_YTDLP_UPDATE") == "1"
        latest, url, sha = _latest_ytdlp_wheel(force=force)
        current = bundled_ytdlp_version()
        if not force and _version_key(latest) <= _version_key(current):
            _update_log(f"yt-dlp {current} is up to date")
            return
        if _pip_update_ytdlp(latest):
            return
        _install_ytdlp_wheel(latest, url, sha)
    except Exception as exc:
        _update_log("update check failed: " + _error_text(exc))


def start_ytdlp_update():
    """Check for updates in the background so startup never blocks."""
    global _UPDATE_THREAD
    with _UPDATE_LOCK:
        if _UPDATE_THREAD is not None and _UPDATE_THREAD.is_alive():
            return
        _UPDATE_THREAD = threading.Thread(
            target=_auto_update_worker, name="ytdlp-update", daemon=True)
        _UPDATE_THREAD.start()


_FFMPEG_CACHE = {"checked": False, "path": None}


def ffmpeg_path():
    """System ffmpeg if available, otherwise the one bundled by imageio-ffmpeg."""
    if _FFMPEG_CACHE["checked"]:
        return _FFMPEG_CACHE["path"]
    _FFMPEG_CACHE["checked"] = True
    exe = shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg
            candidate = imageio_ffmpeg.get_ffmpeg_exe()
            if candidate and os.path.exists(candidate):
                exe = candidate
        except Exception:
            exe = None
    _FFMPEG_CACHE["path"] = exe
    return exe


def require_ytdlp():
    cached = sys.modules.get("yt_dlp")
    if cached is not None:
        return cached

    # Give the background updater a short chance to finish before the first
    # extraction. If it is slow or offline we simply use the bundled version.
    thread = _UPDATE_THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=10)

    force = os.environ.get("MP3_GRABBER_FORCE_YTDLP_UPDATE") == "1"
    update = _latest_installed_update()
    if update:
        _, version, root = update
        if force or _version_key(version) > _version_key(bundled_ytdlp_version()):
            try:
                return _load_updated_ytdlp(root)
            except Exception as exc:
                _update_log("could not load yt-dlp update: " + _error_text(exc))

    try:
        import yt_dlp
        return yt_dlp
    except Exception as exc:
        if update:
            try:
                return _load_updated_ytdlp(update[2])
            except Exception:
                pass
        raise FriendlyError(
            "A required audio component is missing.\n"
            "Reinstall SK Grabber and try again."
        ) from exc


def _reload_newer_ytdlp():
    """Switch to a downloaded update if it arrived after yt-dlp was imported."""
    if _UPDATE_FINDER is not None:
        return False
    thread = _UPDATE_THREAD
    if thread is not None and thread.is_alive():
        thread.join(timeout=15)
    update = _latest_installed_update()
    if not update:
        return False
    _, version, root = update
    force = os.environ.get("MP3_GRABBER_FORCE_YTDLP_UPDATE") == "1"
    if not force and _version_key(version) <= _version_key(bundled_ytdlp_version()):
        return False
    try:
        _load_updated_ytdlp(root)
    except Exception as exc:
        _update_log("retry update load failed: " + _error_text(exc))
        return False
    return True


def _error_text(exc):
    text = str(exc or "").strip()
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    text = re.sub(r"^ERROR:\s*", "", text, flags=re.I)
    return text or exc.__class__.__name__


def friendly_stream_error(exc):
    if isinstance(exc, FriendlyError):
        return str(exc)
    text = _error_text(exc)
    low = text.lower()
    first = text.splitlines()[0] if text else ""
    if "unsupported url" in low:
        return ("This website isn't supported yet.\n"
                "Try a direct link to the audio file instead.")
    if "drm" in low:
        return "This audio is protected by DRM and cannot be downloaded."
    if "private" in low:
        return "This audio is private. Only public links can be downloaded."
    if any(word in low for word in ("sign in", "log in", "login", "cookies", "age-restricted")):
        return ("This site is asking for a login or age confirmation.\n"
                "Public links work best.")
    if "not available" in low or "unavailable" in low or "removed" in low:
        return "This audio isn't available (removed, blocked, or region-locked)."
    if "http error 404" in low:
        return friendly_http_error(404)
    if "http error 403" in low:
        return friendly_http_error(403)
    if "http error 429" in low:
        return friendly_http_error(429)
    if "failed to parse json" in low or "jsondecodeerror" in low:
        return ("The site returned an unexpected response.\n"
                "It may be blocking this connection - try again in a moment.")
    if "timed out" in low or "timeout" in low:
        return "The connection timed out. Check your internet and try again."
    if "unable to download webpage" in low or "connection" in low or "network" in low:
        return "Could not reach the site.\nCheck your internet connection or the link."
    if "no video formats" in low or "requested format" in low or "no formats" in low:
        return "No audio stream could be found at this link."
    if "yt-dlp" in low and "install" in low:
        return ("A required audio component is missing.\n"
                "Reinstall SK Grabber and try again.")
    _update_log("extract failed: " + (first[:500] or "unknown error"))
    return ("Could not extract audio from this link.\n"
            "The site may be blocking the download, or the link may be private.")


def _final_path(info):
    if not info:
        return None
    entries = info.get("entries")
    if entries:
        last = None
        for entry in entries:
            if entry:
                last = entry
        return _final_path(last)
    downloads = info.get("requested_downloads") or []
    if downloads:
        path = downloads[0].get("filepath") or downloads[0].get("_filename")
        if path:
            return path
    return info.get("filepath") or info.get("_filename")


def _remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _cleanup_download(*paths):
    """Delete temporary fragments left by an interrupted download."""
    for path in paths:
        if not path:
            continue
        base = os.path.basename(path)
        if ".part" in base or path.lower().endswith((".ytdl", ".temp")):
            _remove(path)
        for suffix in (".part", ".ytdl", ".temp"):
            _remove(path + suffix)
        for extra in glob.glob(glob.escape(path) + ".part*"):
            _remove(extra)


def _impersonate_target():
    """Return yt-dlp's Chrome impersonation target when curl_cffi is present."""
    try:
        from curl_cffi import requests as curl_requests
        if not hasattr(curl_requests, "get"):
            return None
        from yt_dlp.networking.impersonate import ImpersonateTarget
        return ImpersonateTarget.from_str("chrome")
    except Exception:
        return None


def _make_ydl(yt_dlp, opts):
    """Create a YoutubeDL instance, retrying without impersonation if this
    yt-dlp build cannot use curl_cffi targets."""
    try:
        return yt_dlp.YoutubeDL(opts)
    except Exception as exc:
        low = str(exc).lower()
        if "impersonat" in low and ("not available" in low or "unsupported" in low):
            opts.pop("impersonate", None)
            return yt_dlp.YoutubeDL(opts)
        raise


def _apply_browser_ydl_opts(opts):
    """Apply the app-wide browser fingerprint (Chrome impersonation and a
    realistic User-Agent/Accept-Language) to a yt-dlp options dict."""
    headers = dict(BROWSER_HEADERS)
    extra = opts.get("http_headers") or {}
    headers.update(extra)
    opts["http_headers"] = headers
    if "impersonate" not in opts:
        target = _impersonate_target()
        if target is not None:
            opts["impersonate"] = target
    return opts


def is_media_stream_url(url):
    """True for URLs ffmpeg can consume directly (audio/HLS/DASH)."""
    try:
        path = urllib.parse.unquote(urllib.parse.urlparse(url).path).lower()
    except ValueError:
        return False
    ext = os.path.splitext(path)[1]
    return ext in (AUDIO_EXTS | {".m3u8", ".mpd", ".webm", ".mp4"})


def ffmpeg_direct_download(url, folder, q, cancel, referer=None, out_name=None,
                           proxy=None):
    """Last-resort direct fetch with ffmpeg for audio/HLS/DASH URLs.

    HTTP(S) proxies from the free pool can be used through ffmpeg's
    -http_proxy option; ffmpeg cannot talk SOCKS, so those are ignored here
    (yt-dlp handles SOCKS proxies)."""
    exe = ffmpeg_path()
    if not exe:
        raise FriendlyError("Audio conversion isn't available. Reinstall SK Grabber and try again.")
    os.makedirs(folder, exist_ok=True)

    if out_name:
        stem = out_name
    else:
        stem = urllib.parse.unquote(os.path.basename(urllib.parse.urlparse(url).path))
        stem = os.path.splitext(stem)[0] or "audio"
    dest = unique_path(folder, clean_filename(stem)[:150] + ".mp3")
    part = dest + ".part.mp3"

    q.put(("status", "Preparing the audio..."))
    q.put(("start", os.path.basename(dest), 0))
    cmd = [
        exe, "-nostdin", "-y", "-loglevel", "error",
        "-user_agent", USER_AGENT,
        "-headers", f"Accept-Language: {BROWSER_HEADERS['Accept-Language']}\r\n",
    ]
    if referer:
        cmd += ["-referer", referer]
    if str(proxy or "").startswith("http://"):
        cmd += ["-http_proxy", str(proxy)]
    cmd += ["-i", url, "-vn", "-acodec", "libmp3lame", "-q:a", "0", part]

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    err_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=err_file, creationflags=flags,
        )
        while proc.poll() is None:
            if cancel.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                _remove(part)
                raise DownloadCancelled()
            time.sleep(0.2)
        err_file.seek(0)
        detail = err_file.read()[-1500:].strip()
    finally:
        err_file.close()

    if proc.returncode != 0 or not os.path.exists(part) or os.path.getsize(part) == 0:
        _remove(part)
        _update_log("stream download failed: " + (detail[-1000:] or "unknown error"))
        raise FriendlyError(
            "This stream could not be downloaded.\n"
            "Try again, or use a direct audio link.")

    os.replace(part, dest)
    return dest


def convert_to_mp3(path, q, cancel):
    """Convert a downloaded direct-audio file to MP3 and remove the original."""
    if os.path.splitext(path)[1].lower() == ".mp3":
        return path
    exe = ffmpeg_path()
    if not exe:
        return path
    folder = os.path.dirname(path)
    base = os.path.splitext(os.path.basename(path))[0]
    dest = unique_path(folder, clean_filename(base)[:150] + ".mp3")
    part = dest + ".part.mp3"
    q.put(("status", "Converting to MP3..."))
    cmd = [
        exe, "-nostdin", "-y", "-loglevel", "error", "-i", path,
        "-vn", "-map_metadata", "0", "-acodec", "libmp3lame", "-q:a", "0", part,
    ]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    err_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=err_file, creationflags=flags,
        )
        while proc.poll() is None:
            if cancel.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                _remove(part)
                _remove(path)
                raise DownloadCancelled()
            time.sleep(0.2)
        err_file.seek(0)
        detail = err_file.read()[-1000:].strip()
    finally:
        err_file.close()

    if proc.returncode != 0 or not os.path.exists(part) or os.path.getsize(part) == 0:
        _remove(part)
        _update_log("MP3 conversion failed for " + path + ": " + detail[-500:])
        return path
    os.replace(part, dest)
    _remove(path)
    return dest


def _impersonated_file_download(url, folder, q, cancel, referer=None, out_name=None):
    """Download a direct audio file with curl_cffi's Chrome impersonation.

    Rescues media files that reject plain requests with 401/403/Cloudflare
    checks but still serve the file to a real browser fingerprint."""
    from curl_cffi import requests as curl_requests
    os.makedirs(folder, exist_ok=True)
    headers = dict(BROWSER_HEADERS)
    headers["Accept"] = "*/*"
    if referer:
        headers["Referer"] = referer

    if out_name:
        guess = clean_filename(out_name)[:150]
    else:
        url_name = urllib.parse.unquote(
            os.path.basename(urllib.parse.urlparse(url).path))
        guess = clean_filename(url_name or "audio")
    part = os.path.join(folder, ".sk_grabber.part")
    done = 0
    total = 0
    speed = 0.0
    last_t = time.time()
    last_done = 0
    ctype = ""
    q.put(("status", "Retrying the download..."))
    resp = None
    try:
        resp = curl_requests.get(url, headers=headers, impersonate="chrome",
                                 timeout=30, allow_redirects=True, stream=True)
        if resp.status_code >= 400:
            raise FriendlyError(friendly_http_error(resp.status_code))
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        total = int(resp.headers.get("Content-Length") or 0)
        q.put(("start", os.path.basename(guess), total))
        with open(part, "wb") as f:
            for chunk in resp.iter_content(64 * 1024):
                if cancel.is_set():
                    raise DownloadCancelled()
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last_t >= 0.2:
                    inst = (done - last_done) / (now - last_t)
                    speed = inst if speed == 0 else speed * 0.7 + inst * 0.3
                    last_t, last_done = now, done
                    q.put(("progress", done, total, speed))
    except DownloadCancelled:
        _remove(part)
        raise
    except Exception:
        _remove(part)
        raise
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:
                pass

    if done == 0:
        _remove(part)
        raise FriendlyError("The server returned an empty file.")
    ext = os.path.splitext(guess)[1].lower()
    if ext not in AUDIO_EXTS:
        ext = CTYPE_TO_EXT.get(ctype, ".mp3")
        guess = os.path.splitext(guess)[0] + ext
    dest = unique_path(folder, guess)
    os.replace(part, dest)
    q.put(("progress", done, total or done, 0))
    if os.path.splitext(dest)[1].lower() != ".mp3":
        return convert_to_mp3(dest, q, cancel)
    return dest


def stream_download(url, folder, q, cancel, referer=None, out_name=None, proxy=None,
                    force_generic=False):
    """Download the best audio from a URL with yt-dlp and return the file path.

    proxy may be a free-proxy URL from the app's pool; onion URLs always route
    through Tor instead. Site-specific extractors are never used for .onion
    URLs, and force_generic is used for direct media URLs discovered on onion
    pages.
    """
    yt_dlp = require_ytdlp()
    os.makedirs(folder, exist_ok=True)
    ffmpeg = ffmpeg_path()

    use_tor = is_onion_url(url) or is_onion_url(referer)
    if use_tor:
        proxy = ensure_tor()
    original_url = url
    attempts = [url]
    if is_onion_url(url):
        normalized = _onion_http_url(url)
        attempts = [normalized]
        if normalized != url:
            attempts.append(url)

    if out_name:
        stem = clean_filename(out_name)[:150].replace("%", "%%")
        template = os.path.join(folder, stem + ".%(ext)s")
    else:
        template = os.path.join(folder, "%(title,id).150B.%(ext)s")

    state = {"started": False, "last": 0.0, "file": None, "tmp": None}

    def hook(d):
        if d.get("filename"):
            state["file"] = d["filename"]
        if d.get("tmpfilename"):
            state["tmp"] = d["tmpfilename"]
        if cancel.is_set():
            raise DownloadCancelled()
        status = d.get("status")
        if status == "downloading":
            info = d.get("info_dict") or {}
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            speed = d.get("speed") or 0
            if not state["started"]:
                state["started"] = True
                display = os.path.basename(out_name) if out_name else (info.get("title") or "audio")
                q.put(("start", display, total))
            now = time.time()
            if now - state["last"] >= 0.15:
                state["last"] = now
                q.put(("progress", done, total, speed))
        elif status == "finished":
            total = d.get("total_bytes") or 0
            done = d.get("downloaded_bytes") or total
            q.put(("progress", done, total, 0))
            q.put(("status", "Converting to MP3..." if ffmpeg else "Finishing..."))

    logger = _YTDLPLogger()
    opts = {
        "format": "bestaudio/best",
        "outtmpl": template,
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "continuedl": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 20,
        "windowsfilenames": True,
        "trim_file_name": 180,
        "progress_hooks": [hook],
        "logger": logger,
    }
    headers = dict(BROWSER_HEADERS)
    if referer:
        headers["Referer"] = referer
    opts["http_headers"] = headers
    if is_onion_url(original_url) or force_generic:
        opts["force_generic_extractor"] = True
    if use_tor:
        # curl_cffi impersonation can conflict with a SOCKS proxy, and native
        # HLS keeps every fragment inside Tor instead of handing ffmpeg a URL.
        opts["hls_prefer_native"] = True
    else:
        opts = _apply_browser_ydl_opts(opts)
    if proxy:
        opts["proxy"] = proxy
        opts["nocheckcertificate"] = True
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"},
            {"key": "FFmpegMetadata", "add_metadata": True},
        ]
    else:
        opts["format"] = ("bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[ext=ogg]/"
                          "bestaudio[ext=opus]/bestaudio/best")

    try:
        info = None
        last_exc = None
        for attempt_url in attempts:
            try:
                with _make_ydl(yt_dlp, opts) as ydl:
                    info = ydl.extract_info(attempt_url, download=True)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                _cleanup_download(state["tmp"], state["file"])
                if cancel.is_set():
                    raise DownloadCancelled()
                if len(attempts) > 1:
                    state.update(started=False, last=0.0, file=None, tmp=None)
                    continue
        if last_exc is not None:
            # Some HLS/DASH endpoints fail yt-dlp's parser but are easy for
            # ffmpeg. Do not use this for onion URLs: ffmpeg has no SOCKS support.
            if is_media_stream_url(original_url) and not use_tor:
                try:
                    return ffmpeg_direct_download(
                        original_url, folder, q, cancel, referer=referer,
                        out_name=out_name, proxy=proxy)
                except DownloadCancelled:
                    raise
                except Exception as ffmpeg_exc:
                    _update_log("ffmpeg fallback failed: " + _error_text(ffmpeg_exc))
            raise last_exc
    except Exception:
        _cleanup_download(state["tmp"], state["file"])
        raise

    if cancel.is_set():
        _cleanup_download(state["tmp"], state["file"])
        raise DownloadCancelled()

    path = _final_path(info)
    if path and os.path.exists(path):
        return path
    if state["file"] and os.path.exists(state["file"]):
        return state["file"]
    if state["file"]:
        stem = os.path.splitext(state["file"])[0]
        for ext in (".mp3", ".m4a", ".opus", ".ogg", ".wav", ".webm"):
            if os.path.exists(stem + ext):
                return stem + ext
    return path or state["file"] or folder


_PROXY_RETRY_HINTS = (
    "timed out", "timeout", "timedout", "connection", "connect", "refused",
    "reset", "unreachable", "temporary failure", "network", "ssl",
    "certificate", "http error 403", "http error 429", "http error 451",
    "http error 500", "http error 502", "http error 503", "http error 504",
    "captcha", "cloudflare", "blocked", "region", "geo", "json",
    "failed to parse", "empty response", "unable to download",
)


def _proxy_retry_worthwhile(exc):
    """True when an error looks like a network/geo block a proxy could fix."""
    text = _error_text(exc).lower()
    return any(hint in text for hint in _PROXY_RETRY_HINTS)


def download_with_fallback(url, folder, q, cancel, referer=None, out_name=None):
    """Download directly; when a network/geo failure happens and the free
    proxy toggle is on, retry through validated public proxies."""
    if is_onion_url(url) or is_onion_url(referer):
        q.put(("status", "Connecting privately..."))
        return _onion_candidate_download(
            url, folder, q, cancel, referer=referer, out_name=out_name)
    try:
        return stream_download(url, folder, q, cancel, referer=referer,
                               out_name=out_name)
    except DownloadCancelled:
        raise
    except Exception as direct_exc:
        if not _proxy_enabled() or not _proxy_retry_worthwhile(direct_exc):
            raise
        q.put(("status", "Trying another route..."))
        proxies = _proxy_candidates(3)
        last_exc = direct_exc
        for index, proxy in enumerate(proxies, 1):
            if cancel.is_set():
                raise DownloadCancelled()
            q.put(("status", "Retrying..."))
            try:
                return stream_download(url, folder, q, cancel, referer=referer,
                                       out_name=out_name, proxy=proxy)
            except DownloadCancelled:
                raise
            except Exception as proxy_exc:
                last_exc = proxy_exc
                if cancel.is_set():
                    raise DownloadCancelled()
        raise last_exc


def _page_fallback(url, folder, q, cancel):
    """Last resort: scan the page itself for plain audio links."""
    if cancel.is_set():
        return False
    try:
        q.put(("status", "Searching this page for audio..."))
        page, final_url = fetch_page(url, limit=3 * 1024 * 1024)
        candidates = collapse_candidates(find_audio_links(page, final_url))
        if not candidates:
            candidates = find_embed_links(page, final_url)
        blobs = find_blob_links(page)
    except FriendlyError as exc:
        q.put(("error", str(exc)))
        return True
    except Exception:
        return False
    if not candidates:
        if blobs:
            q.put(("error",
                   "This page only plays audio inside a browser player, so the "
                   "link can't be downloaded directly.\n"
                   "Try a direct audio link, or the site's official player."))
            return True
        return False
    if len(candidates) == 1:
        download_candidate(candidates[0], folder, q, cancel, referer=final_url)
    else:
        q.put(("choose", candidates, final_url))
    return True


# ------------------------------------------------------------ onion handling
_CHOICE_PENDING = object()


class _OnionPageResponse(Exception):
    """An onion media URL actually returned HTML/JSON; scan it as a page."""

    def __init__(self, url, page_html):
        super().__init__("page response")
        self.url = url
        self.page_html = page_html


class _OnionStreamPlaylist(Exception):
    """The media URL turned out to be an HLS/DASH manifest."""

    def __init__(self, url):
        super().__init__("stream playlist")
        self.url = url


def _dedupe(urls):
    found = []
    for url in urls:
        if url and url not in found:
            found.append(url)
    return found


def _is_stream_manifest_url(url):
    try:
        path = urllib.parse.unquote(urllib.parse.urlparse(url).path).lower()
    except ValueError:
        return False
    return os.path.splitext(path)[1] in (".m3u8", ".mpd")


def _download_onion_file(url, folder, q, cancel, referer=None, out_name=None):
    """Stream a direct media file through Tor, then convert it to MP3.

    This bypasses yt-dlp entirely for .onion media links: no site-specific
    extractor is ever consulted, and no DNS/HTTP request can escape the Tor
    SOCKS proxy.
    """
    requests = _load_requests()
    _disable_insecure_warnings()
    proxy = ensure_tor()
    os.makedirs(folder, exist_ok=True)
    headers = dict(BROWSER_HEADERS)
    headers["Accept"] = "*/*"
    if referer:
        headers["Referer"] = referer

    session = requests.Session()
    part = None
    dest = None
    try:
        with session.get(
            url, headers=headers,
            proxies={"http": proxy, "https": proxy},
            timeout=30, verify=not is_onion_url(url),
            allow_redirects=True, stream=True,
        ) as resp:
            if resp.status_code >= 400:
                raise FriendlyError(friendly_http_error(resp.status_code))

            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            ctype_low = ctype.lower()
            if any(token in ctype_low for token in (
                    "mpegurl", "dash+xml")):
                raise _OnionStreamPlaylist(str(resp.url or url))
            if (ctype in ("text/html", "application/xhtml+xml")
                    or ctype.startswith("text/")
                    or ctype in ("application/json", "application/xml")
                    or ctype.endswith("+json") or ctype.endswith("+xml")):
                chunks = []
                size = 0
                for chunk in resp.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= 2 * 1024 * 1024:
                        break
                raw = b"".join(chunks)
                page_html = _decode_page(raw, resp.encoding, 2 * 1024 * 1024)
                raise _OnionPageResponse(str(resp.url or url), page_html)

            url_name = urllib.parse.unquote(
                os.path.basename(urllib.parse.urlparse(resp.url or url).path))
            guess = out_name or filename_from_headers(resp.headers) or url_name or "audio"
            guess = clean_filename(guess)[:150]
            ext = os.path.splitext(guess)[1].lower()
            ctype_ext = CTYPE_TO_EXT.get(ctype)
            if not ctype_ext and ctype_low.startswith("video/"):
                ctype_ext = {"video/mp4": ".mp4", "video/webm": ".webm"}.get(ctype_low)
            if ext not in (AUDIO_EXTS | {".mp4", ".webm"}):
                ext = ctype_ext or ".mp3"
                guess = (os.path.splitext(guess)[0] or "audio") + ext
            elif ext not in AUDIO_EXTS and ext not in (".mp4", ".webm"):
                guess = (os.path.splitext(guess)[0] or "audio") + ".mp3"

            dest = unique_path(folder, guess)
            part = dest + ".part"
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            q.put(("start", os.path.basename(dest), total))

            done = 0
            last_t = time.time()
            last_done = 0
            speed = 0.0
            with open(part, "wb") as handle:
                for chunk in resp.iter_content(64 * 1024):
                    if cancel.is_set():
                        raise DownloadCancelled()
                    if not chunk:
                        continue
                    handle.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last_t >= 0.2:
                        inst = (done - last_done) / (now - last_t)
                        speed = inst if speed == 0 else speed * 0.7 + inst * 0.3
                        last_t, last_done = now, done
                        q.put(("progress", done, total, speed))

        if cancel.is_set():
            raise DownloadCancelled()
        if total and done < total:
            raise FriendlyError("The connection was cut before the file finished downloading.")
        if done == 0:
            raise FriendlyError("The server returned an empty file.")
        os.replace(part, dest)
        q.put(("progress", done, total or done, 0))
        if os.path.splitext(dest)[1].lower() != ".mp3":
            return convert_to_mp3(dest, q, cancel)
        return dest
    except (DownloadCancelled, FriendlyError, _OnionPageResponse,
            _OnionStreamPlaylist):
        _remove(part)
        raise
    except Exception as exc:
        _remove(part)
        _update_log("tor media download failed: " + _error_text(exc)[:500])
        raise FriendlyError(
            "Could not download this audio through Tor.\n"
            "Try again in a moment."
        ) from exc
    finally:
        try:
            session.close()
        except Exception:
            pass


def _download_onion_stream(url, folder, q, cancel, referer=None, out_name=None):
    """Download an HLS/DASH manifest through Tor using yt-dlp's generic path."""
    q.put(("status", "Preparing the stream..."))
    return stream_download(
        url, folder, q, cancel, referer=referer, out_name=out_name,
        proxy=ensure_tor(), force_generic=True)


def _download_onion_media(url, folder, q, cancel, referer=None, out_name=None):
    """Fetch one media URL from an onion page without site extractors."""
    if _is_stream_manifest_url(url):
        return _download_onion_stream(
            url, folder, q, cancel, referer=referer, out_name=out_name)

    # Most onion services speak plain HTTP. Try that first, then the original
    # HTTPS form, while still keeping all traffic inside Tor.
    targets = [url]
    if is_onion_url(url):
        normalized = _onion_http_url(url)
        if normalized != url:
            targets = [normalized, url]
    last_exc = None
    for target in targets:
        try:
            return _download_onion_file(
                target, folder, q, cancel, referer=referer, out_name=out_name)
        except _OnionStreamPlaylist:
            return _download_onion_stream(
                target, folder, q, cancel, referer=referer, out_name=out_name)
        except (_OnionPageResponse, DownloadCancelled):
            raise
        except FriendlyError as exc:
            last_exc = exc
    raise last_exc


def _scan_onion_page(url, cancel, depth=0, seen=None, page_html=None,
                     final_url=None, referer=None):
    """Fetch and scan an onion page tree for embedded media links.

    Only onion pages are fetched recursively. Known clearnet embeds are kept
    separately so yt-dlp can handle them through the Tor proxy.
    """
    seen = seen if seen is not None else set()
    if cancel.is_set():
        raise DownloadCancelled()
    if url in seen:
        return {"media": [], "embeds": [], "blobs": [], "base": final_url or url}
    seen.add(url)

    if page_html is None:
        page_html, final_url = fetch_page(
            url, referer=referer, limit=6 * 1024 * 1024)
    final_url = final_url or url
    seen.add(final_url)

    media, generic = _collect_audio_links(page_html, final_url)
    containers = find_onion_containers(page_html, final_url)
    embeds = find_embed_links(page_html, final_url)
    blobs = find_blob_links(page_html)

    media = list(media)
    for candidate in generic:
        if candidate in media or candidate in containers:
            continue
        if _looks_like_audio_endpoint(candidate):
            media.append(candidate)
        elif is_onion_url(candidate):
            containers.append(candidate)

    # A <video src="youtube.com/embed/..."> is a player, not a media file.
    direct_media = []
    for candidate in _dedupe(media):
        canonical = _canonical_embed(candidate)
        if canonical:
            embeds.append(canonical)
        else:
            direct_media.append(candidate)
    media = direct_media
    containers = _dedupe(containers)
    embeds = _dedupe(embeds)
    blobs = _dedupe(blobs)
    _update_log(
        f"onion scan: {len(media)} media, {len(embeds)} embeds, "
        f"{len(containers)} containers, {len(blobs)} blobs")

    if not media and depth < 2 and len(seen) < 8:
        for container in containers[:3]:
            if container in seen:
                continue
            try:
                sub = _scan_onion_page(
                    container, cancel, depth=depth + 1, seen=seen,
                    referer=final_url)
            except DownloadCancelled:
                raise
            except Exception as exc:
                _update_log("onion container scan failed: " + _error_text(exc)[:300])
                continue
            media.extend(sub["media"])
            embeds.extend(sub["embeds"])
            blobs.extend(sub["blobs"])

    return {
        "media": _dedupe(media),
        "embeds": _dedupe(embeds),
        "blobs": _dedupe(blobs),
        "base": final_url,
    }


def _onion_page_download(url, folder, q, cancel, referer=None, out_name=None,
                         depth=0, seen=None, page_html=None, final_url=None):
    """Download audio from an onion web page by scanning its raw HTML."""
    q.put(("status", "Searching this page for audio..."))
    scan = _scan_onion_page(
        url, cancel, depth=depth, seen=seen, page_html=page_html,
        final_url=final_url, referer=referer)
    media = _dedupe(collapse_candidates(scan["media"]))
    embeds = scan["embeds"]

    if media:
        if len(media) == 1:
            try:
                return _download_onion_media(
                    media[0], folder, q, cancel, referer=scan["base"],
                    out_name=out_name)
            except _OnionPageResponse as page_response:
                if depth < 2 and page_response.url not in (seen or set()):
                    return _onion_page_download(
                        page_response.url, folder, q, cancel,
                        referer=scan["base"], out_name=out_name,
                        depth=depth + 1, seen=seen,
                        page_html=page_response.page_html,
                        final_url=page_response.url)
                raise FriendlyError(
                    "That link opens another web page instead of an audio file.\n"
                    "Try a direct link to the audio file.")
        q.put(("choose", media, scan["base"]))
        return _CHOICE_PENDING

    if embeds:
        if len(embeds) == 1:
            q.put(("status", "Preparing the player..."))
            return stream_download(
                embeds[0], folder, q, cancel, referer=scan["base"],
                proxy=ensure_tor())
        q.put(("choose", embeds, scan["base"]))
        return _CHOICE_PENDING

    if scan["blobs"]:
        raise FriendlyError(
            "This page only plays audio inside a browser-only player, so the "
            "stream can't be fetched directly.\n"
            "Try a direct link to the audio file, or the site's official player.")
    raise FriendlyError(
        "No downloadable audio was found on this .onion page.\n"
        "The player may build its stream inside a script. "
        "Try a direct link to the audio file.")


def _onion_candidate_download(url, folder, q, cancel, referer=None, out_name=None):
    """Route a link found on/for an onion page without using site extractors."""
    direct = is_direct_audio_url(url) or is_media_stream_url(url)
    if not direct and is_onion_url(url):
        direct = _looks_like_audio_endpoint(url)
    if direct:
        try:
            return _download_onion_media(
                url, folder, q, cancel, referer=referer, out_name=out_name)
        except _OnionPageResponse as page_response:
            if is_onion_url(page_response.url) or is_onion_url(url):
                return _onion_page_download(
                    page_response.url, folder, q, cancel,
                    referer=referer, out_name=out_name,
                    page_html=page_response.page_html,
                    final_url=page_response.url)
            raise FriendlyError(
                "That link opens another web page instead of an audio file.\n"
                "Try a direct link to the audio file.")
    if is_onion_url(url):
        return _onion_page_download(
            url, folder, q, cancel, referer=referer, out_name=out_name)
    q.put(("status", "Preparing the player..."))
    return stream_download(
        url, folder, q, cancel, referer=referer, proxy=ensure_tor())


def onion_worker(url, folder, q, cancel, referer=None):
    """Private .onion pipeline: raw page scan first, no yt-dlp site extractors."""
    try:
        q.put(("status", "Connecting privately..."))
        path = _onion_candidate_download(
            url, folder, q, cancel, referer=referer)
        if path is _CHOICE_PENDING:
            return
        if cancel.is_set():
            q.put(("cancelled",))
            return
        q.put(("done", path or folder))
    except DownloadCancelled:
        q.put(("cancelled",))
    except Exception as exc:
        if cancel.is_set():
            q.put(("cancelled",))
            return
        q.put(("error", friendly_stream_error(exc)))


def stream_worker(url, folder, q, cancel, referer=None):
    if is_audiomack_url(url):
        audiomack_worker(url, folder, q, cancel)
        return
    if is_onion_url(url) or is_onion_url(referer):
        # Never send an onion page through yt-dlp's site extractors. Fetch the
        # raw HTML through Tor and download the embedded media directly.
        onion_worker(url, folder, q, cancel, referer=referer)
        return
    try:
        q.put(("status", "Finding the audio..."))
        path = download_with_fallback(url, folder, q, cancel, referer)
        if cancel.is_set():
            q.put(("cancelled",))
            return
        q.put(("done", path or folder))
    except DownloadCancelled:
        q.put(("cancelled",))
    except Exception as exc:
        if cancel.is_set():
            q.put(("cancelled",))
            return
        if _reload_newer_ytdlp():
            q.put(("status", "Retrying..."))
            try:
                path = download_with_fallback(url, folder, q, cancel, referer)
                if cancel.is_set():
                    q.put(("cancelled",))
                    return
                q.put(("done", path or folder))
                return
            except DownloadCancelled:
                q.put(("cancelled",))
                return
            except Exception as retry_exc:
                exc = retry_exc
        if _page_fallback(url, folder, q, cancel):
            return
        q.put(("error", friendly_stream_error(exc)))


def download_candidate(url, folder, q, cancel, referer=None):
    """Download one link chosen by the page scanner (direct or streaming)."""
    use_tor = is_onion_url(url) or is_onion_url(referer)
    if is_direct_audio_url(url) and not use_tor:
        download_worker(url, folder, q, cancel, referer=referer, allow_page=False)
        return
    try:
        path = download_with_fallback(url, folder, q, cancel, referer=referer)
        if path is _CHOICE_PENDING:
            return
        if cancel.is_set():
            q.put(("cancelled",))
            return
        q.put(("done", path or folder))
    except DownloadCancelled:
        q.put(("cancelled",))
    except Exception as exc:
        q.put(("error", friendly_stream_error(exc)))


# ---------------------------------------------------------------- spotify
def resolve_spotify_url(url):
    """Expand spotify.link / spotify.app.link share links."""
    if not SPOTIFY_SHORT_RE.search(url):
        return url
    try:
        req = urllib.request.Request(url, headers=dict(BROWSER_HEADERS))
        with urlopen_ctx(req, timeout=15) as resp:
            return resp.geturl() or url
    except Exception:
        return url


def _spotify_entity(url):
    url = resolve_spotify_url(url)
    match = SPOTIFY_URL_RE.search(url)
    if not match:
        raise FriendlyError(
            "Could not open this Spotify link.\n"
            "Paste the full track, album, or playlist link instead."
        )
    kind = match.group(1).lower()
    if kind in ("episode", "show", "artist"):
        raise FriendlyError(
            "Spotify artist and podcast pages aren't supported yet.\n"
            "Paste a music track, album, or playlist link."
        )
    embed_url = f"https://open.spotify.com/embed/{kind}/{match.group(2)}"
    try:
        page, _ = fetch_page(embed_url, limit=2 * 1024 * 1024)
    except Exception as exc:
        raise FriendlyError(
            "Could not read this Spotify link.\n"
            "Check your internet connection and make sure the link is public."
        ) from exc

    entity = None
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            entity = (data.get("props", {})
                      .get("pageProps", {})
                      .get("state", {})
                      .get("data", {})
                      .get("entity"))
        except (ValueError, KeyError, TypeError):
            entity = None

    # Fallback for single tracks if the embed layout changes again.
    if not entity or not (entity.get("title") or entity.get("trackList")):
        try:
            oembed_url = ("https://open.spotify.com/oembed?url="
                          + urllib.parse.quote(url, safe=""))
            raw, _ = fetch_page(oembed_url, limit=256 * 1024)
            oembed = json.loads(raw)
            title = (oembed.get("title") or "").strip()
            if title:
                entity = {"title": title, "subtitle": "", "artists": []}
        except Exception:
            pass

    if not entity:
        raise FriendlyError(
            "Could not read this Spotify link.\n"
            "Make sure it is a public track, album, or playlist."
        )
    return kind, entity


def _spotify_duration(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return value / 1000.0 if value > 1000 else value


def _spotify_artists(entity):
    names = [a.get("name") for a in entity.get("artists") or [] if a.get("name")]
    return ", ".join(names) or (entity.get("subtitle") or "")


def spotify_tracks(url):
    kind, entity = _spotify_entity(url)
    if kind == "track":
        title = (entity.get("title") or entity.get("name") or "").strip()
        if not title:
            raise FriendlyError("Could not read the track name from this Spotify link.")
        return kind, [{
            "title": title,
            "artist": _spotify_artists(entity).strip(),
            "duration": _spotify_duration(entity.get("duration")),
        }]

    tracks = []
    for item in entity.get("trackList") or []:
        if item.get("entityType") not in (None, "track"):
            continue
        title = (item.get("title") or "").strip()
        if not title:
            continue
        tracks.append({
            "title": title,
            "artist": (item.get("subtitle") or "").strip(),
            "duration": _spotify_duration(item.get("duration")),
        })
        if len(tracks) >= SPOTIFY_MAX_TRACKS:
            break
    if not tracks:
        raise FriendlyError(
            "No tracks were found in this Spotify link.\n"
            "Make sure it is public and contains music tracks."
        )
    return kind, tracks


# ------------------------------------------------- Apple Music / DRM metadata
def _json_nodes(value):
    """Yield every dict/list node inside a parsed JSON document."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_nodes(child)


def _json_ld_documents(page_html):
    for match in re.finditer(
            r"""<script[^>]+type\s*=\s*["']application/ld\+json[^"']*["'][^>]*>"""
            r"""(.*?)</script>""", page_html, re.I | re.S):
        raw = html.unescape(match.group(1).strip())
        raw = re.sub(r"^\s*(?://)?\s*<!\[CDATA\[", "", raw)
        raw = re.sub(r"\]\]>\s*$", "", raw).strip()
        try:
            yield json.loads(raw)
        except (ValueError, TypeError):
            continue


def _name_of(value):
    if isinstance(value, str):
        return html.unescape(value).strip()
    if isinstance(value, dict):
        return _name_of(value.get("name") or value.get("title"))
    if isinstance(value, list):
        names = []
        for item in value:
            name = _name_of(item)
            if name and name not in names:
                names.append(name)
        return ", ".join(names)
    return ""


def _duration_seconds(value):
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    match = re.match(
        r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$",
        text, re.I,
    )
    if not match:
        return 0.0
    days, hours, minutes, seconds = match.groups()
    return (int(days or 0) * 86400 + int(hours or 0) * 3600
            + int(minutes or 0) * 60 + float(seconds or 0))


def _json_track(obj, default_artist=""):
    if not isinstance(obj, dict):
        return None
    if isinstance(obj.get("item"), dict):
        obj = obj["item"]
    title = _name_of(obj.get("name") or obj.get("title") or obj.get("trackName"))
    artist = _name_of(obj.get("byArtist") or obj.get("artist")
                      or obj.get("artists") or obj.get("author"))
    audio = obj.get("audio")
    if isinstance(audio, dict):
        title = title or _name_of(audio.get("name"))
        artist = artist or _name_of(audio.get("byArtist") or audio.get("artist"))
    duration = _duration_seconds(obj.get("duration") or obj.get("timeRequired"))
    if not duration and isinstance(audio, dict):
        duration = _duration_seconds(audio.get("duration"))
    if not duration:
        for key in ("durationInMillis", "durationMs", "trackTimeMillis"):
            try:
                millis = float(obj.get(key) or 0)
            except (TypeError, ValueError):
                millis = 0
            if millis > 0:
                duration = millis / 1000.0
                break
    artist = artist or default_artist
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return None
    return {"title": title[:300], "artist": artist[:300], "duration": duration}


def _tracks_from_json_ld(page_html, default_artist=""):
    tracks = []

    def add(track, fallback_artist=""):
        if not track:
            return
        if not track.get("artist"):
            track["artist"] = fallback_artist
        title_key = track["title"].casefold()
        for existing in tracks:
            if existing["title"].casefold() != title_key:
                continue
            if (existing.get("artist") and track.get("artist")
                    and existing["artist"].casefold() != track["artist"].casefold()):
                continue
            if not existing.get("artist"):
                existing["artist"] = track.get("artist") or ""
            if not existing.get("duration"):
                existing["duration"] = track.get("duration") or 0.0
            return
        tracks.append(track)

    for document in _json_ld_documents(page_html):
        for node in _json_nodes(document):
            if not isinstance(node, dict):
                continue
            node_type = node.get("@type")
            if isinstance(node_type, list):
                node_type = " ".join(str(part) for part in node_type)
            node_type = str(node_type or "")
            if "MusicRecording" in node_type or "MusicComposition" in node_type:
                add(_json_track(node, default_artist))
            elif "MusicAlbum" in node_type or "MusicPlaylist" in node_type:
                album_artist = (_name_of(node.get("byArtist") or node.get("artist"))
                                or default_artist)
                items = node.get("tracks") or node.get("track") or []
                if isinstance(items, dict):
                    items = [items]
                for item in items if isinstance(items, list) else []:
                    add(_json_track(item, album_artist), album_artist)
            if len(tracks) >= MAX_METADATA_TRACKS:
                return tracks
    return tracks


def _meta_content(page_html, key):
    key_re = re.escape(key)
    for tag in re.findall(r"<meta\b[^>]*>", page_html, re.I):
        if re.search(r"""(?:property|name|itemprop)\s*=\s*["']"""
                     + key_re + r"""["']""", tag, re.I):
            match = re.search(r"""\bcontent\s*=\s*["']([^"']*)["']""", tag, re.I | re.S)
            if match:
                return html.unescape(match.group(1)).strip()
    return ""


def _page_title(page_html):
    match = re.search(r"<title[^>]*>(.*?)</title>", page_html, re.I | re.S)
    if not match:
        return ""
    title = re.sub(r"<[^>]+>", " ", match.group(1))
    return re.sub(r"\s+", " ", html.unescape(title)).strip()


def _split_title_artist(title, description=""):
    title = html.unescape(str(title or ""))
    title = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", title)
    title = re.sub(r"\s+", " ", title).strip()
    description = re.sub(r"\s+", " ", html.unescape(str(description or ""))).strip()
    service = r"(?:Apple Music|Spotify|TIDAL|Deezer|Amazon Music|YouTube Music)"
    on_marker = bool(re.search(r"\s+on\s+" + service + r"\s*$", title, re.I))
    song_by_marker = bool(re.search(r"\bsong\s+by\b", title, re.I))
    title = re.sub(r"\s*[-–—|]\s*" + service + r"\s*$", "", title, flags=re.I)
    title = re.sub(r"\s+on\s+" + service + r"\s*$", "", title, flags=re.I)
    title = re.sub(r"^\s*(?:Listen to|Stream)\s+", "", title, flags=re.I)

    artist = ""
    match = None
    if song_by_marker:
        match = re.search(
            r"^(?P<title>.+?)\s+-\s+(?:song\s+)?by\s+(?P<artist>.+?)"
            r"(?:\s+on\s+.*)?$", title, re.I,
        )
    if not match and on_marker:
        # Greedy title so a song such as "Stand by Me" keeps its full name.
        match = re.search(
            r"^(?P<title>.+)\s+(?:song\s+)?by\s+(?P<artist>.+?)"
            r"(?:\s+on\s+.*)?$", title, re.I,
        )
    if match:
        title = match.group("title").strip(" -–—")
        artist = match.group("artist").strip(" -–—")
    elif description:
        match = re.search(
            r"\b(?:listen to|stream)\s+(?P<title>.+)\s+by\s+(?P<artist>.+?)"
            r"(?:\s+on\s+|\s*[|]\s*|\s*\.?\s*$)", description, re.I,
        )
        if match:
            title = match.group("title").strip(" -–—\"'")
            artist = match.group("artist").strip(" -–—\"'")
        else:
            # Deezer and a few other stores use "Artist - song - year".
            match = re.search(
                r"^(?P<artist>.+?)\s*[-–—]\s*(?:song|album|single|track|playlist)\b",
                description, re.I,
            )
            if match:
                artist = match.group("artist").strip(" -–—\"'")
    title = re.sub(r"\s*[-–—|]\s*" + service + r"\s*$", "", title, flags=re.I)
    title = re.sub(r"\s+on\s+" + service + r"\s*$", "", title, flags=re.I)
    artist = re.sub(r"\s*[-–—|]\s*" + service + r"\s*$", "", artist, flags=re.I)
    artist = re.sub(r"\s+on\s+" + service + r"\s*$", "", artist, flags=re.I)
    title = re.sub(r"\s*[-–—]\s*(?:Single|EP)\s*$", "", title, flags=re.I)
    return title.strip(), artist.strip()


def _meta_tracks(page_html, default_artist=""):
    title = (_meta_content(page_html, "og:title")
             or _meta_content(page_html, "twitter:title")
             or _page_title(page_html))
    description = (_meta_content(page_html, "og:description")
                   or _meta_content(page_html, "description"))
    title, artist = _split_title_artist(title, description)
    if not title:
        return []
    return [{
        "title": title,
        "artist": artist or default_artist,
        "duration": 0.0,
    }]


def _apple_music_ids(url):
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return "", ""
    query = urllib.parse.parse_qs(parsed.query)
    track_id = (query.get("i") or [""])[0].strip()
    path = parsed.path or ""
    path_ids = re.findall(r"/(?:id)?(\d{5,})(?=/|$)", path)
    collection_id = path_ids[-1] if path_ids else ""
    if "/song/" in path and collection_id:
        track_id = track_id or collection_id
        collection_id = ""
    return track_id, collection_id


def _apple_lookup_tracks(url):
    track_id, collection_id = _apple_music_ids(url)
    lookup_id = track_id or collection_id
    if not lookup_id:
        return []
    query = urllib.parse.urlencode({"id": lookup_id, "entity": "song", "limit": 50})
    try:
        data = fetch_json("https://itunes.apple.com/lookup?" + query, timeout=20)
    except Exception:
        return []
    tracks = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        if item.get("wrapperType") != "track" and item.get("kind") != "song":
            continue
        title = (item.get("trackName") or "").strip()
        artist = (item.get("artistName") or "").strip()
        if not title:
            continue
        try:
            duration = float(item.get("trackTimeMillis") or 0) / 1000.0
        except (TypeError, ValueError):
            duration = 0.0
        tracks.append({"title": title, "artist": artist, "duration": duration})
    return tracks[:1] if track_id else tracks[:MAX_METADATA_TRACKS]


def apple_music_tracks(url):
    """Read public Apple Music metadata from JSON-LD/API (never DRM audio)."""
    path = urllib.parse.urlparse(url).path or ""
    if "/artist/" in path:
        raise FriendlyError(
            "Apple Music artist pages aren't supported yet.\n"
            "Paste a song, album, or playlist link instead."
        )
    page = ""
    fetch_error = None
    try:
        page, _ = fetch_page(url, limit=4 * 1024 * 1024)
    except Exception as exc:
        fetch_error = exc

    track_id, _ = _apple_music_ids(url)
    single = bool(track_id) or "/song/" in path
    tracks = _tracks_from_json_ld(page) if page else []
    if single and len(tracks) > 1:
        tracks = tracks[:1]
    if not tracks:
        tracks = _apple_lookup_tracks(url)
    if single and len(tracks) > 1:
        tracks = tracks[:1]
    if not tracks and page:
        tracks = _meta_tracks(page)
    if not tracks:
        if fetch_error is not None:
            raise FriendlyError(
                "Could not read this Apple Music link.\n"
                "Check your internet connection and make sure the link is public."
            ) from fetch_error
        raise FriendlyError(
            "Could not read the track details from this Apple Music link.\n"
            "Try a specific song link instead of a storefront home page."
        )
    kind = "playlist" if "/playlist/" in path else ("album" if len(tracks) > 1 else "track")
    return kind, tracks[:MAX_METADATA_TRACKS]


def generic_drm_tracks(url):
    """Best-effort metadata reader for other DRM streaming services."""
    try:
        page, _ = fetch_page(url, limit=4 * 1024 * 1024)
    except Exception as exc:
        raise FriendlyError(
            "Could not read this music link.\n"
            "Check your internet connection and make sure the link is public."
        ) from exc

    tracks = _tracks_from_json_ld(page)
    if not tracks:
        tracks = _meta_tracks(page)
    if not tracks:
        # A few services only expose the song name in a serialized JSON blob.
        for match in re.finditer(
                r'"(?:trackName|songName|trackTitle)"\s*:\s*"([^"]{1,300})"',
                page, re.I):
            title = html.unescape(match.group(1)).strip()
            if title:
                tracks.append({"title": title, "artist": "", "duration": 0.0})
                break
    if not tracks:
        raise FriendlyError(
            "Could not read the track details from this music link.\n"
            "Make sure the link is public and points to a song or album."
        )
    return ("album" if len(tracks) > 1 else "track"), tracks[:MAX_METADATA_TRACKS]


def _match_score(entry, title, artist, duration, rank):
    """Lower is better: prefer matching duration, artist and title tokens."""
    text = (entry.get("title") or "").lower()
    channel = (entry.get("channel") or entry.get("uploader") or "").lower()
    score = rank * 4.0
    entry_duration = entry.get("duration")
    if duration and entry_duration:
        score += abs(float(entry_duration) - float(duration))
    tokens = {
        t for t in re.findall(r"[a-z0-9]+", f"{artist} {title}".lower())
        if len(t) > 2 and t not in _STOPWORDS
    }
    for token in tokens:
        if token in text:
            score -= 12
        if token in channel:
            score -= 8
    if "cover" in text and "cover" not in title.lower():
        score += 25
    if "live" in text and "live" not in title.lower():
        score += 15
    if any(w in text for w in ("official audio", "official video", "lyrics", "topic")):
        score -= 3
    return score


def _tag_audio(path, title, artist):
    """Write clean title/artist tags when mutagen is available."""
    try:
        from mutagen import File as MutagenFile
    except Exception:
        return
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return
        audio["title"] = [title]
        if artist:
            audio["artist"] = [artist]
        audio.save()
    except Exception:
        pass


def _search_and_download(track, folder, q, cancel, prefix=""):
    yt_dlp = require_ytdlp()
    title = track["title"]
    artist = track.get("artist") or ""
    duration = track.get("duration") or 0
    query = f"{artist} {title}".strip()

    q.put(("status", f"{prefix}Finding: {query}"))
    logger = _YTDLPLogger()
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 25,
        "retries": 3,
        "logger": logger,
        "http_headers": dict(BROWSER_HEADERS),
    }
    opts = _apply_browser_ydl_opts(opts)

    errors = []
    seen_urls = set()
    last_error = None
    for search_prefix, source_name in (("ytsearch5:", "YouTube"),
                                       ("scsearch5:", "SoundCloud")):
        if cancel.is_set():
            raise DownloadCancelled()
        if source_name == "SoundCloud":
            q.put(("status", f"{prefix}Trying another source..."))
        try:
            with _make_ydl(yt_dlp, opts) as ydl:
                info = ydl.extract_info(search_prefix + query, download=False)
            entries = [entry for entry in (info.get("entries") or [])
                       if entry and not entry.get("is_live")]
        except Exception as exc:
            errors.append(exc)
            continue
        if not entries:
            continue

        ranked = sorted(
            enumerate(entries),
            key=lambda pair: _match_score(pair[1], title, artist, duration, pair[0]),
        )
        for rank, entry in ranked[:3]:
            if cancel.is_set():
                raise DownloadCancelled()
            video_url = entry.get("webpage_url") or entry.get("url")
            if not video_url:
                continue
            video_url = str(video_url)
            if not video_url.startswith("http") and entry.get("id"):
                if search_prefix.startswith("ytsearch"):
                    video_url = "https://www.youtube.com/watch?v=" + str(entry["id"])
                else:
                    continue
            if video_url in seen_urls:
                continue
            seen_urls.add(video_url)

            q.put(("status", f"{prefix}Downloading: {artist} - {title}".strip(" -")))
            display = f"{artist} - {title}".strip(" -") or title
            try:
                path = download_with_fallback(video_url, folder, q, cancel,
                                              out_name=display)
                if path:
                    _tag_audio(path, title, artist)
                    return path
            except DownloadCancelled:
                raise
            except Exception as exc:
                last_error = exc
                errors.append(exc)
                if cancel.is_set():
                    raise DownloadCancelled()
                q.put(("status", f"{prefix}Trying another match..."))

    if last_error is not None:
        raise FriendlyError(friendly_stream_error(last_error))
    if errors:
        raise FriendlyError(friendly_stream_error(errors[-1]))
    raise FriendlyError(f"No matching audio was found for: {query}")


def _download_track_list(source, kind, tracks, folder, q, cancel):
    total = len(tracks)
    if total <= 0:
        q.put(("error", f"No tracks were found in this {source} link."))
        return
    if total > 1:
        q.put(("status", f"{total} tracks found. Starting..."))

    last_path = None
    failures = 0
    for i, track in enumerate(tracks, 1):
        if cancel.is_set():
            q.put(("cancelled",))
            return
        prefix = f"[{i}/{total}] " if total > 1 else ""
        try:
            path = _search_and_download(track, folder, q, cancel, prefix)
            if path:
                last_path = path
        except DownloadCancelled:
            q.put(("cancelled",))
            return
        except Exception as exc:
            if cancel.is_set():
                q.put(("cancelled",))
                return
            failures += 1
            if total == 1:
                q.put(("error", friendly_stream_error(exc)))
                return
            _update_log("skipped track: " + _error_text(exc).splitlines()[0][:300])
            q.put(("status", f"{prefix}Skipped an unavailable track."))

    if failures == total:
        q.put(("error", f"No tracks could be downloaded from this {source} link."))
        return
    if total > 1:
        q.put(("done", last_path or folder,
               f"Done! Saved {total - failures} of {total} {source} track(s)."))
    else:
        q.put(("done", last_path or folder))


def metadata_worker(url, folder, q, cancel):
    """Handle Spotify, Apple Music, and other DRM-only music links."""
    try:
        if is_spotify_url(url):
            q.put(("status", "Reading track details..."))
            kind, tracks = spotify_tracks(url)
            source = "Spotify"
        elif is_apple_music_url(url):
            q.put(("status", "Reading track details..."))
            kind, tracks = apple_music_tracks(url)
            source = "Apple Music"
        else:
            q.put(("status", "Reading track details..."))
            kind, tracks = generic_drm_tracks(url)
            source = "music service"
        _download_track_list(source, kind, tracks, folder, q, cancel)
    except DownloadCancelled:
        q.put(("cancelled",))
    except Exception as exc:
        if cancel.is_set():
            q.put(("cancelled",))
            return
        q.put(("error", friendly_stream_error(exc)))


def spotify_worker(url, folder, q, cancel):
    metadata_worker(url, folder, q, cancel)


def audiomack_worker(url, folder, q, cancel):
    """Download an Audiomack song through their public API; when the stream
    is region-locked or premium-only, match the song on another service."""
    try:
        q.put(("status", "Reading track details..."))
        signed_url = None
        info = None
        stream_error = None
        try:
            signed_url, info = audiomack_stream_url(url)
        except DownloadCancelled:
            raise
        except Exception as exc:
            stream_error = exc
            if cancel.is_set():
                raise DownloadCancelled()
            try:
                info = audiomack_info(url)
            except Exception:
                info = None
        if signed_url:
            q.put(("status", "Downloading..."))
            display = f"{info.get('artist', '')} - {info.get('title', '')}".strip(" -")
            path = download_with_fallback(signed_url, folder, q, cancel,
                                          referer=url, out_name=display or None)
            if cancel.is_set():
                q.put(("cancelled",))
                return
            q.put(("done", path or folder))
            return
        if not info or not info.get("title"):
            if stream_error:
                _update_log("audiomack read failed: " + _error_text(stream_error))
            raise FriendlyError(
                "Could not read this Audiomack link.\n"
                "Make sure the link points to a public song.")
        q.put(("status", "Finding another source..."))
        track = {"title": info["title"], "artist": info.get("artist", ""),
                 "duration": 0.0}
        path = _search_and_download(track, folder, q, cancel)
        if cancel.is_set():
            q.put(("cancelled",))
            return
        q.put(("done", path or folder))
    except DownloadCancelled:
        q.put(("cancelled",))
    except Exception as exc:
        if cancel.is_set():
            q.put(("cancelled",))
            return
        q.put(("error", friendly_stream_error(exc)))


def _try_proxy_download(url, folder, q, cancel, referer=None):
    """Retry a failed direct download through the free proxy pool."""
    if not _proxy_enabled() or is_onion_url(url):
        return False
    proxies = _proxy_candidates(3, q=q)
    if not proxies:
        return False
    for index, proxy in enumerate(proxies, 1):
        if cancel.is_set():
            q.put(("cancelled",))
            return True
        q.put(("status", "Retrying..."))
        try:
            path = stream_download(url, folder, q, cancel, referer=referer,
                                   proxy=proxy)
            q.put(("done", path or folder))
            return True
        except DownloadCancelled:
            q.put(("cancelled",))
            return True
        except Exception:
            continue
    return False


# ----------------------------------------------------------------- worker
def download_worker(url, folder, q, cancel, referer=None, allow_page=True):
    # Never let urllib resolve an onion host directly; yt-dlp handles Tor.
    if is_onion_url(url) or is_onion_url(referer):
        stream_worker(url, folder, q, cancel, referer=referer)
        return
    part = None
    try:
        headers = dict(BROWSER_HEADERS)
        headers["Accept"] = "*/*"
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urlopen_ctx(req, timeout=20) as resp:
            ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            url_name = urllib.parse.unquote(
                os.path.basename(urllib.parse.urlparse(resp.geturl()).path)
            )
            name = filename_from_headers(resp.headers) or url_name
            name = clean_filename(name)
            ext = os.path.splitext(name)[1].lower()

            # A web page: look for audio files inside it
            if ctype in ("text/html", "application/xhtml+xml"):
                if not allow_page:
                    q.put(("error", "That link opens a web page, not an audio file."))
                    return
                q.put(("status", "Searching this page for audio..."))
                raw = resp.read(3 * 1024 * 1024)
                charset = resp.headers.get_content_charset() or "utf-8"
                page_html = raw.decode(charset, errors="ignore")
                links = find_audio_links(page_html, resp.geturl())
                if not links:
                    links = find_embed_links(page_html, resp.geturl())
                raise PageFound(links)
            if ctype.startswith("text/") or ctype in ("application/json", "application/xml"):
                q.put(("error", "This link is not an audio file."))
                return
            is_audio = ctype.startswith("audio/") or ctype in CTYPE_TO_EXT or ext in AUDIO_EXTS
            if not is_audio:
                q.put(("error",
                       "This link does not look like an audio file.\n"
                       "Supported: MP3, M4A, WAV, OGG, FLAC."))
                return

            if ext not in AUDIO_EXTS:
                name = os.path.splitext(name)[0] + CTYPE_TO_EXT.get(ctype, ".mp3")

            os.makedirs(folder, exist_ok=True)
            dest = unique_path(folder, name)
            part = dest + ".part"
            total = int(resp.headers.get("Content-Length") or 0)
            q.put(("start", os.path.basename(dest), total))

            done = 0
            last_t = time.time()
            last_done = 0
            speed = 0.0
            with open(part, "wb") as f:
                while True:
                    if cancel.is_set():
                        break
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last_t >= 0.2:
                        inst = (done - last_done) / (now - last_t)
                        speed = inst if speed == 0 else speed * 0.7 + inst * 0.3
                        last_t, last_done = now, done
                        q.put(("progress", done, total, speed))

        if cancel.is_set():
            _remove(part)
            q.put(("cancelled",))
            return
        if total and done < total:
            _remove(part)
            q.put(("error", "The connection was cut before the file finished downloading."))
            return
        os.replace(part, dest)
        q.put(("progress", done, total or done, 0))
        final = dest
        if os.path.splitext(dest)[1].lower() != ".mp3":
            try:
                final = convert_to_mp3(dest, q, cancel)
            except DownloadCancelled:
                q.put(("cancelled",))
                return
        q.put(("done", final))

    except PageFound as pf:
        cands = collapse_candidates(pf.candidates)
        if not cands:
            q.put(("error",
                   "No audio file was found on this page.\n"
                   "The site may load audio through a protected player or a streaming service. "
                   "Try right-click on the player > Copy audio address."))
        elif len(cands) == 1:
            download_candidate(cands[0], folder, q, cancel, referer=url)
        else:
            q.put(("choose", cands, url))
    except urllib.error.HTTPError as e:
        _remove(part)
        if e.code in (401, 403, 429, 451):
            try:
                path = _impersonated_file_download(url, folder, q, cancel,
                                                   referer=referer)
                q.put(("done", path))
                return
            except DownloadCancelled:
                q.put(("cancelled",))
                return
            except Exception as imp_exc:
                _update_log("impersonated file retry failed: "
                            + _error_text(imp_exc))
        if e.code in (403, 429, 451, 503) and _try_proxy_download(
                url, folder, q, cancel, referer):
            return
        q.put(("error", friendly_http_error(e.code)))
    except (socket.timeout, TimeoutError):
        _remove(part)
        if _try_proxy_download(url, folder, q, cancel, referer):
            return
        q.put(("error", "The connection timed out. Check your internet and try again."))
    except urllib.error.URLError as e:
        _remove(part)
        timed_out = isinstance(e.reason, (socket.timeout, TimeoutError))
        if _try_proxy_download(url, folder, q, cancel, referer):
            return
        if timed_out:
            q.put(("error", "The connection timed out. Check your internet and try again."))
        else:
            q.put(("error", "Could not reach the server.\n"
                            "Check your internet connection or the link."))
    except ValueError:
        _remove(part)
        q.put(("error", "The link is not valid."))
    except PermissionError:
        _remove(part)
        q.put(("error", "Cannot write to that folder. Choose another folder."))
    except (ConnectionError, OSError) as e:
        _remove(part)
        _update_log("download failed: " + _error_text(e))
        q.put(("error", "The download couldn't be completed.\n"
                        "Check your connection and try again."))
    except Exception as e:  # last resort
        _remove(part)
        _update_log("unexpected download error: " + _error_text(e))
        q.put(("error", "Something went wrong during the download.\n"
                        "Please try again."))


# -------------------------------------------------------------------- GUI
WIN_W, WIN_H = 660, 628
UI_BG = "#070a12"
UI_CARD = "#101827"
UI_CARD_2 = "#0a111e"
UI_BORDER = "#263450"
UI_TEXT = "#eef2ff"
UI_DIM = "#8fa0bd"
UI_ACCENT = "#5eead4"
UI_ACCENT_2 = "#818cf8"
UI_DANGER = "#ff7a7a"
UI_OK = "#7de3b0"

PLATFORM_SECTIONS = (
    ("Music streaming", (
        "SoundCloud - tracks, sets and private links",
        "Audiomack - songs, albums and trending charts",
        "YouTube Music and YouTube videos",
        "Bandcamp, Mixcloud, Audius, Jamendo",
        "Vimeo, Dailymotion and PeerTube",
    )),
    ("Music services - match and download", (
        "Spotify - track / album / playlist links",
        "Apple Music - song / album / playlist links",
        "TIDAL, Deezer and Amazon Music links",
        "Public details are matched to the best playable audio",
    )),
    ("Video and social platforms", (
        "YouTube, TikTok, Instagram, Facebook",
        "Reddit, X / Twitter, Twitch clips, Snapchat",
        "Thousands of other public video and audio sites",
    )),
    ("Direct audio and streams", (
        "MP3, M4A, AAC, WAV, FLAC, OGG, OPUS, WMA",
        "Live and on-demand streaming playlists",
        "Player-only streams are traced back to their source",
    )),
    ("Protected pages and hidden audio", (
        "Audio buried inside web pages and embedded players",
        "Embedded details and player information are read automatically",
        "Many bot checks and protected pages are handled automatically",
        "Automatic MP3 conversion with clean title and artist tags",
    )),
    ("Tor and .onion", (
        "Automatic detection of .onion addresses",
        "Private routing for every onion page and download",
        "Starts local Tor automatically when it is installed",
        "Onion pages and media never leave the private route",
    )),
    ("Free VPN / proxy", (
        "One-switch free proxy connection",
        "A fresh connection is chosen every time the switch is turned on",
        "The quickest working option is used first",
        "Helps when a site is blocked on your network",
    )),
)

class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        migrate_legacy_data()
        ensure_proxies_file()
        _register_bundled_fonts()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.resizable(False, False)
        self.configure(fg_color=UI_BG)

        self.cfg: AppConfig = load_config()
        _set_proxy_mode(self.cfg.proxy_mode)
        self.q: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_file: str | None = None
        self.total = 0
        self.ui_font = _best_font_family(self)
        self._status_job = None
        self._platforms_open = False
        self._platforms_page = None

        start_ytdlp_update()
        if _proxy_enabled():
            threading.Thread(
                target=self._warm_proxy_pool,
                args=(False,),
                daemon=True,
            ).start()

        self._set_icon()
        self._build_header()
        self._build_content()
        self._build_platforms_page()
        self._pulse_glow()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", lambda _e: self._close_platforms())
        self.bind("<Return>", lambda _e: self.start())
        self.after(250, self.url_entry.focus_set)
        self.after(100, self.poll)

    # ---- visual construction
    def _set_icon(self) -> None:
        icon = asset_path("sk_grabber.ico")
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                return

    def _font(self, size=13, weight="normal"):
        return ctk.CTkFont(family=self.ui_font, size=size, weight=weight)

    def _card(self, master):
        return ctk.CTkFrame(master, fg_color=UI_CARD, corner_radius=18,
                            border_width=1, border_color=UI_BORDER)

    @staticmethod
    def _round_rect(canvas, x1, y1, x2, y2, r, **kwargs):
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return canvas.create_polygon(points, smooth=True, **kwargs)

    def _build_header(self):
        self.header = tk.Canvas(self, height=152, bg=UI_BG,
                                highlightthickness=0, bd=0)
        self.header.pack(fill="x")

        # Rendered as a smooth gradient grid with soft radial glows: this is
        # the glassy backdrop behind the title and badge.
        top = (7, 10, 18)
        bottom = (23, 18, 50)
        glows = (
            (60, 4, 290, (56, 90, 190), 0.55),
            (620, -20, 320, (110, 70, 210), 0.50),
            (30, 116, 150, (38, 180, 170), 0.15),
        )
        cell = 6
        for y in range(0, 152, cell):
            t = min(1.0, y / 151)
            base = [top[i] + (bottom[i] - top[i]) * t for i in range(3)]
            for x in range(0, WIN_W, cell):
                rgb = list(base)
                for gx, gy, radius, color, strength in glows:
                    d = ((x - gx) ** 2 + (y - gy) ** 2) ** 0.5
                    if d < radius:
                        f = (1 - d / radius) ** 2 * strength
                        for i in range(3):
                            rgb[i] += (color[i] - rgb[i]) * f
                fill = "#%02x%02x%02x" % tuple(
                    max(0, min(255, int(round(v)))) for v in rgb)
                self.header.create_rectangle(x, y, x + cell, y + cell,
                                             fill=fill, outline=fill)

        self.header.create_line(0, 151, WIN_W, 151, fill="#1a2437")
        self._accent_line = self.header.create_line(28, 17, 122, 17,
                                                     fill=UI_ACCENT, width=2)
        self.header.create_text(28, 53, anchor="w", text=APP_NAME,
                                fill=UI_TEXT,
                                font=(self.ui_font, 32, "bold"))
        try:
            title_w = tkfont.Font(family=self.ui_font, size=32,
                                  weight="bold").measure(APP_NAME)
        except Exception:
            title_w = 205
        bx = 28 + title_w + 16
        self._badge_id = self._round_rect(
            self.header, bx, 35, bx + 112, 67, 16,
            fill="#10312f", outline=UI_ACCENT)
        self.header.create_text(bx + 56, 51, text=APP_TAGLINE,
                                fill=UI_ACCENT,
                                font=(self.ui_font, 12, "bold"))
        self.header.create_text(30, 96, anchor="w", text=APP_SLOGAN,
                                fill=UI_DIM,
                                font=(self.ui_font, 13))

    def _build_content(self):
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=22, pady=(4, 16))

        # Link card
        card = self._card(wrap)
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(inner, text="LINK", text_color=UI_DIM,
                     font=self._font(10, "bold")).pack(anchor="w", pady=(0, 4))
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        self.url_entry = ctk.CTkEntry(
            row, height=40, corner_radius=12, fg_color=UI_CARD_2,
            border_color=UI_BORDER, text_color=UI_TEXT,
            placeholder_text="Paste any link - song, video, page, or .onion",
            font=self._font(13))
        self.url_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            row, text="Paste", width=78, height=40, corner_radius=12,
            fg_color="#1c2a44", hover_color="#26385a",
            border_width=1, border_color=UI_BORDER,
            font=self._font(12), command=self.paste,
        ).pack(side="left", padx=(8, 0))

        # Folder card
        card = self._card(wrap)
        card.pack(fill="x", pady=(10, 0))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=12)
        ctk.CTkLabel(inner, text="SAVE TO", text_color=UI_DIM,
                     font=self._font(10, "bold")).pack(anchor="w", pady=(0, 4))
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        self.folder_entry = ctk.CTkEntry(
            row, height=38, corner_radius=12, fg_color=UI_CARD_2,
            border_color=UI_BORDER, text_color=UI_TEXT,
            placeholder_text="Save to folder...", font=self._font(12))
        self.folder_entry.pack(side="left", fill="x", expand=True)
        default = self.cfg.folder or os.path.join(os.path.expanduser("~"), "Downloads")
        self.folder_entry.insert(0, default)
        ctk.CTkButton(
            row, text="Browse", width=78, height=38, corner_radius=12,
            fg_color="#1c2a44", hover_color="#26385a",
            border_width=1, border_color=UI_BORDER,
            font=self._font(12), command=self.browse,
        ).pack(side="left", padx=(8, 0))

        card = self._card(wrap)
        card.pack(fill="x", pady=(10, 0))
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=10)
        switch_style = {
            "font": self._font(12, "bold"),
            "progress_color": UI_ACCENT,
            "button_color": "#d8fff9",
            "button_hover_color": UI_ACCENT,
            "text_color": UI_TEXT,
        }
        self.free_proxy_switch = ctk.CTkSwitch(
            inner,
            text="Free Auto Proxy",
            command=self.toggle_free_proxy,
            **switch_style,
        )
        self.free_proxy_switch.pack(side="left")
        self.custom_proxy_switch = ctk.CTkSwitch(
            inner,
            text="Custom Proxies",
            command=self.toggle_custom_proxy,
            **switch_style,
        )
        self.custom_proxy_switch.pack(side="left", padx=(18, 0))
        ctk.CTkLabel(
            inner,
            text="proxies.txt",
            text_color="#5b6b8c",
            font=self._font(10),
        ).pack(side="right")
        if self.cfg.proxy_mode is ProxyMode.FREE:
            self.free_proxy_switch.select()
        elif self.cfg.proxy_mode is ProxyMode.CUSTOM:
            self.custom_proxy_switch.select()

        # Action row
        row = ctk.CTkFrame(wrap, fg_color="transparent")
        row.pack(fill="x", pady=(14, 0))
        self.dl_btn = ctk.CTkButton(
            row, text="Download", height=44, corner_radius=14,
            fg_color=UI_ACCENT, hover_color="#7ff5e2", text_color="#06211e",
            font=self._font(14, "bold"), command=self.start)
        self.dl_btn.pack(side="left", fill="x", expand=True)
        self.cancel_btn = ctk.CTkButton(
            row, text="Cancel", height=44, width=82, corner_radius=14,
            state="disabled", fg_color="#3a1a24", hover_color="#5b2634",
            border_width=1, border_color="#6b2a3a",
            font=self._font(12), command=self.cancel)
        self.cancel_btn.pack(side="left", padx=(8, 0))
        self.reset_btn = ctk.CTkButton(
            row, text="Reset", height=44, width=78, corner_radius=14,
            fg_color="#16233a", hover_color="#203454",
            border_width=1, border_color=UI_BORDER,
            text_color=UI_TEXT, text_color_disabled="#5b6b8c",
            font=self._font(12), command=self.reset_ui)
        self.reset_btn.pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            row, text="Platforms", height=44, width=104, corner_radius=14,
            fg_color="#16233a", hover_color="#203454",
            border_width=1, border_color=UI_BORDER,
            font=self._font(12), command=self.show_platforms,
        ).pack(side="left", padx=(8, 0))

        # Progress + status
        self.bar = ctk.CTkProgressBar(wrap, height=10, corner_radius=6,
                                      progress_color=UI_ACCENT,
                                      fg_color="#1a2336")
        self.bar.set(0)
        self.bar.pack(fill="x", pady=(18, 8))
        self.status = ctk.CTkLabel(wrap, text="Ready", anchor="w",
                                   justify="left", wraplength=600,
                                   text_color=UI_TEXT, font=self._font(12))
        self.status.pack(fill="x")
        self.result_row = ctk.CTkFrame(wrap, fg_color="transparent")
        self.result_row.pack(fill="x", pady=(2, 0))
        self.stats = ctk.CTkLabel(self.result_row, text="", anchor="w",
                                  text_color=UI_DIM, font=self._font(11))
        self.stats.pack(side="left")
        self.open_btn = ctk.CTkButton(
            self.result_row, text="Open Folder", width=116, height=30,
            corner_radius=10, fg_color="#1c2a44", hover_color="#26385a",
            border_width=1, border_color=UI_BORDER,
            font=self._font(11), command=self.open_folder)

        footer = ctk.CTkFrame(wrap, fg_color="transparent")
        footer.pack(side="bottom", fill="x", pady=(14, 0))
        ctk.CTkLabel(footer, text="SK Grabber - mp3 version",
                     text_color="#5b6b8c",
                     font=self._font(10)).pack()

    def _build_platforms_page(self):
        page = ctk.CTkFrame(self, fg_color="#0a0f1c", corner_radius=0)
        self._platforms_page = page

        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(16, 8))
        ctk.CTkButton(
            top, text="\u2190  Back", width=86, height=36, corner_radius=12,
            fg_color="#16233a", hover_color="#203454",
            border_width=1, border_color=UI_BORDER,
            font=self._font(12, "bold"), command=self._close_platforms,
        ).pack(side="left")
        ctk.CTkLabel(top, text="Supported Platforms", text_color=UI_TEXT,
                     font=self._font(22, "bold")).pack(side="left", padx=(16, 0))
        ctk.CTkLabel(
            page,
            text="Every source SK Grabber can read - all in one place.",
            text_color=UI_DIM, justify="left", wraplength=600,
            font=self._font(11),
        ).pack(fill="x", padx=20, pady=(0, 10))

        body = ctk.CTkScrollableFrame(
            page, fg_color=UI_CARD, corner_radius=18,
            border_width=1, border_color=UI_BORDER)
        body.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        for title, items in PLATFORM_SECTIONS:
            ctk.CTkLabel(body, text=title.upper(), text_color=UI_ACCENT,
                         font=self._font(10, "bold"), anchor="w"
                         ).pack(fill="x", padx=12, pady=(14, 4))
            for item in items:
                row = ctk.CTkFrame(body, fg_color="transparent")
                row.pack(fill="x", padx=12, pady=1)
                ctk.CTkLabel(row, text=">", text_color=UI_ACCENT_2, width=16,
                             font=self._font(11, "bold")).pack(side="left")
                ctk.CTkLabel(row, text=item, text_color="#c7d2e8",
                             anchor="w", justify="left", wraplength=560,
                             font=self._font(12)).pack(side="left", fill="x",
                                                        expand=True)
        ctk.CTkLabel(
            body,
            text=("Note: Spotify, Apple Music, TIDAL, Deezer and Amazon Music "
                  "don't offer direct downloads. SK Grabber reads their public "
                  "details and finds the best matching playable audio."),
            text_color=UI_DIM, justify="left", wraplength=560,
            font=self._font(11),
        ).pack(fill="x", padx=16, pady=(16, 12))

    def show_platforms(self):
        page = self._platforms_page
        if page is None or self._platforms_open:
            return
        self._platforms_open = True
        page.place(x=WIN_W, y=0, relwidth=1, relheight=1)
        page.lift()
        self._slide_overlay(page, WIN_W, 0)

    def _close_platforms(self):
        page = self._platforms_page
        if page is None or not self._platforms_open:
            return
        self._platforms_open = False
        self._slide_overlay(page, 0, WIN_W, on_done=page.place_forget)

    def _slide_overlay(self, widget, start, end, on_done=None, steps=14):
        delta = end - start

        def step(i=0):
            if not widget.winfo_exists():
                return
            try:
                widget.place_configure(x=int(start + delta * (i / steps)))
            except Exception:
                return
            if i < steps:
                self.after(13, lambda: step(i + 1))
            elif on_done:
                on_done()

        step()

    def _pulse_glow(self):
        self._glow_on = not getattr(self, "_glow_on", False)
        try:
            self.header.itemconfigure(
                self._accent_line,
                fill="#a7fbef" if self._glow_on else UI_ACCENT,
                width=3 if self._glow_on else 2)
            self.header.itemconfigure(
                self._badge_id,
                outline="#a7fbef" if self._glow_on else UI_ACCENT)
        except Exception:
            pass
        try:
            self.after(1500, self._pulse_glow)
        except Exception:
            pass

    # ---- actions
    def paste(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)

    def browse(self):
        start = self.folder_entry.get().strip() or os.path.expanduser("~")
        path = filedialog.askdirectory(initialdir=start, title="Choose download folder")
        if path:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, os.path.normpath(path))

    def toggle_free_proxy(self) -> None:
        mode = ProxyMode.FREE if self.free_proxy_switch.get() else ProxyMode.NONE
        self._apply_proxy_mode(mode)

    def toggle_custom_proxy(self) -> None:
        mode = ProxyMode.CUSTOM if self.custom_proxy_switch.get() else ProxyMode.NONE
        self._apply_proxy_mode(mode)

    def _apply_proxy_mode(self, mode: ProxyMode) -> None:
        if mode is ProxyMode.FREE:
            self.free_proxy_switch.select()
            self.custom_proxy_switch.deselect()
        elif mode is ProxyMode.CUSTOM:
            self.custom_proxy_switch.select()
            self.free_proxy_switch.deselect()
        else:
            self.free_proxy_switch.deselect()
            self.custom_proxy_switch.deselect()

        _set_proxy_mode(mode)
        self.cfg.proxy_mode = mode
        self.cfg.save()

        if mode is ProxyMode.FREE:
            proxy_manager.free.invalidate()
            self.set_status("Free proxy mode enabled.")
            threading.Thread(
                target=self._warm_proxy_pool,
                args=(True,),
                daemon=True,
            ).start()
        elif mode is ProxyMode.CUSTOM:
            entries = proxy_manager.custom.refresh()
            if entries:
                self.set_status("Custom proxy mode enabled.")
            else:
                self.set_status(
                    "Add at least one proxy to proxies.txt to use custom proxies.",
                    error=True,
                )
        else:
            self.set_status("Ready")

    def _warm_proxy_pool(self, force: bool = False) -> None:
        try:
            proxy_manager.warm(force=force)
        except Exception:
            return

    def start(self) -> None:
        if self._platforms_open:
            return
        url = self.url_entry.get().strip()
        folder = self.folder_entry.get().strip()
        if not url:
            return self.set_status("Please paste a link first.", error=True)
        if not re.match(r"^https?://", url, re.I):
            return self.set_status("The link must start with http:// or https://", error=True)
        if not folder:
            return self.set_status("Please choose a download folder.", error=True)

        self.cfg.folder = folder
        self.cfg.save()
        if is_drm_metadata_url(url):
            self.launch_metadata(url, folder)
        elif is_audiomack_url(url):
            self.launch_audiomack(url, folder)
        elif is_direct_audio_url(url) and not is_onion_url(url):
            self.launch(url, folder)
        else:
            self.launch_stream(url, folder)

    def _begin(self, target, args):
        self.open_btn.pack_forget()
        self.bar.configure(mode="determinate")
        self.bar.set(0)
        self.stats.configure(text="")
        self.set_status("Connecting...")
        self.dl_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.reset_btn.configure(state="disabled")
        self.cancel_event.clear()
        self.total = 0
        self.thread = threading.Thread(target=target, args=args, daemon=True)
        self.thread.start()

    def launch(self, url, folder, referer=None, allow_page=True):
        self._begin(download_worker,
                    (url, folder, self.q, self.cancel_event, referer, allow_page))

    def launch_stream(self, url, folder):
        self._begin(stream_worker, (url, folder, self.q, self.cancel_event))

    def launch_metadata(self, url, folder):
        self._begin(metadata_worker, (url, folder, self.q, self.cancel_event))

    def launch_audiomack(self, url, folder):
        self._begin(audiomack_worker, (url, folder, self.q, self.cancel_event))

    def launch_spotify(self, url, folder):
        self.launch_metadata(url, folder)

    def cancel(self):
        self.cancel_event.set()
        self.cancel_btn.configure(state="disabled")
        self.set_status("Cancelling...")

    def show_chooser(self, links, page_url):
        self.finish_ui()
        self.set_status(f"Found {len(links)} audio files on the page. Choose one.")
        dlg = ctk.CTkToplevel(self)
        dlg.title("Choose an audio file")
        dlg.geometry("580x400")
        dlg.configure(fg_color=UI_BG)
        dlg.transient(self)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        try:
            dlg.attributes("-alpha", 0.0)
        except Exception:
            pass
        dlg.after(150, dlg.grab_set)
        ctk.CTkLabel(dlg, text="Audio files found on this page",
                     font=self._font(17, "bold"),
                     text_color=UI_TEXT).pack(pady=(16, 8))
        box = ctk.CTkScrollableFrame(dlg, fg_color=UI_CARD,
                                     border_width=1, border_color=UI_BORDER,
                                     corner_radius=16)
        box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        for link in links[:40]:
            parsed = urllib.parse.urlparse(link)
            name = urllib.parse.unquote(os.path.basename(parsed.path)) or link
            ctk.CTkButton(
                box, text=f"{name[:60]}\n{parsed.netloc}", anchor="w", height=48,
                fg_color="#16233a", hover_color="#203454",
                border_width=1, border_color=UI_BORDER,
                font=self._font(12),
                command=lambda l=link: self.pick(l, dlg, page_url),
            ).pack(fill="x", pady=3)

        def fade(i=0):
            if not dlg.winfo_exists():
                return
            try:
                dlg.attributes("-alpha", min(1.0, i / 10))
            except Exception:
                return
            if i < 10:
                dlg.after(16, lambda: fade(i + 1))

        dlg.after(30, fade)

    def pick(self, link, dlg, page_url):
        dlg.destroy()
        folder = self.folder_entry.get().strip()
        self._begin(download_candidate,
                    (link, folder, self.q, self.cancel_event, page_url))

    def open_folder(self):
        if self.last_file and os.path.isfile(self.last_file):
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(self.last_file)])
                return
        folder = self.last_file if self.last_file and os.path.isdir(self.last_file) else None
        folder = folder or self.folder_entry.get().strip()
        if folder and os.path.isdir(folder):
            if sys.platform.startswith("win"):
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])

    def reset_ui(self):
        # Keep the chosen save folder and proxy preference; everything else
        # returns to the state the app had right after launch.
        if self.thread and self.thread.is_alive():
            return
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass
        self.cancel_event.clear()
        self.url_entry.delete(0, "end")
        self.bar.stop()
        self.bar.configure(mode="determinate")
        self.bar.set(0)
        self.stats.configure(text="")
        self.last_file = None
        self.total = 0
        self.open_btn.pack_forget()
        self.set_status("Ready")
        self.finish_ui()
        self.url_entry.focus_set()

    def on_close(self):
        self.cancel_event.set()
        self.destroy()

    # ---- UI updates
    def set_status(self, text, error=False):
        self.status.configure(text=text)
        self._animate_status_color(UI_DANGER if error else UI_TEXT)

    def _animate_status_color(self, target, steps=10):
        if self._status_job:
            try:
                self.after_cancel(self._status_job)
            except Exception:
                pass
            self._status_job = None
        try:
            start = self.status.cget("text_color")
            if isinstance(start, (tuple, list)):
                start = start[0]
            if not isinstance(start, str) or not start.startswith("#"):
                start = UI_TEXT
        except Exception:
            start = UI_TEXT

        def step(i=0):
            try:
                self.status.configure(
                    text_color=_mix_hex(start, target, i / steps))
            except Exception:
                return
            if i < steps:
                self._status_job = self.after(28, lambda: step(i + 1))

        step()

    def finish_ui(self):
        self.dl_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        if hasattr(self, "reset_btn"):
            self.reset_btn.configure(state="normal")

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "start":
                    _, name, total = msg
                    self.total = total
                    self.set_status(f"Downloading: {name}")
                    self.bar.stop()
                    if total:
                        self.bar.configure(mode="determinate")
                        self.bar.set(0)
                    else:
                        self.bar.configure(mode="indeterminate")
                        self.bar.start()
                elif kind == "status":
                    self.set_status(msg[1])
                elif kind == "choose":
                    self.show_chooser(msg[1], msg[2])
                elif kind == "progress":
                    _, done, total, speed = msg
                    if total and not self.total:
                        self.total = total
                        self.bar.stop()
                        self.bar.configure(mode="determinate")
                    if total:
                        self.bar.set(min(done / total, 1))
                        pct = done / total * 100
                        eta = fmt_time((total - done) / speed) if speed > 0 else "--:--"
                        self.stats.configure(
                            text=f"{pct:.0f}%   |   {fmt_size(done)} / {fmt_size(total)}"
                                 f"   |   {fmt_size(speed)}/s   |   ETA {eta}")
                    else:
                        self.stats.configure(text=f"{fmt_size(done)}   |   {fmt_size(speed)}/s")
                elif kind == "done":
                    path = msg[1]
                    note = msg[2] if len(msg) > 2 else None
                    self.bar.stop()
                    self.bar.configure(mode="determinate")
                    self.bar.set(1)
                    self.last_file = path
                    self.set_status(note or f"Done! Saved as: {os.path.basename(path)}")
                    self.stats.configure(text="100%")
                    self.open_btn.pack(side="right")
                    self.finish_ui()
                elif kind == "error":
                    self.bar.stop()
                    self.bar.configure(mode="determinate")
                    self.bar.set(0)
                    self.open_btn.pack_forget()
                    self.stats.configure(text="")
                    self.set_status(msg[1], error=True)
                    self.finish_ui()
                elif kind == "cancelled":
                    self.bar.stop()
                    self.bar.configure(mode="determinate")
                    self.bar.set(0)
                    self.open_btn.pack_forget()
                    self.stats.configure(text="")
                    self.set_status("Download cancelled.")
                    self.finish_ui()
        except queue.Empty:
            pass
        self.after(100, self.poll)


def run_selftest(
    check_tor: bool = False,
    check_proxy: bool = False,
    check_audiomack: bool = False,
) -> bool:
    lines: list[str] = []
    ok = True

    def log(text: object) -> None:
        lines.append(str(text))

    proxy_file = ensure_proxies_file()
    log("version: " + APP_VERSION)
    log(f"proxies.txt: {proxy_file} exists={proxy_file.exists()}")
    ok = ok and proxy_file.exists()
    log("frozen: " + str(bool(getattr(sys, "frozen", False))))
    log("bundled yt-dlp: " + bundled_ytdlp_version())
    try:
        yt_dlp = require_ytdlp()
        log("yt-dlp: " + yt_dlp.version.__version__)
        log("yt-dlp path: " + str(getattr(yt_dlp, "__file__", "")))
    except Exception as exc:
        log("yt-dlp: FAILED " + _error_text(exc))
        ok = False

    try:
        target = _impersonate_target()
        log("impersonation: " + (str(target) if target is not None else "unavailable"))
        if target is None:
            ok = False
    except Exception as exc:
        log("impersonation: FAILED " + _error_text(exc))
        ok = False

    try:
        import curl_cffi
        log("curl_cffi: " + str(getattr(curl_cffi, "__version__", "unknown")))
    except Exception as exc:
        log("curl_cffi: FAILED " + _error_text(exc))

    try:
        icon = asset_path("sk_grabber.ico")
        font_names = ("Poppins-Regular.ttf", "Poppins-Medium.ttf",
                      "Poppins-SemiBold.ttf", "Poppins-Bold.ttf")
        font_paths = [asset_path("fonts", name) for name in font_names]
        present = [p for p in font_paths if os.path.exists(p)]
        log(f"icon: {icon} exists={os.path.exists(icon)}")
        log(f"fonts: {len(present)}/{len(font_paths)} bundled")
        ok = ok and os.path.exists(icon)
        ok = ok and len(present) == len(font_paths)
    except Exception as exc:
        log("assets: FAILED " + _error_text(exc))
        ok = False

    try:
        import requests
        import socks
        log("requests: " + str(getattr(requests, "__version__", "unknown")))
        log("PySocks: " + str(getattr(socks, "__version__", "unknown")))
    except Exception as exc:
        log("Tor dependencies: FAILED " + _error_text(exc))

    try:
        sample = (
            '<audio src="/media/track.mp3"></audio>'
            '<div data-audio-src="https://cdn.example/stream"></div>'
            '<script>var hls = "https:\\/\\/cdn.example\\/live.m3u8";'
            'var blob = "blob:https://example.com/1234";</script>'
        )
        links = find_audio_links(sample, "https://example.com/page")
        blobs = find_blob_links(sample)
        log("page scanner: " + ", ".join(links))
        log("blob scanner: " + ", ".join(blobs))
        ok = ok and any(link.endswith("/media/track.mp3") for link in links)
        ok = ok and any(link.endswith("/live.m3u8") for link in links)
        ok = ok and bool(blobs)
    except Exception as exc:
        log("page scanner: FAILED " + _error_text(exc))
        ok = False

    try:
        onion_sample = (
            '<audio src="/media/private.mp3"></audio>'
            '<script>var player = "http:\\/\\/abc.onion\\/stream.m3u8";</script>'
            '<iframe src="/player"></iframe>'
        )
        media, _generic = _collect_audio_links(
            onion_sample, "http://abc.onion/page")
        containers = find_onion_containers(
            onion_sample, "http://abc.onion/page")
        log("onion scanner: " + ", ".join(media + containers))
        ok = ok and any(link.endswith("/media/private.mp3") for link in media)
        ok = ok and any(link.endswith("/stream.m3u8") for link in media)
        ok = ok and any(link.endswith("/player") for link in containers)
    except Exception as exc:
        log("onion scanner: FAILED " + _error_text(exc))
        ok = False

    try:
        sample_list = (
            "1.2.3.4:8080\n"
            "socks5://5.6.7.8:1080\n"
            "https://9.10.11.12:3128\n"
            "10.0.0.1:8080\n"
            "127.0.0.1:9050\n"
            "2001:db8::1:8080\n"
            "1.2.3.4:8080\n"
        )
        parsed = parse_proxy_lines(sample_list)
        log("proxy parser: " + ", ".join(parsed))
        ok = ok and "http://1.2.3.4:8080" in parsed
        ok = ok and "socks5://5.6.7.8:1080" in parsed
        ok = ok and "http://9.10.11.12:3128" in parsed
        ok = ok and len(parsed) == 3
        ok = ok and not any("10.0.0.1" in p or "127.0.0.1" in p for p in parsed)

        custom = parse_custom_proxy_lines(
            "# local proxies\n"
            "10.0.0.1:8080\n"
            "127.0.0.1:9050\n"
            "user:pass@proxy.example:3128\n"
            "socks5h://[::1]:1080\n"
        )
        log("custom proxy parser: " + ", ".join(custom))
        ok = ok and "http://10.0.0.1:8080" in custom
        ok = ok and "http://127.0.0.1:9050" in custom
        ok = ok and "http://user:pass@proxy.example:3128" in custom
        ok = ok and "socks5h://[::1]:1080" in custom
    except Exception as exc:
        log("proxy parser: FAILED " + _error_text(exc))
        ok = False

    try:
        sign_params = {"a": "1", "oauth_nonce": "fixed", "oauth_timestamp": "1"}
        sig1 = _oauth1_signature("GET", "https://api.example.com/v1/x",
                                 sign_params, "secret")
        sig2 = _oauth1_signature("GET", "https://api.example.com/v1/x",
                                 sign_params, "secret")
        log("oauth signer: " + (sig1[:16] + "..." if sig1 else "empty"))
        ok = ok and bool(sig1) and sig1 == sig2
        ok = ok and is_audiomack_url(
            "https://audiomack.com/artist/song/title-123")
    except Exception as exc:
        log("oauth signer: FAILED " + _error_text(exc))
        ok = False

    try:
        import certifi
        bundle = certifi.where()
        exists = os.path.exists(bundle)
        log(f"certifi: {bundle} exists={exists}")
        ok = ok and exists
    except Exception as exc:
        log("certifi: FAILED " + _error_text(exc))
        ok = False

    exe = ffmpeg_path()
    log(f"ffmpeg: {exe} exists={bool(exe and os.path.exists(exe))}")
    if exe and os.path.exists(exe):
        try:
            proc = subprocess.run([exe, "-version"], capture_output=True,
                                  text=True, timeout=20)
            version = (proc.stdout or proc.stderr).splitlines()
            log("ffmpeg version: " + (version[0] if version else "unknown"))
        except Exception as exc:
            log("ffmpeg run: FAILED " + _error_text(exc))
            ok = False
    else:
        ok = False

    if check_tor:
        try:
            proxy = ensure_tor()
            log("tor proxy: " + proxy)
            page = ""
            for test_url in (ONION_TEST_URL, ONION_TEST_FALLBACK):
                try:
                    page, final_url = fetch_page(test_url, limit=300 * 1024)
                    log(f"tor fetch: {final_url} chars={len(page)}")
                    if len(page) > 500:
                        break
                except Exception as exc:
                    log("tor fetch attempt: " + _error_text(exc)[:200])
            ok = ok and len(page) > 500
        except Exception as exc:
            log("tor fetch: FAILED " + _error_text(exc))
            ok = False

    if check_proxy:
        try:
            _set_proxy_mode(ProxyMode.FREE)
            working = proxy_manager.free.refresh(force=True)
            log(f"proxy pool: {len(working)} working")
            ok = ok and bool(working)
        except Exception as exc:
            log("proxy pool: FAILED " + _error_text(exc))
            ok = False
        finally:
            _set_proxy_mode(ProxyMode.NONE)

    if check_audiomack:
        try:
            data = _audiomack_api("music/trending/page/1", {"type": "song"})
            results = (data or {}).get("results") or []
            log(f"audiomack api: {len(results)} trending songs")
            ok = ok and bool(results)
            playable = next((item for item in results
                             if not item.get("geo_restricted")), None)
            if playable:
                play = _audiomack_api(f"music/play/{playable.get('id')}",
                                      {"environment": "desktop-web", "hq": "true"})
                signed = str((play or {}).get("signedUrl") or "")
                log("audiomack stream: " + ("yes" if signed else "no"))
                ok = ok and bool(signed)
                if signed:
                    tmp = tempfile.mkdtemp(prefix="mp3_grabber_audiomack_")
                    try:
                        aq = queue.Queue()
                        ac = threading.Event()
                        path = stream_download(signed, tmp, aq, ac,
                                               out_name="audiomack_selftest")
                        size = os.path.getsize(path) if path and os.path.exists(path) else 0
                        log(f"audiomack download: size={size}")
                        ok = ok and size > 0
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)
        except Exception as exc:
            log("audiomack api: FAILED " + _error_text(exc))
            ok = False

    folder = tempfile.mkdtemp(prefix="sk_grabber_selftest_")
    q = queue.Queue()
    cancel = threading.Event()
    try:
        path = stream_download("https://www.w3schools.com/html/horse.mp3",
                               folder, q, cancel)
        size = os.path.getsize(path) if path and os.path.exists(path) else 0
        log(f"download: {path} size={size}")
        ok = ok and size > 0
    except Exception as exc:
        log("download: FAILED " + _error_text(exc))
        ok = False
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    log("RESULT: " + ("OK" if ok else "FAILED"))
    log_path = os.path.join(tempfile.gettempdir(), SELFTEST_LOG)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        if "--update" in sys.argv:
            os.environ["MP3_GRABBER_FORCE_YTDLP_UPDATE"] = "1"
            _auto_update_worker()
        sys.exit(0 if run_selftest(
            check_tor="--tor" in sys.argv,
            check_proxy=("--proxy" in sys.argv or "--proxies" in sys.argv),
            check_audiomack="--audiomack" in sys.argv,
        ) else 1)
    App().mainloop()
