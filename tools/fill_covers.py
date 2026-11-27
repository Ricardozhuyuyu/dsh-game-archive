#!/usr/bin/env python3
"""只补「缺封面」的条目，且必须过名称校验。

上一版之所以把 Astro Bot 抓成《Sackboy》ASTRO BOT 服装，是因为 Steam 搜索的第一条
往往是 DLC / 捆绑包。这里改成：
  - 查 storesearch，拿全部候选
  - 用 difflib 比名字，低于阈值的丢掉；
  - 只收 app 类型（有 id 且是游戏条目），不碰 bundle/sub
  - 已经有 cover 的一律不覆盖
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
HOSTS = ['https://cdn.cloudflare.steamstatic.com', 'https://cdn.akamai.steamstatic.com',
         'https://shared.akamai.steamstatic.com']
BAD = re.compile(r'(DLC|dlc|服装|皮肤|套装|捆绑|bundle|pack|soundtrack|原声|season pass|升级包|礼包)', re.I)


def norm(s: str) -> str:
    s = str(s or '').lower().replace('™', '').replace('®', '')
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]+', '', s)


def get(url: str, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def search(term: str) -> list[dict]:
    url = 'https://store.steampowered.com/api/storesearch/?' + urllib.parse.urlencode(
        {'term': term, 'cc': 'cn', 'l': 'zh'})
    try:
        data = json.loads(get(url).decode('utf-8', 'replace'))
        return data.get('items') or []
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', required=True)
    ap.add_argument('--min-score', type=float, default=0.72)
    ap.add_argument('--sleep', type=float, default=0.7)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    media = json.load(open(args.file))
    todo = [k for k, v in media.items()
            if isinstance(v, dict) and not v.get('cover') and not BAD.search(k)]
    todo.sort()
    if args.limit:
        todo = todo[:args.limit]
    print(f'缺封面 {len(todo)} 条待试')

    found = []
    for i, name in enumerate(todo, 1):
        for cand in search(name)[:6]:
            cid, cname = cand.get('id'), cand.get('name') or ''
            if not cid or BAD.search(cname):
                continue
            score = difflib.SequenceMatcher(None, norm(name), norm(cname)).ratio()
            if score < args.min_score:
                continue
            m = media[name]
            m['cover'] = f'{HOSTS[0]}/steam/apps/{cid}/header.jpg'
            m['src'] = 'steam'
            m.setdefault('cn', m.get('cn') or '')
            found.append((name, cname, round(score, 2), cid))
            break
        if i % 40 == 0:
            print(f'  {i}/{len(todo)} 命中 {len(found)}', flush=True)
        time.sleep(args.sleep)

    print(f'命中 {len(found)} / {len(todo)}')
    for f in found[:12]:
        print('  ', f)
    if args.apply:
        stamp = time.strftime('%Y%m%d-%H%M%S')
        shutil.copy2(args.file, f'{args.file}.bak-{stamp}')
        with open(args.file, 'w', encoding='utf-8') as fh:
            json.dump(media, fh, ensure_ascii=False, indent=1)
            fh.write('\n')
        print('wrote', args.file)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
