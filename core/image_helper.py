import os
import aiohttp
from io import BytesIO
try:
    from PIL import Image, ImageFilter
except ImportError:
    Image = None

from config import Config

DOWNLOADS_DIR = Config.DOWNLOADS_DIR

async def get_16_9_thumbnail(url: str, song_title: str) -> str:
    """
    Downloads an image and converts it into a 16:9 widescreen thumbnail
    by padding the background with a blurred version of itself.
    """
    default_thumb = "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?q=80&w=1280"
    
    if not url or Image is None:
        return default_thumb
        
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    img_data = await resp.read()
                else:
                    return default_thumb
                    
        # Process with PIL
        img = Image.open(BytesIO(img_data)).convert("RGB")
        target_width = 1280
        target_height = 720
        
        # Create a blurred background from the original
        bg = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=25))
        
        # Resize original keeping aspect ratio
        img_ratio = img.width / img.height
        target_ratio = target_width / target_height
        
        if img_ratio > target_ratio:
            # Wider
            new_width = target_width
            new_height = int(new_width / img_ratio)
        else:
            # Taller (Portrait poster)
            new_height = target_height
            new_width = int(new_height * img_ratio)
            
        fg = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Paste centered
        x = (target_width - new_width) // 2
        y = (target_height - new_height) // 2
        bg.paste(fg, (x, y))
        
        safe_title = "".join(c for c in song_title if c.isalnum() or c.isspace()).strip().replace(" ", "_")
        if not safe_title:
            safe_title = "thumb"
            
        out_path = os.path.join(DOWNLOADS_DIR, f"16x9_{safe_title}.jpg")
        bg.save(out_path, "JPEG", quality=90)
        return out_path
        
    except Exception as e:
        print(f"[Thumbnail] Error creating 16:9 thumbnail: {e}")
        return default_thumb
