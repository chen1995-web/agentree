"""agentree Web 服务：FastAPI + SSE，把代理树事件实时推给浏览器（Vue3 前端）。

启动: python3 -m agentree.server [--host 127.0.0.1] [--port 8765]
前端: frontend/ 目录 pnpm build 后由本服务托管（frontend/dist）
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import random
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .agent import AgentConfig, run_agent
from .llm import LLMClient
from .team import Team
from .tracer import Tracer

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
MAX_RUNS = 50

_client: LLMClient | None = None


class RunInfo:
    def __init__(self, run_id: str, task: str, config: AgentConfig):
        self.run_id = run_id
        self.task = task
        self.config = config
        self.status = "running"  # running | done | error | cancelled
        self.label: str | None = None  # 用户自定义显示名（编辑不改原始任务与运行数据）
        self.events: list[dict] = []
        self.result: dict | None = None
        self.handle: asyncio.Task | None = None
        self.team = None  # 团队运行时引用（取消传播用）
        self.created = time.time()

    def push(self, rec: dict) -> None:
        self.events.append(rec)

    def summary(self) -> dict:
        return {"run_id": self.run_id, "task": self.task, "status": self.status,
                "label": self.label, "created": self.created, "result": self.result}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _client
    _client = LLMClient()
    yield


app = FastAPI(title="agentree", lifespan=lifespan)


class StartBody(BaseModel):
    task: str
    model: str | None = None
    max_depth: int = 2
    max_steps: int = 30
    max_children: int = 8


RUNS: dict[str, RunInfo] = {}


# --------------- 鉴权：滑块验证 + 第三方统一登录系统（参考 shell 项目 auth.py） ---------------
# 登录不在本地校验账号：密码 AES 加密后转发给统一登录系统（POST /api/login），
# 成功后由登录系统下发 JWT；本服务仅本地验签（共享密钥 HS256），失败再走网络校验。

LOGIN_SYSTEM_URL = os.environ.get("AGENTREE_LOGIN_SYSTEM_URL", "http://192.168.6.3:18010")
LOGIN_SYSTEM_URL_FALLBACK = os.environ.get("AGENTREE_LOGIN_SYSTEM_URL_FALLBACK", "")
LOGIN_APP_NAME = os.environ.get("AGENTREE_LOGIN_APP_NAME", "agentree")
LOGIN_AES_KEY = os.environ.get("AGENTREE_LOGIN_AES_KEY", "login_system_123")
LOGIN_AES_IV = os.environ.get("AGENTREE_LOGIN_AES_IV", "login_system_iv_")
LOGIN_JWT_SECRET = os.environ.get("AGENTREE_LOGIN_JWT_SECRET", "my_super_secret_key_qw1230")
LOGIN_SLIDER_TTL = int(os.environ.get("AGENTREE_LOGIN_SLIDER_TTL", "180"))
AUTH_CACHE_TTL = 300

# 演示模式：跳过第三方统一登录，直接下发一个本地签名的 demo token。
# 用于公开演示 / 截图 / 无内网登录系统的环境。生产环境保持 off。
DEMO_AUTH = os.environ.get("AGENTREE_DEMO_AUTH", "off").lower() in ("on", "1", "true")

_slider_challenges: dict[str, dict] = {}


class LoginBody(BaseModel):
    username: str
    password: str
    slider_challenge_id: str
    slider_value: float = 0.0


@app.get("/api/auth/slider")
async def slider_challenge():
    now = time.time()
    for k in [k for k, v in _slider_challenges.items() if v["expires"] < now]:
        _slider_challenges.pop(k, None)
    cid = uuid4().hex
    # 参考页合法 offset 窗口为 75..235（l=42, r=10, w=310）
    target = random.randint(90, 220)
    _slider_challenges[cid] = {"target": target, "tolerance": 6, "expires": now + LOGIN_SLIDER_TTL}
    return {"code": 200, "msg": "ok",
            "data": {"challenge_id": cid, "min": 75, "max": 235, "target": target, "tolerance": 6}}


def _aes_encrypt_password(plain: str) -> str:
    """与登录系统约定的 AES-CBC + PKCS7 + base64（复制 shell 项目 auth.py）。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_padding

    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(plain.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(LOGIN_AES_KEY.encode()), modes.CBC(LOGIN_AES_IV.encode()))
    enc = cipher.encryptor()
    return base64.b64encode(enc.update(padded) + enc.finalize()).decode()


async def _post_json(url: str, payload: dict, headers: dict, timeout: float = 10.0):
    """返回 (status_code, body_dict)；网络错误 / 非 JSON 抛异常由调用方处理。"""
    import httpx

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.post(url, json=payload, headers=headers)
        return resp.status_code, resp.json()


async def login_system_login(username: str, password: str):
    """向第三方统一登录系统认证。成功返回 (token, user)；失败抛 RuntimeError。

    容错：主地址网络失败时自动改用备用地址重试一次（运行期故障转移）。
    """
    payload = {"username": username, "password": _aes_encrypt_password(password)}
    headers = {"X-App-Name": LOGIN_APP_NAME}
    urls = [LOGIN_SYSTEM_URL.rstrip("/")]
    fallback = LOGIN_SYSTEM_URL_FALLBACK.rstrip("/")
    if fallback and fallback not in urls:
        urls.append(fallback)

    for base in urls:
        try:
            status_code, body = await _post_json(f"{base}/api/login", payload, headers)
        except Exception as e:  # 网络错误/空响应/非 JSON：换下一个候选地址
            print(f"[auth] login system unreachable at {base}: {e}", flush=True)
            continue
        if status_code == 200 and body.get("code") == 200:
            data = body.get("data") or {}
            token = data.get("token")
            if not token:
                raise RuntimeError("Login service did not return a token")
            return token, {"username": data.get("username", username), "level": data.get("level")}
        # 服务有业务响应（含 422 校验失败、401 密码错误）：不再换地址
        raise RuntimeError(body.get("msg") or "Incorrect username or password")
    raise RuntimeError("Login service unreachable")


def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode((seg + "=" * (-len(seg) % 4)).encode())


def decode_token_payload(token: str):
    """用登录系统共享密钥本地验签（HS256），返回 payload 或 None。"""
    if not token or token.count(".") != 2:
        return None
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected = hmac.new(LOGIN_JWT_SECRET.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
        if not isinstance(payload, dict):
            return None
        exp = payload.get("exp")
        if exp is not None and float(exp) < time.time():
            return None  # expired
        return payload
    except Exception:
        return None


def _make_token(username: str, ttl: float = 86400) -> str:
    """用与登录系统共享的密钥本地签发一个 HS256 JWT（演示模式专用）。

    与 verify_token 的本地验签走同一密钥，因此演示 token 无需联网即可校验。
    """
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": username, "exp": time.time() + ttl}
    h = base64.urlsafe_b64encode(json.dumps(header, separators=(",", ":")).encode()).decode().rstrip("=")
    p = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(LOGIN_JWT_SECRET.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    s = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{h}.{p}.{s}"


@app.get("/api/auth/status")
async def auth_status():
    """前端据此决定是否展示「演示模式」入口（GET，无需鉴权）。"""
    return {"demo": DEMO_AUTH}


_token_cache: dict[str, tuple] = {}


async def verify_token(token: str):
    """返回 {'authenticated': True, 'username': ...} 或 None。

    先本地验签（无网络调用）；失败（如密钥不匹配）再走登录系统网络校验。
    """
    if not token:
        return None
    payload = decode_token_payload(token)
    if payload:
        username = payload.get("sub") or payload.get("username")
        return {"authenticated": True, "username": str(username) if username else None}

    now = time.time()
    cached = _token_cache.get(token)
    if cached and cached[2] > now:
        return cached[1] if cached[0] else None

    base = LOGIN_SYSTEM_URL.rstrip("/")
    ok, user = False, None
    try:
        status_code, body = await _post_json(f"{base}/api/users/list", {},
                                             {"Authorization": f"Bearer {token}"})
        if status_code == 200 and body.get("code") == 200:
            ok, user = True, {"authenticated": True}
    except Exception as e:
        print(f"[auth] token verification failed to reach login system: {e}", flush=True)
        _token_cache[token] = (False, None, now + 2)
        return None
    _token_cache[token] = (ok, user, now + AUTH_CACHE_TTL)
    return user if ok else None


@app.post("/api/auth/login")
async def login(body: LoginBody):
    ch = _slider_challenges.pop(body.slider_challenge_id, None)
    if not ch or ch["expires"] < time.time():
        return {"code": 400, "msg": "Verification expired, please refresh and retry"}
    if abs(body.slider_value - ch["target"]) > ch["tolerance"]:
        return {"code": 400, "msg": "Slider verification failed"}
    try:
        token, user = await login_system_login(body.username, body.password)
    except RuntimeError as e:
        return {"code": 401, "msg": str(e)}
    return {"code": 200, "msg": "ok", "data": {"token": token, "user": user}}


@app.post("/api/auth/demo")
async def demo_login():
    """演示模式：免账号密码 + 免滑动验证，直接下发本地签名 token。

    仅在 AGENTREE_DEMO_AUTH=on 时可用；公开演示 / 截图场景用，生产保持关闭。
    """
    if not DEMO_AUTH:
        raise HTTPException(403, "Demo mode not enabled (set AGENTREE_DEMO_AUTH=on)")
    token = _make_token("demo")
    return {"code": 200, "msg": "ok",
            "data": {"token": token, "user": {"username": "demo", "level": "demo"}}}


async def require_auth(request: Request):
    token = request.query_params.get("token") or ""  # EventSource 带不了 header，兼容 query 参数
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    user = await verify_token(token)
    if not user:
        raise HTTPException(401, "Not logged in or session expired")


authed = APIRouter(dependencies=[Depends(require_auth)])


def _finalize(info: RunInfo, status: str, error: str | None = None, **extra) -> None:
    # 先入队事件、再改状态，保证 SSE 客户端先收到 run_final 再收到 end
    info.push({"t": time.time(), "kind": "run_final", "run_id": info.run_id,
               "status": status, "error": error, **extra})
    info.status = status


async def _execute(info: RunInfo, client: LLMClient, own_client: bool) -> None:
    tracer = Tracer(echo=False, sink=info.push)
    try:
        result = await run_agent(info.task, info.config, client=client, tracer=tracer)
    except asyncio.CancelledError:
        if own_client:
            await client.aclose()
        _finalize(info, "cancelled", error="cancelled by user")
        return
    except Exception as e:  # 兜底：任何异常都变成界面可见的失败状态
        if own_client:
            await client.aclose()
        _finalize(info, "error", error=f"{type(e).__name__}: {e}")
        return
    if own_client:
        await client.aclose()
    info.result = {"output": result.output, "steps": result.steps,
                   "tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
                   "children": result.children_spawned}
    _finalize(info, "done" if result.error is None else "error",
              error=result.error, output=result.output, steps=result.steps,
              tokens_in=result.tokens_in, tokens_out=result.tokens_out,
              children=result.children_spawned)


@authed.post("/api/runs")
async def start_run(body: StartBody):
    task = (body.task or "").strip()
    if not task:
        raise HTTPException(400, "task must not be empty")
    config = AgentConfig(
        max_depth=max(0, min(3, body.max_depth)),
        max_steps=max(1, min(100, body.max_steps)),
        max_children=max(1, min(32, body.max_children)),
    )
    run_id = uuid4().hex[:8]
    info = RunInfo(run_id, task, config)
    RUNS[run_id] = info
    info.push({"t": time.time(), "kind": "run_queued", "run_id": run_id, "task": task,
               "config": {"max_depth": config.max_depth, "max_steps": config.max_steps,
                          "max_children": config.max_children}})
    while len(RUNS) > MAX_RUNS:  # 只保留最近 MAX_RUNS 条（优先清理已结束的）
        for old_id, old in list(RUNS.items()):
            if old.status != "running":
                del RUNS[old_id]
                break
        else:
            break
    own = bool(body.model) and body.model != _client.model
    client = LLMClient(model=body.model) if own else _client
    info.handle = asyncio.create_task(_execute(info, client, own))
    return {"run_id": run_id}


class TeamRunBody(BaseModel):
    task: str


async def _team_execute(info: RunInfo, client: LLMClient, own_client: bool) -> None:
    """团队运行：常驻 teammate + 消息协作 + 共享任务板，直到 lead 收尾。"""

    def emit(kind: str, **data) -> None:
        info.push({"t": time.time(), "kind": kind, **data})

    team = Team(emit=emit, client=client)
    info.team = team
    try:
        output = await team.run(info.task)
    except asyncio.CancelledError:
        team.cancel()
        if own_client:
            await client.aclose()
        _finalize(info, "cancelled", error="cancelled by user")
        return
    except Exception as e:
        if own_client:
            await client.aclose()
        _finalize(info, "error", error=f"{type(e).__name__}: {e}")
        return
    if own_client:
        await client.aclose()
    info.result = {"output": output, "team": team.roster_summary()}
    _finalize(info, "done", output=output, team=team.roster_summary())


@authed.post("/api/team/runs")
async def start_team_run(body: TeamRunBody):
    task = (body.task or "").strip()
    if not task:
        raise HTTPException(400, "task must not be empty")
    run_id = uuid4().hex[:8]
    info = RunInfo(run_id, task, AgentConfig())
    RUNS[run_id] = info
    info.push({"t": time.time(), "kind": "run_queued", "run_id": run_id, "task": task, "mode": "team"})
    info.handle = asyncio.create_task(_team_execute(info, _client, False))
    return {"run_id": run_id}


@authed.get("/api/runs")
async def list_runs():
    return sorted((r.summary() for r in RUNS.values()), key=lambda r: r["created"], reverse=True)


@authed.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    info = RUNS.get(run_id)
    if not info:
        raise HTTPException(404, "run not found")
    return info.summary()


class RunLabelBody(BaseModel):
    label: str


@authed.patch("/api/runs/{run_id}")
async def edit_run(run_id: str, body: RunLabelBody):
    """仅修改历史列表的显示名，原始任务与运行数据保持不变。传空字符串恢复默认显示。"""
    info = RUNS.get(run_id)
    if not info:
        raise HTTPException(404, "run not found")
    info.label = body.label.strip()[:80] or None
    return info.summary()


@authed.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    info = RUNS.get(run_id)
    if not info:
        raise HTTPException(404, "run not found")
    if info.status == "running":
        raise HTTPException(400, "run is still in progress; cancel it before deleting")
    if info.team:
        info.team.cancel()
    if info.handle and not info.handle.done():
        info.handle.cancel()
    RUNS.pop(run_id, None)
    return {"deleted": True}


@authed.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    info = RUNS.get(run_id)
    if not info:
        raise HTTPException(404, "run not found")
    if info.status == "running" and info.handle and not info.handle.done():
        if info.team:
            info.team.cancel()
        info.handle.cancel()
        return {"cancelled": True}
    return {"cancelled": False, "status": info.status}


@authed.get("/api/runs/{run_id}/events")
async def run_events(run_id: str):
    info = RUNS.get(run_id)
    if not info:
        raise HTTPException(404, "run not found")

    async def gen():
        idx = 0
        while True:
            while idx < len(info.events):  # 先补发历史（历史回放也走这条）
                yield f"data: {json.dumps(info.events[idx], ensure_ascii=False, default=str)}\n\n"
                idx += 1
            if info.status != "running":
                yield "event: end\ndata: {}\n\n"
                return
            await asyncio.sleep(0.15)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@authed.get("/api/info")
async def info():
    return {"model": _client.model, "base_url": _client.base_url, "version": __version__}


@authed.get("/api/models")
async def models():
    try:
        return await _client.list_models()
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch model list: {e}")


app.include_router(authed)

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="web")
else:
    @app.get("/")
    async def _no_ui():
        return {"message": "Frontend not built: run `pnpm install && pnpm build` in the frontend/ directory and restart the server"}


def main():
    p = argparse.ArgumentParser(prog="agentree-server", description="agentree Web 界面")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
