import os
from aiohttp import web

async def handle_health_check(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "online",
        "service": "TD Discord Bot",
        "timestamp": str(os.times())
    })

async def handle_root(request: web.Request) -> web.Response:
    return web.Response(
        text="TD Discord Bot is running smoothly 24/7!",
        content_type="text/plain"
    )

async def start_keep_alive(port: int = None):
    if port is None:
        port = int(os.getenv("PORT", "8080"))
    
    app = web.Application()
    app.router.add_get("/", handle_root)
    app.router.add_get("/health", handle_health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
