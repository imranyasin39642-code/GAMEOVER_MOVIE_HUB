"""
🎮 GameOver Music Bot — Core YouTube module (Pure yt-dlp & Centralized Cookies Setup)
Resolves YouTube stream URLs, metadata, search queries, and playlists directly via yt-dlp.
"""

import os
import asyncio
import re
import aiohttp
import urllib.parse
from typing import Optional, List, Dict, Any
from config import Config

def load_cookies_from_file(cookie_file: str) -> dict:
    """Parses a Netscape format cookies.txt file and returns a dictionary of cookie names and values."""
    cookies = {}
    if not os.path.exists(cookie_file):
        return cookies
    try:
        with open(cookie_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('#') or not line.strip():
                    continue
                parts = line.strip().split('\t')
                if len(parts) >= 7:
                    domain = parts[0]
                    name = parts[5]
                    value = parts[6]
                    if 'youtube.com' in domain or 'google.com' in domain:
                        cookies[name] = value
    except Exception as e:
        print(f"[Cookies Loader] Error reading cookies: {e}")
    return cookies

# yt-dlp format selectors matching target device specs
YTDLP_AUDIO_FORMAT = "bestaudio/best"
YTDLP_VIDEO_FORMAT = "bestvideo[height<=720][fps<=60]+bestaudio/best[height<=720]/best[height<=720][fps<=60]"

def extract_video_id(url: str) -> Optional[str]:
    """Helper to extract YouTube video ID from various link types."""
    pattern = r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|embed/|v/|shorts/)|youtu\.be/)([^?&#/]+)"
    match = re.search(pattern, url)
    return match.group(1) if match else None

def extract_playlist_id(url: str) -> Optional[str]:
    """Helper to extract YouTube playlist ID from various link types."""
    pattern = r"[?&]list=([a-zA-Z0-9_-]+)"
    match = re.search(pattern, url)
    return match.group(1) if match else None

def blacklist_host(host: str):
    """Dummy blacklist helper for backward compatibility."""
    pass

def is_host_blacklisted(host: str) -> bool:
    """Dummy helper for backward compatibility."""
    return False

COBALT_INSTANCES = [
    "https://api.qwkuns.me",
    "https://cobaltapi.kittycat.boo",
    "https://nuko-c.meowing.de",
    "https://rue-cobalt.xenon.zone",
    "https://api.cobalt.liubquanti.click",
    "https://subito-c.meowing.de",
]

async def resolve_via_cobalt(target_url: str) -> Optional[str]:
    """Resolves direct download URL from Cobalt APIs in parallel for speed & proxy bypass."""
    payload = {"url": target_url, "videoQuality": "720", "downloadMode": "video"}
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        async def check_instance(instance: str) -> Optional[str]:
            try:
                async with session.post(instance, json=payload, timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "error":
                            return None
                        stream_url = data.get("url")
                        if stream_url:
                            return stream_url
            except Exception:
                pass
            return None

        tasks = [asyncio.create_task(check_instance(inst)) for inst in COBALT_INSTANCES]
        for future in asyncio.as_completed(tasks):
            try:
                res = await future
                if res:
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    return res
            except Exception:
                pass
    return None

async def resolve_via_cobalt_audio(target_url: str) -> Optional[str]:
    """Resolves direct audio-only download URL from Cobalt."""
    payload = {"url": target_url, "downloadMode": "audio"}
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
        async def check_instance(instance: str) -> Optional[str]:
            try:
                async with session.post(instance, json=payload, timeout=8) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "error":
                            return None
                        stream_url = data.get("url")
                        if stream_url:
                            return stream_url
            except Exception:
                pass
            return None

        tasks = [asyncio.create_task(check_instance(inst)) for inst in COBALT_INSTANCES]
        for future in asyncio.as_completed(tasks):
            try:
                res = await future
                if res:
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    return res
            except Exception:
                pass
    return None

async def get_youtube_oembed(video_id: str) -> Optional[Dict[str, Any]]:
    """Fetches video metadata (title, author, thumbnail) using official YouTube OEmbed API (never blocked)."""
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "title": data.get("title", "YouTube Video"),
                        "uploader": data.get("author_name", "YouTube Creator"),
                        "thumbnail": data.get("thumbnail_url", f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg")
                    }
    except Exception as e:
        print(f"[OEmbed Scraper] Error: {e}")
    return None

async def search_youtube_http(query: str) -> Optional[Dict[str, Any]]:
    """Backup HTTP scraper to fetch YouTube search results without yt-dlp."""
    encoded_query = urllib.parse.quote(query)
    url = f"https://www.youtube.com/results?search_query={encoded_query}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    video_ids = re.findall(r'"videoId":"([^"]+)"', html)
                    if video_ids:
                        unique_ids = []
                        for vid in video_ids:
                            if vid not in unique_ids:
                                unique_ids.append(vid)
                        first_id = unique_ids[0]
                        
                        title = query
                        title_match = re.search(r'"videoId":"' + re.escape(first_id) + r'".*?"title":\{"runs":\[\{"text":"([^"]+)"', html)
                        if title_match:
                            title = title_match.group(1)
                        else:
                            title_match = re.search(r'"title":\{"runs":\[\{"text":"([^"]+)"\].*?"videoId":"' + re.escape(first_id) + r'"', html)
                            if title_match:
                                title = title_match.group(1)
                                
                        return {
                            "id": first_id,
                            "title": title,
                            "duration": 180,
                            "uploader": "YouTube Search",
                            "thumbnail": f"https://i.ytimg.com/vi/{first_id}/hqdefault.jpg"
                        }
    except Exception as e:
        print(f"[Search HTTP Fallback] Error: {e}")
    return None


PIPED_INSTANCES = [
    "https://api.piped.projectsegfau.lt",
    "https://pipedapi.nosebs.ru",
    "https://piped-api.privacy.com.de",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.kavin.rocks",
]

async def resolve_via_piped(video_id: str) -> Optional[Dict[str, str]]:
    """Resolves stream URLs using public Piped API instances in parallel."""
    url_path = f"/streams/{video_id}"
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        async def check_instance(instance: str) -> Optional[Dict[str, str]]:
            try:
                async with session.get(f"{instance}{url_path}", timeout=8) as resp:
                    print(f"[Piped check {instance}] Status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        video_url = None
                        audio_url = None
                        
                        video_streams = data.get("videoStreams", [])
                        for s in video_streams:
                            # Prefer 480p/720p/360p video
                            if s.get("quality") in ("480p", "360p", "720p") or not video_url:
                                video_url = s.get("url")
                        
                        audio_streams = data.get("audioStreams", [])
                        if audio_streams:
                            audio_url = audio_streams[0].get("url")
                            
                        if video_url or audio_url:
                            return {
                                "video_url": video_url or audio_url,
                                "audio_url": audio_url or video_url
                            }
            except Exception as e:
                print(f"[Piped check {instance}] Error: {e}")
            return None

        tasks = [asyncio.create_task(check_instance(inst)) for inst in PIPED_INSTANCES]
        for future in asyncio.as_completed(tasks):
            try:
                res = await future
                if res:
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    return res
            except Exception:
                pass
    return None

INVIDIOUS_INSTANCES = [
    "https://invidious.yewtu.be",
    "https://vid.konradkraft.de",
    "https://inv.tux.im",
    "https://invidious.flokinet.to",
    "https://invidious.projectsegfau.lt",
]

async def resolve_via_invidious(video_id: str) -> Optional[Dict[str, str]]:
    """Resolves stream URLs using public Invidious API instances in parallel."""
    url_path = f"/api/v1/videos/{video_id}"
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        async def check_instance(instance: str) -> Optional[Dict[str, str]]:
            try:
                async with session.get(f"{instance}{url_path}", timeout=8) as resp:
                    print(f"[Invidious check {instance}] Status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        format_streams = data.get("formatStreams", [])
                        adaptive_formats = data.get("adaptiveFormats", [])
                        
                        video_url = None
                        audio_url = None
                        
                        audio_formats = [f for f in adaptive_formats if f.get("type", "").startswith("audio/")]
                        if audio_formats:
                            audio_url = audio_formats[0].get("url")
                            
                        video_formats = [f for f in format_streams if f.get("container") == "mp4"]
                        if video_formats:
                            video_url = video_formats[0].get("url")
                        elif format_streams:
                            video_url = format_streams[0].get("url")
                            
                        if video_url or audio_url:
                            return {
                                "video_url": video_url or audio_url,
                                "audio_url": audio_url or video_url
                            }
            except Exception as e:
                print(f"[Invidious check {instance}] Error: {e}")
            return None

        tasks = [asyncio.create_task(check_instance(inst)) for inst in INVIDIOUS_INSTANCES]
        for future in asyncio.as_completed(tasks):
            try:
                res = await future
                if res:
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    return res
            except Exception:
                pass
    return None


def extract_live_cookies_via_selenium() -> bool:
    """
    Launches Chrome headless via Selenium, pointing to a copy of the user's logged-in
    profile directory to bypass SingletonLock, navigates to YouTube, and extracts the
    live cookies in Netscape cookies.txt format.
    """
    import shutil
    import time
    import tempfile
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    user_data_dir = getattr(Config, 'CHROME_USER_DATA_DIR', '/root/.config/google-chrome')
    profile_name = getattr(Config, 'CHROME_PROFILE_NAME', 'Default')
    output_file = getattr(Config, 'LIVE_COOKIES_FILE', 'live_cookies.txt')

    print("[Selenium Cookie Exporter] Starting live cookie extraction...")
    
    # 1. Lock-free profile copying to temp directory to bypass SingletonLock
    temp_profile_dir = os.path.join(tempfile.gettempdir(), "chrome_temp_profile")
    temp_default_dir = os.path.join(temp_profile_dir, profile_name)
    
    local_state_src = os.path.join(user_data_dir, "Local State")
    
    # Try modern Chrome path first (Network/Cookies), fall back to legacy (Cookies)
    network_cookies_src = os.path.join(user_data_dir, profile_name, "Network", "Cookies")
    legacy_cookies_src = os.path.join(user_data_dir, profile_name, "Cookies")
    
    cookies_src = None
    cookies_dst = None
    
    if os.path.exists(network_cookies_src):
        cookies_src = network_cookies_src
        cookies_dst = os.path.join(temp_default_dir, "Network", "Cookies")
        os.makedirs(os.path.join(temp_default_dir, "Network"), exist_ok=True)
        print("[Selenium Cookie Exporter] Found modern Chrome Network/Cookies database.")
    elif os.path.exists(legacy_cookies_src):
        cookies_src = legacy_cookies_src
        cookies_dst = os.path.join(temp_default_dir, "Cookies")
        os.makedirs(temp_default_dir, exist_ok=True)
        print("[Selenium Cookie Exporter] Found legacy Chrome Cookies database.")
    else:
        print(f"[Selenium Cookie Exporter] Error: No Cookies database found in profile {profile_name}.")
        return False
        
    # Check if Local State file exists
    if not os.path.exists(local_state_src):
        print(f"[Selenium Cookie Exporter] Error: 'Local State' file not found at: {local_state_src}")
        return False
        
    try:
        # Copy files
        os.makedirs(temp_profile_dir, exist_ok=True)
        shutil.copy2(local_state_src, os.path.join(temp_profile_dir, "Local State"))
        shutil.copy2(cookies_src, cookies_dst)
        print("[Selenium Cookie Exporter] Safely copied profile files to isolated temp path.")
    except Exception as e:
        print(f"[Selenium Cookie Exporter] Error copying profile files: {e}")
        return False

    # 2. Setup Selenium options
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument(f'--user-data-dir={temp_profile_dir}')
    chrome_options.add_argument(f'--profile-directory={profile_name}')
    
    # Stealth parameters to bypass detection
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        
        # Set window size
        driver.set_window_size(1920, 1080)
        
        print("[Selenium Cookie Exporter] Loading https://www.youtube.com ...")
        driver.get("https://www.youtube.com")
        
        # Wait a bit for cookies to load
        time.sleep(2.0)
        
        cookies = driver.get_cookies()
        if not cookies:
            print("[Selenium Cookie Exporter] ❌ Error: No cookies retrieved from DOM.")
            return False
            
        print(f"[Selenium Cookie Exporter] Retrieved {len(cookies)} cookies.")
        
        # Convert and write in Netscape format
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# This file was generated by Selenium cookie exporter\n")
            f.write("# http://curl.haxx.se/rfc/cookie_spec.html\n")
            f.write("# This is a generated file! Do not edit.\n\n")
            for c in cookies:
                domain = c.get('domain', '')
                # Ensure youtube and google domains have a leading dot if they don't already
                if (domain.endswith('youtube.com') or domain.endswith('google.com')) and not domain.startswith('.'):
                    domain = '.' + domain
                
                domain = domain.lower()
                flag = "TRUE" if domain.startswith('.') else "FALSE"
                path = c.get('path', '/')
                secure = "TRUE" if c.get('secure', False) else "FALSE"
                
                expiry_val = c.get('expiry')
                if expiry_val is None:
                    expiry = 2147483647 # Far future / Session cookie fallback (Year 2038)
                else:
                    try:
                        expiry = int(expiry_val)
                    except (ValueError, TypeError):
                        expiry = 2147483647
                        
                name = c.get('name', '')
                value = c.get('value', '')
                f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}\n")
                
        print(f"[Selenium Cookie Exporter] ✅ Success: Saved cookies to {output_file}")
        return True
    except Exception as e:
        print(f"[Selenium Cookie Exporter] ❌ Error during extraction: {e}")
        return False
    finally:
        if driver:
            try:
                driver.quit()
                print("[Selenium Cookie Exporter] Chrome driver closed.")
            except Exception as q_err:
                print(f"[Selenium Cookie Exporter] Warning: Failed to quit driver: {q_err}")


def get_ytdlp_opts(extra_opts: Optional[dict] = None) -> dict:
    """
    Construct standard YoutubeDL options with smart cookie injection.

    Cookie source priority:
      1. Chrome browser via Selenium headless session (live_cookies.txt) — if COOKIE_SOURCE=="chrome"
      2. cookies.txt legacy file — if Chrome/Selenium fails or COOKIE_SOURCE=="file"
      3. No cookies — last resort fallback
    """
    import time
    cookie_source = getattr(Config, 'COOKIE_SOURCE', 'chrome')

    print(f"[yt-dlp config] Cookie source mode: {cookie_source.upper()}")

    # ── Base yt-dlp options ───────────────────────────────────────────────────
    opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'socket_timeout': 30.0,
        'retries': 5,
        'fragment_retries': 5,
        'extractor_retries': 5,
        'source_address': '0.0.0.0',  # Force IPv4 to prevent IPv6 rate-limits
        'extractor_args': {
            'youtube': {
                'client': ['ios']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
        }
    }

    # ── Cookie Injection Logic ────────────────────────────────────────────────
    if cookie_source == 'chrome':
        live_cookies = getattr(Config, 'LIVE_COOKIES_FILE', 'live_cookies.txt')
        is_fresh = False
        if os.path.exists(live_cookies):
            age_seconds = time.time() - os.path.getmtime(live_cookies)
            if age_seconds < 300: # 5 minutes cache
                is_fresh = True
                
        if not is_fresh:
            print("[yt-dlp config] live_cookies.txt is missing or expired. Fetching fresh cookies via Selenium...")
            success = extract_live_cookies_via_selenium()
            if not success and not os.path.exists(live_cookies):
                print("[yt-dlp config] ❌ Selenium extraction failed and no legacy cookies exist.")

        if os.path.exists(live_cookies):
            opts['cookiefile'] = live_cookies
            print(f"[yt-dlp config] ✅ SUCCESS: Chrome browser cookies injected via {live_cookies}.")
        else:
            # Fallback to legacy cookies.txt
            cookies_file = Config.COOKIES_FILE
            if os.path.exists(cookies_file):
                size_kb = os.path.getsize(cookies_file) / 1024
                opts['cookiefile'] = cookies_file
                print(f"[yt-dlp config] ⚠️ FALLBACK: Selenium failed. Using legacy cookies.txt ({size_kb:.1f} KB).")
            else:
                print("[yt-dlp config] ❌ WARNING: No live cookies and no cookies.txt found. Running WITHOUT authentication!")
    else:
        # Legacy mode: use cookies.txt file
        cookies_file = Config.COOKIES_FILE
        cookies_exist = os.path.exists(cookies_file)
        print(f"[yt-dlp config] Cookies file path: {cookies_file}")
        print(f"[yt-dlp config] Cookies file exists: {cookies_exist}")
        if cookies_exist:
            size_kb = os.path.getsize(cookies_file) / 1024
            opts['cookiefile'] = cookies_file
            print(f"[yt-dlp config] ✅ SUCCESS: Injected cookies.txt ({size_kb:.1f} KB).")
        else:
            print("[yt-dlp config] ⚠️ WARNING: Running WITHOUT cookies (file not found).")

    if extra_opts:
        opts.update(extra_opts)
    return opts

def _run_ytdlp_extract(url: str, mode: str) -> Optional[Dict[str, Any]]:
    """Programmatic yt-dlp call to extract direct stream URLs."""
    import yt_dlp
    format_selector = YTDLP_AUDIO_FORMAT if mode == "audio" else YTDLP_VIDEO_FORMAT
    opts = get_ytdlp_opts({
        'format': format_selector,
        'skip_download': True,
        'check_formats': False,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            
            video_url = None
            audio_url = None
            width = info.get('width') or 16
            height = info.get('height') or 9
            
            requested_formats = info.get('requested_formats')
            if requested_formats:
                for f in requested_formats:
                    if f.get('vcodec') != 'none':
                        video_url = f.get('url')
                        width = f.get('width') or width
                        height = f.get('height') or height
                    if f.get('acodec') != 'none':
                        audio_url = f.get('url')
                        
            if not video_url or not audio_url:
                url_extracted = info.get('url')
                if not url_extracted:
                    formats = info.get('formats', [])
                    if formats:
                        url_extracted = formats[-1].get('url')
                        width = formats[-1].get('width') or width
                        height = formats[-1].get('height') or height
                if url_extracted:
                    video_url = video_url or url_extracted
                    audio_url = audio_url or url_extracted
                    
            if video_url or audio_url:
                return {
                    "video_url": video_url or audio_url,
                    "audio_url": audio_url or video_url,
                    "width": width,
                    "height": height
                }
    except Exception as e:
        print(f"[yt-dlp extract] Error extracting stream URLs: {e}")
    return None

async def resolve_ytdlp_stream(video_id: str, mode: str = "audio") -> Optional[Dict[str, str]]:
    """Async wrapper around programmatic yt-dlp extractor with automatic Cobalt API fallback."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    loop = asyncio.get_event_loop()
    res = None
    try:
        res = await asyncio.wait_for(
            loop.run_in_executor(None, _run_ytdlp_extract, url, mode),
            timeout=30.0
        )
    except Exception as e:
        print(f"[yt-dlp] Stream resolution failed/timed out for ID {video_id}: {e}")
        
    if res and (res.get("video_url") or res.get("audio_url")):
        return res
        
    print(f"[youtube fallback] yt-dlp failed to resolve stream for {video_id}. Activating Playwright Multi-site API Scraper fallback...")
    try:
        from core.playwright_extractor import playwright_extract_stream
        pw_url = await playwright_extract_stream(video_id)
        if pw_url:
            print(f"[youtube fallback] SUCCESS: Resolved stream via Multi-site Scraper: {pw_url[:80]}...")
            return {
                "video_url": pw_url,
                "audio_url": pw_url,
                "width": 1280,
                "height": 720
            }
    except Exception as pw_err:
        print(f"[youtube fallback] Multi-site API scraper error: {pw_err}")
        
    print(f"[youtube fallback] Multi-site scraper failed. Activating Cobalt API fallback...")
    try:
        cobalt_url = None
        if mode == "audio":
            cobalt_url = await resolve_via_cobalt_audio(url)
        else:
            cobalt_url = await resolve_via_cobalt(url)
            
        if cobalt_url:
            print(f"[youtube fallback] SUCCESS: Resolved stream via Cobalt API: {cobalt_url[:80]}...")
            return {
                "video_url": cobalt_url,
                "audio_url": cobalt_url,
                "width": 1280,
                "height": 720
            }
    except Exception as cobalt_err:
        print(f"[youtube fallback] Cobalt API fallback error: {cobalt_err}")

    print(f"[youtube fallback] Cobalt failed. Activating Piped API stream fallback for ID {video_id}...")
    try:
        piped_res = await resolve_via_piped(video_id)
        if piped_res:
            print(f"[youtube fallback] SUCCESS: Resolved stream via Piped API: {piped_res['audio_url'][:80]}...")
            return {
                "video_url": piped_res["video_url"],
                "audio_url": piped_res["audio_url"],
                "width": 1280,
                "height": 720
            }
    except Exception as piped_err:
        print(f"[youtube fallback] Piped API fallback error: {piped_err}")

    print(f"[youtube fallback] Piped failed. Activating Invidious API stream fallback for ID {video_id}...")
    try:
        invid_res = await resolve_via_invidious(video_id)
        if invid_res:
            print(f"[youtube fallback] SUCCESS: Resolved stream via Invidious API: {invid_res['audio_url'][:80]}...")
            return {
                "video_url": invid_res["video_url"],
                "audio_url": invid_res["audio_url"],
                "width": 1280,
                "height": 720
            }
    except Exception as invid_err:
        print(f"[youtube fallback] Invidious API fallback error: {invid_err}")
    return None

async def refresh_youtube_stream(video_id: str, mode: str = "audio", quality: str = "480") -> Optional[Dict[str, str]]:
    """Directly refreshes and fetches live stream URLs for the player queue."""
    return await resolve_ytdlp_stream(video_id, mode=mode)

def _run_ytdlp_search(query: str, mode: str) -> Optional[Dict[str, Any]]:
    """Runs a direct YouTube search using ytsearch1:query via yt-dlp."""
    import yt_dlp
    format_selector = YTDLP_AUDIO_FORMAT if mode == "audio" else YTDLP_VIDEO_FORMAT
    opts = get_ytdlp_opts({
        'format': format_selector,
        'skip_download': True,
        'check_formats': False,
        'nplaylist': True,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if not info or 'entries' not in info or not info['entries']:
                return None
            entry = info['entries'][0]
            video_id = entry.get('id')
            title = entry.get('title')
            duration = entry.get('duration') or 0
            uploader = entry.get('uploader', 'Unknown')
            thumbnail = entry.get('thumbnail', f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else "")
            
            video_url = None
            audio_url = None
            width = entry.get('width') or 16
            height = entry.get('height') or 9
            
            requested_formats = entry.get('requested_formats')
            if requested_formats:
                for f in requested_formats:
                    if f.get('vcodec') != 'none':
                        video_url = f.get('url')
                        width = f.get('width') or width
                        height = f.get('height') or height
                    if f.get('acodec') != 'none':
                        audio_url = f.get('url')
                        
            if not video_url or not audio_url:
                url = entry.get('url')
                if not url:
                    formats = entry.get('formats', [])
                    if formats:
                        url = formats[-1].get('url')
                        width = formats[-1].get('width') or width
                        height = formats[-1].get('height') or height
                if url:
                    video_url = video_url or url
                    audio_url = audio_url or url
                    
            if video_url or audio_url:
                return {
                    "id": video_id,
                    "title": title,
                    "duration": duration,
                    "uploader": uploader,
                    "thumbnail": thumbnail,
                    "video_url": video_url or audio_url,
                    "audio_url": audio_url or video_url,
                    "width": width,
                    "height": height
                }
    except Exception as e:
        print(f"[yt-dlp search] Error searching for query '{query}': {e}")
    return None

def _run_ytdlp_direct(url: str, mode: str) -> Optional[Dict[str, Any]]:
    """Runs a direct YouTube video metadata and stream extraction call via yt-dlp."""
    import yt_dlp
    format_selector = YTDLP_AUDIO_FORMAT if mode == "audio" else YTDLP_VIDEO_FORMAT
    opts = get_ytdlp_opts({
        'format': format_selector,
        'skip_download': True,
        'check_formats': False,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None
            video_id = info.get("id")
            video_url = None
            audio_url = None
            requested_formats = info.get('requested_formats')
            if requested_formats:
                for f in requested_formats:
                    if f.get('vcodec') != 'none':
                        video_url = f.get('url')
                    if f.get('acodec') != 'none':
                        audio_url = f.get('url')
            if not video_url or not audio_url:
                url_ext = info.get('url')
                if not url_ext:
                    formats = info.get('formats', [])
                    if formats:
                        url_ext = formats[-1].get('url')
                video_url = video_url or url_ext
                audio_url = audio_url or url_ext
            
            return {
                "title": info.get("title", "YouTube Video"),
                "duration": info.get("duration") or 0,
                "uploader": info.get("uploader", "Unknown"),
                "thumbnail": info.get("thumbnail", f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else ""),
                "video_url": video_url,
                "audio_url": audio_url,
                "width": info.get("width") or 16,
                "height": info.get("height") or 9
            }
    except Exception as e:
        print(f"[yt-dlp direct] Error resolving URL {url}: {e}")
    return None

async def get_video_info(query: str, quality: str = "480") -> Optional[dict]:
    """Query YouTube metadata and streams via direct yt-dlp executor."""
    query = query.strip()
    if not query:
        return None

    print(f"\n[YouTube] Processing request: '{query}'")

    video_id = extract_video_id(query)
    mode = "audio" if quality == "audio" else "video"
    video_url = None
    audio_url = None

    # Pre-check local caching before requesting streams
    if video_id:
        local_video_file = os.path.join("downloads", f"{video_id}_video.mp4")
        local_audio_file = os.path.join("downloads", f"{video_id}_audio.mp4")
        local_file = local_video_file if mode == "video" else local_audio_file
        if os.path.exists(local_file) and os.path.getsize(local_file) > 100000:
            print(f"[YouTube] Found cached local file for ID: {video_id}. Bypassing stream resolution.")
            return {
                "id": video_id,
                "title": "Cached Video",
                "duration": "00:00",
                "duration_secs": 0,
                "uploader": "Cached",
                "thumbnail": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "video_url": "local",
                "audio_url": "local",
                "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
                "width": 16,
                "height": 9
            }

    loop = asyncio.get_event_loop()
    if not video_id:
        # Search Query Path
        try:
            res = await asyncio.wait_for(
                loop.run_in_executor(None, _run_ytdlp_search, query, mode),
                timeout=30.0
            )
        except Exception as e:
            print(f"[YouTube] Search error for query '{query}': {e}")
            res = None
            
        if not res:
            print(f"[youtube fallback] yt-dlp search failed for '{query}'. Activating HTTP Search scraper fallback...")
            search_res = await search_youtube_http(query)
            if search_res:
                vid_id = search_res["id"]
                
                # 1. Multi-site API Scraper
                print(f"[youtube fallback] Scraped video ID {vid_id}. Resolving streams via Multi-site API Scraper...")
                try:
                    from core.playwright_extractor import playwright_extract_stream
                    pw_url = await playwright_extract_stream(vid_id)
                    if pw_url:
                        video_url = pw_url
                        audio_url = pw_url
                except Exception as pw_err:
                    print(f"[youtube fallback] Multi-site API Scraper failed: {pw_err}")

                # 2. Cobalt
                if not audio_url:
                    print(f"[youtube fallback] Multi-site failed. Resolving ID {vid_id} via Cobalt API...")
                    try:
                        if mode == "audio":
                            stream_url = await resolve_via_cobalt_audio(f"https://www.youtube.com/watch?v={vid_id}")
                        else:
                            stream_url = await resolve_via_cobalt(f"https://www.youtube.com/watch?v={vid_id}")
                        if stream_url:
                            video_url = stream_url
                            audio_url = stream_url
                    except Exception as cobalt_err:
                        print(f"[youtube fallback] Cobalt API resolution failed: {cobalt_err}")
                
                # 2. Piped
                if not audio_url:
                    print(f"[youtube fallback] Cobalt failed. Resolving ID {vid_id} via Piped API...")
                    try:
                        piped_res = await resolve_via_piped(vid_id)
                        if piped_res:
                            video_url = piped_res["video_url"]
                            audio_url = piped_res["audio_url"]
                    except Exception as piped_err:
                        print(f"[youtube fallback] Piped API resolution failed: {piped_err}")
                        
                # 3. Invidious
                if not audio_url:
                    print(f"[youtube fallback] Piped failed. Resolving ID {vid_id} via Invidious API...")
                    try:
                        invid_res = await resolve_via_invidious(vid_id)
                        if invid_res:
                            video_url = invid_res["video_url"]
                            audio_url = invid_res["audio_url"]
                    except Exception as invid_err:
                        print(f"[youtube fallback] Invidious API resolution failed: {invid_err}")
                
                if audio_url:
                    res = {
                        "id": vid_id,
                        "title": search_res["title"],
                        "duration": search_res["duration"],
                        "uploader": search_res["uploader"],
                        "thumbnail": search_res["thumbnail"],
                        "video_url": video_url or audio_url,
                        "audio_url": audio_url or video_url,
                        "width": 1280,
                        "height": 720
                    }
        if not res:
            return None

        duration_secs = int(res.get("duration") or 0)
        minutes = duration_secs // 60
        seconds = duration_secs % 60
        return {
            "id": res["id"],
            "title": res["title"],
            "duration": f"{minutes}:{seconds:02d}",
            "duration_secs": duration_secs,
            "uploader": res["uploader"],
            "thumbnail": res["thumbnail"],
            "video_url": res["video_url"],
            "audio_url": res["audio_url"],
            "webpage_url": f"https://www.youtube.com/watch?v={res['id']}",
            "width": res.get("width") or 16,
            "height": res.get("height") or 9
        }
    else:
        # Direct URL Path
        url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            res = await asyncio.wait_for(
                loop.run_in_executor(None, _run_ytdlp_direct, url, mode),
                timeout=30.0
            )
        except Exception as e:
            print(f"[YouTube] Direct resolution error for ID {video_id}: {e}")
            res = None

        if not res:
            print(f"[youtube fallback] yt-dlp direct resolve failed for ID {video_id}. Activating OEmbed/Multi-API fallback...")
            oembed_data = await get_youtube_oembed(video_id)
            
            # 1. Multi-site API Scraper
            try:
                from core.playwright_extractor import playwright_extract_stream
                pw_url = await playwright_extract_stream(video_id)
                if pw_url:
                    video_url = pw_url
                    audio_url = pw_url
            except Exception as pw_err:
                print(f"[youtube fallback] Multi-site API Scraper direct resolve failed: {pw_err}")
                
            # 2. Cobalt
            if not audio_url:
                print(f"[youtube fallback] Multi-site failed. Resolving direct link ID {video_id} via Cobalt...")
                try:
                    if mode == "audio":
                        stream_url = await resolve_via_cobalt_audio(url)
                    else:
                        stream_url = await resolve_via_cobalt(url)
                    if stream_url:
                        video_url = stream_url
                        audio_url = stream_url
                except Exception as cobalt_err:
                    print(f"[youtube fallback] Cobalt direct resolve failed: {cobalt_err}")
                
            # 2. Piped
            if not audio_url:
                print(f"[youtube fallback] Cobalt failed. Resolving direct link ID {video_id} via Piped...")
                try:
                    piped_res = await resolve_via_piped(video_id)
                    if piped_res:
                        video_url = piped_res["video_url"]
                        audio_url = piped_res["audio_url"]
                except Exception as piped_err:
                    print(f"[youtube fallback] Piped direct resolve failed: {piped_err}")
                    
            # 3. Invidious
            if not audio_url:
                print(f"[youtube fallback] Piped failed. Resolving direct link ID {video_id} via Invidious...")
                try:
                    invid_res = await resolve_via_invidious(video_id)
                    if invid_res:
                        video_url = invid_res["video_url"]
                        audio_url = invid_res["audio_url"]
                except Exception as invid_err:
                    print(f"[youtube fallback] Invidious direct resolve failed: {invid_err}")
                
            if audio_url:
                title = oembed_data.get("title", "YouTube Video") if oembed_data else "YouTube Video"
                uploader = oembed_data.get("uploader", "YouTube Creator") if oembed_data else "YouTube Creator"
                thumbnail = oembed_data.get("thumbnail", f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg") if oembed_data else f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                res = {
                    "title": title,
                    "duration": 180,
                    "uploader": uploader,
                    "thumbnail": thumbnail,
                    "video_url": video_url or audio_url,
                    "audio_url": audio_url or video_url,
                    "width": 1280,
                    "height": 720
                }

        if not res:
            return None

        duration_secs = int(res["duration"])
        minutes = duration_secs // 60
        seconds = duration_secs % 60
        return {
            "id": video_id,
            "title": res["title"],
            "duration": f"{minutes}:{seconds:02d}",
            "duration_secs": duration_secs,
            "uploader": res["uploader"],
            "thumbnail": res["thumbnail"],
            "video_url": res["video_url"],
            "audio_url": res["audio_url"],
            "webpage_url": url,
            "width": res.get("width") or 16,
            "height": res.get("height") or 9
        }

def _run_search_list(query: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    """Runs search in yt-dlp flat playlist extraction mode to collect query hits."""
    import yt_dlp
    opts = get_ytdlp_opts({
        'extract_flat': 'in_playlist',
        'skip_download': True,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
            if not info or 'entries' not in info:
                return None
            results = []
            for entry in info['entries']:
                if not entry:
                    continue
                video_id = entry.get('id')
                results.append({
                    "title": entry.get("title", "Unknown Title"),
                    "duration": entry.get("duration", 0),
                    "id": video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
                })
            return results
    except Exception as e:
        print(f"[yt-dlp search list] Error searching: {e}")
    return None

async def search_videos(query: str, limit: int = 5) -> Optional[List[Dict[str, Any]]]:
    """Search videos using yt-dlp search and return a list of query hits."""
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run_search_list, query, limit)
    except Exception:
        return None

def _run_playlist_extract(url: str) -> List[str]:
    """Extracts all video IDs from a YouTube playlist URL using yt-dlp."""
    import yt_dlp
    opts = get_ytdlp_opts({
        'extract_flat': 'in_playlist',
        'skip_download': True,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or 'entries' not in info:
                return []
            return [entry['id'] for entry in info['entries'] if entry and entry.get('id')]
    except Exception as e:
        print(f"[yt-dlp playlist] Error extracting playlist video IDs: {e}")
    return []

async def get_playlist_video_ids(playlist_id: str) -> List[str]:
    """Fetches YouTube playlist page and extracts video IDs using HTML regex parsing with fallback to yt-dlp."""
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    video_ids = []
    
    # 1. Try raw HTML parsing first (fast and doesn't hit Innertube API restrictions)
    try:
        import aiohttp
        # Build cookies dict for the aiohttp session.
        # Try Chrome DB cookies first (via load_cookies_from_file helper on the DB copy),
        # then fall back to loading from cookies.txt if Chrome approach is not active.
        cookies = {}
        cookie_source = getattr(Config, 'COOKIE_SOURCE', 'chrome')
        if cookie_source == 'chrome' and _get_chrome_cookies_safely():
            # We only use load_cookies_from_file for the aiohttp HTTP playlist scraper.
            # The Chrome Cookies DB is not Netscape format so we skip it here and
            # rely on the yt-dlp fallback below if the HTTP scraper fails.
            pass
        elif os.path.exists(Config.COOKIES_FILE):
            cookies = load_cookies_from_file(Config.COOKIES_FILE)
        async with aiohttp.ClientSession(headers=headers, cookies=cookies) as session:
            async with session.get(url, timeout=12) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    found = re.findall(r'\\?"videoId\\?":\\?"([a-zA-Z0-9_-]{11})\\?"', html)
                    seen = set()
                    for vid in found:
                        if vid not in seen:
                            seen.add(vid)
                            video_ids.append(vid)
    except Exception as e:
        print(f"[Playlist HTML] Regex parsing failed: {e}")
        
    if video_ids:
        print(f"[Playlist] HTML parsed successfully! Found {len(video_ids)} videos.")
        return video_ids
        
    # 2. Fall back to yt-dlp extraction (which works if cookies are supplied or IP is clean)
    print("[Playlist] HTML parsing failed or empty. Falling back to yt-dlp...")
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(None, _run_playlist_extract, url)
    except Exception as e:
        print(f"[Playlist yt-dlp] Fallback extraction failed: {e}")
    return []
