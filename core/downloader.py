"""
🎮 GameOver Music Bot — Asynchronous Downloader & Stream Merger
Downloads YouTube and MovieBox streams natively at 480p @ 60 FPS to minimize server CPU usage,
and merges split streams using FFmpeg with PTS reconstruction to ensure perfect lip-sync.
"""

import os
import time
import asyncio
import aiohttp
import socket
from typing import Optional, Callable, Awaitable
from core.queue_manager import SongInfo

# Force 30-second socket timeout globally
socket.setdefaulttimeout(30.0)
from config import Config

DOWNLOADS_DIR = Config.DOWNLOADS_DIR

# Ensure downloads directory exists
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Strictly locks download formats to native 1080p @ 60 FPS max
YTDLP_AUDIO_FORMAT = "bestaudio/best"
YTDLP_VIDEO_FORMAT = "bestvideo[height<=1080][fps<=60]+bestaudio/best[height<=1080]/best[height<=1080][fps<=60]"

async def download_file(url: str, dest_path: str, progress_callback: Optional[Callable[[int, int, int], Awaitable[None]]] = None, headers: Optional[dict] = None) -> bool:
    """Asynchronously download a URL to a file with progress updates, supporting Range resume and retries."""
    loop = asyncio.get_running_loop()
    if not headers:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    else:
        headers = dict(headers)
        
    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except Exception:
            pass

    max_retries = 5
    total_size = 0
    downloaded = 0
    
    start_time = time.time()
    last_update_time = time.time()
    last_console_time = 0
    last_percent = 0

    timeout = aiohttp.ClientTimeout(total=None, connect=30, sock_read=60)
    for attempt in range(1, max_retries + 1):
        connector = aiohttp.TCPConnector(ssl=False)
        try:
            # Only support Range resume for VOD downloads (non-YouTube, non-scraped streams)
            is_scraped = any(domain in url for domain in ("cobalt", "piped", "invidious", "loader.to", "savefrom", "sf-helper", "youtube", "youtu.be"))
            existing_bytes = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
            
            if existing_bytes > 0 and not is_scraped:
                headers["Range"] = f"bytes={existing_bytes}-"
                file_mode = "ab"
                print(f"[Downloader] Resuming VOD download from byte {existing_bytes} (Attempt {attempt}/{max_retries})...")
            else:
                if "Range" in headers:
                    del headers["Range"]
                file_mode = "wb"
                # If it's a retry and we are starting over, clean the file first to prevent corruption
                if attempt > 1 and os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except:
                        pass
                print(f"[Downloader] Starting VOD download (Attempt {attempt}/{max_retries})...")

            async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
                async with session.get(url, timeout=timeout, allow_redirects=True) as response:
                    if response.status not in (200, 206):
                        if response.status == 416:
                            print(f"[Downloader] Status 416 received. File might be fully downloaded already.")
                            return True
                        print(f"[Downloader] Bad status code {response.status} for URL: {url[:60]}")
                        raise Exception(f"HTTP Status {response.status}")

                    if existing_bytes == 0 or is_scraped:
                        total_size = int(response.headers.get('content-length', 0))
                    else:
                        content_range = response.headers.get('Content-Range', '')
                        if '/' in content_range:
                            try:
                                total_size = int(content_range.split('/')[-1])
                            except Exception:
                                pass
                        if not total_size:
                            partial_length = int(response.headers.get('content-length', 0))
                            total_size = existing_bytes + partial_length

                    total_size_mb = total_size / (1024 * 1024)
                    downloaded = 0 if is_scraped else existing_bytes

                    with open(dest_path, file_mode) as f:
                        async for chunk in response.content.iter_chunked(128 * 1024):  # 128KB chunks
                            await loop.run_in_executor(None, f.write, chunk)
                            downloaded += len(chunk)

                            now = time.time()
                            elapsed = now - start_time
                            if elapsed <= 0:
                                elapsed = 0.01
                            speed_bps = downloaded / elapsed
                            speed_mb = speed_bps / (1024 * 1024)
                            downloaded_mb = downloaded / (1024 * 1024)

                            if speed_bps > 0 and total_size > 0:
                                remaining_bytes = total_size - downloaded
                                seconds_left = max(0, int(remaining_bytes / speed_bps))
                                time_left_str = f"{seconds_left}s"
                            else:
                                time_left_str = "calculating..."

                            if now - last_console_time >= 0.5 or downloaded == total_size:
                                percent = int((downloaded / total_size) * 100) if total_size > 0 else 0
                                print(f"[Console Downloader] -> {percent}% | {downloaded_mb:.2f}/{total_size_mb:.2f} MB | Speed: {speed_mb:.2f} MB/s | ETA: {time_left_str}  ", end="\r", flush=True)
                                last_console_time = now

                            if progress_callback:
                                percent = int((downloaded / total_size) * 100) if total_size > 0 else 0
                                if now - last_update_time >= 2.0 or (total_size > 0 and percent - last_percent >= 15) or (total_size == 0 and downloaded - last_percent >= 2097152):
                                    await progress_callback(percent, downloaded, total_size)
                                    last_update_time = now
                                    last_percent = percent if total_size > 0 else downloaded

                    if total_size > 0 and downloaded < total_size:
                        raise Exception(f"Downloaded bytes {downloaded} is less than total expected {total_size}")
                    
                    if downloaded < 100000:
                        raise Exception(f"Downloaded file size too small ({downloaded} bytes). Request likely rate-limited or blocked.")

                    print()  # Finalize carriage return line
                    if progress_callback:
                        await progress_callback(100, downloaded, total_size)
                    return True

        except Exception as e:
            print(f"\n[Downloader] Attempt {attempt} failed: {e}")
            
            # Temporary blacklist the host if it's a scraped stream and it fails
            from urllib.parse import urlparse
            from core.youtube import blacklist_host
            host = urlparse(url).netloc
            if host and is_scraped:
                blacklist_host(host)
                # Abort immediately if host is blacklisted (don't retry same URL)
                break
                
            if attempt == max_retries:
                break
            await asyncio.sleep(2)

    print(f"[Downloader] VOD download failed after {max_retries} attempts.")
    if os.path.exists(dest_path):
        try:
            os.remove(dest_path)
        except Exception:
            pass
    return False

async def merge_video_audio(video_path: str, audio_path: str, output_path: str) -> bool:
    """
    Merge separate video and audio files using FFmpeg without re-encoding (copy streams).
    Applies +genpts to reconstruct missing presentation timestamps for perfect audio/video Lip-Sync.
    """
    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts", # Reconstruct timestamps to avoid audio-video drift
        "-i", video_path,
        "-i", audio_path,
        "-c", "copy",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-shortest", # Terminate output when shortest input ends
        output_path
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        return process.returncode == 0
    except Exception as e:
        print(f"[Downloader] FFmpeg merge error: {e}")
        return False

async def download_youtube_ytdlp(song: SongInfo, output_path: str, mode: str, progress_callback: Optional[Callable[[int, int, int], Awaitable[None]]] = None) -> bool:
    """Downloads YouTube streams natively using yt-dlp to bypass severe rate-limiting/throttling."""
    import yt_dlp
    from functools import partial
    
    loop = asyncio.get_event_loop()
    last_update_time = [time.time()]
    last_percent = [0]
    
    def ytdlp_hook(d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            pct = int((downloaded / total) * 100) if total > 0 else 0
            
            now = time.time()
            if now - last_update_time[0] >= 2.0 or pct - last_percent[0] >= 15:
                if progress_callback:
                    asyncio.run_coroutine_threadsafe(
                        progress_callback(pct, downloaded, total),
                        loop
                    )
                last_update_time[0] = now
                last_percent[0] = pct
                
            speed = d.get('speed', 0) or 0
            speed_mb = speed / (1024 * 1024)
            eta = d.get('eta', 0) or 0
            eta_str = f"~{eta}s" if eta else "calculating..."
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total / (1024 * 1024) if total else 0
            print(f"[Console Downloader] -> {pct}% | {downloaded_mb:.2f}/{total_mb:.2f} MB | Speed: {speed_mb:.2f} MB/s | ETA: {eta_str}  ", end="\r", flush=True)
            
        elif d['status'] == 'finished':
            print("\n[Downloader] yt-dlp download finished, processing post-processing/merging...")
            
    if ".m3u8" in song.video_url.lower() or "m3u8" in song.video_url.lower():
        format_spec = "best/best[height<=1080]"
    else:
        format_spec = YTDLP_AUDIO_FORMAT if mode == "audio" else YTDLP_VIDEO_FORMAT
    outtmpl = output_path.rsplit('.', 1)[0] + '.%(ext)s'
    
    from core.domain_manager import get_domain
    domain = get_domain()
    
    ydl_opts = {
        'format': format_spec,
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [ytdlp_hook],
        'merge_output_format': 'mp4',
        'socket_timeout': 30.0,
        'retries': 5,
        'fragment_retries': 5,
        'extractor_retries': 5,
        'nocheckcertificate': True,
        'source_address': '0.0.0.0', # Force IPv4
        'extractor_args': {
            'youtube': {
                'client': ['ios']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Origin': f'https://{domain}',
            'Referer': f'https://{domain}/'
        }
    }

    cookies_file = Config.COOKIES_FILE
    cookies_exist = os.path.exists(cookies_file)
    print(f"[Downloader config] Centralized Cookies File Path: {cookies_file}")
    print(f"[Downloader config] Cookies File Exists: {cookies_exist}")
    
    if cookies_exist:
        ydl_opts['cookiefile'] = cookies_file
        print("[Downloader config] SUCCESS: Injected cookies file path into YoutubeDL options.")
    else:
        print("[Downloader config] WARNING: Running WITHOUT cookies (file not found).")

    
    def run():
        url_to_download = song.webpage_url
        try:
            print(f"[Downloader] Natively downloading webpage_url: {url_to_download}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url_to_download])
        except Exception as primary_err:
            print(f"[Downloader] Natively downloading webpage_url failed: {primary_err}")
            fallback_url = song.video_url if mode == "video" else song.audio_url
            if fallback_url and fallback_url != "local" and not fallback_url.startswith("downloads"):
                print(f"[Downloader] Attempting download of direct stream URL fallback: {fallback_url[:80]}...")
                opts_fallback = ydl_opts.copy()
                opts_fallback.pop('format', None) # direct URL doesn't need format selector
                # Direct URLs might fail with customized YouTube headers, so let's use default headers
                opts_fallback['http_headers'] = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
                with yt_dlp.YoutubeDL(opts_fallback) as ydl_fallback:
                    ydl_fallback.download([fallback_url])
            else:
                raise primary_err
            
    try:
        await loop.run_in_executor(None, run)
        
        # In case the file was not named exactly output_path, find the correct file and rename it
        clean_id = os.path.basename(output_path).rsplit('_', 1)[0]
        if not os.path.exists(output_path):
            found_file = None
            for file in os.listdir(DOWNLOADS_DIR):
                if file.startswith(f"{clean_id}_{mode}.") and not file.endswith(".part") and not file.endswith(".ytdl"):
                    found_file = os.path.join(DOWNLOADS_DIR, file)
                    break
            if found_file:
                os.rename(found_file, output_path)
                print(f"[Downloader] Renamed {found_file} to final {output_path}")
                
        if progress_callback and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            await progress_callback(100, size, size)
            
        return os.path.exists(output_path)
    except Exception as e:
        print(f"[Downloader] Programmatic yt-dlp download error: {e}")
        return False

async def download_song(song: SongInfo, mode: str = "audio", progress_callback: Optional[Callable[[int, int, int], Awaitable[None]]] = None) -> Optional[str]:
    """
    Downloads the song video/audio files locally and returns the local file path.
    If split streams exist, downloads both and merges them using FFmpeg with strict lip-sync.
    """
    # Extract a safe clean ID from the webpage URL
    if "v=" in song.webpage_url:
        clean_id = song.webpage_url.split("v=")[-1].split("&")[0]
    elif "youtu.be/" in song.webpage_url:
        clean_id = song.webpage_url.split("youtu.be/")[-1].split("?")[0]
    else:
        clean_id = song.webpage_url.split("/")[-1].split("?")[0]
    clean_id = "".join(c for c in clean_id if c.isalnum() or c in ("-", "_"))
    if not clean_id:
        clean_id = str(abs(hash(song.title)))
        
    output_filename = f"{clean_id}_{mode}.mp4"
    output_path = os.path.join(DOWNLOADS_DIR, output_filename)
    
    # Return path if file is already cached/downloaded and valid
    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        if size > 100000:
            print(f"[Downloader] File already downloaded and valid: {output_path} ({size / (1024*1024):.2f} MB)")
            if progress_callback:
                try:
                    await progress_callback(100, size, size)
                except Exception as cb_err:
                    print(f"[Downloader] Error in cached progress callback: {cb_err}")
            return output_path
        else:
            print(f"[Downloader] Deleting corrupted/invalid cached file (size {size} <= 100KB): {output_path}")
            try:
                os.remove(output_path)
            except Exception:
                pass
        
    # ── YouTube / HLS (.m3u8) Download via yt-dlp ──────────────────────────
    is_youtube = "youtube.com" in song.webpage_url or "youtu.be" in song.webpage_url or "youtube" in song.webpage_url
    is_m3u8 = ".m3u8" in song.video_url.lower() or "m3u8" in song.video_url.lower()
    
    # Determine if we have a truly direct downloadable URL (Cobalt tunnel = direct, Piped/Invidious manifest = NOT direct)
    target_url = song.audio_url if mode == "audio" else song.video_url
    
    # Piped, Invidious, yt-dlp manifest URLs are stream manifests — not downloadable directly
    # Only Cobalt URLs are genuine direct download links
    is_cobalt_direct = target_url and (
        "cobalt" in target_url or 
        "qwkuns.me" in target_url or
        "kittycat.boo" in target_url or
        "meowing.de" in target_url or
        "xenon.zone" in target_url or
        "liubquanti.click" in target_url or
        "cobaltapi" in target_url
    )
    
    if is_youtube or is_m3u8:
        if not is_cobalt_direct:
            # Always use yt-dlp for YouTube — it handles stream formats, throttling bypass, and cookies
            print(f"[Downloader] YouTube yt-dlp download initiated for: {song.title} (mode={mode}, HLS={is_m3u8})")
            ok = await download_youtube_ytdlp(song, output_path, mode, progress_callback)
            if ok and os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
                return output_path
            print(f"[Downloader] yt-dlp download failed or file too small. Trying multi-site scraper fallback...")
        else:
            print(f"[Downloader] Cobalt direct URL detected. Downloading directly: {target_url[:80]}...")

        # Scraper fallback: refresh stream URLs from Piped/Invidious/Cobalt
        from core.youtube import extract_video_id, refresh_youtube_stream
        video_id = extract_video_id(song.webpage_url)
        if video_id:
            fresh = await refresh_youtube_stream(video_id, mode=mode, quality=getattr(song, 'quality', '480'))
            if fresh:
                print(f"[Downloader] Scraper fallback resolved new URL: {fresh.get('video_url' if mode == 'video' else 'audio_url', '')[:80]}...")
                song.video_url = fresh.get('video_url', '')
                song.audio_url = fresh.get('audio_url', '')
                target_url = song.audio_url if mode == "audio" else song.video_url
            else:
                print(f"[Downloader] All fallbacks exhausted. Cannot download: {song.title}")
                return None
        else:
            return None

    # Check if this is a scraped YouTube stream link or VOD to apply referer headers
    download_headers = None
    target_url = song.audio_url if mode == "audio" else song.video_url
    if target_url:
        if "savenow.to" in target_url or "loader.to" in target_url:
            download_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://loader.to/",
                "Origin": "https://loader.to"
            }
        elif "sf-helper" in target_url or "savefrom" in target_url:
            download_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://en.savefrom.net/",
                "Origin": "https://en.savefrom.net"
            }
        elif getattr(song, "uploader", None) == "MOVIES Engine" or song.duration == "VOD":
            download_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://themoviebox.org",
                "Referer": "https://themoviebox.org/",
                "Sec-Fetch-Dest": "video",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "cross-site"
            }

    # Same source URL for video and audio (unified container)
    if song.video_url == song.audio_url:
        target_url = song.audio_url if mode == "audio" else song.video_url
        print(f"[Downloader] Downloading unified stream for: {song.title}")
        ok = await download_file(target_url, output_path, progress_callback, headers=download_headers)
        if ok:
            return output_path

        # If download failed (e.g. 502/403), re-resolve the stream and retry once
        print(f"[Downloader] Direct download failed (possible 502/403). Re-resolving stream...")
        from core.youtube import extract_video_id, refresh_youtube_stream
        video_id = extract_video_id(song.webpage_url)
        if video_id:
            fresh = await refresh_youtube_stream(video_id, mode=mode, quality=getattr(song, 'quality', '480'))
            if fresh:
                new_url = fresh.get('audio_url') if mode == 'audio' else fresh.get('video_url')
                if new_url and new_url != target_url:
                    print(f"[Downloader] Got fresh URL, retrying download: {new_url[:80]}...")
                    ok2 = await download_file(new_url, output_path, progress_callback, headers=None)
                    return output_path if ok2 else None
        return None
        
    # Split source URLs (e.g. separate formats)
    if mode == "audio":
        print(f"[Downloader] Downloading audio stream for: {song.title}")
        ok = await download_file(song.audio_url, output_path, progress_callback, headers=download_headers)
        return output_path if ok else None
    else:
        # Video mode requires downloading both tracks and merging with PTS alignment
        print(f"[Downloader] Downloading split video/audio streams for: {song.title}")
        temp_v = os.path.join(DOWNLOADS_DIR, f"{clean_id}_temp_v.mp4")
        temp_a = os.path.join(DOWNLOADS_DIR, f"{clean_id}_temp_a.mp4")
        
        try:
            # Step 1: Download Video Track (70% of progress display)
            print("[Downloader] Downloading video track...")
            async def v_cb(pct, down, tot):
                if progress_callback:
                    await progress_callback(int(pct * 0.7), down, tot)
            v_ok = await download_file(song.video_url, temp_v, v_cb, headers=download_headers)
            if not v_ok:
                return None
                
            # Step 2: Download Audio Track (25% of progress display)
            print("[Downloader] Downloading audio track...")
            async def a_cb(pct, down, tot):
                if progress_callback:
                    await progress_callback(70 + int(pct * 0.25), down, tot)
            a_ok = await download_file(song.audio_url, temp_a, a_cb, headers=download_headers)
            if not a_ok:
                return None
                
            # Step 3: Merge Tracks with Lip-Sync alignment
            print("[Downloader] Merging tracks with FFmpeg copy...")
            if progress_callback:
                await progress_callback(96, 0, 0)
                
            merge_ok = await merge_video_audio(temp_v, temp_a, output_path)
            if progress_callback:
                await progress_callback(100 if merge_ok else 0, 0, 0)
                
            return output_path if merge_ok else None
            
        finally:
            # Cleanup temp split files
            for f in (temp_v, temp_a):
                if os.path.exists(f):
                    try:
                        os.remove(f)
                    except:
                        pass

def clean_cached_file(file_path: Optional[str]):
    """Removes the downloaded file from the filesystem to ensure 0% storage bloat."""
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            print(f"[Downloader] Deleted local cached file: {file_path}")
        except Exception as e:
            print(f"[Downloader] Error deleting file {file_path}: {e}")
