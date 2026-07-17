"""
🎰 Surprise Me / Random VOD Manager
Selects a random, highly-rated blockbuster movie or TV series, verifies its Hindi dubbed
availability on the MovieBox API, and returns it for instant streaming.
"""

import random
from core.vod_scraper import search_vod, SubjectType
from moviebox_api.v2 import Session

# Curated list of 60+ popular blockbuster movies and TV series available in Hindi on MovieBox
PREMIUM_BLOCKBUSTERS = [
    # TV Series (Hindi Dubbed)
    "The Boys", "House of the Dragon", "Loki", "Gen V", "Squid Game", 
    "Stranger Things", "Dark", "Money Heist", "Wednesday", "Reacher", 
    "All of Us Are Dead", "Alice in Borderland", "The Witcher", "Arrow", 
    "The Flash", "Moon Knight", "WandaVision", "Invincible", "The Last of Us", "Fallout",
    
    # Movies (Hindi Dubbed)
    "Avengers: Endgame", "Avengers: Infinity War", "Spider-Man: No Way Home", 
    "Deadpool & Wolverine", "Deadpool 2", "Deadpool", "Inception", "Interstellar", 
    "Avatar: The Way of Water", "Avatar", "Iron Man 3", "Iron Man", 
    "Captain America: Civil War", "The Dark Knight", "Joker", "Oppenheimer", 
    "Barbie", "Dune: Part Two", "Dune", "Gladiator", "Transformers: Rise of the Beasts", 
    "Fast X", "Furiosa: A Mad Max Saga", "Mad Max: Fury Road", "Godzilla x Kong: The New Empire", 
    "Godzilla Minus One", "John Wick: Chapter 4", "John Wick", "Top Gun: Maverick", 
    "Bullet Train", "Free Guy", "The Gray Man", "Red Notice", "Extraction 2", 
    "Extraction", "Spider-Man: Into the Spider-Verse", "Spider-Man: Across the Spider-Verse", 
    "Kung Fu Panda 4", "Inside Out 2", "Despicable Me 4"
]

async def get_random_hindi_title(retries: int = 5):
    """
    Select a random title from the premium blockbuster list, resolve its Hindi dubbed
    version on MovieBox, and return it with VOD session metadata.
    """
    session = Session()
    shuffled_pool = list(PREMIUM_BLOCKBUSTERS)
    random.shuffle(shuffled_pool)

    for attempt in range(min(retries, len(shuffled_pool))):
        target_title = shuffled_pool[attempt]
        print(f"[RandomManager] Attempting to resolve random title: '{target_title}' in Hindi...")
        
        try:
            # Search MovieBox with Hindi language preference
            items = await search_vod(target_title, language="hi")
            if not items:
                continue
                
            # Filter results for a title that is dubbed in Hindi
            hindi_item = None
            for item in items:
                title_lower = item.title.lower()
                if "hindi" in title_lower:
                    hindi_item = item
                    break
                    
            if not hindi_item:
                # If none explicitly mention Hindi, fallback to top item (might still have it)
                # but to be safe, we prefer explicit Hindi version if found
                continue
                
            is_series = hindi_item.subjectType == SubjectType.TV_SERIES or int(getattr(hindi_item, "subjectType", 1)) == 2
            clean_title = hindi_item.title.replace("[Hindi]", "").replace("[English]", "").replace("[english]","").replace("[Hindi]","").strip()
            
            # Format release year
            year = "N/A"
            if getattr(hindi_item, "releaseDate", None):
                date_str = str(hindi_item.releaseDate)
                year = date_str.split("-")[0] if "-" in date_str else date_str[:4]
                
            rating = "N/A"
            if getattr(hindi_item, "imdbRatingValue", None):
                rating = str(hindi_item.imdbRatingValue)

            print(f"[RandomManager] Successfully selected: '{clean_title}' ({year}) - Rating: {rating}")
            
            return {
                "item": hindi_item,
                "is_series": is_series,
                "title": clean_title,
                "year": year,
                "rating": rating,
                "session": session
            }
            
        except Exception as e:
            print(f"[RandomManager] Resolution failed for '{target_title}': {e}")
            continue

    print("[RandomManager] Failed to find a valid random Hindi title within retries.")
    return None
