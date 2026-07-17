"""
🎬 Trending & Latest Movies Manager
Fetches trending content from the MovieBox homepage, checks for Hindi versions,
and caches results to SQLite to ensure zero-latency replies.
"""

import asyncio
import time
from moviebox_api.v2 import Session, Homepage
from core.domain_manager import detect_working_domain
from core.db import save_cached_trending_items, get_cached_trending_items, get_setting, set_setting
from core.vod_scraper import search_hindi_version

# Background lock to prevent concurrent fetches
_update_lock = asyncio.Lock()

async def update_trending_cache():
    """Fetch popular items from Homepage API, detect Hindi availability in parallel, and cache them."""
    async with _update_lock:
        print("[TrendingManager] Fetching latest trending content from MovieBox...")
        try:
            # 1. Ensure working mirror is initialized
            await detect_working_domain()
            
            # 2. Get Homepage model
            session = Session()
            homepage = Homepage(session=session)
            content = await homepage.get_content_model()
            if not content or not content.operatingList:
                print("[TrendingManager] Homepage list empty or unreachable.")
                return False

            # Extract popular items
            pop_movies_category = next((op for op in content.operatingList if op.title == "Popular Movie"), None)
            pop_series_category = next((op for op in content.operatingList if op.title == "Popular Series"), None)

            # Limit categories to top 10 items each
            movies = pop_movies_category.subjects[:10] if pop_movies_category and pop_movies_category.subjects else []
            series = pop_series_category.subjects[:10] if pop_series_category and pop_series_category.subjects else []

            # 3. Process items and verify Hindi availability in parallel
            async def process_item(item):
                title = str(item.title)
                clean_title = title.replace("[Hindi]", "").replace("[English]", "").strip()
                has_hindi = "hindi" in title.lower()
                
                # If title doesn't explicitly mention Hindi, check if a dubbed version exists
                if not has_hindi:
                    try:
                        hindi_ver = await search_hindi_version(session, clean_title)
                        if hindi_ver:
                            has_hindi = True
                    except Exception:
                        pass
                
                # Parse release date to year
                year = ""
                if getattr(item, "releaseDate", None):
                    date_str = str(item.releaseDate)
                    if "-" in date_str:
                        year = date_str.split("-")[0]
                    else:
                        year = date_str[:4]
                        
                # Extract rating
                rating = 0.0
                if getattr(item, "imdbRatingValue", None):
                    try:
                        rating = float(item.imdbRatingValue)
                    except ValueError:
                        pass

                return {
                    "subject_id": int(item.subjectId),
                    "title": clean_title,
                    "release_date": year,
                    "rating": rating,
                    "has_hindi": has_hindi
                }

            # Run verification tasks in parallel
            movie_tasks = [process_item(m) for m in movies]
            series_tasks = [process_item(s) for s in series]

            verified_movies = await asyncio.gather(*movie_tasks) if movie_tasks else []
            verified_series = await asyncio.gather(*series_tasks) if series_tasks else []

            # 4. Save to SQLite database cache
            save_cached_trending_items("trending_movies", verified_movies)
            save_cached_trending_items("trending_series", verified_series)
            
            # Update cache timestamp
            set_setting("trending_cache_time", str(time.time()))
            print(f"[TrendingManager] Caching successful! Saved {len(verified_movies)} movies & {len(verified_series)} series.")
            return True
            
        except Exception as e:
            print(f"[TrendingManager] Error updating cache: {e}")
            return False

async def get_trending_list(category: str) -> list:
    """
    Get cached trending items.
    If the cache is older than 12 hours or completely empty, triggers a background refresh.
    """
    # Check cache time
    cache_time_str = get_setting("trending_cache_time")
    cache_age = 9999999.0
    if cache_time_str:
        try:
            cache_age = time.time() - float(cache_time_str)
        except ValueError:
            pass

    # Retrieve from DB
    items = get_cached_trending_items(category)
    
    # Trigger refresh if empty or expired (> 12 hours / 43200 seconds)
    if not items or cache_age > 43200:
        if not _update_lock.locked():
            # If DB is empty, fetch synchronously so the user gets results immediately.
            # Otherwise, fetch in background so response is instant.
            if not items:
                print("[TrendingManager] Cache empty! Fetching trending content synchronously...")
                await update_trending_cache()
                items = get_cached_trending_items(category)
            else:
                print("[TrendingManager] Cache expired. Triggering background refresh...")
                asyncio.create_task(update_trending_cache())
                
    return items
