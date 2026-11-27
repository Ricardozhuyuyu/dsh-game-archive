#!/usr/bin/env python3
"""把 TGA 名单和游戏库对上：中文名、封面、可点击。

为什么要这个脚本：tga-history 里是维基的英文题名，库里 PSN / Switch 的游戏只有中文名，
两边对不上就会——显示英文、没封面、还点不动（灰的）。

做法：
  1. 自动匹配：库里 name / enrichment.name / nameOnSteam，与 wiki 名及其 alias、media.cn 比
     （归一化后相等，或去掉副标题后相等）
  2. 人工映射表 MANUAL：库里中文名 -> wiki 题名，只收 MANUAL 里确实出现在名单中的
  3. 命中后写 media[wiki] = {cn: 库中文名, cover: 库封面}、alias[wiki] = 库中文名
  4. 顺手清掉 media 里的脏中文名（抓到 DLC / 服装 / 捆绑包那种）

用法：
  python3 tools/link_tga.py --runtime ~/Documents/deepseek-harness/work/游戏档案 --apply
  不带 --apply 只打印会改什么。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')

# 库里只有中文名（PSN / Switch / Xbox），靠这张表跟 wiki 题名接上
MANUAL = {
    '战神：诸神黄昏': 'God of War Ragnarök',
    '对马岛之魂：导演剪辑版': 'Ghost of Tsushima',
    '女神异闻录５ 皇家版': 'Persona 5 Royal',
    '如龙7 光与暗的去向': 'Yakuza: Like a Dragon',
    '人中之龙０\u3000誓约的场所': 'Yakuza 0',
    '人中之龙８': 'Like a Dragon: Infinite Wealth',
    '审判之眼：死神的遗言 重制版': 'Judgment',
    '审判之逝：湮灭的记忆': 'Lost Judgment',
    '仁王２：完全重制版': 'Nioh 2',
    '地平线 零之曙光': 'Horizon Zero Dawn',
    '死亡搁浅 导演剪辑版': 'Death Stranding',
    '天穗之咲稻姬': 'Sakuna: Of Rice and Ruin',
    '宇宙机器人无线控制器使用指南': "Astro's Playroom",
    '星球大战 绝地：陨落的武士团': 'Star Wars Jedi: Fallen Order',
    '霍格沃茨：遗产': 'Hogwarts Legacy',
    '极乐迪斯科：最终剪辑版': 'Disco Elysium',
    '漫威蜘蛛侠:迈尔斯·莫拉莱斯': "Marvel's Spider-Man: Miles Morales",
    '漫威蜘蛛侠年度版': "Marvel's Spider-Man",
    '无间冥寺': 'Curse of the Dead Gods',
    '极限巅峰': 'Steep',
    '极限国度': 'Riders Republic',
    '风火轮：爆发': 'Hot Wheels Unleashed',
    '勇者斗恶龙XI S 寻觅逝去的时光 决定版': 'Dragon Quest XI',
    '生化危机7': 'Resident Evil 7: Biohazard',
    '底特律：化身为人': 'Detroit: Become Human',
    '异度神剑 终极版': 'Xenoblade Chronicles: Definitive Edition',
    '怪物猎人：崛起': 'Monster Hunter Rise',
    '超级马里奥派对': 'Super Mario Party',
    '八方旅人': 'Octopath Traveler',
    '胡闹厨房：全都好吃': 'Overcooked! All You Can Eat',
    '卡比的梦想自助餐': "Kirby's Dream Buffet",
    '任天堂全明星大乱斗 特别版': 'Super Smash Bros. Ultimate',
    '超级鸡马': 'Ultimate Chicken Horse',
    '黑魂 重制版': 'Dark Souls Remastered',
    '喷射战士2': 'Splatoon 2',
    '宝可梦 剑': 'Pokémon Sword',
    '宝可梦 晶灿钻石': 'Pokémon Brilliant Diamond',
    '乐高哈利波特：第5-7年': 'LEGO Harry Potter',
    '伊苏8：达娜的安魂曲': 'Ys VIII: Lacrimosa of Dana',
    '看门狗': 'Watch Dogs',
    '刺客信条3 重制版': "Assassin's Creed III Remastered",
    '刺客信条：艾吉奥合集': "Assassin's Creed: The Ezio Collection",
    '一起玩农场': 'Farm Together',
    '喵咪斗恶龙2': 'Cat Quest II',
    '十三機兵防衛圏 体験版': '13 Sentinels: Aegis Rim',
    '这就是警察': 'This Is the Police',
    '神力科莎:竞技版': 'Assetto Corsa Competizione',
    '真・三国无双 起源': 'Dynasty Warriors: Origins',
    '极品飞车：热度': 'Need for Speed Heat',
    '神秘海域:盗贼传奇合辑': 'Uncharted: Legacy of Thieves Collection',
}

DIRTY = re.compile(r'《|》|服装|赛车服|DLC|捆绑|套装|季票|扩展包|皮肤|道具|原声|soundtrack|bundle|costume', re.I)


def norm(s: str) -> str:
    s = str(s or '').lower()
    s = re.sub(r'[™®©]', '', s)
    return re.sub(r'[^\w\u4e00-\u9fff]+', '', s, flags=re.U)


def base(s: str) -> str:
    s = re.sub(r'[™®©]', '', str(s or ''))
    s = re.split(r'[:\-–—]| - ', s)[0]
    return norm(s)


def has_cjk(s: str) -> bool:
    return bool(re.search(r'[\u3400-\u9fff]', str(s or '')))


def clean_cn(cn: str) -> str:
    """把「中文名 + 英文括注 + DLC 尾巴」收拾成干净中文名。"""
    s = str(cn or '').strip().replace('《', '').replace('》', '')
    s = re.sub(r'[（(][^)）]*[)）]', lambda m: '' if not has_cjk(m.group(0)) else m.group(0), s)
    s = re.split(r'\s*(?:DLC|dlc|服装|皮肤|捆绑|套装|季票|扩展包|原声|Soundtrack|Bundle|Costume)', s)[0]
    s = s.strip(' -—–·・:：,，')
    if has_cjk(s):
        first = re.search(r'[\u3400-\u9fff]', s)
        if first and first.start() > 12:          # 前面挂着一长串英文，砍掉
            s = s[first.start():].strip(' -—–·・:：,，')
    return s


def dirty(cn: str) -> bool:
    cn = str(cn or '')
    if not cn:
        return False
    if DIRTY.search(cn):
        return True
    if not has_cjk(cn):
        return True                      # 纯英文，等于没翻
    if len(cn) > 26:
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--runtime', required=True, help='运行时数据目录（含 tga-media.json / tga-alias.json）')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    hist = json.load(open(os.path.join(DATA, 'tga-history.json')))
    records = json.load(open(os.path.join(DATA, 'records.json')))['games']
    enrichment = json.load(open(os.path.join(DATA, 'enrichment.json')))
    alias = json.load(open(os.path.join(args.runtime, 'tga-alias.json')))
    media = json.load(open(os.path.join(args.runtime, 'tga-media.json')))

    names: set[str] = set()
    for y in hist['years']:
        for c in y['categories']:
            for n in [c.get('winner')] + list(c.get('nominees') or []):
                if n and n != 'TBD':
                    names.add(n)

    # 库候选键 -> 游戏
    lib: dict[str, dict] = {}
    for g in records:
        e = enrichment.get(g.get('id')) or {}
        keys = {norm(g['name']), base(g['name']), norm(e.get('name') or ''), base(e.get('name') or ''),
                norm(e.get('nameOnSteam') or ''), base(e.get('nameOnSteam') or '')}
        keys.discard('')
        for k in keys:
            lib.setdefault(k, g)

    # wiki 名索引
    widx: dict[str, str] = {}
    for n in names:
        for k in {norm(n), base(n), norm(alias.get(n) or ''), base(alias.get(n) or ''),
                  norm((media.get(n) or {}).get('cn') or ''), base((media.get(n) or {}).get('cn') or '')}:
            if k:
                widx.setdefault(k, n)

    hits: dict[str, dict] = {}          # wiki 名 -> 库游戏
    for k, g in lib.items():
        n = widx.get(k)
        if n:
            hits.setdefault(n, g)

    # 人工映射（只认名单里真有的题名）
    manual_by_norm = {norm(k): v for k, v in MANUAL.items()}
    name_by_norm = {norm(n): n for n in names}
    manual_added = []
    for g in records:
        target = manual_by_norm.get(norm(g['name']))
        if not target:
            continue
        n = name_by_norm.get(norm(target)) or (target if target in names else None)
        if not n:
            continue
        if hits.get(n) and hits[n]['id'] != g['id']:
            continue
        hits[n] = g
        manual_added.append((g['name'], n))

    changed_cn, changed_cover, cleared, cleaned = [], [], [], []
    for n, g in hits.items():
        m = media.setdefault(n, {})
        cur = m.get('cn') or ''
        if (not cur) or dirty(cur):
            new = g['name']
            if new != cur:
                m['cn'] = new
                changed_cn.append((n, cur, new))
        if not m.get('cover') and g.get('cover'):
            m['cover'] = g['cover']
            m['src'] = m.get('src') or 'library'
            changed_cover.append((n, g['cover'][:48]))
        alias[n] = g['name']

    for n, m in media.items():
        cur = (m or {}).get('cn') or ''
        if n in hits or not dirty(cur):
            continue
        fixed = clean_cn(cur)
        if fixed and fixed != cur and not dirty(fixed):
            m['cn'] = fixed
            cleaned.append((n, cur, fixed))
        else:
            m['cn'] = ''
            cleared.append((n, cur))

    print(f'wiki 题名 {len(names)}，对上库 {len(hits)}（人工映射新增 {len(manual_added)}）')
    print(f'改中文名 {len(changed_cn)}、补封面 {len(changed_cover)}、收拾脏名 {len(cleaned)}、清空 {len(cleared)}')
    for x in manual_added[:8]:
        print('  manual:', x)
    for x in changed_cn[:8]:
        print('  cn:', x)
    for x in cleaned:
        print('  clean:', x)
    for x in cleared:
        print('  clear:', x)

    if not args.apply:
        print('（未写入，加 --apply 才落盘）')
        return 0

    stamp = time.strftime('%Y%m%d-%H%M%S')
    for path, obj in ((os.path.join(args.runtime, 'tga-media.json'), media),
                      (os.path.join(args.runtime, 'tga-alias.json'), alias),
                      (os.path.join(DATA, 'tga-media.json'), media),
                      (os.path.join(DATA, 'tga-alias.json'), alias)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            shutil.copy2(path, f'{path}.bak-{stamp}')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.write('\n')
        print('wrote', path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
