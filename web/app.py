"""FastAPI 应用工厂：Web UI 入口、token 认证、路由挂载。"""

from __future__ import annotations

import secrets
import sys
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


# 全局 token（启动时生成）
_auth_token: str = ""


def get_auth_token() -> str:
    return _auth_token


def create_app() -> FastAPI:
    global _auth_token
    _auth_token = secrets.token_urlsafe(32)

    app = FastAPI(title="Octopus Agent Web UI")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Token 认证中间件
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        # 静态文件不拦截（首页需要加载）
        path = request.url.path
        if path.startswith("/static") or path == "/" or path == "/index.html":
            # 首页：如果有 token 参数，设置 cookie 后重定向到无 token URL
            url_token = request.query_params.get("token", "")
            if url_token and url_token == _auth_token and path in ("/", "/index.html"):
                response = await call_next(request)
                response.set_cookie("octopus_token", url_token, httponly=True, max_age=86400)
                return response
            response = await call_next(request)
            return response
        elif path.startswith("/api") or path == "/ws":
            # 优先从 cookie 读取，其次 header / query
            token = request.cookies.get("octopus_token", "")
            if not token:
                token = request.query_params.get("token", "")
            if not token:
                auth_header = request.headers.get("authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:]
            if token != _auth_token:
                return Response(status_code=401, content="Unauthorized")
        response = await call_next(request)
        return response

    # 路由
    from web.routes_api import router as api_router
    from web.routes_ws import router as ws_router
    app.include_router(api_router)
    app.include_router(ws_router)

    # 静态文件（开发阶段禁用缓存）
    from starlette.responses import Response as _StarletteResponse
    class _NoCacheStatic(StaticFiles):
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", _NoCacheStatic(directory=str(static_dir)), name="static")

    # 根路径重定向到 index.html
    from fastapi.responses import FileResponse

    @app.get("/")
    async def index():
        return FileResponse(str(static_dir / "index.html"))

    return app


def launch_web(host: str = "0.0.0.0", port: int = 8765):
    """Web UI 启动入口。"""
    import uvicorn

    app = create_app()
    token = get_auth_token()

    # 输出到 stderr，避免被 uvicorn 吞掉
    sys.stderr.write(f"\n  Octopus Web UI\n")
    sys.stderr.write(f"  URL:   http://{host}:{port}?token={token}\n")
    sys.stderr.write(f"  Token: {token}\n\n")
    sys.stderr.flush()

    # 延迟打开浏览器
    def _open_browser():
        time.sleep(1.5)
        try:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{port}?token={token}")
        except Exception:
            pass

    threading.Thread(target=_open_browser, daemon=True).start()

    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        print("\n  Web UI stopped.")
        sys.exit(0)
