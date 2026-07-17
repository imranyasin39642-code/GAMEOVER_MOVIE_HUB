"""
Multi-site YouTube stream extractor using internal REST APIs.
No Playwright/headless browser needed — each site has a clean internal API
that works exactly like what their browser JS calls behind the scenes.

IMPORTANT: Uses DNS-over-HTTPS (DoH) connector to bypass broken VPS system DNS.
"""

import asyncio
import re
import json
import urllib.parse
from typing import Optional
import aiohttp
from core.dns_helper import get_doh_connector

# ─── SITES TO TRY ──────────────────────────────────────────────────────────────
EXTRACTOR_SITES = [
    "yt5s",         # yt5s.in — multiple endpoints
    "yt1s",         # yt1s.com — sister site to yt5s
    "y2mate",       # y2mate.com
    "ytmp3",        # ytmp3.cc — very clean API
    "9xbuddy",      # 9xbuddy.app
]

# ─── MAIN ENTRY POINT ──────────────────────────────────────────────────────────
async def playwright_extract_stream(video_id: str) -> Optional[str]:
    """
    Main entry point. Tries all configured sites in order.
    Returns the direct .mp4 download URL on success, None on failure.
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"[Scraper] Starting multi-site extraction for: {video_url}")

    extractors = {
        "yt5s":    _extract_yt5s,
        "yt1s":    _extract_yt1s,
        "y2mate":  _extract_y2mate,
        "ytmp3":   _extract_ytmp3,
        "9xbuddy": _extract_9xbuddy,
    }

    for site in EXTRACTOR_SITES:
        try:
            fn = extractors.get(site)
            if not fn:
                continue
            result = await fn(video_url)
            if result:
                print(f"[Scraper] SUCCESS via {site}! URL: {result[:80]}...")
                return result
        except Exception as e:
            print(f"[Scraper] Site {site} failed: {e}")

    print("[Scraper] All sites failed.")
    return None


# ─── EXTRACTOR: yt5s ─────────────────────────────────────────────────────────
async def _extract_yt5s(video_url: str) -> Optional[str]:
    """yt5s.in — two-step: search then convert (DoH-enabled)"""
    domains = ["yt5s.in", "yt5s.com", "yt5s.io"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }

    # Each attempt creates a fresh DoH connector so we always get DoH DNS
    for domain in domains:
        connector = get_doh_connector()
        try:
            h = {**headers, "Origin": f"https://{domain}", "Referer": f"https://{domain}/"}
            async with aiohttp.ClientSession(connector=connector) as session:
                search_url = f"https://{domain}/api/ajaxSearch/index"
                payload = f"query={urllib.parse.quote(video_url)}&vt=mp4"

                print(f"[Scraper/yt5s] Trying {domain}...")
                async with session.post(
                    search_url, data=payload, headers=h,
                    timeout=aiohttp.ClientTimeout(total=12)
                ) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                    if not text.strip():
                        continue
                    try:
                        data = json.loads(text)
                    except Exception:
                        continue

                    if data.get("status") != "ok":
                        continue

                    links_html = data.get("links", "")
                    fid_match = re.search(r'data-fid="([^"]+)"', links_html)
                    if not fid_match:
                        continue
                    fid = fid_match.group(1)

                    # Find the best quality mp4 key
                    k_match = (
                        re.search(r'data-ftype="mp4"[^>]*data-fquality="720"[^>]*data-k="([^"]+)"', links_html)
                        or re.search(r'data-ftype="mp4"[^>]*data-fquality="480"[^>]*data-k="([^"]+)"', links_html)
                        or re.search(r'data-ftype="mp4"[^>]*data-k="([^"]+)"', links_html)
                    )
                    if not k_match:
                        continue

                    k_val = k_match.group(1)
                    print(f"[Scraper/yt5s] Got fid, converting on {domain}...")

                    convert_url = f"https://{domain}/api/ajaxConvert/convert"
                    convert_payload = f"vid={fid}&k={k_val}"
                    async with session.post(
                        convert_url, data=convert_payload, headers=h,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as c_resp:
                        if c_resp.status == 200:
                            c_text = await c_resp.text()
                            try:
                                c_data = json.loads(c_text)
                                if c_data.get("status") == "ok":
                                    dl = c_data.get("dlink")
                                    if dl:
                                        return dl
                            except Exception:
                                pass
        except Exception as e:
            print(f"[Scraper/yt5s] {domain} error: {e}")
        finally:
            await connector.close()
    return None


# ─── EXTRACTOR: yt1s ─────────────────────────────────────────────────────────
async def _extract_yt1s(video_url: str) -> Optional[str]:
    """yt1s.com — sister site with similar API (DoH-enabled)"""
    domains = ["yt1s.com", "yt1s.io"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }

    for domain in domains:
        connector = get_doh_connector()
        try:
            h = {**headers, "Referer": f"https://{domain}/"}
            async with aiohttp.ClientSession(connector=connector) as session:
                search_url = f"https://{domain}/api/ajaxSearch"
                payload = f"query={urllib.parse.quote(video_url)}&vt=mp4"

                print(f"[Scraper/yt1s] Trying {domain}...")
                async with session.post(
                    search_url, data=payload, headers=h,
                    timeout=aiohttp.ClientTimeout(total=12)
                ) as resp:
                    if resp.status != 200:
                        continue
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        continue

                    if data.get("status") != "ok":
                        continue

                    links = data.get("links", {})
                    vid = data.get("vid") or data.get("id")
                    mp4_links = links.get("mp4", {})
                    k_val = None
                    for q in ["720p", "480p", "360p"]:
                        if q in mp4_links:
                            k_val = mp4_links[q].get("k") or mp4_links[q].get("f")
                            if k_val:
                                break

                    if not k_val or not vid:
                        continue

                    convert_url = f"https://{domain}/api/ajaxConvert"
                    convert_payload = f"vid={vid}&k={k_val}"
                    async with session.post(
                        convert_url, data=convert_payload, headers=h,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as c_resp:
                        if c_resp.status == 200:
                            try:
                                c_data = await c_resp.json(content_type=None)
                                dl = c_data.get("dlink") or c_data.get("url")
                                if dl:
                                    return dl
                            except Exception:
                                pass
        except Exception as e:
            print(f"[Scraper/yt1s] {domain} error: {e}")
        finally:
            await connector.close()
    return None


# ─── EXTRACTOR: y2mate ───────────────────────────────────────────────────────
async def _extract_y2mate(video_url: str) -> Optional[str]:
    """y2mate.com — analyze then convert (DoH-enabled)"""
    domains = ["www.y2mate.com", "y2mate.is", "y2mate.nu"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }

    print(f"[Scraper/y2mate] Trying y2mate variants...")
    for domain in domains:
        connector = get_doh_connector()
        try:
            h = {**headers, "Referer": f"https://{domain}/"}
            async with aiohttp.ClientSession(connector=connector) as session:
                analyze_url = f"https://{domain}/mates/en/analyze/ajax"
                analyze_payload = f"url={urllib.parse.quote(video_url)}&q_auto=0&ajax=1"

                async with session.post(
                    analyze_url, data=analyze_payload, headers=h,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        continue
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        continue

                    vid = data.get("vid")
                    if not vid:
                        continue

                    links = data.get("links", {})
                    mp4_links = links.get("mp4", {})
                    k_val = None
                    for quality in ["720p", "480p", "360p"]:
                        if quality in mp4_links:
                            k_val = mp4_links[quality].get("k")
                            if k_val:
                                print(f"[Scraper/y2mate] Found {quality} key from {domain}")
                                break

                    if not k_val:
                        continue

                    convert_url = f"https://{domain}/mates/en/convert"
                    convert_payload = f"vid={vid}&k={k_val}"
                    async with session.post(
                        convert_url, data=convert_payload, headers=h,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as c_resp:
                        if c_resp.status == 200:
                            try:
                                c_data = await c_resp.json(content_type=None)
                                dl_url = c_data.get("dlink")
                                if dl_url:
                                    return dl_url
                            except Exception:
                                pass
        except Exception as e:
            print(f"[Scraper/y2mate] {domain} error: {e}")
        finally:
            await connector.close()
    return None


# ─── EXTRACTOR: ytmp3 ────────────────────────────────────────────────────────
async def _extract_ytmp3(video_url: str) -> Optional[str]:
    """ytmp3.cc — single-step GET API (DoH-enabled)"""
    domains = ["ytmp3.cc", "ytmp3.nu", "ytmp3.su"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    print(f"[Scraper/ytmp3] Trying ytmp3 variants...")
    for domain in domains:
        connector = get_doh_connector()
        try:
            async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
                api_url = f"https://{domain}/api/json/mp4?url={urllib.parse.quote(video_url)}"
                async with session.get(
                    api_url, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status != 200:
                        continue
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        continue
                    dl = data.get("url") or data.get("dlink") or data.get("download_url")
                    if dl and dl.startswith("http"):
                        print(f"[Scraper/ytmp3] Found link from {domain}!")
                        return dl
        except Exception as e:
            print(f"[Scraper/ytmp3] {domain} error: {e}")
        finally:
            await connector.close()
    return None


# ─── EXTRACTOR: 9xbuddy ──────────────────────────────────────────────────────
async def _extract_9xbuddy(video_url: str) -> Optional[str]:
    """9xbuddy.app — process API (DoH-enabled)"""
    domains = ["9xbuddy.app", "9xbuddy.in", "9xbuddy.com"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    }

    print(f"[Scraper/9xbuddy] Trying 9xbuddy variants...")
    for domain in domains:
        connector = get_doh_connector()
        try:
            h = {**headers, "Referer": f"https://{domain}/"}
            async with aiohttp.ClientSession(headers=h, connector=connector) as session:
                encoded = urllib.parse.quote(video_url)
                api_url = f"https://{domain}/process?url={encoded}"

                async with session.get(
                    api_url, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text()
                    if not text or not text.strip() or text.strip().startswith("<"):
                        continue
                    try:
                        data = json.loads(text)
                    except Exception:
                        continue
                    download_links = data.get("download", [])
                    for link in download_links:
                        label = str(link.get("label", "")).lower()
                        url = link.get("url", "")
                        if ("720" in label or "480" in label) and url.startswith("http"):
                            print(f"[Scraper/9xbuddy] Found {link.get('label')} from {domain}!")
                            return url
                    # Fallback to first available link
                    if download_links and download_links[0].get("url", "").startswith("http"):
                        return download_links[0]["url"]
        except Exception as e:
            print(f"[Scraper/9xbuddy] {domain} error: {e}")
        finally:
            await connector.close()
    return None


# ─── FULL HEADLESS PLAYWRIGHT (Nuclear Option) ───────────────────────────────
async def playwright_headless_extract(video_id: str) -> Optional[str]:
    """
    True headless browser extraction using Playwright.
    Used as a last resort when all API-based scrapers fail.

    Requires: pip install playwright && playwright install chromium
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[Playwright/Headless] playwright not installed.")
        return None

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"[Playwright/Headless] Launching headless Chromium for: {video_url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        captured_url = {"value": None}

        async def capture_download(request):
            url = request.url
            if any(x in url for x in [".mp4", "download", "cdn", "googlevideo"]):
                if not captured_url["value"]:
                    captured_url["value"] = url

        page = await context.new_page()
        try:
            await page.goto("https://yt5s.in/", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1)
            input_sel = "input#s-input, input[name='url'], input[type='text']"
            await page.wait_for_selector(input_sel, timeout=10000)
            await page.fill(input_sel, video_url)
            await asyncio.sleep(0.5)
            btn_sel = "button#s-btn, button[type='submit'], form button"
            await page.click(btn_sel)
            await asyncio.sleep(5)
            dl_selectors = ["a[href*='.mp4']", "button[data-fquality='720']", "a.download-btn"]
            for sel in dl_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        href = await el.get_attribute("href")
                        if href and href.startswith("http"):
                            return href
                except Exception:
                    pass
        except Exception as e:
            print(f"[Playwright/Headless] Page interaction failed: {e}")
        finally:
            await browser.close()
    return None
