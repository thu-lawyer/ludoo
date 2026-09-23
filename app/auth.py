"""访问口令保护：LUDOO_PASSWORD 设置后，页面与 API 均需登录。

会话：HMAC-SHA256 签名 cookie（ludoo_auth），HttpOnly，7 天有效。
密钥 = 口令派生密钥 + 服务启动时的随机盐（存内存），重启后需重新登录。
口令未设置时鉴权整体关闭，本地体验与无此模块一致。
"""
import hashlib
import hmac
import os
import secrets
import time

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import config

COOKIE_NAME = "ludoo_auth"
TTL_SECONDS = 7 * 24 * 3600
# 启动时随机盐：cookie 无法跨服务重启伪造，也无需额外存储
_SERVER_SALT = secrets.token_hex(16)

_LOGIN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>登录 · 律读</title>
<style>
:root{--bg:#f6f4ef;--paper:#fffdf8;--ink:#2a2823;--ink-2:#6d675c;--ink-3:#a09a8c;
--line:#e7e2d6;--accent:#1f4e5f;--accent-hover:#2a6277;--danger:#b3543f;
--sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
--serif:"Songti SC","STSong","Source Han Serif SC","Noto Serif SC",Georgia,serif}
[data-theme="dark"]{--bg:#191815;--paper:#211f1b;--ink:#d9d4c8;--ink-2:#9d968a;--ink-3:#6e685e;
--line:#35322b;--accent:#6aa3b8;--accent-hover:#86bacd;--danger:#d07a5f}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:var(--sans);background:var(--bg);color:var(--ink);min-height:100vh;
display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:var(--paper);border:1px solid var(--line);border-radius:12px;
padding:38px 34px 32px;width:360px;max-width:100%;
box-shadow:0 1px 3px rgba(42,40,35,.06),0 6px 24px rgba(42,40,35,.07)}
.mark{width:52px;height:52px;border-radius:13px;background:var(--accent);color:#fff;
display:flex;align-items:center;justify-content:center;font-family:var(--serif);
font-size:26px;font-weight:700;margin:0 auto 16px}
h1{font-family:var(--serif);font-size:20px;text-align:center;margin-bottom:4px}
.sub{text-align:center;font-size:12px;color:var(--ink-3);letter-spacing:.14em;margin-bottom:26px}
input{width:100%;padding:11px 13px;border:1px solid var(--line);border-radius:7px;
font-size:15px;background:var(--paper);color:var(--ink);outline:none;margin-bottom:14px}
input:focus{border-color:var(--accent)}
button{width:100%;padding:11px;border:none;border-radius:7px;background:var(--accent);
color:#fff;font-size:15px;font-family:inherit;cursor:pointer}
button:hover{background:var(--accent-hover)}
.err{color:var(--danger);font-size:13px;text-align:center;margin-bottom:12px;display:none}
.tint{background:var(--danger)}
</style>
</head>
<body>
<div class="card">
  <div class="mark">律</div>
  <h1>律读</h1>
  <div class="sub">LUDOO · 法学文献阅读器</div>
  <div class="err" id="err">口令不正确，请重试</div>
  <form method="post" action="/login">
    <input type="password" name="password" placeholder="访问口令" autofocus required>
    <button type="submit">进 入</button>
  </form>
</div>
<script>if(location.search.includes("err=1"))document.getElementById("err").style.display="block";
if(window.matchMedia&&matchMedia("(prefers-color-scheme: dark)").matches)document.documentElement.dataset.theme="dark";</script>
</body>
</html>"""


def _session_key() -> bytes:
    return hashlib.sha256(f"{_SERVER_SALT}:{config.LUDOO_PASSWORD}".encode()).digest()


def _sign(expires: int) -> str:
    msg = str(expires).encode()
    return hmac.new(_session_key(), msg, hashlib.sha256).hexdigest()


def _make_cookie_value() -> str:
    expires = int(time.time()) + TTL_SECONDS
    return f"{expires}.{_sign(expires)}"


def _valid(value: str | None) -> bool:
    if not value or not config.LUDOO_PASSWORD:
        return False
    try:
        expires, sig = value.split(".", 1)
        if int(expires) < time.time():
            return False
        return hmac.compare_digest(sig, _sign(int(expires)))
    except (ValueError, TypeError):
        return False


def is_authenticated(request: Request) -> bool:
    return _valid(request.cookies.get(COOKIE_NAME))


async def auth_middleware(request: Request, call_next):
    """LUDOO_PASSWORD 已设置且未登录：API 401 / 页面跳登录。"""
    if not config.LUDOO_PASSWORD or is_authenticated(request):
        return await call_next(request)
    path = request.url.path
    if path in ("/login", "/logout") or path.endswith(".ico"):
        return await call_next(request)
    if path.startswith("/api/"):
        return Response(status_code=401, headers={"WWW-Authenticate": "Cookie"})
    return RedirectResponse("/login", status_code=302)


def login_page() -> HTMLResponse:
    return HTMLResponse(_LOGIN_PAGE)


def handle_login(password: str) -> Response:
    if config.LUDOO_PASSWORD and hmac.compare_digest(password, config.LUDOO_PASSWORD):
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie(COOKIE_NAME, _make_cookie_value(),
                        max_age=TTL_SECONDS, httponly=True, samesite="lax")
        return resp
    return RedirectResponse("/login?err=1", status_code=302)


def logout() -> RedirectResponse:
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME)
    return resp
