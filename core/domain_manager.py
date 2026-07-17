import httpx
import asyncio

DOMAINS = ["themoviebox.org", "moviebox.ph", "moviebox.pk"]
WORKING_DOMAIN = "themoviebox.org"  # Default working mirror fallback

async def detect_working_domain() -> str:
    """
    Ping the MovieBox mirror domains and find the first working one.
    """
    global WORKING_DOMAIN
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    data = {"keyword": "Avengers"}
    
    print("[DomainManager] Checking MovieBox mirror domains for connectivity...")
    for domain in DOMAINS:
        url = f"https://{domain}/wefeed-h5api-bff/subject/search-suggest"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=data, headers=headers, timeout=4.0)
                if resp.status_code == 200 and "subject" in resp.text.lower():
                    WORKING_DOMAIN = domain
                    print(f"[DomainManager] working domain detected: {WORKING_DOMAIN}")
                    return WORKING_DOMAIN
        except Exception as e:
            print(f"[DomainManager] Mirror domain check failed for {domain}: {type(e).__name__}")
            
    print(f"[DomainManager] No responsive mirrors found. Falling back to default: {WORKING_DOMAIN}")
    return WORKING_DOMAIN

def get_domain() -> str:
    return WORKING_DOMAIN
