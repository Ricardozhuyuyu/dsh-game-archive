/**
 * 游戏档案 — Host 半边。
 * 数据三件套：records.json（自动同步）、userdata.json（手动：状态/评分/短评）、awards.json（TGA）。
 * 同步永远不碰 userdata，手动改过的字段不会被覆盖。
 */
import { readFile, writeFile, mkdir, rename, copyFile, stat } from 'node:fs/promises';
import { join, dirname, extname } from 'node:path';
import { homedir } from 'node:os';
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SEED_DIR = join(HERE, 'data');
const SYNC_SCRIPT = join(HERE, 'tools', 'sync.py');

const COVER_HOSTS = [
  'cdn.cloudflare.steamstatic.com',
  'cdn.akamai.steamstatic.com',
  'shared.akamai.steamstatic.com',
  'heyboxbj.max-c.com',
  'cdn.max-c.com',
  'cdn1.epicgames.com',
  'store-images.s-microsoft.com',
  'images-eds-ssl.xboxlive.com',
  'upload.wikimedia.org',
  'assets.nintendo.com',
  'max-c.com',        // 小黑盒的图床（imgheybox / heyboxbj / cdn 都是它的子域）
  'xiaoheihe.cn',
];

function resolveDataDir(configDir) {
  const pick = (v) => (typeof v === 'string' && v.trim() ? v.trim() : '');
  const chosen = pick(configDir)
    || pick(process.env.DSH_GAME_ARCHIVE_DIR)
    || join(homedir(), 'Documents', 'deepseek-harness', 'work', '游戏档案');
  return chosen.replace(/^["']|["']$/g, '').replace(/[\\/]+$/, '') || chosen;
}

let DIR = resolveDataDir();
let PORT = 9333;
const FILES = () => ({
  records: join(DIR, 'records.json'),
  enrichment: join(DIR, 'enrichment.json'),
  covers: join(DIR, 'covers'),
  user: join(DIR, 'userdata.json'),
  awards: join(DIR, 'awards.json'),
  exclude: join(DIR, 'exclude.json'),
  nameCn: join(DIR, 'name-cn.json'),
  manual: join(DIR, 'manual.json'),
  syncLog: join(DIR, 'sync-state.json'),
  extra: join(DIR, 'extra-games.json'),
  accounts: join(DIR, 'accounts.json'),
  recommend: join(DIR, 'recommend.json'),
});


/** 汇率（固定值，不是实时）：2026-11 口径，1 单位外币 ≈ 多少人民币。
    只用来把不同币种折算成 CNY 展示，算完就固定在代码里，不联网。 */
const FX_TO_CNY = { CNY: 1, USD: 7.1, HKD: 0.91, JPY: 0.048, EUR: 7.7, TWD: 0.225, GBP: 9.0 };

function fxRate(cur) {
  return FX_TO_CNY[String(cur || 'CNY').toUpperCase()] || 1;
}

/** 把任意币种的价格折成 CNY；原始值放在 original 里，明细页还要用。 */
function priceToCNY(p) {
  if (!p) return null;
  const cur = String(p.currency || 'CNY').toUpperCase();
  const rate = fxRate(cur);
  const initial = Number(p.initial) || 0;
  const final = Number(p.final) || 0;
  return {
    currency: 'CNY',
    initial: Math.round(initial * rate * 100) / 100,
    final: Math.round(final * rate * 100) / 100,
    free: Boolean(p.free) || initial <= 0,
    ...(cur !== 'CNY' ? { original: { currency: cur, initial, final } } : {}),
  };
}


/** 把各种写法的发售日统一成 YYYY-MM-DD（「2022 年 10 月 20 日」「2022/10/20」都收）。 */
function isoDate(v) {
  if (!v) return null;
  const s = String(v).trim();
  let m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(s);
  if (!m) m = /^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?/.exec(s);
  if (!m) m = /^(\d{4})[/.](\d{1,2})[/.](\d{1,2})/.exec(s);
  if (!m) return /^\d{4}$/.test(s) ? s : null;
  return `${m[1]}-${String(m[2]).padStart(2, '0')}-${String(m[3]).padStart(2, '0')}`;
}

async function readJson(file, fallback) {
  try {
    return JSON.parse(await readFile(file, 'utf8'));
  } catch {
    return fallback;
  }
}

async function writeJson(file, value) {
  await mkdir(dirname(file), { recursive: true }).catch(() => {});
  const temp = `${file}.tmp-${process.pid}`;
  await writeFile(temp, JSON.stringify(value, null, 1), 'utf8');
  try {
    await rename(temp, file);
  } catch {
    await writeFile(file, JSON.stringify(value, null, 1), 'utf8').catch(() => {});
  }
}

/** 首次启动把插件自带的种子数据铺到数据目录（不覆盖已有）。 */
async function seed() {
  const f = FILES();
  await mkdir(DIR, { recursive: true }).catch(() => {});
  for (const [src, dst] of [
    [join(SEED_DIR, 'records.json'), f.records],
    [join(SEED_DIR, 'switch-override.json'), join(DIR, 'switch-override.json')],
    [join(SEED_DIR, 'extra-games.json'), join(DIR, 'extra-games.json')],
    [join(SEED_DIR, 'accounts.json'), join(DIR, 'accounts.json')],
  ]) {
    const exists = await stat(dst).then(() => true).catch(() => false);
    if (!exists) await copyFile(src, dst).catch(() => {});
  }
  // awards.json / tga-history.json / cover-override.json 是随插件走的策展数据（不是你的编辑），
  // 每次启动都以插件内的为准，这样加了新内容不用重新同步、也不会被旧副本挡住。
  await copyFile(join(SEED_DIR, 'awards.json'), f.awards).catch(() => {});
  await copyFile(join(SEED_DIR, 'tga-history.json'), join(DIR, 'tga-history.json')).catch(() => {});
  await copyFile(join(SEED_DIR, 'cover-override.json'), join(DIR, 'cover-override.json')).catch(() => {});
  // 不算游戏的东西（壁纸工具这类，Steam 自己标成 game 的）也随插件走
  await copyFile(join(SEED_DIR, 'exclude.json'), f.exclude).catch(() => {});
  await copyFile(join(SEED_DIR, 'name-cn.json'), f.nameCn).catch(() => {});
  // 陈列室的封面/中文名也是策展数据：每次启动覆盖，更新插件即生效
  await copyFile(join(SEED_DIR, 'tga-media.json'), join(DIR, 'tga-media.json')).catch(() => {});
  {
    const has = await stat(join(DIR, 'tga-alias.json')).then(() => true).catch(() => false);
    if (!has) await copyFile(join(SEED_DIR, 'tga-alias.json'), join(DIR, 'tga-alias.json')).catch(() => {});
  }
  // enrichment.json 是抓来的（也算你的数据）：只铺一次
  const en = await stat(f.enrichment).then(() => true).catch(() => false);
  if (!en) await copyFile(join(SEED_DIR, 'enrichment.json'), f.enrichment).catch(() => {});
  const u = await stat(f.user).then(() => true).catch(() => false);
  if (!u) await writeJson(f.user, {});
}

/** 完成度：库里存的可能是数字，也可能是 "31/43" 这种文本。 */
function progressOf(g) {
  if (typeof g.progress === 'number') return g.progress;
  const m = /^(\d+)\s*\/\s*(\d+)$/.exec(String(g.progress || g.ach || '').trim());
  if (m && Number(m[2])) return Math.round((Number(m[1]) / Number(m[2])) * 100);
  return null;
}

const DAY = 86400000;
/** 日期只到年或只到月时，取年中/月中，避免把「2023」当成 2023-01-01。 */
function daysSince(dateish) {
  let s = String(dateish || '').trim();
  if (!s) return null;
  if (/^\d{4}$/.test(s)) s = `${s}-06-15`;
  else if (/^\d{4}-\d{2}$/.test(s)) s = `${s}-15`;
  const t = Date.parse(s);
  if (!Number.isFinite(t)) return null;
  return Math.round((Date.now() - t) / DAY);
}
/** 补录过月份就用补录的末月当「最后游玩」，否则用同步来的日期。 */
function effectiveLast(g, manual) {
  const m = manual?.months;
  if (m && /^\d{4}-\d{2}$/.test(String(m.to || ''))) return `${m.to}-01`;
  return g.last || '';
}

/** 自动状态，六档：
 *  还没碰过 backlog（时长 < 0.1h）→ 白金 platinum（完成度 100%）→
 *  正在玩 playing（30 天内动过）→ 已荒废 shelved（其余）。
 *  「通关」和「弃坑」只由人标：完成度不等于通关，机器不替你做这个决定。
 *  没有任何日期的也算已荒废（没法证明你最近在玩），另挂 dateUnknown 等补录。 */
function deriveStatus(g, manual) {
  if (manual?.status) return { status: manual.status, auto: false };
  const hours = g.hours || 0;
  if (hours < 0.1) return { status: 'backlog', auto: true };
  const p = progressOf(g);
  if (p !== null && p >= 100) return { status: 'platinum', auto: true };
  const d = daysSince(effectiveLast(g, manual));
  if (d !== null && d <= 30) return { status: 'playing', auto: true };
  return { status: 'shelved', auto: true };
}

/** 「该接着玩」打分：完成度高、时长够、荒得久，三项都算好事。 */
function pickUpNext(merged) {
  const now = Date.now();
  const out = [];
  for (const g of merged) {
    // 1) 没通关 —— 手标的通关/白金排除
    if (['finished', 'platinum'].includes(g.status)) continue;
    // 2) 纯网游 / 大逃杀 / MOBA 不进回坑榜（没有「通关」这回事）
    if (/(大型多人|多人在线|大逃杀|MOBA)/i.test(String(g.genre || ''))) continue;
    // 3) 玩过比较长时间
    const h = g.hours || 0;
    if (h < 5) continue;
    // 4) 有一定数量的奖杯 / 成就
    const p = g.progressPct;
    // records 里的 ach 是 "47/53" 这种
    const am = /^(\d+)\s*\/\s*(\d+)/.exec(String(g.ach || ''));
    const got = am ? Number(am[1]) : null;
    const total = am ? Number(am[2]) : null;
    if (p === null && !(got !== null && got >= 3)) continue;   // 既没进度也没奖杯 → 不算
    if (p !== null && p >= 95) continue;            // 就差白金了，不算「该回坑」
    if ((g.daysSincePlay ?? 0) < 14) continue;      // 最近还在动，不算回坑

    // ---- 打分：先把各维度压到 0~1，再按权重加 ----
    const sHours = Math.min(1, Math.log10(1 + h) / Math.log10(1 + 200));  // 200h 封顶
    const sProg = p === null ? 0.35 : Math.min(1, p / 90);                // 越接近通关越值得回去
    const sMeta = g.metacritic ? Math.min(1, Math.max(0, (g.metacritic - 60) / 35)) : 0.4;  // 60 分以下算 0
    const honors = Array.isArray(g.awards) ? g.awards.length : 0;
    const sAward = g.goty ? 1 : (g.gotyNom ? 0.6 : (honors ? Math.min(0.8, 0.35 + honors * 0.12) : 0));
    const d = g.daysSincePlay ?? 0;
    const sFresh = Math.min(1, d / 730);                                  // 荒得久一点点加分（提醒你）

    let score = sHours * 26 + sProg * 30 + sMeta * 22 + sAward * 22 + sFresh * 6;

    const reasons = [];
    if (p !== null) reasons.push(`已完成 ${p}%`);
    else if (got !== null) reasons.push(`成就 ${got}${total ? '/' + total : ''}`);
    if (h >= 10) reasons.push(`${Math.round(h)} 小时下去了`);
    if (g.metacritic) reasons.push(`M 站 ${g.metacritic}`);
    if (g.goty) reasons.push('TGA 年度游戏');
    else if (g.gotyNom) reasons.push('TGA 年度提名');
    else if (honors) reasons.push(`拿了 ${honors} 项 TGA`);
    if (d >= 365) reasons.push(`荒了 ${Math.round(d / 365 * 10) / 10} 年`);
    else if (d >= 30) reasons.push(`荒了 ${Math.round(d / 30)} 个月`);

    // 一句话的「回坑理由」：挑最有说服力的两个维度
    let hook;
    if (p !== null && p >= 70) hook = `都 ${p}% 了，收个尾就通关`;
    else if (h >= 60) hook = `砸了 ${Math.round(h)} 小时，别烂尾`;
    else if (g.metacritic >= 85) hook = `M 站 ${g.metacritic} 分，口碑摆在那`;
    else if (g.goty) hook = '年度游戏，值得从头认真玩一遍';
    else if (g.gotyNom) hook = h >= 40 ? `TGA 提名 + 已经 ${Math.round(h)} 小时` : '年度游戏提名，还差临门一脚';
    else if (p !== null && p >= 40) hook = `已经过半（${p}%），接着往下就行`;
    else if (d >= 365) hook = '放太久了，趁还记得剧情捡起来';
    else hook = '玩了几个小时，值得再给一次机会';

    out.push({ ...g, score: Math.round(score), reason: reasons.join(' · '), hook, honors });
  }
  return out.sort((a, b) => b.score - a.score).slice(0, 60);
}

function statsOf(merged) {
  const byPlatform = {};
  let hours = 0;
  let played = 0;
  for (const g of merged) {
    const p = (byPlatform[g.platform] ||= { platform: g.platform, count: 0, hours: 0, played: 0 });
    p.count += 1;
    p.hours += g.hours || 0;
    if ((g.hours || 0) >= 0.1) {
      p.played += 1;
      played += 1;
    }
    hours += g.hours || 0;
  }
  const buckets = { backlog: 0, playing: 0, shelved: 0, dropped: 0, finished: 0, platinum: 0, wish: 0 };
  for (const g of merged) buckets[g.status] = (buckets[g.status] || 0) + 1;
  const awards = merged.filter((g) => g.awards?.length).length;
  const finishedTotal = (buckets.finished || 0) + (buckets.platinum || 0);
  return {
    buckets,
    finishedTotal,
    total: merged.length,
    hours: Math.round(hours * 10) / 10,
    played,
    awards,
    buckets,
    platforms: Object.values(byPlatform)
      .map((p) => ({ ...p, hours: Math.round(p.hours * 10) / 10 }))
      .sort((a, b) => b.hours - a.hours),
  };
}

/** 月份区间展开成 ['2023-06','2023-07',…]；非法区间返回 []。 */
function monthsBetween(from, to) {
  if (!/^\d{4}-\d{2}$/.test(String(from || '')) || !/^\d{4}-\d{2}$/.test(String(to || ''))) return [];
  let [fy, fm] = from.split('-').map(Number);
  let [ty, tm] = to.split('-').map(Number);
  if (ty * 12 + tm < fy * 12 + fm) [fy, fm, ty, tm] = [ty, tm, fy, fm];
  const out = [];
  let y = fy, m = fm;
  for (let guard = 0; guard < 600; guard++) {
    out.push(`${y}-${String(m).padStart(2, '0')}`);
    if (y === ty && m === tm) break;
    m += 1;
    if (m > 12) { m = 1; y += 1; }
  }
  return out;
}

/** 月度时长：有补录就摊到那几个月，没有就不参与。 */
function monthlyOf(merged) {
  const acc = {};
  for (const g of merged) {
    const m = g.months;
    if (!m) continue;
    const span = monthsBetween(m.from, m.to);
    if (!span.length) continue;
    const per = (g.hours || 0) / span.length;
    for (const month of span) acc[month] = (acc[month] || 0) + per;
  }
  return Object.entries(acc)
    .map(([month, hours]) => ({ month, hours: Math.round(hours * 10) / 10 }))
    .sort((a, b) => a.month.localeCompare(b.month));
}

/** 年度回顾：补录过的按月份摊到对应年份，没补录的按最后游玩年归一次（近似）。 */
function yearlyOf(merged) {
  const years = {};
  const bump = (year, g, hours) => {
    const row = (years[year] ||= { year, games: 0, hours: 0, finished: 0 });
    row.hours += hours;
    if (g.status === 'finished' || g.status === 'platinum') row.finished += 1;
    row.games += 1;
  };
  for (const g of merged) {
    const m = g.months;
    const span = m ? monthsBetween(m.from, m.to) : [];
    if (span.length) {
      const per = (g.hours || 0) / span.length;
      const byYear = {};
      for (const month of span) byYear[month.slice(0, 4)] = (byYear[month.slice(0, 4)] || 0) + per;
      for (const [year, hours] of Object.entries(byYear)) bump(year, { ...g }, hours);
      continue;
    }
    const y = String(g.last || '').slice(0, 4);
    if (!/^\d{4}$/.test(y)) continue;
    bump(y, g, g.hours || 0);
  }
  return Object.values(years)
    .map((r) => ({ ...r, hours: Math.round(r.hours * 10) / 10 }))
    .sort((a, b) => a.year.localeCompare(b.year));
}

/** 库价值：按原价合计，分币种，免费/赠送单独摘出来。拿不到价格的不计入、只记 missing。 */
function valueOf(merged) {
  const cur = {};
  const bucket = (key, g, price) => {
    const row = (cur[key] ||= { key, games: 0, total: 0, paidNow: 0, freeValue: 0, missing: 0, byCurrency: {} });
    return row;
  };
  const addTo = (row, g, price) => {
    row.games += 1;
    if (!price) { row.missing += 1; return; }
    const initial = Number(price.initial) || 0;
    const final = Number(price.final) || 0;
    const isFree = Boolean(price.free) || initial <= 0 || String(g.platform) === 'Epic';
    // 真免费（原价就是 0，比如 Dota 2）不算钱，也不占币种
    if (initial <= 0) return;
    const c = price.currency || 'CNY';
    const cRow = (row.byCurrency[c] ||= { total: 0, paidNow: 0, freeValue: 0 });
    cRow.total += initial;
    if (isFree) cRow.freeValue += initial;
    else cRow.paidNow += final;
  };

  const groups = {
    platform: new Map(),
    genre: new Map(),
    status: new Map(),
  };
  for (const g of merged) {
    const price = g.price || null;
    const keys = {
      platform: String(g.platform || '未知'),
      genre: String(g.genre || '未分类').split(' / ')[0].trim() || '未分类',
      status: String(g.status || 'unknown'),
    };
    for (const [dim, key] of Object.entries(keys)) {
      const map = groups[dim];
      if (!map.has(key)) map.set(key, bucket(key, g, price));
      addTo(map.get(key), g, price);
    }
  }

  const finish = (row) => {
    const currencies = Object.keys(row.byCurrency);
    const pick = (k) => currencies.reduce((acc, c) => {
      acc[c] = Math.round(row.byCurrency[c][k] * 100) / 100;
      return acc;
    }, {});
    return {
      key: row.key,
      games: row.games,
      missing: row.missing,
      currencies,
      total: pick('total'),
      paidNow: pick('paidNow'),
      freeValue: pick('freeValue'),
    };
  };
  const out = {};
  for (const [dim, map] of Object.entries(groups)) {
    out[dim] = [...map.values()].map(finish).sort((a, b) => {
      const av = Object.values(a.total).reduce((x, y) => x + y, 0);
      const bv = Object.values(b.total).reduce((x, y) => x + y, 0);
      return bv - av;
    });
  }
  const sum = (rows, k) => rows.reduce((acc, r) => {
    for (const [c, v] of Object.entries(r[k])) acc[c] = Math.round(((acc[c] || 0) + v) * 100) / 100;
    return acc;
  }, {});
  const all = out.platform;
  const currencies = [...new Set(all.flatMap((r) => r.currencies))];
  return {
    currencies,
    total: sum(all, 'total'),
    paidNow: sum(all, 'paidNow'),
    freeValue: sum(all, 'freeValue'),
    games: merged.length,
    missing: all.reduce((n, r) => n + r.missing, 0),
    ...out,
  };
}

/** 「待确认」清单：机器拿不准的，等人一句话。 */
function triageOf(merged) {
  const needStatus = merged
    .filter((g) => g.statusAuto && g.status === 'shelved')
    .filter((g) => (g.progressPct || 0) >= 60 || (g.hours || 0) >= 10 || g.daysSincePlay === null)
    .sort((a, b) => (b.hours || 0) - (a.hours || 0))
    .slice(0, 80)
    .map((g) => ({
      id: g.id, name: g.name, platform: g.platform, hours: g.hours, progressPct: g.progressPct,
      last: g.last, status: g.status, daysSincePlay: g.daysSincePlay,
    }));
  const needMonths = merged
    .filter((g) => !g.months && (g.hours || 0) >= 0.1 && !/^\d{4}-\d{2}-\d{2}$/.test(String(g.last || '')))
    .sort((a, b) => (b.hours || 0) - (a.hours || 0))
    .map((g) => {
      const last = String(g.last || '');
      const yearOnly = /^\d{4}$/.test(last) ? last : '';
      return {
        id: g.id, name: g.name, platform: g.platform, hours: g.hours, last,
        // 平台只给了年份（或者给了「3年前」折算出的年）：先把整年摆上去，点一下确认即可
        yearOnly,
        suggest: yearOnly ? { from: `${yearOnly}-01`, to: `${yearOnly}-12` } : null,
      };
    });
  const remain = merged.filter((g) => g.statusAuto && g.status === 'shelved').length;
  return { needStatus, needMonths, remain };
}


/** 把 TGA 名单套到同步来的记录上：改 awards.json 不用重新同步。 */
// 陈列室只保留这些奖项（主人 2026-11-26 指定的 21 类，含历史拆分名）
const HONOR_ACCEPT = new Set([
  '年度游戏',
  '最佳游戏指导',
  '最佳叙事',
  '最佳美术指导',
  '最佳配乐',
  '最佳配乐/原声',
  '最佳音效设计',
  '最佳动作游戏',
  '最佳动作冒险游戏',
  '最佳角色扮演游戏',
  '玩家之声',
  '最佳持续运营游戏',
  '最佳社区支持',
  '最佳格斗游戏',
  '最佳家庭游戏',
  '最佳模拟策略游戏',
  '最佳策略游戏',
  '最佳体育竞速游戏',
  '最佳 VR/AR 游戏',
  '最佳VR游戏',
  '最佳多人游戏',
  '最佳独立游戏',
  '最佳新晋独立游戏',
  '最佳独立游戏处女作',
  '最具影响力游戏',
]);

function normalizeName(s) {
  return String(s || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
}
/** 年度游戏提名（银框）：只标没拿到年度游戏的那几款。 */
function applyNominees(games, list) {
  const rows = games.map((g) => ({ g, key: normalizeName(g.name) }));
  for (const item of list || []) {
    const keys = [...(item.names || [])].map(normalizeName).filter(Boolean);
    if (!keys.length) continue;
    const hit = rows.find((r) => keys.includes(r.key) && !r.g.goty && !r.g.gotyNom)
      || rows.find((r) => keys.some((k) => r.key.includes(k)) && !r.g.goty && !r.g.gotyNom);
    if (!hit) continue;
    hit.g.gotyNom = item.year || null;
  }
  return games;
}

function applyAwards(games, list) {
  const rows = games.map((g) => ({ g, key: normalizeName(g.name) }));
  for (const g of games) {
    g.awards = [];
    g.awardYear = null;
  }
  for (const g of games) { g.gotyNom = null; }
  for (const item of list || []) {
    const keys = [...(item.names || []), ...(item.aliases || [])].map(normalizeName).filter(Boolean);
    const bad = (item.exclude || []).map(normalizeName).filter(Boolean);
    if (!keys.length) continue;
    const ok = (r) => !bad.some((k) => r.key.includes(k));
    let hits = rows.filter((r) => ok(r) && keys.includes(r.key));
    if (!hits.length) hits = rows.filter((r) => ok(r) && keys.some((k) => r.key.includes(k)));
    const honors = (item.honors || []).filter((h) => HONOR_ACCEPT.has(h));
    if (!honors.length) continue;
    for (const hit of hits) {
      if (hit.g.awards.length) continue;
      hit.g.awards = honors;
      hit.g.awardYear = item.year || null;
      hit.g.goty = honors.includes('年度游戏');
    }
  }
  return games;
}

async function buildPayload() {
  const f = FILES();
  const rec = await readJson(f.records, { games: [] });
  const user = await readJson(f.user, {});
  const aw = await readJson(f.awards, { awards: [], gotyNominees: [] });
  const enrich = await readJson(f.enrichment, {});
  const coverOverride = await readJson(join(DIR, 'cover-override.json'), {});
  const tga = await readJson(join(DIR, 'tga-history.json'), { years: [] });
  const tgaAlias = await readJson(join(DIR, 'tga-alias.json'), {});
  const tgaMedia = await readJson(join(DIR, 'tga-media.json'), {});
  const nameCn = await readJson(f.nameCn, {});
  const manual = await readJson(f.manual, {});   // 你自己/AI 填的表，优先级最高
  const recommend = await readJson(f.recommend, null);
  const extraDoc = await readJson(f.extra, { games: [] });
  const extraGames = Array.isArray(extraDoc?.games) ? extraDoc.games : [];
  // 剔掉「不算游戏」的（壁纸工具这类 Steam 也标成 game 的）
  const ex = await readJson(f.exclude, {});
  const excluded = new Set();
  const addNames = (obj) => {
    for (const [plat, names] of Object.entries(obj || {})) {
      if (plat.startsWith('_') || !Array.isArray(names)) continue;
      for (const n of names) excluded.add(`${plat}|${normalizeName(n)}`);
    }
  };
  addNames(ex);          // 兼容旧格式：{ Steam: [...] }
  addNames(ex && ex.tools);   // 新格式：{ tools: { Steam: [...] } }
  // 试玩 / 体验 / 测试版一律不算「库里的游戏」：demo、试玩、体验版、体験版、
  // 网络测试、预览版、friend's pass（双人成行的好友通行证）、beta / trial / 公测
  const NOT_A_GAME = /(^|[^a-z])(demo|trial|beta|试玩版?|体验版|体験版|预览版?|網絡測試|网络测试|ネットワークテスト|公测|封测|测试版|friend's pass|好友通行证)([^a-z]|$)/i;
  const extraRows = extraGames
    .filter((g) => g && g.id && g.name)
    .map((g) => ({
      id: g.id,
      name: g.name,
      platform: g.platform || 'Switch',
      hours: Number(g.hours) || 0,
      progress: g.progress ?? null,
      ach: g.ach || '',
      last: g.last || (g.months && g.months.to ? `${g.months.to}-15` : ''),
      detail: g.note || '',
      note: g.note || '手动补录',
      cn: g.cn || '',
      cover: g.cover || '',
      _extra: true,
      _status: g.status || '',
      _months: g.months || null,
    }));
  const playable = (rec.games || []).concat(extraRows)
    .filter((g) => !excluded.has(`${g.platform}|${normalizeName(g.name)}`))
    .filter((g) => !NOT_A_GAME.test(g.name));
  applyAwards(playable, aw.awards || []);
  applyNominees(playable, aw.gotyNominees || []);

  // 封面兜底：名字 → 直链（只补没有 cover 的）
  const coverMap = coverOverride && typeof coverOverride === 'object' ? coverOverride : {};
  const coverByKey = new Map();
  for (const [k, v] of Object.entries(coverMap)) {
    if (k.startsWith('_') || !v) continue;
    const norm = typeof v === 'string'
      ? { url: v, fit: 'cover', src: 'override' }
      : { url: v.url, fit: v.fit === 'contain' ? 'contain' : 'cover', src: v.src || 'override' };
    if (!norm.url) continue;
    coverByKey.set(normalizeName(k), norm);
  }

  const merged = playable.map((g) => {
    const m = user[g.id] || (g._extra && g._status ? { status: g._status } : {});
    const { status, auto } = deriveStatus(g, m);
    const p = progressOf(g);
    const lastPlayed = effectiveLast(g, m);
    const en = enrich[g.id] || {};
    const ov = coverByKey.get(normalizeName(g.name)) || null;
    // 封面优先用 Steam 商店给的正版头图（库里存的偶有 appid 变更导致 404）
    const cov = en.cover || g.cover || (ov ? ov.url : '');
    const covFit = (en.cover && en.coverFit === 'contain') ? 'contain'
      : (en.cover ? 'cover' : (g.cover ? 'cover' : (ov ? ov.fit : 'cover')));
    const man = manual[g.id] || {};
    return {
      ...g,
      // 中文名：人工 > 手写表 > 自动抓的；平台名本身就是中文时直接当中文名用
      // （否则 明细 里会显示「缺中文名」、卡片标题也会变成英文）
      cn: (man.cn || nameCn[g.name] || en.cn || g.cn
        || (/[\u4e00-\u9fff]/.test(g.name) ? g.name : '')),
      en: (man.en || en.en || (/[\u4e00-\u9fff]/.test(g.name) ? '' : g.name)),
      cover: cov,
      coverFit: covFit,
      release: isoDate(man.release || en.release || null),   // 「即将推出」这类会被丢成 null
      metacritic: (() => {
        const m = man.metacritic !== undefined ? man.metacritic : en.metacritic;
        return typeof m === 'number' ? m : (m ? Number(m) || null : null);
      })(),
      genre: man.genre || en.genre || null,
      manual: Object.keys(man),
      price: priceToCNY(man.price || en.price || null),
      priceRaw: man.price || en.price || null,
      appid: en.appid || null,
      progressPct: p,
      lastEffective: lastPlayed,
      daysSincePlay: daysSince(lastPlayed),
      months: (m.months && m.months.from && m.months.to)
        ? { from: m.months.from, to: m.months.to }
        : (g._months && g._months.from && g._months.to ? g._months : null),
      status,
      statusAuto: auto,
      rating: typeof m.rating === 'number' ? m.rating : null,
      review: m.review || '',
      tags: Array.isArray(m.tags) ? m.tags : [],
      pinned: Boolean(m.pinned),
      hidden: Boolean(m.hidden),
    };
  }).filter((g) => !g.hidden)
    // 领了没玩的小体量免费游戏也剔掉（价格未知的一律保留，不当免费处理）
    .filter((g) => {
      const rule = (ex && ex.lowfree) || {};
      if (rule.enabled === false) return true;
      const maxH = Number(rule.maxHours) > 0 ? Number(rule.maxHours) : 2;
      if ((g.hours || 0) >= maxH) return true;
      const p = g.price;
      if (!p) return true;                       // 没有价格数据 → 保留
      // 只剔「本来就免费」的（原价 0：F2P 网游、试玩）；
      // 白嫖到的付费游戏（Epic 每周免费、会免）原价 > 0，是资产，必须留着
      const orig = p.original ? Number(p.original.initial) : Number(p.initial);
      return !(Number.isFinite(orig) && orig === 0);
    });
  const syncState = await readJson(f.syncLog, {});
  return {
    updated: rec.updated || '',
    games: merged,
    stats: statsOf(merged),
    next: pickUpNext(merged),
    yearly: yearlyOf(merged),
    triage: triageOf(merged),
    value: valueOf(merged),
    tga: {
      years: (tga.years || []),
      alias: tgaAlias && typeof tgaAlias === 'object' ? tgaAlias : {},
      media: tgaMedia && typeof tgaMedia === 'object' ? tgaMedia : {},
    },
    recommend: recommend && Array.isArray(recommend.items) ? recommend : null,
    sync: syncState,
  };
}

/** 把一次编辑并进 userdata（纯函数，路由和自测共用）。 */
function applyEdit(user, body) {
  const next = { ...(user[body.id] || {}) };
  for (const key of ['status', 'review', 'pinned', 'hidden']) {
    if (key in body) next[key] = body[key];
  }
  if ('rating' in body) next.rating = body.rating === null ? null : Number(body.rating);
  if ('tags' in body && Array.isArray(body.tags)) next.tags = body.tags.slice(0, 12).map(String);
  if ('months' in body) {
    const m = body.months;
    const ok = m && /^\d{4}-\d{2}$/.test(String(m.from || '')) && /^\d{4}-\d{2}$/.test(String(m.to || ''));
    if (ok) next.months = { from: String(m.from), to: String(m.to) };
    else delete next.months;
  }
  if (body.reset) delete user[body.id];
  else user[body.id] = next;
  return user;
}

function sendJson(res, code, value) {
  const body = JSON.stringify(value);
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'content-length': Buffer.byteLength(body),
  });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > 1_000_000) return resolve(null);
      chunks.push(c);
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
      } catch {
        resolve(null);
      }
    });
    req.on('error', () => resolve(null));
  });
}

/** 封面走本机代理：统一缓存、去掉 referer 依赖、离线也能看。 */
async function serveCover(res, rawUrl) {
  let url;
  try {
    url = new URL(rawUrl || '');
  } catch {
    res.writeHead(400).end('bad url');
    return;
  }
  if (url.protocol !== 'https:' || !COVER_HOSTS.some((h) => url.hostname === h || url.hostname.endsWith(`.${h}`))) {
    res.writeHead(403).end('host not allowed');
    return;
  }
  const f = FILES();
  const key = createHash('sha1').update(url.toString()).digest('hex');
  const cached = join(f.covers, `${key}.bin`);
  const typeFile = join(f.covers, `${key}.type`);
  const hit = await readFile(cached).catch(() => null);
  if (hit) {
    const type = await readFile(typeFile, 'utf8').catch(() => 'image/jpeg');
    res.writeHead(200, { 'content-type': type, 'cache-control': 'public, max-age=604800' }).end(hit);
    return;
  }
  try {
    // 图源偶尔限流（wikimedia 的 429 最常见），重试两次再放弃
    let r = null;
    for (let i = 0; i < 3; i += 1) {
      r = await fetch(url, {
        headers: {
          referer: 'https://store.steampowered.com/',
          'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0 Safari/537.36',
        },
      });
      if (r.ok) break;
      if (![429, 500, 502, 503, 504].includes(r.status)) break;
      await new Promise((ok) => setTimeout(ok, 400 * (i + 1)));
    }
    if (!r || !r.ok) {
      res.writeHead(404).end(`upstream failed ${r ? r.status : ''}`);
      return;
    }
    const buf = Buffer.from(await r.arrayBuffer());
    const type = r.headers.get('content-type') || 'image/jpeg';
    await mkdir(f.covers, { recursive: true }).catch(() => {});
    await writeFile(cached, buf).catch(() => {});
    await writeFile(typeFile, type, 'utf8').catch(() => {});
    res.writeHead(200, { 'content-type': type, 'cache-control': 'public, max-age=604800' }).end(buf);
  } catch {
    res.writeHead(502).end('fetch failed');
  }
}

const PYTHON_CANDIDATES = [
  process.env.DSH_GAME_ARCHIVE_PYTHON,
  'python3',
  'python',
  'py',
  '/usr/bin/python3',
  '/opt/homebrew/bin/python3',
  '/usr/local/bin/python3',
  // Windows：装了 Python 的典型位置
  process.platform === 'win32' ? 'C:\\Python313\\python.exe' : null,
  process.platform === 'win32' ? 'C:\\Python312\\python.exe' : null,
  process.platform === 'win32'
    ? join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python313', 'python.exe')
    : null,
  process.platform === 'win32'
    ? join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python312', 'python.exe')
    : null,
].filter(Boolean);

function runOnce(python) {
  return new Promise((resolve) => {
    execFile(python, [SYNC_SCRIPT, '--port', String(PORT), '--out', DIR], {
      timeout: 12 * 60 * 1000,
      maxBuffer: 8 * 1024 * 1024,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    }, (error, stdout, stderr) => {
      resolve({ ok: !error, error: error ? String(error.message || error) : '', stdout: stdout || '', stderr: stderr || '' });
    });
  });
}

/** 试一个候选：能跑出 Python 3.8+ 的版本号才算数（Windows 的商店占位 stubs 会在这里被筛掉）。 */
function probePython(cand) {
  return new Promise((resolve) => {
    execFile(cand, ['-c', 'import sys;print(sys.version_info[0],sys.version_info[1])'], {
      timeout: 20000,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    }, (error, stdout) => {
      if (error) { resolve(null); return; }
      const m = /(\d+)\s+(\d+)/.exec(String(stdout || ''));
      resolve(m && Number(m[1]) === 3 && Number(m[2]) >= 8 ? cand : null);
    });
  });
}

let cachedPython = null;

/** 按 PYTHON_CANDIDATES 顺序挑第一个真正可用的解释器，再跑同步。 */
async function runSync() {
  if (!cachedPython) {
    for (const cand of PYTHON_CANDIDATES) {
      const ok = await probePython(cand);
      if (ok) { cachedPython = ok; break; }
    }
  }
  if (!cachedPython) {
    return {
      ok: false,
      error: '找不到可用的 Python 3.8+（Windows 请从 python.org 装 Python 3，安装时勾选 Add python.exe to PATH；'
        + '或把 python.exe 的完整路径写进环境变量 DSH_GAME_ARCHIVE_PYTHON）',
      stdout: '',
      stderr: '',
    };
  }
  return runOnce(cachedPython);
}

function makeTools() {
  return [
    {
      name: 'game_archive_query',
      description: '查询游戏档案：按平台、状态、关键词、时长、完成度筛选。返回匹配的游戏条目。',
      parameters: {
        type: 'object',
        properties: {
          platform: { type: 'string', enum: ['Steam', 'PSN', 'Switch', 'Xbox', 'Epic'] },
          status: { type: 'string', enum: ['backlog', 'playing', 'finished', 'dropped', 'wish'] },
          keyword: { type: 'string' },
          minHours: { type: 'number' },
          awardedOnly: { type: 'boolean', description: '只看 TGA 获奖的作品' },
          limit: { type: 'number' },
        },
        additionalProperties: false,
      },
      async execute({ platform, status, keyword, minHours, awardedOnly, limit } = {}) {
        const { games } = await buildPayload();
        const kw = String(keyword || '').toLowerCase();
        const rows = games.filter((g) => (
          (!platform || g.platform === platform)
          && (!status || g.status === status)
          && (!kw || g.name.toLowerCase().includes(kw))
          && (typeof minHours !== 'number' || (g.hours || 0) >= minHours)
          && (!awardedOnly || (g.awards || []).length)
        )).sort((a, b) => (b.hours || 0) - (a.hours || 0)).slice(0, Math.min(Number(limit) || 20, 100));
        return rows.map((g) => ({
          name: g.name, platform: g.platform, hours: g.hours,
          progress: g.progressPct, status: g.status, last: g.last,
          awards: g.awards || [], rating: g.rating,
        }));
      },
    },
    {
      name: 'game_archive_stats',
      description: '游戏档案总览：总时长、各平台分布、状态分布、TGA 获奖数量、年度回顾、该接着玩的推荐。',
      parameters: { type: 'object', properties: {}, additionalProperties: false },
      async execute() {
        const p = await buildPayload();
        return { stats: p.stats, next: p.next.map((g) => ({ name: g.name, platform: g.platform, reason: g.reason })), yearly: p.yearly };
      },
    },
  ];
}

export const inject = ['webServer', 'tools'];

export function apply(ctx, config) {
  DIR = resolveDataDir(config?.dataDir);
  PORT = Number(config?.cdpPort) || 9333;

  ctx.effect(() => {
    seed().catch(() => {});
  }, 'game-archive-seed');

  if (ctx.tools?.register) {
    ctx.effect(() => {
      const disposers = [];
      for (const tool of makeTools()) {
        try {
          const dispose = ctx.tools.register(tool);
          if (typeof dispose === 'function') disposers.push(dispose);
        } catch (error) {
          console.warn(`[dsh-game-archive] 工具 ${tool.name} 没注册上：${error?.message || error}`);
        }
      }
      return () => { for (const d of disposers) if (typeof d === 'function') d(); };
    }, 'game-archive-tools');
  }

  ctx.effect(() => ctx.webServer.register({
    kind: 'prefix',
    path: '/dsh-game-archive',
    async handler(req, res) {
      const url = new URL(req.url || '/', 'http://localhost');
      const p = url.pathname.replace(/\/+$/, '');
      try {
        if (p === '/dsh-game-archive/data') {
          sendJson(res, 200, await buildPayload());
          return;
        }
        if (p === '/dsh-game-archive/cover') {
          await serveCover(res, url.searchParams.get('u'));
          return;
        }
        if (p === '/dsh-game-archive/edit' && req.method === 'POST') {
          const body = await readBody(req);
          if (!body || !body.id) {
            sendJson(res, 400, { ok: false, error: 'id required' });
            return;
          }
          const f = FILES();
          const user = await readJson(f.user, {});
          applyEdit(user, body);
          await writeJson(f.user, user);
          sendJson(res, 200, { ok: true });
          return;
        }
        // 库明细里的逐格编辑：直接写 manual.json，优先级最高
        if (p === '/dsh-game-archive/field' && req.method === 'POST') {
          const body = await readBody(req);
          if (!body || !body.id || !body.key) {
            sendJson(res, 400, { ok: false, error: 'id + key required' });
            return;
          }
          const okKeys = ['cn', 'en', 'release', 'metacritic', 'genre', 'price'];
          if (!okKeys.includes(body.key)) {
            sendJson(res, 400, { ok: false, error: 'bad key' });
            return;
          }
          const f = FILES();
          const manual = await readJson(f.manual, {});
          const rec = { ...(manual[body.id] || {}) };
          const raw = body.value;
          const empty = raw === null || raw === undefined || String(raw).trim() === '' || String(raw).trim() === '-';
          if (body.key === 'price') {
            if (empty) delete rec.price;
            else {
              const num = Number(raw);
              if (!Number.isFinite(num) || num < 0) {
                sendJson(res, 400, { ok: false, error: 'bad price' });
                return;
              }
              rec.price = {
                currency: String(body.currency || (rec.price && rec.price.currency) || 'CNY').toUpperCase(),
                initial: num,
                final: num,
                free: num <= 0,
              };
            }
          } else if (body.key === 'metacritic') {
            if (empty) delete rec.metacritic;
            else {
              const num = Number(raw);
              if (!Number.isFinite(num) || num < 0 || num > 100) {
                sendJson(res, 400, { ok: false, error: 'bad score' });
                return;
              }
              rec.metacritic = Math.round(num);
            }
          } else if (empty) {
            delete rec[body.key];
          } else {
            rec[body.key] = String(raw).trim();
          }
          if (Object.keys(rec).length) manual[body.id] = rec;
          else delete manual[body.id];
          await writeJson(f.manual, manual);
          sendJson(res, 200, { ok: true, manual: Object.keys(rec) });
          return;
        }
        if (p === '/dsh-game-archive/sync' && req.method === 'POST') {
          const result = await runSync();
          const f = FILES();
          const state = await readJson(f.syncLog, {});
          const next = {
            ...state,
            lastRun: new Date().toISOString(),
            ok: result.ok,
            error: result.error,
            tail: (result.stdout || result.stderr || '').split('\n').filter(Boolean).slice(-40),
          };
          await writeJson(f.syncLog, next);
          sendJson(res, 200, { ...next, payload: await buildPayload() });
          return;
        }
        res.writeHead(404).end('not found');
      } catch (error) {
        sendJson(res, 500, { ok: false, error: String(error?.message || error) });
      }
    },
  }), 'game-archive-web');
}

/** 只在本地调试时用：让 devdata.mjs 能直接算一份 payload，不必启动宿主。 */
export const __test = { buildPayload, deriveStatus, monthlyOf, triageOf, yearlyOf, monthsBetween, applyEdit };
