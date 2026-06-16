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
from starlette.responses import PlainTextResponse


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
        allow_origins=[],
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
        elif path.startswith("/api") or path.startswith("/ws"):
            # query → cookie → header
            token = request.query_params.get("token", "")
            if not token:
                token = request.cookies.get("octopus_token", "")
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
    from web.routes_pty import router as pty_router
    app.include_router(api_router)
    app.include_router(ws_router)
    app.include_router(pty_router)

    # 静态文件（开发阶段禁用缓存）
    from starlette.responses import Response as _StarletteResponse
    class _NoCacheStatic(StaticFiles):
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", _NoCacheStatic(directory=str(static_dir)), name="static")

    # 视频目录挂载（支持 HTTP Range 流式播放）
    from config import get as config_get
    video_dir = config_get("video_directory")
    if video_dir:
        from pathlib import Path as _Path
        vd = _Path(video_dir)
        if vd.is_dir():
            VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".ogv", ".ogg", ".m4v", ".ts"}
            class _VideoStatic(_NoCacheStatic):
                async def get_response(self, path, scope):
                    # 白名单校验：只允许视频扩展名
                    ext = _Path(path).suffix.lower()
                    if ext not in VIDEO_EXTS:
                        return PlainTextResponse("Forbidden", status_code=403)
                    return await super().get_response(path, scope)
            app.mount("/videos", _VideoStatic(directory=str(vd)), name="videos")

    # 音频目录挂载
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

    # 图片目录挂载
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

    # 文档目录挂载（与视频/音频/图片相同的模式）
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

    # 根路径重定向到 index.html
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
