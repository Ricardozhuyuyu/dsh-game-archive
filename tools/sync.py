#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五平台游戏档案 · 一键同步

借你已登录的 Chrome（默认 CDP 端口 9333）把五个平台的数据抓回来，写成
records.json。手动打的状态 / 评分 / 短评在 userdata.json 里，这里永远不碰。

    python3 tools/sync.py --port 9333 --out "$HOME/Documents/.../游戏档案"

平台开关：--only steam,psn   --skip switch,epic
账号参数：--steam-id  --psn-id  --xbox-xuid  --switch-player

只依赖标准库：WebSocket 客户端是自己写的，不需要 pip 装任何东西。
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36")

# 账号不写死在代码里：放在数据目录的 accounts.json，命令行参数优先
DEFAULTS = {
    "steam_id": "",
    "psn_id": "",
    "xbox_xuid": "",
    "switch_player": "",
    "heybox_user_id": "",
}

ACCOUNTS_HELP = """{
  "steam_id": "你的 Steam 自定义网址（steamcommunity.com/id/<这里>）",
  "psn_id": "你的 PSN 在线 ID",
  "xbox_xuid": "Xbox 的 xuid（16 位数字）",
  "switch_player": "Switch 好友码 SW-xxxx-xxxx-xxxx",
  "heybox_user_id": "小黑盒 user_id（分享链接里 user_id= 后面那串）"
}"""


def load_accounts(out_dir: str, explicit: str = "") -> dict:
    """读 accounts.json（数据目录里），命令行参数后面会覆盖它。"""
    path = explicit or os.path.join(out_dir, "accounts.json")
    if not os.path.exists(path):
        return {}
    try:
        data = json.load(open(path, encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        log(f"[配置] accounts.json 读不动：{e}")
        return {}
    return {k: str(v) for k, v in data.items() if k in DEFAULTS and v}


def log(msg: str) -> None:
    print(msg, flush=True)


# ───────────────────────────── WebSocket（最小实现） ─────────────────────────────
class WS:
    """够用就行的 RFC6455 客户端：文本帧 + ping/pong + 分片忽略。"""

    def __init__(self, url: str, timeout: float = 60.0):
        u = urllib.parse.urlparse(url)
        host = u.hostname or "127.0.0.1"
        port = u.port or 80
        self.sock = socket.create_connection((host, port), timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path + (("?" + u.query) if u.query else "")
        req = (
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket 握手被断开")
            buf += chunk
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError("WebSocket 握手失败：" + head.decode("utf-8", "replace")[:200])

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("WebSocket 已关闭")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text: str) -> None:
        data = text.encode()
        header = b"\x81"
        n = len(data)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(header + mask + body)

    def recv(self) -> str:
        while True:
            b1, b2 = self._read(2)
            op = b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n) if n else b""
            if op == 0x8:
                raise ConnectionError("WebSocket 对端关闭")
            if op == 0x9:
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if op in (0x1, 0x2):
                return payload.decode("utf-8", "replace")

    def settimeout(self, t):
        self.sock.settimeout(t)


class CDP:
    """一个 page target 的窄封装：命令 + 事件 + 取签名 URL。"""

    def __init__(self, port: int = 9333):
        url = f"http://127.0.0.1:{port}/json"
        try:
            info = json.load(urllib.request.urlopen(url, timeout=5))
        except Exception as exc:  # noqa: BLE001
            hint = (
                f'  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
                f"--remote-debugging-port={port}"
                if sys.platform == "win32" else
                f'  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" '
                f"--remote-debugging-port={port}"
            )
            raise SystemExit(
                f"连不上 CDP 端口 {port}：{exc}\n"
                f"先把已经登录好的 Chrome 用调试端口启动（Windows 双击 启动Chrome调试.bat）：\n{hint}"
            )
        pages = [t for t in info if t.get("type") == "page"]
        if not pages:
            raise SystemExit("Chrome 里没有可用的页面，先随便开一个标签页")
        self.target = pages[0]
        self.ws = WS(self.target["webSocketDebuggerUrl"])
        self.n = 0
        self.events: list[dict] = []

    def cmd(self, method: str, **params):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg)

    def drain(self, seconds: float = 0.5) -> None:
        self.ws.settimeout(seconds)
        try:
            while True:
                msg = json.loads(self.ws.recv())
                if "method" in msg:
                    self.events.append(msg)
        except (socket.timeout, TimeoutError):
            pass
        except ConnectionError:
            pass
        finally:
            self.ws.settimeout(120)

    def js(self, expr: str, await_promise: bool = False):
        res = self.cmd(
            "Runtime.evaluate",
            expression=expr,
            returnByValue=True,
            awaitPromise=await_promise,
            userGesture=True,
        )
        return res.get("result", {}).get("value")

    def goto(self, url: str, settle: float = 2.5) -> None:
        self.cmd("Page.navigate", url=url)
        deadline = time.time() + settle
        while time.time() < deadline:
            self.drain(0.4)
        try:
            self.js("document.readyState")
        except Exception:  # noqa: BLE001
            pass

    def signed_url(self, page: str, needle: str, budget: float = 15.0) -> str:
        """打开页面，从网络事件里捞一条含 needle 的完整 URL（带 hkey 签名）。"""
        self.cmd("Network.enable")
        self.events.clear()
        self.cmd("Page.navigate", url=page)
        deadline = time.time() + budget
        found = ""
        while time.time() < deadline:
            self.drain(0.4)
            for ev in self.events:
                if ev.get("method") == "Network.requestWillBeSent":
                    u = ev["params"]["request"]["url"]
                    if needle in u and "hkey=" in u:
                        found = u
                elif ev.get("method") == "Network.responseReceived":
                    u = ev["params"]["response"]["url"]
                    if needle in u and "hkey=" in u:
                        found = u
            if found:
                return found
        raise RuntimeError(f"没抓到 {needle} 的签名请求（页面可能没登录/没绑定）")


COOKIE = ""


def cookie_header(tab: CDP, needles=("xiaoheihe", "max-c.com")) -> str:
    """把 Chrome 里的登录 cookie 拼成 Cookie 头——小黑盒接口要登录态。"""
    try:
        jar = tab.cmd("Network.getAllCookies").get("cookies") or []
    except Exception:  # noqa: BLE001
        return ""
    keep = [c for c in jar if any(n in (c.get("domain") or "") for n in needles)]
    return "; ".join(f"{c['name']}={c['value']}" for c in keep)


def get_json(url: str, timeout: float = 30.0):
    headers = {
        "user-agent": UA,
        "accept": "application/json, text/plain, */*",
        "referer": "https://web.xiaoheihe.cn/",
    }
    if COOKIE:
        headers["cookie"] = COOKIE
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# ───────────────────────────── 小工具 ─────────────────────────────
def num(x, default=0.0) -> float:
    if x is None:
        return default
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"\d+(?:\.\d+)?", str(x).replace(",", ""))
    return float(m.group()) if m else default


def fmt_date(value: str) -> str:
    return str(value or "")[:10]


def rel_year(text: str, today: dt.date | None = None) -> str:
    """「3年前」→ 2023；「4年前」→ 2022。"""
    today = today or dt.date.today()
    m = re.search(r"(\d+)\s*年前", str(text or ""))
    if m:
        return str(today.year - int(m.group(1)))
    m = re.search(r"(\d{4})-(\d{2})", str(text or ""))
    return m.group(1) if m else ""


def steam_date(text: str) -> str:
    """Steam 的「上次运行」今年内只写「Nov 4」，跨年才带年份——两种都得认。"""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return dt.datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    # 没有年份：按今年算；若落成未来日期，说明是去年
    for fmt in ("%b %d", "%B %d"):
        try:
            d = dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        today = dt.date.today()
        cand = d.replace(year=today.year)
        if cand > today + dt.timedelta(days=1):
            cand = cand.replace(year=today.year - 1)
        return cand.isoformat()
    return ""


def gid(platform: str, name: str) -> str:
    h = hashlib.sha1(f"{platform}|{name}".encode()).hexdigest()[:8]
    return f"{platform.lower()}-{h}"


# ───────────────────────────── Steam ─────────────────────────────
STEAM_JS = r"""
(() => {
  const out = [];
  const seen = new Set();
  const anchors = [...document.querySelectorAll('a[href*="/app/"]')];
  for (const a of anchors) {
    const m = (a.getAttribute('href') || '').match(/\/app\/(\d+)/);
    if (!m) continue;
    const appid = m[1];
    if (seen.has(appid)) continue;
    let el = a;
    let row = null;
    for (let i = 0; i < 5 && el; i++) {
      const t = el.innerText || '';
      if (t.length > (a.innerText || '').length + 4) { row = el; break; }
      el = el.parentElement;
    }
    if (!row) continue;
    seen.add(appid);
    const lines = (row.innerText || '').split('\n').map((x) => x.trim()).filter(Boolean);
    out.push({ appid, name: lines[0] || '', text: row.innerText || '' });
  }
  return JSON.stringify(out);
})()
"""


def sync_steam(tab: CDP, cfg, out: list) -> None:
    url = f"https://steamcommunity.com/id/{cfg['steam_id']}/games/?tab=all"
    log(f"[Steam] 打开 {url}")
    tab.goto(url, settle=6)
    raw = tab.js(STEAM_JS) or "[]"
    rows = json.loads(raw)
    if not rows:
        body = tab.js("document.body.innerText.slice(0,200)") or ""
        raise RuntimeError(f"没解析到游戏行，页面文本：{body[:120]}")
    for r in rows:
        text = r["text"]
        hm = re.search(r"(?:TOTAL PLAYED|总时数|總時數|总时长)\s*\n?\s*([\d,]+(?:\.\d+)?)\s*(hours|hrs|小时)", text, re.I)
        mm = re.search(r"(?:TOTAL PLAYED|总时数|總時數|总时长)\s*\n?\s*([\d,]+)\s*(minutes|分钟)", text, re.I)
        if hm:
            hours = num(hm.group(1))
        elif mm:
            hours = num(mm.group(1)) / 60.0
        else:
            hours = 0.0
        ach = re.search(r"(\d+)\s*(?:of|/)\s*(\d+)\s*(?:\(\d+%\))?", text)
        played = re.search(
            r"(?:LAST PLAYED|最近运行|上次运行)\s*\n?\s*"
            r"([A-Za-z]{3,9} \d{1,2}, \d{4}|[A-Za-z]{3,9} \d{1,2}|\d{4}-\d{2}-\d{2})",
            text, re.I)
        out.append({
            "id": gid("Steam", r["name"]),
            "name": r["name"],
            "platform": "Steam",
            "hours": round(hours, 1),
            "progress": f"{ach.group(1)}/{ach.group(2)}" if ach else None,
            "ach": f"{ach.group(1)}/{ach.group(2)} 成就" if ach else "",
            "last": steam_date(played.group(1)) if played else "",
            "detail": "",
            "note": "Steam 页面",
            "cover": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{r['appid']}/header.jpg",
        })
    log(f"[Steam] {len(out)} 款")


# ───────────────────────────── PSN ─────────────────────────────
def sync_psn(tab: CDP, cfg, out: list) -> None:
    page = ("https://web.xiaoheihe.cn/account/psn_personal_page/home"
            f"?is_share=1&player_id={urllib.parse.quote(cfg['psn_id'])}"
            f"&user_id={urllib.parse.quote(cfg['heybox_user_id'])}")
    log("[PSN] 抓签名 URL…")
    base = tab.signed_url(page, "get_player_games")
    games: list[dict] = []
    for offset in (0, 30, 60):
        url = re.sub(r"&limit=\d+", "&limit=30", base)
        url = re.sub(r"&offset=\d+", "", url) + f"&offset={offset}"
        data = get_json(url)
        batch = (data.get("result") or {}).get("games") or []
        games.extend(batch)
        if len(batch) < 30:
            break
    for g in games:
        tot, got = int(g.get("achivement_count") or 0), int(g.get("achieved_count") or 0)
        out.append({
            "id": gid("PSN", g.get("game_name") or ""),
            "name": g.get("game_name") or "",
            "platform": "PSN",
            "hours": round(((g.get("playtime_second") or 0) / 3600), 1),
            "progress": int(g.get("progress") or 0) if tot else None,
            "ach": f"{got}/{tot} 奖杯" if tot else "",
            "last": fmt_date(g.get("last_play_date")),
            "detail": " · ".join(g.get("version_tags") or []),
            "note": "小黑盒 PSN",
            "cover": g.get("game_img") or "",
        })
    log(f"[PSN] {len(out)} 款")


# ───────────────────────────── Switch ─────────────────────────────
def sync_switch(tab: CDP, cfg, out: list, override: dict) -> None:
    by_name = override.get("byName") or {}
    extras = override.get("extra") or []
    player = cfg.get("switch_player") or ""
    page = ("https://web.xiaoheihe.cn/account/switch_personal_page/home"
            f"?is_share=1&player_id={urllib.parse.quote(player)}"
            f"&user_id={urllib.parse.quote(cfg['heybox_user_id'])}")
    log("[Switch] 抓签名 URL…")
    base = tab.signed_url(page, "/game/switch/jp/games/data")
    games: list[dict] = []
    for offset in (0, 100):
        url = re.sub(r"&offset=\d+", "", base) + f"&offset={offset}"
        data = get_json(url)
        batch = (data.get("result") or {}).get("games") or data.get("result") or []
        if isinstance(batch, dict):
            batch = batch.get("list") or []
        games.extend(batch)
        if len(batch) < 100:
            break
    seen = set()
    for g in games:
        name = g.get("name") or ""
        if not name or name in seen:
            continue
        seen.add(name)
        played = g.get("played_time")
        hours = num(played)
        note = "小黑盒 Switch"
        if by_name.get(name):
            hours = float(by_name[name])
            note = "任天堂 App 计时"
        out.append({
            "id": gid("Switch", name),
            "name": name,
            "platform": "Switch",
            "hours": round(hours, 1),
            "progress": None,
            "ach": "",
            "last": rel_year(g.get("last_play_time")),
            "detail": "",
            "note": note,
            "cover": g.get("image") or g.get("square_image") or "",
        })
    for e in extras:
        if not e.get("name") or e["name"] in seen:
            continue
        seen.add(e["name"])
        out.append({
            "id": gid("Switch", e["name"]),
            "name": e["name"],
            "platform": "Switch",
            "hours": round(float(e.get("hours") or 0), 1),
            "progress": None,
            "ach": "",
            "last": "",
            "detail": "",
            "note": "任天堂 App 计时",
            "cover": "",
        })
    log(f"[Switch] {len(out)} 款")


# ───────────────────────────── Xbox ─────────────────────────────
def sync_xbox(tab: CDP, cfg, out: list) -> None:
    xuid = cfg["xbox_xuid"]
    page = ("https://web.xiaoheihe.cn/account/xbox_personal_page/home"
            f"?is_share=1&xuid={xuid}")
    log("[Xbox] 抓签名 URL…")
    base = tab.signed_url(page, "/game/xbox/v3/game_list")
    url = re.sub(r"&limit=\d+", "", base)
    url = re.sub(r"&offset=\d+", "", url) + "&limit=50&offset=0"
    data = get_json(url)
    games = ((data.get("result") or {}).get("list")) or []
    for g in games:
        tot = int(g.get("total_achievements") or 0)
        got = int(g.get("earned_achievements") or 0)
        out.append({
            "id": gid("Xbox", g.get("name") or ""),
            "name": g.get("name") or "",
            "platform": "Xbox",
            "hours": round((g.get("minutes_played") or 0) / 60, 1),
            "progress": f"{got}/{tot}" if tot else None,
            "ach": f"{got}/{tot} 成就" if tot else "",
            "last": fmt_date(g.get("last_played_desc")),
            "detail": "",
            "note": "小黑盒 Xbox",
            "cover": (g.get("head_img_info") or {}).get("url") or "",
        })
    log(f"[Xbox] {len(out)} 款")


# ───────────────────────────── Epic ─────────────────────────────
EPIC_JS = r"""
(async () => {
  const all = [];
  let token = '';
  for (let i = 0; i < 40; i++) {
    const q = 'count=10&sortDir=DESC&sortBy=DATE' + (token ? '&nextPageToken=' + encodeURIComponent(token) : '');
    const r = await fetch('/account/v2/payment/ajaxGetOrderHistory?' + q, {
      credentials: 'include', headers: { accept: 'application/json' },
    });
    if (!r.ok) return JSON.stringify({ error: 'HTTP ' + r.status, orders: all });
    const j = await r.json();
    const orders = j.orders || [];
    all.push(...orders);
    token = j.nextPageToken || '';
    if (!token || !orders.length) break;
  }
  return JSON.stringify({ orders: all });
})()
"""


def sync_epic(tab: CDP, cfg, out: list) -> None:
    log("[Epic] 打开账户后台…")
    tab.goto("https://accounts.epicgames.com/account/personal", settle=4)
    raw = tab.js(EPIC_JS, await_promise=True)
    if not raw:
        raise RuntimeError("页面没返回订单（可能没登录）")
    data = json.loads(raw)
    if data.get("error"):
        raise RuntimeError(f"订单接口 {data['error']}")
    seen = set()
    for o in data.get("orders") or []:
        items = o.get("items") or []
        if not items:
            continue
        name = (items[0].get("description") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        list_price = sum((it.get("amount") or 0) for it in items) / 100
        promo = sum((p.get("amount") or 0) for p in (o.get("promotions") or [])) / 100
        when = dt.datetime.fromtimestamp((o.get("createdAtMillis") or 0) / 1000).strftime("%Y-%m-%d")
        note = "免费领取" if list_price <= 0 or promo >= list_price - 0.01 else f"原价 ¥{list_price:.0f}"
        if len(items) > 1:
            note += f"（含 {len(items)} 件）"
        out.append({
            "id": gid("Epic", name),
            "name": name,
            "platform": "Epic",
            "hours": 0,
            "progress": None,
            "ach": "",
            "last": when,
            "detail": "",
            "note": note,
            "cover": "",
        })
    log(f"[Epic] {len(out)} 款")


# ───────────────────────────── 主流程 ─────────────────────────────

def dedupe(rows: list[dict]) -> list[dict]:
    """同一平台同名的多条（PSN 常把 PS4/PS5 两个版本各报一次）合成一条：
    时长取大的、进度取高的、最后游玩取晚的，id 沿用第一条（于是人工数据不会错位）。"""
    out: list[dict] = []
    seen: dict[tuple, dict] = {}
    for g in rows:
        key = ((g.get("platform") or ""), (g.get("name") or "").strip().lower())
        hit = seen.get(key)
        if not hit:
            seen[key] = g
            out.append(g)
            continue
        hit["hours"] = max(hit.get("hours") or 0, g.get("hours") or 0)
        if g.get("progress") is not None:
            hit["progress"] = max(hit.get("progress") or 0, g.get("progress") or 0)
        if (g.get("last") or "") > (hit.get("last") or ""):
            hit["last"] = g.get("last")
        if g.get("ach") and g["ach"] not in (hit.get("ach") or ""):
            hit["ach"] = g["ach"] if not hit.get("ach") else hit["ach"]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="五平台游戏档案同步")
    ap.add_argument("--port", type=int, default=9333, help="Chrome 调试端口")
    ap.add_argument("--out", required=True, help="数据目录（records.json 写这里）")
    ap.add_argument("--only", default="", help="只同步这些平台，逗号分隔")
    ap.add_argument("--skip", default="", help="跳过这些平台，逗号分隔")
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), dest=k, default=v)
    ap.add_argument("--accounts", default="", help="accounts.json 的路径（默认在 --out 目录里）")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    cfg = {k: "" for k in DEFAULTS}
    cfg.update(load_accounts(args.out, args.accounts))
    for k in DEFAULTS:                       # 命令行给的值优先
        v = getattr(args, k, "")
        if v:
            cfg[k] = v
    only = {s.strip().lower() for s in args.only.split(",") if s.strip()}
    skip = {s.strip().lower() for s in args.skip.split(",") if s.strip()}

    override_path = os.path.join(args.out, "switch-override.json")
    override = {}
    if os.path.exists(override_path):
        try:
            override = json.load(open(override_path, encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            override = {}

    old_ids = {}
    rec_path = os.path.join(args.out, "records.json")
    if os.path.exists(rec_path):
        try:
            for g in (json.load(open(rec_path, encoding="utf-8")).get("games") or []):
                old_ids[(g.get("platform"), g.get("name"))] = g.get("id")
        except Exception:  # noqa: BLE001
            pass

    tab = CDP(args.port)
    global COOKIE
    COOKIE = cookie_header(tab)
    if COOKIE:
        log(f"[登录态] 取到 {COOKIE.count('=')} 个 cookie")
    else:
        log("[登录态] 没取到小黑盒 cookie，PSN/Switch/Xbox 可能会要求登录")
    games: list[dict] = []
    failures: list[str] = []
    jobs = [
        ("steam", lambda o: sync_steam(tab, cfg, o)),
        ("psn", lambda o: sync_psn(tab, cfg, o)),
        ("switch", lambda o: sync_switch(tab, cfg, o, override)),
        ("xbox", lambda o: sync_xbox(tab, cfg, o)),
        ("epic", lambda o: sync_epic(tab, cfg, o)),
    ]
    for key, fn in jobs:
        if only and key not in only:
            continue
        if key in skip:
            continue
        buf: list[dict] = []
        t0 = time.time()
        try:
            fn(buf)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{key}: {exc}")
            log(f"[{key}] 失败：{exc}")
            continue
        log(f"[{key}] 完成，{len(buf)} 款，{time.time() - t0:.1f}s")
        games.extend(buf)

    before = len(games)
    games = dedupe(games)
    if before != len(games):
        log(f"[去重] {before} → {len(games)} 款（同平台同名的合并了 {before - len(games)} 条）")

    # id 尽量沿用旧的，手动数据才不会错位
    for g in games:
        g["id"] = old_ids.get((g["platform"], g["name"]), g["id"])

    if not games:
        log("一条都没抓到，保留原有 records.json 不动。")
        return 2

    payload = {
        "updated": dt.date.today().isoformat(),
        "games": games,
    }
    tmp = rec_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, rec_path)

    by_plat: dict[str, int] = {}
    for g in games:
        by_plat[g["platform"]] = by_plat.get(g["platform"], 0) + 1
    total_h = sum(g["hours"] for g in games)
    log("")
    log(f"写入 {rec_path}")
    log(f"合计 {len(games)} 款 · {total_h:.1f} 小时 · " +
        " / ".join(f"{k} {v}" for k, v in by_plat.items()))
    if failures:
        log("有平台失败（其它平台的已经写入）：")
        for f in failures:
            log("  - " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
