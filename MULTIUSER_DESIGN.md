# WebUI 多用户 + 沙箱隔离 改造方案

> 状态：方案设计（未实施）
> 目标：将单用户 WebUI 改造为支持用户注册/登录、SSO、点登录的多用户系统，并通过 Bubblewrap 实现沙箱隔离

---

## 目录

- [背景与现状](#背景与现状)
- [整体架构](#整体架构)
- [阶段一：多用户支持](#阶段一多用户支持)
- [阶段二：沙箱隔离](#阶段二沙箱隔离)
- [文件变更清单](#文件变更清单)
- [实施顺序](#实施顺序)
- [数据库 Schema](#数据库-schema)
- [SSO 支持（可选扩展）](#sso-支持可选扩展)

---

## 背景与现状

### 现状分析

| 维度 | 当前实现 | 局限 |
|------|---------|------|
| **认证** | 单一全局 token（启动时随机生成） | 无用户概念 |
| **会话存储** | `~/.octopus/projects/<encoded-cwd>/<session_id>.jsonl` | 按工作目录隔离，无用户维度 |
| **后台任务** | 全局 dict `_background_tasks` | 用户间可见 |
| **工作目录** | 进程级全局 `AgentState.cwd` | 用户间互相影响 |
| **API 路径** | 无边界检查 | 可访问任意路径 |
| **网络** | SSRF 防护已就位 | 缺用户级限制 |

### 目标

- **阶段一**：支持多用户注册/登录/点登录/SSO，会话与配置按用户隔离
- **阶段二**：通过 Bubblewrap 实现 Bash 沙箱隔离，防止用户间干扰

---

## 整体架构

```
                          ┌─────────────────────────────────────────┐
                          │              Browser / Client            │
                          └──────────────┬──────────────────────────┘
                                         │ HTTPS + JWT
                          ┌──────────────▼──────────────────────────┐
                          │           FastAPI Backend               │
                          │  ┌────────────────────────────────────┐  │
                          │  │  JWT Auth Middleware               │  │
                          │  │  - 验证 token                      │  │
                          │  │  - 解析 user_id → request.state  │  │
                          │  └──────────────┬─────────────────────┘  │
                          │                │                        │
                          │  ┌──────────────▼─────────────────────┐  │
                          │  │  Routes                            │  │
                          │  │  - /api/auth/*  (登录/注册/登出)  │  │
                          │  │  - /api/sessions/* (用户会话)     │  │
                          │  │  - /api/config/*  (用户配置)     │  │
                          │  │  - /ws/*  (WebSocket + user_id)   │  │
                          │  └──────────────┬─────────────────────┘  │
                          └─────────────────┼─────────────────────────┘
                                            │
                          ┌─────────────────▼─────────────────────────┐
                          │          Per-User Layer                    │
                          │  ┌────────────────────────────────────┐  │
                          │  │  AgentState (thread-local)          │  │
                          │  │  - user_id, user_root              │  │
                          │  │  - cwd (restricted to user_root)    │  │
                          │  │  - tasks, pending_plan             │  │
                          │  └──────────────┬─────────────────────┘  │
                          │                │                        │
                          │  ┌──────────────▼─────────────────────┐  │
                          │  │  Tools (file_ops, bash, git ...)  │  │
                          │  │  - All paths validated via        │  │
                          │  │    AgentState.abs_path()          │  │
                          │  │  - Bash → Bubblewrap (阶段二)     │  │
                          │  └────────────────────────────────────┘  │
                          └──────────────────────────────────────────┘
                                            │
                          ┌─────────────────▼─────────────────────────┐
                          │          Storage Layer                     │
                          │  ~/.octopus/users/<user_id>/              │
                          │    ├── projects/                           │
                          │    │   └── <encoded_cwd>/                  │
                          │    │       └── <session_id>.jsonl         │
                          │    ├── config.json                        │
                          │    └── trusted_dirs.json                  │
                          └──────────────────────────────────────────┘
```

---

## 阶段一：多用户支持

### 1.1 新建文件

| 文件 | 说明 |
|------|------|
| `server/__init__.py` | server 包初始化 |
| `server/models/__init__.py` | 模型包初始化 |
| `server/models/user.py` | 用户模型 + SQLAlchemy ORM |
| `server/database.py` | SQLite 连接管理 |
| `server/auth.py` | JWT 签发/验证、密码哈希、SSO 回调 |
| `web/routes_auth.py` | 登录/注册/登出/刷新 token API |
| `migrations/001_initial.sql` | 数据库初始 schema |

#### `server/models/user.py`

```python
"""用户模型"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: uuid.uuid4().hex[:16]
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # SSO
    sso_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sso_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # JWT 版本号（换密码时递增，使旧 token 失效）
    token_version: Mapped[int] = mapped_column(default=0)

    @property
    def home_dir(self) -> Path:
        """用户根目录"""
        return Path.home() / ".octopus" / "users" / self.id

    def ensure_dirs(self):
        """确保用户目录结构存在"""
        (self.home_dir / "projects").mkdir(parents=True, exist_ok=True)
```

#### `server/auth.py`

```python
"""认证核心：JWT + 密码"""
from __future__ import annotations

import secrets
import time
from typing import Any

import bcrypt
import jwt

# JWT 配置
JWT_SECRET = secrets.token_urlsafe(32)  # 启动时生成，写入配置文件持久化
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24 * 7  # 7 天


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_access_token(user_id: str, token_version: int) -> str:
    """签发 JWT"""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + JWT_EXPIRE_HOURS * 3600,
        "v": token_version,  # 版本号，换密码时递增
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, token_version: int) -> str:
    """签发 Refresh Token（有效期 30 天）"""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + 30 * 24 * 3600,
        "v": token_version,
        "type": "refresh",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str, token_version: int) -> dict[str, Any] | None:
    """验证 token，返回 payload 或 None"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("v", 0) != token_version:
            return None
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
```

### 1.2 改造文件

#### `web/app.py`

替换全局 token 认证为 JWT 中间件：

```python
# 公开路径（不需要认证）
_PUBLIC_PATHS = {
    "/", "/index.html", "/static",
    "/api/auth/login", "/api/auth/register", "/api/auth/refresh",
    "/api/auth/sso/callback",
}

class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        # 获取 token
        token = ""
        token = request.query_params.get("token", "")
        if not token:
            token = request.cookies.get("octopus_token", "")
        if not token:
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]

        if not token:
            return Response(status_code=401, content="Unauthorized")

        # 验证 token 并注入用户信息
        from server.auth import verify_token
        from server.database import Session, User

        with Session() as db:
            user = db.query(User).filter(User.id == payload["sub"]).first()
            if not user or not user.is_active:
                return Response(status_code=401, content="Unauthorized")
            request.state.user_id = user.id
            request.state.username = user.username

        return await call_next(request)
```

#### `web/routes_api.py`

所有 API 增加 `user_id` 过滤：

```python
@router.get("/sessions")
async def list_sessions(request: Request):
    from session import list_sessions
    user_id = request.state.user_id
    return await asyncio.to_thread(list_sessions, user_id=user_id)

@router.post("/sessions")
async def create_session(request: Request, body: dict[str, Any] = Body(default={})):
    from session import create_session
    user_id = request.state.user_id
    name = body.get("name") if body else None
    return {"session_id": await asyncio.to_thread(create_session, name, None, user_id)}
```

#### `session.py`

所有函数增加 `user_id` 参数（默认 `None` 兼容 TUI/CLI）：

```python
_BASE_DIR = Path.home() / ".octopus"
_USERS_ROOT = _BASE_DIR / "users"

def _user_dir(user_id: str | None) -> Path:
    if user_id:
        return _USERS_ROOT / user_id
    return _BASE_DIR  # 兼容 TUI/CLI

def _project_dir(user_id: str | None = None, cwd: str | None = None) -> Path:
    user_root = _user_dir(user_id)
    if cwd is None:
        cwd = os.getcwd()
    encoded = cwd.replace("/", "-").replace("\\", "-")
    d = user_root / "projects" / encoded
    d.mkdir(parents=True, exist_ok=True)
    return d

def create_session(name: str | None = None, cwd: str | None = None,
                   user_id: str | None = None) -> str:
    # ...
    project = _project_dir(user_id, cwd)
    # ... 后续逻辑不变

def load_session(session_id: str, user_id: str | None = None,
                 cwd: str | None = None) -> tuple[list[dict], str, dict]:
    # 先在用户目录下查找，找不到再尝试全局目录（兼容旧数据）
    # ...
```

#### `config.py`

新增用户配置支持：

```python
_USER_CONFIG_PATH_TEMPLATE = Path.home() / ".octopus" / "users" / "{user_id}" / "config.json"

def get_user_config(user_id: str) -> dict[str, Any]:
    path = Path(str(_USER_CONFIG_PATH_TEMPLATE).format(user_id=user_id))
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}

def set_user_value(user_id: str, key: str, value: Any):
    path = Path(str(_USER_CONFIG_PATH_TEMPLATE).format(user_id=user_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            existing = json.load(f)
    existing[key] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
```

#### `tools/state.py`

```python
class AgentState:
    def __init__(self, user_id: str = "", user_root: str = ""):
        self.user_id = user_id          # Web 模式：用户 ID；TUI 模式：""
        self.user_root = user_root      # Web 模式：用户根目录；TUI 模式：""
        self.cwd: str = user_root if user_root else os.getcwd()
        self.tasks: dict[int, dict] = {}
        self.next_task_id: int = 1
        self.pending_plan: str | None = None

    def abs_path(self, path: str) -> str:
        abs_path = os.path.realpath(path) if os.path.isabs(path) \
                   else os.path.realpath(os.path.join(self.cwd, path))

        # Web 模式下强制目录边界
        if self.user_root:
            if not abs_path.startswith(self.user_root + os.sep) and abs_path != self.user_root:
                from tools.exceptions import ToolError
                raise ToolError(f"越权访问: {path}")

        return abs_path

    def set_cwd(self, path: str) -> None:
        new_cwd = self.abs_path(path)
        if self.user_root and not new_cwd.startswith(self.user_root + os.sep) and new_cwd != self.user_root:
            from tools.exceptions import ToolError
            raise ToolError(f"越权切换目录: {path}")
        self.cwd = new_cwd
```

#### `web/routes_ws.py`

WebSocket 用户绑定：

```python
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # JWT 验证
    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=4001, reason="No token")
        return

    from server.auth import verify_token
    from server.database import Session, User

    payload = verify_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Invalid token")
        return

    user_id = payload["sub"]
    with Session() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            await websocket.close(code=4001, reason="User inactive")
            return

    await websocket.accept()

    # 创建带用户隔离的 AgentState
    from tools.state import AgentState
    user_root = str(user.home_dir)
    bridge.agent_state = AgentState(user_id=user_id, user_root=user_root)
    # ...
```

### 1.3 新增 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册 |
| POST | `/api/auth/login` | 用户登录 |
| POST | `/api/auth/logout` | 登出 |
| POST | `/api/auth/refresh` | 刷新 token |
| GET | `/api/auth/me` | 获取当前用户信息 |
| PATCH | `/api/auth/me/password` | 修改密码 |

#### `web/routes_auth.py`

```python
from fastapi import APIRouter, Body, Request, Response
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/api/auth")


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
async def register(body: RegisterRequest):
    from server.database import Session, User
    from server.auth import hash_password

    with Session() as db:
        existing = db.query(User).filter(User.username == body.username).first()
        if existing:
            return {"error": "用户名已存在"}

        user = User(
            username=body.username,
            password_hash=hash_password(body.password),
            email=body.email,
        )
        user.ensure_dirs()
        db.add(user)
        db.commit()

    return {"user_id": user.id, "username": user.username}


@router.post("/login")
async def login(response: Response, body: LoginRequest):
    from server.database import Session, User
    from server.auth import verify_password, create_access_token, create_refresh_token

    with Session() as db:
        user = db.query(User).filter(User.username == body.username).first()
        if not user or not verify_password(body.password, user.password_hash):
            return {"error": "用户名或密码错误"}

        if not user.is_active:
            return {"error": "账户已被禁用"}

        user.last_login_at = datetime.utcnow()
        user.token_version += 1
        db.commit()

        access_token = create_access_token(user.id, user.token_version)
        refresh_token = create_refresh_token(user.id, user.token_version)

        response.set_cookie(
            "octopus_token", access_token,
            httponly=True, max_age=7 * 24 * 3600, samesite="lax"
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {"id": user.id, "username": user.username}
        }


@router.get("/me")
async def get_me(request: Request):
    from server.database import Session, User
    with Session() as db:
        user = db.query(User).filter(User.id == request.state.user_id).first()
        if not user:
            return {"error": "用户不存在"}
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "created_at": user.created_at.isoformat(),
        }
```

### 1.4 数据库

使用 SQLite（`~/.octopus/users.db`）：

```python
# server/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pathlib import Path

DB_PATH = Path.home() / ".octopus" / "users.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)

# 初始化表
from server.models.user import Base
Base.metadata.create_all(engine)
```

---

## 阶段二：沙箱隔离

### 2.1 `tools/bash.py` — Bubblewrap 集成

```python
"""Bash 工具：支持 Bubblewrap 沙箱隔离"""
import os
import shutil
import subprocess
import signal
from pathlib import Path
from tools.state import get_state

# 后台任务按用户隔离
_background_tasks: dict[str, dict[str, dict]] = {}  # {user_id: {task_id: task}}


def _is_bwrap_available() -> bool:
    return shutil.which("bwrap") is not None


def _build_bwrap_command(command: str, cwd: str, user_root: str) -> list[str]:
    """构建 Bubblewrap 命令"""
    ws_dir = user_root  # 用户根目录作为 /workspace

    cmd = ["bwrap"]

    # Namespace 隔离
    cmd += ["--unshare-user", "--unshare-ipc", "--unshare-pid", "--new-session"]

    # 根文件系统（只读）
    cmd += [
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/etc/ssl", "/etc/ssl",
        "--ro-bind", "/etc/passwd", "/etc/passwd",
        "--ro-bind", "/etc/group", "/etc/group",
        "--ro-bind", "/etc/nsswitch.conf", "/etc/nsswitch.conf",
    ]

    # 用户可写目录
    cmd += ["--bind", ws_dir, "/workspace"]

    # 临时目录（独立）
    cmd += ["--tmpfs", "/tmp", "--tmpfs", "/var/tmp"]

    # proc 和 dev
    cmd += ["--proc", "/proc", "--dev", "/dev"]

    # 隐藏其他用户目录（只读主目录）
    home = str(Path.home())
    if home != user_root:
        cmd += ["--ro-bind-try", home, home]

    # 环境变量
    cmd += [
        "--setenv", "HOME", "/workspace",
        "--setenv", "PATH", "/usr/bin:/bin",
        "--setenv", "USER", "octopus",
        "--setenv", "LANG", "en_US.UTF-8",
    ]

    # 工作目录
    cmd += ["--chdir", cwd]

    # 执行命令
    cmd += ["bash", "-c", command]

    return cmd


def run_bash(command: str, timeout: int = 120,
             run_in_background: bool = False, user_id: str = "") -> str:
    state = get_state()
    user_root = state.user_root
    cwd = state.cwd

    if run_in_background:
        # 后台任务隔离
        if user_id not in _background_tasks:
            _background_tasks[user_id] = {}
        # ...
        return

    # 检查是否使用沙箱
    if user_root and _is_bwrap_available():
        return _run_bash_sandboxed(command, cwd, user_root, timeout)

    # 降级到普通 subprocess
    return _run_bash_native(command, cwd, timeout)


def _run_bash_sandboxed(command: str, cwd: str, user_root: str, timeout: int) -> str:
    """使用 Bubblewrap 执行命令"""
    bwrap_cmd = _build_bwrap_command(command, cwd, user_root)

    proc = subprocess.Popen(
        bwrap_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    lines = []
    try:
        for line in proc.stdout:
            lines.append(line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        return f"[超时 {timeout}s]"

    output = "".join(lines).strip()
    if proc.returncode != 0:
        output += f"\n[exit code: {proc.returncode}]"
    return output or "(no output)"


def _run_bash_native(command: str, cwd: str, timeout: int) -> str:
    """普通 subprocess 执行（环境变量已过滤）"""
    env = os.environ.copy()
    env.pop("OCTOPUS_API_KEY", None)
    env.pop("API_KEY", None)

    proc = subprocess.Popen(
        command, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
        cwd=cwd, env=env,
        preexec_fn=os.setsid,
    )
    lines = []
    for line in proc.stdout:
        lines.append(line)
    proc.wait(timeout=timeout)
    output = "".join(lines).strip()
    if proc.returncode != 0:
        output += f"\n[exit code: {proc.returncode}]"
    return output or "(no output)"
```

### 2.2 `tools/file_ops.py` — 强化边界检查

所有文件操作已通过 `_abs_path` → `get_state().abs_path()` 自动获得边界保护。无需大规模改动。

```python
def run_write_file(path: str, content: str, mode: str = "w") -> str:
    abs_path = _abs_path(path)  # 自动边界检查

    if is_sensitive_path(abs_path):
        raise ToolError(f"拒绝写入敏感路径: {path}")

    # 原子写入
    # ...
```

### 2.3 资源限制（可选 cgroups）

```python
# tools/cgroup.py

import os

CGROUP_ROOT = "/sys/fs/cgroup/octopus"

def ensure_user_cgroup(user_id: str) -> str:
    """确保用户 cgroup 存在，返回 cgroup 路径"""
    cgroup_path = f"{CGROUP_ROOT}/{user_id}"
    os.makedirs(cgroup_path, exist_ok=True)

    # CPU: 2 cores
    with open(f"{cgroup_path}/cpu.max", "w") as f:
        f.write("200000 100000\n")

    # 内存: 2GB
    with open(f"{cgroup_path}/memory.max", "w") as f:
        f.write("2G\n")

    # 进程数: 100
    with open(f"{cgroup_path}/pids.max", "w") as f:
        f.write("100\n")

    return cgroup_path


def move_to_cgroup(pid: int, user_id: str):
    """将进程移动到用户 cgroup"""
    cgroup_path = ensure_user_cgroup(user_id)
    with open(f"{cgroup_path}/cgroup.procs", "w") as f:
        f.write(str(pid))
```

---

## 文件变更清单

### 新建文件

| 文件 | 阶段 |
|------|------|
| `server/__init__.py` | 1 |
| `server/models/__init__.py` | 1 |
| `server/models/user.py` | 1 |
| `server/database.py` | 1 |
| `server/auth.py` | 1 |
| `web/routes_auth.py` | 1 |
| `tools/cgroup.py` | 2 |
| `migrations/001_initial.sql` | 1 |

### 改造文件

| 文件 | 改动 | 阶段 |
|------|------|------|
| `web/app.py` | JWT 中间件替换全局 token | 1 |
| `web/routes_api.py` | 用户维度隔离 | 1 |
| `web/routes_ws.py` | WebSocket 用户绑定 | 1 |
| `session.py` | 用户目录隔离 | 1 |
| `config.py` | 用户配置支持 | 1 |
| `tools/state.py` | AgentState user_id/user_root | 1 |
| `tools/bash.py` | Bubblewrap + 后台任务隔离 | 2 |
| `tools/file_ops.py` | 边界检查强化 | 2 |
| `tools/security.py` | 新增 is_path_within_user_dir | 1 |

### TUI/CLI 变更

**无任何变更** — 所有改动通过默认参数向后兼容：

- TUI/CLI 使用 `AgentState()`（`user_id=""`, `user_root=""`），无边界检查
- Web 模式使用 `AgentState(user_id, user_root)`，启用边界检查

---

## 实施顺序

```
阶段一（多用户）
  │
  ├─ 1. 新建 server/models/user.py, server/auth.py, server/database.py
  ├─ 2. 新建 web/routes_auth.py
  ├─ 3. 改造 web/app.py（JWT 中间件）
  ├─ 4. 改造 session.py（用户目录隔离）
  ├─ 5. 改造 tools/state.py（AgentState user_id）
  ├─ 6. 改造 web/routes_api.py（用户维度 API）
  ├─ 7. 改造 web/routes_ws.py（WebSocket 用户绑定）
  ├─ 8. 改造 config.py（用户配置）
  │
  └─ 9. 前端登录/注册界面
          │
阶段二（沙箱隔离）
  │
  ├─ 10. 改造 tools/bash.py（Bubblewrap）
  ├─ 11. 改造 tools/file_ops.py（边界强化）
  ├─ 12. 新建 tools/cgroup.py（资源限制）
  └─ 13. 集成测试 + 压力测试
```

---

## 数据库 Schema

```sql
CREATE TABLE users (
    id              TEXT PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    email           TEXT,
    sso_provider    TEXT,
    sso_id          TEXT,
    is_active       INTEGER DEFAULT 1,
    is_admin        INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at   TIMESTAMP,
    token_version   INTEGER DEFAULT 0
);

CREATE INDEX ix_users_username ON users(username);
CREATE INDEX ix_users_email ON users(email);
```

---

## SSO 支持（可选扩展）

```python
# web/routes_auth.py 扩展

@router.get("/sso/{provider}")
async def sso_login(provider: str):
    """发起 SSO 登录（OAuth2）"""
    from server.auth import get_sso_config
    config = get_sso_config(provider)
    redirect_uri = f"{base_url}/api/auth/sso/callback"
    auth_url = build_oauth_url(config, redirect_uri)
    return RedirectResponse(auth_url)


@router.get("/sso/callback")
async def sso_callback(provider: str, code: str, request: Request):
    """SSO 回调处理"""
    from server.auth import exchange_sso_code
    sso_user = await exchange_sso_code(provider, code)

    with Session() as db:
        user = db.query(User).filter(
            User.sso_provider == provider,
            User.sso_id == sso_user["id"]
        ).first()

        if not user:
            # 首次 SSO 登录，自动创建账户
            user = User(
                username=f"{provider}_{sso_user['id'][:16]}",
                sso_provider=provider,
                sso_id=sso_user["id"],
                email=sso_user.get("email"),
            )
            user.ensure_dirs()
            db.add(user)

        user.token_version += 1
        db.commit()

    access_token = create_access_token(user.id, user.token_version)
    return {"access_token": access_token, "user": {...}}
```

---

## 关键设计点

### 向后兼容

- 所有 `tools/state.py` 改动通过默认参数实现，TUI/CLI 完全无感知
- `session.py` 中 `user_id` 参数默认 `None`，TUI/CLI 仍使用旧目录
- `tools/bash.py` 中 Bubblewrap 仅在 `user_root` 非空时启用

### 性能考量

- JWT stateless，无需服务器存储 session
- SQLite 单机足够（多用户高并发时可迁移到 PostgreSQL）
- Bubblewrap 启动开销 < 10ms，可接受

### 安全加固

- 密码 bcrypt rounds=12（推荐值）
- JWT 7 天 + Refresh 30 天双 token
- 用户目录硬隔离（path 边界检查）
- Bubblewrap namespace 隔离（不可逃逸）
- cgroup 资源限制（CPU/内存/进程数）

---

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 旧数据迁移 | session.py 兼容旧路径，找不到再 fallback |
| Bubblewrap 不可用 | 自动降级到普通 subprocess + 目录边界检查 |
| JWT secret 持久化 | 启动时生成并写入 `~/.octopus/.jwt_secret` |
| 路径穿越攻击 | `os.path.realpath` + 边界检查 |
| 用户间资源抢占 | cgroup v2 资源限制 |
| 容器逃逸 | Bubblewrap rootless + 最小化挂载 |
