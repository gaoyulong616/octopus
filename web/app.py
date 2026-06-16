"""FastAPI 应用工厂：Web UI 入口、JWT 认证、路由挂载。"""

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


# 全局 token（启动时生成，保留用于 TUI/CLI 兼容）
_auth_token: str = ""


def get_auth_token() -> str:
    return _auth_token


def create_app() -> FastAPI:
    global _auth_token
    _auth_token = secrets.token_urlsafe(32)

    # 初始化数据库
    from server.database import init_db
    init_db()

    app = FastAPI(title="Octopus Agent Web UI")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 公开路径（不需要认证）
    _PUBLIC_PATHS = {
        "/", "/index.html",
        "/api/auth/login", "/api/auth/register", "/api/auth/refresh",
    }

    # Token 认证中间件（兼容 JWT + 旧版 token）
    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path

        # 公开路径直接放行
        if path in _PUBLIC_PATHS or path.startswith("/static/"):
            return await call_next(request)

        # 获取 token
        token = request.query_params.get("token", "")
        if not token:
            token = request.cookies.get("octopus_token", "")
        if not token:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            return Response(status_code=401, content="Unauthorized")

        # 尝试 JWT 验证
        from server.auth import verify_token
        from server.database import Session
        from server.models.user import User

        # 首先尝试解析 JWT（不解密版本号）
        import jwt
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            if payload.get("sub"):
                # 看起来是 JWT，完整验证
                with Session() as db:
                    user = db.query(User).filter(User.id == payload["sub"]).first()
                    if user and user.is_active:
                        # JWT 验证通过
                        payload = verify_token(token, user.token_version)
                        if payload:
                            request.state.user_id = user.id
                            request.state.username = user.username
                            request.state.is_admin = user.is_admin
                            return await call_next(request)
        except jwt.InvalidTokenError:
            pass

        # 回退到旧版全局 token 验证（兼容 TUI/CLI）
        if token == _auth_token:
            # 旧版 token 验证通过，设置默认用户上下文
            request.state.user_id = ""
            request.state.username = "cli"
            request.state.is_admin = False
            return await call_next(request)

        return Response(status_code=401, content="Unauthorized")

    # 路由
    from web.routes_api import router as api_router
    from web.routes_ws import router as ws_router
    from web.routes_pty import router as pty_router
    from web.routes_auth import router as auth_router
    app.include_router(api_router)
    app.include_router(ws_router)
    app.include_router(pty_router)
    app.include_router(auth_router)

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

    # 文档目录挂载
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
    sys.stderr.write(f"\n  Octopus Web UI (Multi-User Mode)\n")
    sys.stderr.write(f"  URL:   http://{host}:{port}\n")
    sys.stderr.write(f"  Token: {token} (CLI legacy)\n\n")
    sys.stderr.flush()

    # 延迟打开浏览器
    def _open_browser():
        time.sleep(1.5)
        try:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:
            pass

    threading.Thread(target=_open_browser, daemon=True).start()

    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except KeyboardInterrupt:
        print("\n  Web UI stopped.")
        sys.exit(0)
