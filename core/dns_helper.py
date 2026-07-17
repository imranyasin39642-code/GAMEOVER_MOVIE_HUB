"""
🌐 DNS-over-HTTPS (DoH) Resolver for bypassing broken VPS system DNS resolvers.
Resolves hostnames using multiple public DoH servers in parallel for maximum reliability.
Tries Google (8.8.8.8), Cloudflare (1.1.1.1), and NextDNS simultaneously — fastest wins.
"""

import asyncio
import aiohttp
from typing import List, Dict, Any, Optional
from aiohttp.resolver import AbstractResolver, DefaultResolver

# DoH endpoints — all queried simultaneously; fastest response wins
DOH_SERVERS = [
    "https://8.8.8.8/resolve",          # Google DoH (via raw IP)
    "https://1.1.1.1/dns-query",        # Cloudflare DoH (via raw IP)
    "https://45.90.28.0/dns-query",     # NextDNS DoH (via raw IP)
]

DOH_HEADERS = {
    "Accept": "application/dns-json",
}

async def _query_single_doh(session: aiohttp.ClientSession, endpoint: str, hostname: str) -> Optional[str]:
    """Queries a single DoH server and returns the resolved IP, or None on failure."""
    try:
        async with session.get(
            endpoint,
            params={"name": hostname, "type": "A"},
            headers=DOH_HEADERS,
            timeout=aiohttp.ClientTimeout(total=4)
        ) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                answers = data.get("Answer", [])
                for ans in answers:
                    if ans.get("type") == 1:  # A record
                        ip = ans.get("data", "").strip()
                        if ip:
                            return ip
    except Exception:
        pass
    return None

async def resolve_dns_doh(hostname: str) -> Optional[str]:
    """
    Resolves a hostname to an IP using multiple DoH servers in parallel.
    Returns the first successful result (fastest DNS server wins).
    """
    # Use a raw connector with no DoH recursion for the DoH queries themselves
    connector = aiohttp.TCPConnector(ssl=False)
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                asyncio.create_task(_query_single_doh(session, endpoint, hostname))
                for endpoint in DOH_SERVERS
            ]
            # Return the first non-None result
            for coro in asyncio.as_completed(tasks):
                try:
                    result = await coro
                    if result:
                        # Cancel remaining tasks
                        for t in tasks:
                            if not t.done():
                                t.cancel()
                        return result
                except Exception:
                    pass
    except Exception as e:
        print(f"[DoH] Session error resolving {hostname}: {e}")
    finally:
        try:
            await connector.close()
        except Exception:
            pass
    return None


class DoHResolver(AbstractResolver):
    def __init__(self):
        self.fallback = DefaultResolver()
        self._cache: Dict[str, str] = {}  # Simple in-memory DNS cache

    async def resolve(self, hostname: str, port: int = 0, family: int = 0) -> List[Dict[str, Any]]:
        # Don't DoH-resolve raw IPs — let aiohttp handle them directly
        import re
        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", hostname):
            return await self.fallback.resolve(hostname, port, family)

        # Check in-memory cache first
        if hostname in self._cache:
            ip = self._cache[hostname]
            return [{"hostname": hostname, "host": ip, "port": port, "family": family, "proto": 0, "flags": 0}]

        # Try DoH resolution (parallel, fastest wins)
        ip = await resolve_dns_doh(hostname)
        if ip:
            self._cache[hostname] = ip  # Cache for this session
            return [{"hostname": hostname, "host": ip, "port": port, "family": family, "proto": 0, "flags": 0}]

        # Fallback to system resolver (last resort)
        print(f"[DoH] All DoH servers failed for {hostname}, falling back to system DNS.")
        try:
            return await self.fallback.resolve(hostname, port, family)
        except Exception as e:
            print(f"[DoH] System DNS also failed for {hostname}: {e}")
            raise

    async def close(self) -> None:
        await self.fallback.close()


def get_doh_connector() -> aiohttp.TCPConnector:
    """Returns a TCPConnector configured with the multi-server DNS-over-HTTPS resolver."""
    return aiohttp.TCPConnector(resolver=DoHResolver(), ssl=False)
