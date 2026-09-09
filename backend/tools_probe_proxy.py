import asyncio
import httpx

PORTS = [24480, 45444, 5448, 6016]
TEST_URLS = ["https://news.ycombinator.com/rss", "https://export.arxiv.org"]


async def probe(port: int, scheme: str):
    proxy = f"{scheme}://127.0.0.1:{port}"
    results = []
    async with httpx.AsyncClient(proxy=proxy, timeout=8) as client:
        for url in TEST_URLS:
            try:
                r = await client.get(url)
                results.append(f"{url} -> {r.status_code}")
            except Exception as e:
                results.append(f"{url} -> {type(e).__name__}")
    return proxy, results


async def main():
    for port in PORTS:
        for scheme in ("http", "socks5"):
            try:
                proxy, res = await asyncio.wait_for(probe(port, scheme), 20)
                ok = all("-> 2" in r or "-> 3" in r for r in res)
                print(f"[{'OK ' if ok else 'BAD'}] {proxy}: " + " | ".join(res), flush=True)
                if ok:
                    break
            except asyncio.TimeoutError:
                print(f"[TIMEOUT] {scheme} 127.0.0.1:{port}", flush=True)
            except Exception as e:
                print(f"[ERR] {scheme} 127.0.0.1:{port}: {type(e).__name__}", flush=True)


asyncio.run(main())
