"""FastAPI 应用工厂：Web UI 入口、JWT 认证、路由挂载。"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import PlainTextResponse


def create_app() -> FastAPI:
    app = FastAPI(title="Octopus Agent Web UI")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path

        if path.startswith("/static") or path == "/" or path == "/index.html":
            response = await call_next(request)
            return response

        # 解析 token（支持 query、cookie、header）
        token = request.query_params.get("token", "")
        if not token:
            token = request.cookies.get("octopus_token", "")
        if not token:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        # /api/auth/login 和 /api/auth/register 不需要认证
        if path.startswith("/api/auth/login") or path.startswith("/api/auth/register"):
            response = await call_next(request)
            return response

        # 其他 /api/* 需要认证
        if path.startswith("/api"):
            if token:
                from server.auth import get_user_from_token

                user = get_user_from_token(token)
                if user:
                    request.state.user = user
            if not hasattr(request.state, "user") or not request.state.user:
                return Response(status_code=401, content="Unauthorized")
            response = await call_next(request)
            return response

        response = await call_next(request)
        return response

    from web.routes_api import router as api_router
    from web.routes_auth import router as auth_router
    from web.routes_ws import router as ws_router
    from web.routes_pty import router as pty_router
    app.include_router(api_router)
    app.include_router(auth_router)
    app.include_router(ws_router)
    app.include_router(pty_router)

    from starlette.responses import Response as _StarletteResponse

    class _NoCacheStatic(StaticFiles):
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", _NoCacheStatic(directory=str(static_dir)), name="static")

    from config import get as config_get

    video_dir = config_get("video_directory")
    if video_dir:
        from pathlib import Path as _Path

        vd = _Path(video_dir)
        if vd.is_dir():
            VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".ogv", ".ogg", ".m4v", ".ts"}

            class _VideoStatic(_NoCacheStatic):
                async def get_response(self, path, scope):
                    ext = _Path(path).suffix.lower()
                    if ext not in VIDEO_EXTS:
                        return PlainTextResponse("Forbidden", status_code=403)
                    return await super().get_response(path, scope)

            app.mount("/videos", _VideoStatic(directory=str(vd)), name="videos")

    music_dir = config_get("music_directory")
    if music_dir:
        md = _Path(music_dir)
        if md.is_dir():
            AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".wma", ".aac", ".opus", ".weba"}

            class _AudioStatic(_NoCacheStatic):
                async def get_response(self, path, scope):
                    ext = _Path(path).suffix.lower()
                    if ext not in AUDIO_EXTS:
                        return PlainTextResponse("Forbidden", status_code=403)
                    return await super().get_response(path, scope)

            app.mount("/music", _AudioStatic(directory=str(md)), name="music")

    image_dir = config_get("image_directory")
    if image_dir:
        idir = _Path(image_dir)
        if idir.is_dir():
            IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif", ".tiff", ".tif"}

            class _ImageStatic(_NoCacheStatic):
                async def get_response(self, path, scope):
                    ext = _Path(path).suffix.lower()
                    if ext not in IMAGE_EXTS:
                        return PlainTextResponse("Forbidden", status_code=403)
                    return await super().get_response(path, scope)

            app.mount("/images", _ImageStatic(directory=str(idir)), name="images")

    docs_dir = config_get("docs_directory")
    if docs_dir:
        dd = _Path(docs_dir)
        if dd.is_dir():
            DOC_EXTS = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
                        ".txt", ".md", ".csv", ".ofd"}

            class _DocStatic(_NoCacheStatic):
                async def get_response(self, path, scope):
                    ext = _Path(path).suffix.lower()
                    if ext not in DOC_EXTS:
                        return PlainTextResponse("Forbidden", status_code=403)
                    return await super().get_response(path, scope)

            app.mount("/docs", _DocStatic(directory=str(dd)), name="docs")

    from fastapi.responses import FileResponse
    from starlette.responses import Response as _SResponse

    @app.get("/")
    async def index():
        content = (static_dir / "index.html").read_bytes()
        return _SResponse(content=content, media_type="text/html",
                          headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

    return app


def launch_web(host: str = "0.0.0.0", port: int = 8765):
    """Web UI 启动入口。"""
    import uvicorn

    app = create_app()

    sys.stderr.write(f"\n  Octopus Web UI\n")
    sys.stderr.write(f"  URL:   http://{host}:{port}\n")
    sys.stderr.write(f"  首次访问请注册账户\n\n")
    sys.stderr.flush()

    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        print("\n  Web UI stopped.")
        sys.exit(0)