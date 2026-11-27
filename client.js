/* 游戏档案 — Client 半边：左栏图标 + 整页五平台档案馆。
   总览 / 库（网格·列表）/ 接着玩 / 年度回顾 / 奖项，详情抽屉可改状态、评分、短评。 */
window.__ModuleLoader__.load({
  id: 'dsh-game-archive',
  factory(require) {
    const React = require('react');
    const h = React.createElement;
    const { useCallback, useEffect, useMemo, useRef, useState } = React;

    const PANEL_ID = 'game-archive';
    /** 由 apply 注入：把主面板切回对话（keyed main slot 的 null 就是对话）。 */
    let closePanel = () => {};
    const BASE = (() => {
      try {
        if (typeof document !== 'undefined' && document.baseURI) return String(new URL('dsh-game-archive/', document.baseURI));
      } catch (error) { /* ignore */ }
      return '/dsh-game-archive/';
    })();

    const PLATFORM = {
      Steam: { color: '#66c0f4', label: 'Steam' },
      PSN: { color: '#4a7dff', label: 'PSN' },
      Switch: { color: '#ff5a5f', label: 'Switch' },
      Xbox: { color: '#3fbb3f', label: 'Xbox' },
      Epic: { color: '#c8ccd8', label: 'Epic' },
    };
    const STATUS = {
      playing: { label: '正在玩', color: '#5ad1a0' },
      shelved: { label: '已荒废', color: '#d8a657' },
      finished: { label: '通关', color: '#7c9cff' },
      platinum: { label: '白金', color: '#e7c15a' },
      dropped: { label: '弃坑', color: '#c8805a' },
      backlog: { label: '还没碰过', color: '#8b90a0' },
      wish: { label: '想玩', color: '#e0b84c' },
    };
    const STATUS_ORDER = ['playing', 'finished', 'platinum', 'shelved', 'dropped', 'backlog'];
    /** 荒废多久：不到 30 天说天，不到 1 年说月，再往上给一位小数。 */
    const dn = (g) => (g && (g.cn || g.en || g.name)) || '';
const dnAlt = (g) => {
  if (!g) return '';
  const main = dn(g);
  const other = (g.cn && g.en) ? (g.en === main ? g.cn : g.en) : '';
  return other && other !== main ? other : '';
};
const fmtSpan = (days) => {
      if (days === null || days === undefined) return '日期不明';
      if (days < 30) return `${Math.max(1, Math.round(days))} 天`;
      if (days < 365) return `${Math.round(days / 30)} 个月`;
      return `${(days / 365).toFixed(1)} 年`;
    };
    /** 卡上/抽屉里显示的状态文案（荒废带上年数）。 */
    const statusText = (g) => {
      const st = STATUS[g.status] || STATUS.playing;
      if (g.status !== 'shelved') return st.label;
      return g.daysSincePlay === null ? '已荒废 · 日期不明' : `已荒废 ${fmtSpan(g.daysSincePlay)}`;
    };
    const CUR_SYM = { CNY: '¥', USD: '$', EUR: '€', GBP: '£', JPY: 'JP¥', UNKNOWN: '' };
    /** 奖项三档：年度游戏=金，其他奖项=银，年度游戏提名=铜。 */
    const awardTier = (g) => {
      const list = g.awards || [];
      if (g.goty || list.includes('年度游戏')) return 'gold';
      if (list.length) return 'silver';
      return g.gotyNom ? 'copper' : '';
    };
    const fmtPrice = (p) => {
      if (!p) return '—';
      const sym = CUR_SYM[p.currency || 'UNKNOWN'] ?? '';
      if (p.free) return '免费';
      if (typeof p.initial !== 'number') return '—';
      return `${sym || ''}${Math.round(p.initial)}${sym ? '' : ' ' + (p.currency || '')}`;
    };
    const fmtRelease = (r) => {
      if (!r) return '—';
      const m = /^(\d{4})(?:-(\d{2}))?/.exec(String(r));
      return m ? (m[2] ? `${m[1]}-${m[2]}` : m[1]) : String(r);
    };
    const fmtMeta = (n) => (typeof n === 'number' ? `M${n}` : '—');

    // 陈列室只显示这些奖项（与 Host 的 HONOR_ACCEPT 保持一致）
const SHOW_CATS = new Set([
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

// 陈列室固定排序：T0 定义年度 → T1 核心创作 → T2 影响力/独立 → T3 类型专项 → T4 运营与技术。
// 同一层里靠前的先出；没列进来的（以后新增的奖项）排最后，并保持数据原来的先后。
const CAT_ORDER = [
  // T0 定义年度的两项
  '年度游戏', '最佳游戏指导',
  // T1 核心创作 / 高权重类型
  '最佳叙事', '最佳美术指导', '最佳动作冒险游戏', '最佳角色扮演游戏', '最佳演出',
  // T2 特殊影响力，但受机制或类别限制
  '玩家之声', '最佳独立游戏', '最佳独立游戏处女作', '最佳新晋独立游戏', '最具影响力游戏',
  // T3 类型专项
  '最佳动作游戏', '最佳格斗游戏', '最佳家庭游戏', '最佳模拟策略游戏', '最佳策略游戏',
  '最佳体育竞速游戏', '最佳VR游戏', '最佳 VR/AR 游戏', '最佳多人游戏',
  // T4 运营 / 技术向
  '最佳持续运营游戏', '最佳社区支持', '最佳配乐', '最佳配乐/原声', '最佳音效设计',
];
const CAT_RANK = new Map(CAT_ORDER.map((name, i) => [name, i]));
const catRank = (c) => {
  const key = String((c && c.category) || '').trim();
  const r = CAT_RANK.get(key);
  return r === undefined ? CAT_ORDER.length + 100 : r;
};
function orderCats(list) {
  return (list || [])
    .map((c, i) => ({ c, i }))
    .sort((a, b) => (catRank(a.c) - catRank(b.c)) || (a.i - b.i))
    .map((x) => x.c);
}

const VIEWS = [
      { id: 'home', label: '总览' },
      { id: 'library', label: '库' },
      { id: 'next', label: '接着玩什么' },
      { id: 'yearly', label: '统计' },
      { id: 'awards', label: 'TGA' },
      { id: 'triage', label: '待确认' },
      { id: 'recommend', label: '推荐' },
      { id: 'table', label: '明细' },
    ];

    const fmtHours = (n) => {
      const v = Number(n) || 0;
      if (v <= 0) return '—';
      if (v < 1) return v.toFixed(1) + ' h';
      if (v < 10) return v.toFixed(1) + ' h';
      return Math.round(v).toLocaleString('zh-CN') + ' h';
    };
    const cover = (url) => (url ? `${BASE}cover?u=${encodeURIComponent(url)}` : '');
    const initialOf = (name) => String(name || '?').replace(/[^\p{L}\p{N}]/gu, '').slice(0, 1).toUpperCase() || '?';
    const hueOf = (name) => {
      let x = 0;
      for (const ch of String(name || '')) x = (x * 31 + ch.codePointAt(0)) % 360;
      return x;
    };

    const CSS = `
.ga-root{position:absolute;inset:0;padding-top:46px;box-sizing:border-box;display:flex;flex-direction:column;min-height:0;color:var(--dsh-text-1,#e8eaf1);
  background-color:var(--dsh-bg-1,#0b0d13);isolation:isolate;font-size:13px}
.ga-root:before{content:'';position:absolute;inset:0;z-index:-1;pointer-events:none;
  background:radial-gradient(1200px 600px at 15% -10%,rgba(124,92,255,.16),transparent 60%),
             radial-gradient(900px 500px at 90% 0%,rgba(34,211,238,.10),transparent 55%)}
.ga-head{flex:none;padding:10px 26px 0;display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap}
.ga-title{font-size:20px;font-weight:650;letter-spacing:.2px;margin:0}
.ga-sub{color:var(--dsh-text-3,#8b90a0);font-size:12px;margin-top:6px;display:flex;gap:10px;flex-wrap:wrap}
.ga-head-right{margin-left:auto;display:flex;align-items:center;gap:8px}
.ga-btn{border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.04);color:inherit;
  padding:7px 13px;border-radius:9px;cursor:pointer;font-size:12px;line-height:1;display:inline-flex;align-items:center;gap:6px}
.ga-btn:hover{background:rgba(255,255,255,.09);border-color:rgba(255,255,255,.2)}
.ga-btn.ga-back{margin-right:2px}
.ga-btn.primary{background:linear-gradient(135deg,#7c5cff,#22d3ee);border:0;color:#0b0d13;font-weight:650}
.ga-btn.primary:hover{filter:brightness(1.08)}
.ga-btn:disabled{opacity:.55;cursor:default}
.ga-tabs{flex:none;display:flex;gap:4px;padding:16px 26px 0;border-bottom:1px solid rgba(255,255,255,.07)}
.ga-tab{position:relative;padding:9px 14px;border-radius:9px 9px 0 0;cursor:pointer;color:var(--dsh-text-3,#8b90a0);
  border:1px solid transparent;border-bottom:0;font-size:13px;background:transparent}
.ga-tab:hover{color:var(--dsh-text-1,#e8eaf1);background:rgba(255,255,255,.03)}
.ga-tab.on{color:#fff;background:rgba(255,255,255,.06);border-color:rgba(255,255,255,.09)}
.ga-tab.on:after{content:'';position:absolute;left:12px;right:12px;bottom:-1px;height:2px;
  background:linear-gradient(90deg,#7c5cff,#22d3ee);border-radius:2px}
.ga-body{flex:1;min-height:0;overflow:auto;padding:20px 26px 40px}
.ga-body::-webkit-scrollbar{width:10px}
.ga-body::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:8px;border:2px solid transparent;background-clip:padding-box}

/* —— 总览 —— */
.ga-hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}
.ga-stat{position:relative;overflow:hidden;padding:16px 18px;border-radius:14px;border:1px solid rgba(255,255,255,.07);
  background:linear-gradient(160deg,rgba(255,255,255,.055),rgba(255,255,255,.012))}
.ga-stat:before{content:'';position:absolute;inset:0;background:radial-gradient(120px 80px at 100% 0,rgba(124,92,255,.18),transparent 70%)}
.ga-stat b{display:block;font-size:26px;font-weight:640;letter-spacing:-.5px;line-height:1.15}
.ga-stat span{display:block;margin-top:5px;font-size:11.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-bars{display:flex;flex-direction:column;gap:10px;margin:6px 0 22px}
.ga-bar{display:flex;align-items:center;gap:12px}
.ga-bar .n{width:56px;font-size:12px;color:var(--dsh-text-2,#c3c7d4)}
.ga-bar .t{flex:1;height:9px;border-radius:99px;background:rgba(255,255,255,.06);overflow:hidden}
.ga-bar .f{height:100%;border-radius:99px;transition:width .5s cubic-bezier(.4,0,.2,1)}
.ga-bar .v{width:150px;text-align:right;font-size:11.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-section-title{display:flex;align-items:center;gap:10px;margin:22px 0 12px;font-size:13px;font-weight:600}
.ga-section-title:after{content:'';flex:1;height:1px;background:linear-gradient(90deg,rgba(255,255,255,.1),transparent)}
.ga-chips{display:flex;gap:8px;flex-wrap:wrap}
.ga-chip{padding:6px 11px;border-radius:99px;font-size:11.5px;border:1px solid rgba(255,255,255,.08);
  background:rgba(255,255,255,.03);color:var(--dsh-text-2,#c3c7d4)}
.ga-chip i{display:inline-block;width:6px;height:6px;border-radius:99px;margin-right:6px;vertical-align:1px}

/* —— 工具条 —— */
.ga-tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:16px;position:sticky;top:0;z-index:6;
  padding:12px 0;background:linear-gradient(180deg,rgba(11,13,19,.96),rgba(11,13,19,.86) 70%,transparent)}
.ga-search{flex:1 1 220px;min-width:160px;position:relative}
.ga-search input{width:100%;padding:8px 12px 8px 30px;border-radius:9px;border:1px solid rgba(255,255,255,.1);
  background:rgba(255,255,255,.04);color:inherit;font-size:12.5px;outline:none}
.ga-search input:focus{border-color:rgba(124,92,255,.6);background:rgba(255,255,255,.06)}
.ga-search svg{position:absolute;left:9px;top:50%;transform:translateY(-50%);opacity:.5}
.ga-select{padding:8px 10px;border-radius:9px;border:1px solid rgba(255,255,255,.1);
  background:rgba(255,255,255,.04);color:inherit;font-size:12px;outline:none}
.ga-select option{background:#14161f;color:#e8eaf1}
.ga-pill{padding:7px 11px;border-radius:99px;border:1px solid rgba(255,255,255,.09);background:transparent;
  color:var(--dsh-text-3,#8b90a0);font-size:11.5px;cursor:pointer;white-space:nowrap}
.ga-pill:hover{color:#fff;border-color:rgba(255,255,255,.2)}
.ga-pill.on{color:#0b0d13;font-weight:600;border-color:transparent}
.ga-seg{display:inline-flex;border:1px solid rgba(255,255,255,.1);border-radius:9px;overflow:hidden}
.ga-seg button{background:transparent;border:0;color:var(--dsh-text-3,#8b90a0);padding:7px 10px;cursor:pointer;font-size:12px}
.ga-seg button.on{background:rgba(255,255,255,.1);color:#fff}

/* —— 网格 —— */
.ga-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(212px,1fr));gap:14px}
.ga-grid.top6{grid-template-columns:repeat(auto-fill,minmax(186px,1fr));gap:12px}
.ga-card{position:relative;border-radius:13px;overflow:hidden;cursor:pointer;border:1px solid rgba(255,255,255,.07);
  background:rgba(255,255,255,.03);transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease}
.ga-card:hover{transform:translateY(-3px);border-color:rgba(124,92,255,.45);
  box-shadow:0 14px 34px -14px rgba(0,0,0,.9),0 0 0 1px rgba(124,92,255,.18)}
.ga-card.nom{box-shadow:0 0 0 1px rgba(214,224,236,.34),0 16px 38px -24px rgba(186,204,224,.6)}
.ga-card.nom:before{content:'';position:absolute;inset:0;border-radius:inherit;padding:2px;pointer-events:none;z-index:5;
  background:linear-gradient(155deg,#f6f9ff,#c2cfe0 34%,#8d9cb2 52%,#e6edf7 76%,#ffffff);
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;mask-composite:exclude}
.ga-card.nom:hover:before{background:linear-gradient(155deg,#ffffff,#b9c8da 40%,#8595ab 56%,#e7eef8)}
.ga-award-item.copper{border-color:rgba(214,160,116,.5);box-shadow:inset 0 0 0 1px rgba(214,160,116,.14),0 6px 22px -16px rgba(214,150,104,.5)}
.ga-award-item.silver{border-color:rgba(196,208,224,.42);box-shadow:inset 0 0 0 1px rgba(196,208,224,.12),0 6px 22px -16px rgba(180,196,214,.4)}
.ga-award-item.copper .nm:after{content:' · 年度游戏提名';color:#d6a074;font-size:11px;font-weight:500}
.ga-card.goty{box-shadow:0 0 0 1px rgba(248,212,120,.30),0 16px 40px -22px rgba(232,193,90,.65)}
.ga-card.goty:before{content:'';position:absolute;inset:0;border-radius:inherit;padding:2.2px;pointer-events:none;z-index:5;
  background:linear-gradient(155deg,#ffe08c,#e9bd52 34%,#a8791f 52%,#f6d072 78%,#ffe6a3);
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
  -webkit-mask-composite:xor;mask-composite:exclude}
.ga-card.goty:hover:before{background:linear-gradient(155deg,#ffd977,rgba(220,170,60,.35) 45%,#ffd977)}
.ga-award.gold,.ga-award.goty{color:#1a1405;background:linear-gradient(180deg,#f7d97a,#dcae3c);border-color:transparent;font-weight:640}
.ga-award.silver{color:#0e1218;background:linear-gradient(180deg,#e6ecf5,#b9c4d4);box-shadow:0 2px 10px rgba(190,204,222,.28)}
.ga-award.copper{color:#1d130a;background:linear-gradient(180deg,#e8b98a,#c08252);box-shadow:0 2px 10px rgba(214,150,104,.3)}
.ga-card.copper:before{content:'';position:absolute;inset:0;border-radius:inherit;padding:2px;pointer-events:none;z-index:5;
  background:linear-gradient(155deg,#e9bd90,#b97a4c 42%,#e9bd90);
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude}
.ga-card.silver{box-shadow:0 0 0 1px rgba(214,224,236,.2),0 14px 34px -22px rgba(186,204,224,.45)}
.ga-card.silver:before{content:'';position:absolute;inset:0;border-radius:inherit;padding:1.5px;pointer-events:none;z-index:5;
  background:linear-gradient(155deg,rgba(246,250,255,.9),rgba(186,200,218,.55) 50%,rgba(238,244,250,.8));
  -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude}
.ga-award-item.goty{border-color:rgba(232,193,90,.5);box-shadow:inset 0 0 0 1px rgba(232,193,90,.14),0 6px 22px -16px rgba(232,193,90,.5)}
.ga-award-item.goty .nm:after{content:' · 年度游戏';color:#e7c15a;font-size:11px;font-weight:500}
.ga-cover{position:relative;aspect-ratio:460/215;background:#161922;overflow:hidden}
.ga-cover img,.ga-cover .ph{position:absolute;inset:0;width:100%;height:100%}
.ga-cover img{object-fit:cover;display:block;transition:transform .35s ease,filter .2s}
.ga-card:hover .ga-cover img{transform:scale(1.04)}
.ga-cover .cover-blur{filter:blur(16px) brightness(.5) saturate(.9);transform:scale(1.12);background-size:cover;background-position:center}
.ga-cover .contain-img{object-fit:contain;padding:6px 0;filter:drop-shadow(0 4px 14px rgba(0,0,0,.6))}
.ga-cover .ph{display:flex;align-items:center;justify-content:center;
  font-size:34px;font-weight:700;color:rgba(255,255,255,.5);letter-spacing:-1px}
.ga-cover .shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.05) 40%,rgba(0,0,0,.72))}
.ga-award{position:absolute;top:8px;right:8px;display:flex;align-items:center;gap:4px;padding:3px 7px;border-radius:7px;
  font-size:10.5px;font-weight:700;letter-spacing:.2px;color:#2b1d00;
  background:linear-gradient(135deg,#ffe08a,#f5b942);box-shadow:0 2px 10px rgba(245,185,66,.35)}
.ga-award.multi:after{content:'+';font-size:9px;opacity:.7;margin-left:1px}
.ga-plat{position:absolute;top:8px;left:8px;padding:2.5px 7px;border-radius:6px;font-size:10px;font-weight:650;
  background:rgba(8,10,16,.72);backdrop-filter:blur(6px);border:1px solid rgba(255,255,255,.12)}
.ga-hours{position:absolute;bottom:7px;right:9px;font-size:11px;font-weight:650;color:#fff;
  text-shadow:0 1px 6px rgba(0,0,0,.85)}
.ga-card-body{padding:9px 11px 11px}
.ga-card-sub{display:flex;gap:7px;align-items:center;margin-top:3px;font-size:10.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-card-sub .mc{color:#9fb4c9;font-weight:600}
.ga-alt{font-size:11px;color:var(--dim);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ga-alt-i{font-style:normal;font-size:11px;color:var(--dim);margin-left:6px}
.ga-alt-p{font-size:12px;color:var(--dim);margin:2px 0 8px}
.ga-card-name{font-size:12.5px;font-weight:560;line-height:1.35;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ga-card-meta{display:flex;align-items:center;gap:7px;margin-top:6px;font-size:10.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-dot{width:6px;height:6px;border-radius:99px;flex:none}
.ga-prog{height:3px;border-radius:99px;background:rgba(255,255,255,.08);overflow:hidden;margin-top:8px}
.ga-prog i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#7c5cff,#22d3ee)}
.ga-stars{display:inline-flex;gap:1px;color:#f5c451;font-size:10px;letter-spacing:-1px}

/* —— 列表 —— */
.ga-rows{display:flex;flex-direction:column;gap:1px;border-radius:12px;overflow:hidden;border:1px solid rgba(255,255,255,.07)}
.ga-row{display:grid;grid-template-columns:34px 56px 1fr 110px 90px 78px;align-items:center;gap:12px;
  padding:8px 12px;cursor:pointer;background:rgba(255,255,255,.022);border-bottom:1px solid rgba(255,255,255,.04)}
.ga-row:hover{background:rgba(124,92,255,.1)}
.ga-row .idx{font-size:11px;color:var(--dsh-text-3,#8b90a0);text-align:right}
.ga-row .thumb{width:56px;height:26px;border-radius:5px;overflow:hidden;background:#1a1e28;position:relative}
.ga-row .thumb img,.ga-row .thumb .ph{position:absolute;inset:0;width:100%;height:100%}
.ga-row .thumb img{object-fit:cover}
.ga-row .thumb .ph{font-size:12px;display:flex;align-items:center;justify-content:center}
.ga-row .nm{min-width:0}
.ga-row .nm b{display:block;font-size:12.5px;font-weight:540;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ga-row .nm span{font-size:10.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-row .hrs{text-align:right;font-size:12px;font-variant-numeric:tabular-nums}
.ga-row .pg{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--dsh-text-3,#8b90a0)}
.ga-row .pg .bar{flex:1;height:4px;border-radius:99px;background:rgba(255,255,255,.08);overflow:hidden}
.ga-row .pg .bar i{display:block;height:100%;background:linear-gradient(90deg,#7c5cff,#22d3ee)}

/* —— 接着玩 —— */
.ga-nextlist{display:flex;flex-direction:column;gap:8px}
.ga-nrow.rec{cursor:default}
.ga-nrow.rec:hover{transform:none;border-color:rgba(255,255,255,.07)}
.ga-nrow{display:grid;grid-template-columns:34px 104px minmax(0,1fr) 54px;align-items:center;gap:12px;
  padding:9px 12px;border-radius:12px;border:1px solid rgba(255,255,255,.07);
  background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.012));cursor:pointer;
  transition:border-color .18s,background .18s,transform .18s}
.ga-nrow:hover{border-color:rgba(124,92,255,.45);background:rgba(255,255,255,.06);transform:translateX(2px)}
.ga-nrank{font-size:15px;font-weight:700;text-align:center;color:var(--dsh-text-3,#8b90a0);font-variant-numeric:tabular-nums}
.ga-nrank.hot{color:#f3c867}
.ga-nthumb{position:relative;height:58px;border-radius:8px;overflow:hidden;background:rgba(255,255,255,.04)}
.ga-nthumb img,.ga-nthumb .ph{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.ga-nthumb .ph{display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:rgba(255,255,255,.42)}
.ga-nmain{min-width:0}
.ga-nline{display:flex;align-items:center;gap:8px;min-width:0}
.ga-nname{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ga-nhook{margin-top:3px;font-size:12px;color:#b9a6ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ga-nmeta{margin-top:4px;display:flex;gap:10px;flex-wrap:wrap;font-size:11px;color:var(--dsh-text-3,#8b90a0)}
.ga-nright{display:flex;align-items:baseline;justify-content:flex-end;gap:2px}
.ga-nscore{font-size:17px;font-weight:700;color:#cfc2ff;font-variant-numeric:tabular-nums}
.ga-nscorel{font-size:10px;color:var(--dsh-text-3,#8b90a0)}
.ga-next{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}
.ga-next-card{position:relative;border-radius:14px;overflow:hidden;border:1px solid rgba(255,255,255,.08);cursor:pointer;
  background:linear-gradient(160deg,rgba(124,92,255,.1),rgba(255,255,255,.02))}
.ga-next-card:hover{border-color:rgba(124,92,255,.5)}
.ga-next-card .top{position:relative;aspect-ratio:460/215;background:#161922}
.ga-next-card .top img,.ga-next-card .top .ph{position:absolute;inset:0;width:100%;height:100%}
.ga-next-card .top img{object-fit:cover;opacity:.92}
.ga-next-card .top .shade{position:absolute;inset:0;background:linear-gradient(180deg,transparent 30%,rgba(11,13,19,.95))}
.ga-next-card .info{position:relative;padding:0 14px 14px;margin-top:-26px}
.ga-next-card .nm{font-size:15px;font-weight:620;line-height:1.3}
.ga-next-card .why{margin-top:7px;font-size:11.5px;color:var(--dsh-text-3,#8b90a0);line-height:1.6}
.ga-next-card .row{display:flex;align-items:center;gap:8px;margin-top:10px}

/* —— 年度 —— */
.ga-years{display:flex;align-items:flex-end;gap:10px;height:240px;padding:16px 4px 0;overflow-x:auto}
.ga-year{flex:1;min-width:52px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:6px;height:100%}
.ga-year .col{width:100%;border-radius:7px 7px 3px 3px;background:linear-gradient(180deg,#7c5cff,#22d3ee);
  min-height:3px;transition:filter .2s;position:relative}
.ga-year:hover .col{filter:brightness(1.15)}
.ga-year .lb{font-size:10.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-year .hh{font-size:10.5px;color:var(--dsh-text-2,#c3c7d4);font-variant-numeric:tabular-nums}
.ga-yeartable{width:100%;border-collapse:collapse;margin-top:18px;font-size:12px}
.ga-yeartable th{text-align:left;font-weight:500;color:var(--dsh-text-3,#8b90a0);padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.08)}
.ga-yeartable td{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.04);font-variant-numeric:tabular-nums}
.ga-yeartable tr:hover td{background:rgba(124,92,255,.08)}

/* —— 奖项 —— */
.ga-award-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(252px,1fr));gap:12px}
.ga-award-item{display:flex;gap:11px;padding:11px;border-radius:12px;cursor:pointer;
  border:1px solid rgba(245,185,66,.22);background:linear-gradient(150deg,rgba(245,185,66,.1),rgba(255,255,255,.015))}
.ga-award-item:hover{border-color:rgba(245,185,66,.5)}
.ga-award-item .thumb{position:relative;width:74px;height:36px;border-radius:6px;overflow:hidden;background:#1a1e28;flex:none}
.ga-award-item .thumb img,.ga-award-item .thumb .ph{position:absolute;inset:0;width:100%;height:100%}
.ga-award-item .thumb img{object-fit:cover}
.ga-award-item .nm{font-size:12.5px;font-weight:580;line-height:1.35}
.ga-award-item .hs{margin-top:5px;display:flex;gap:5px;flex-wrap:wrap}
/* 奖项三档：年度游戏 = 金，其他奖项 = 银，年度游戏提名 = 铜（虚线，表示没拿到） */
.ga-honor{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:6px;white-space:nowrap;
  font-size:11.5px;font-weight:620;line-height:1.45;border:1px solid rgba(255,255,255,.12);
  background:rgba(255,255,255,.05);color:#c6cbd8}
.ga-honor.gold{color:#2a1c03;border-color:transparent;background:linear-gradient(180deg,#ffe282,#ddab30);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.5),0 4px 14px -7px rgba(232,184,69,.95)}
.ga-honor.gold:before{content:'★';font-size:9px;line-height:1;opacity:.8}
.ga-honor.silver{color:#131a25;border-color:transparent;background:linear-gradient(180deg,#f9fcff,#aebccd);
  box-shadow:inset 0 1px 0 rgba(255,255,255,.7),0 4px 12px -8px rgba(190,204,222,.85)}
.ga-honor.copper{color:#e3ab80;border:1px dashed rgba(212,152,108,.7);background:rgba(212,152,108,.09)}
.ga-honor.copper:before{content:'☆';font-size:9px;line-height:1;opacity:.85}
/* 年份不是奖项：灰字标记，右侧竖线跟奖章隔开 */
.ga-tga-year{display:inline-flex;align-items:baseline;gap:5px;padding-right:10px;margin-right:2px;
  border-right:1px solid rgba(255,255,255,.18);white-space:nowrap;color:#828a9b;font-size:11px;
  letter-spacing:.6px;font-variant-numeric:tabular-nums}
.ga-tga-year em{font-style:normal;font-size:9px;font-weight:700;letter-spacing:1.6px;opacity:.62}
.ga-tga-year b{font-size:12px;font-weight:650;color:#a9b2c4;letter-spacing:.2px}
.ga-honor-row>.ga-tga-year~.ga-tga-year{margin-left:12px}
.ga-award-year{font-size:10.5px;color:#f5c451;opacity:.85;margin-top:4px}
/* —— TGA 陈列室 —— */
.ga-hall{display:flex;gap:18px;align-items:flex-start}
.ga-hall-years{display:flex;flex-direction:column;gap:3px;min-width:74px;position:sticky;top:8px}
.ga-hall-years button{appearance:none;border:1px solid transparent;background:transparent;color:var(--dsh-text-3,#8b90a0);
  font:inherit;font-size:12.5px;font-weight:600;padding:5px 9px;border-radius:8px;cursor:pointer;text-align:left;transition:.15s}
.ga-hall-years button:hover{background:rgba(255,255,255,.05);color:#dfe3ea}
.ga-hall-years button.on{background:linear-gradient(180deg,rgba(245,185,66,.22),rgba(245,185,66,.08));
  border-color:rgba(245,185,66,.42);color:#f7d68a}
.ga-hall-body{flex:1;min-width:0;display:flex;flex-direction:column;gap:10px}
.ga-hall-empty{padding:30px 4px;color:#7b8395;font-size:12.5px;letter-spacing:.2px}
.ga-hall-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:2px}
.ga-hall-head b{font-size:19px;font-weight:700;letter-spacing:.4px}
.ga-hall-head span{font-size:11.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-hall-tools{display:flex;gap:6px;margin-left:auto}
.ga-hall-tools .ga-chip.btn{font-size:11px;padding:3px 9px;border-radius:7px}
.ga-hall-tools .ga-chip.btn.on{background:linear-gradient(180deg,rgba(126,196,255,.28),rgba(126,196,255,.12));
  border-color:rgba(126,196,255,.4);color:#cfe6ff}
.ga-cat2{display:grid;grid-template-columns:304px minmax(0,1fr);gap:16px;padding:14px;
  border:1px solid rgba(255,255,255,.07);border-radius:14px;background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.012))}
.ga-cat2.gold{border-color:rgba(240,200,104,.22);background:linear-gradient(180deg,rgba(240,200,104,.07),rgba(240,200,104,.015))}
.ga-win{display:flex;flex-direction:column;gap:9px;min-width:0}
.ga-win.mine .ga-th.big{box-shadow:0 0 0 1px rgba(120,217,176,.35),0 12px 30px -20px rgba(0,0,0,.9)}
.ga-th{position:relative;flex:none;width:44px;height:25px;border-radius:5px;overflow:hidden;background:rgba(255,255,255,.05)}
.ga-th.big{width:100%;height:auto;aspect-ratio:16/9;border-radius:11px}
.ga-th img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block}
.ga-th img.contain{object-fit:contain;background:rgba(0,0,0,.35)}
.ga-th .ph{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:700;color:rgba(255,255,255,.4);
  background:radial-gradient(circle at 28% 22%,rgba(255,255,255,.1),transparent 62%),linear-gradient(140deg,#2a3040,#161a24)}
.ga-th.big .ph{font-size:32px}
.ga-win-pending{width:100%;aspect-ratio:16/9;border-radius:11px;display:flex;align-items:center;justify-content:center;
  border:1px dashed rgba(255,255,255,.16);background:rgba(255,255,255,.02);
  color:#7b8395;font-size:13px;font-weight:650;letter-spacing:3px}
.ga-win-body{display:flex;flex-direction:column;gap:4px;min-width:0}
.ga-cat-tag{align-self:flex-start;font-size:10px;padding:1.5px 7px;border-radius:5px;font-weight:700;letter-spacing:.3px;
  background:linear-gradient(180deg,#e6ecf5,#b9c4d4);color:#0e1218}
.ga-cat-tag.gold{background:linear-gradient(180deg,#f7d97a,#dcae3c);color:#1a1405}
.ga-win-name{font-size:13.5px;font-weight:660;color:#f4f6fa;line-height:1.35;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ga-win.gold .ga-win-name{color:#f7e2a8}
.ga-win-en{font-size:10px;color:var(--dsh-text-3,#8b90a0);line-height:1.3;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ga-noms{display:grid;grid-template-columns:repeat(auto-fill,minmax(212px,1fr));gap:5px 12px;align-content:start}
.ga-nom{display:flex;align-items:center;gap:8px;min-width:0;font-size:12px;padding:2px 0}
.ga-nom.dim{opacity:.55}
.ga-nom-t{color:var(--dsh-text-2,#a8b0be);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ga-nom .own{font-size:9.5px;padding:0 5px;border-radius:4px;background:rgba(90,209,160,.16);color:#78d9b0;flex:none}
.ga-nom .own.play{background:rgba(102,192,244,.16);color:#7fc8f2}
.ga-cat{border:1px solid rgba(255,255,255,.07);border-radius:12px;background:rgba(255,255,255,.022);overflow:hidden}
.ga-cat-h{padding:8px 12px;font-size:12px;font-weight:640;color:#cfd6e2;border-bottom:1px solid rgba(255,255,255,.05);
  display:flex;align-items:center;gap:7px}
.ga-cat-h .tag{font-size:9.5px;padding:1px 6px;border-radius:5px;font-weight:700;letter-spacing:.2px}
.ga-cat-b{display:grid;grid-template-columns:1fr 1fr;gap:2px 16px;padding:9px 12px 11px}
.ga-ent{display:flex;align-items:center;gap:6px;font-size:12px;line-height:1.9;min-width:0}
.ga-ent .w{color:#f5d98a;font-weight:600}
.ga-ent .n{color:var(--dsh-text-2,#a8b0be)}
.ga-ent .own{font-size:9.5px;padding:0 5px;border-radius:4px;background:rgba(90,209,160,.16);color:#78d9b0;flex:none}
.ga-ent .own.play{background:rgba(102,192,244,.16);color:#7fc8f2}
.ga-ent.dim{opacity:.5}
.ga-ent.dim .n{color:var(--dsh-text-3,#8b90a0)}
.ga-hall-stats{font-size:11.5px;color:var(--dsh-text-3,#8b90a0);margin-bottom:2px}
/* —— 折叠 —— */
.ga-fold{display:flex;justify-content:center;margin-top:10px}
.ga-fold button{appearance:none;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.03);
  color:var(--dsh-text-2,#a8b0be);font:inherit;font-size:11.5px;padding:6px 16px;border-radius:8px;cursor:pointer}
.ga-fold button:hover{background:rgba(255,255,255,.07);color:#e6e9ef}
/* —— 状态按钮 —— */
.ga-chip.btn{cursor:pointer;transition:.15s}
.ga-chip.btn:hover{background:rgba(255,255,255,.09);border-color:rgba(255,255,255,.2);transform:translateY(-1px)}
/* —— 库价值 —— */
.ga-value{margin-top:14px;border:1px solid rgba(255,255,255,.07);border-radius:12px;background:rgba(255,255,255,.022);padding:12px 14px}
.ga-value-h{display:flex;align-items:center;justify-content:space-between;gap:10px;cursor:pointer}
.ga-value-h b{font-size:13px}
.ga-value-h .big{font-size:20px;font-weight:700;letter-spacing:.4px}
.ga-value-h .sub{font-size:11px;color:var(--dsh-text-3,#8b90a0)}
.ga-value-b{margin-top:11px;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}
.ga-vtable{width:100%;border-collapse:collapse;font-size:11.5px}
.ga-vtable th{text-align:left;font-weight:600;color:var(--dsh-text-3,#8b90a0);padding:4px 6px;border-bottom:1px solid rgba(255,255,255,.07)}
.ga-vtable td{padding:4px 6px;border-bottom:1px solid rgba(255,255,255,.04)}
.ga-vtable td.num{text-align:right;font-variant-numeric:tabular-nums}
.ga-vtitle{font-size:11px;font-weight:640;color:#cfd6e2;margin-bottom:5px}
/* —— 月份选择器 —— */
.ga-mpick{display:flex;align-items:center;gap:4px}
.ga-mpick select{appearance:none;background:#1b1f2a;color:#dfe3ea;border:1px solid rgba(255,255,255,.12);
  border-radius:7px;font:inherit;font-size:11.5px;padding:5px 6px;cursor:pointer}
.ga-mpick select:focus{outline:none;border-color:rgba(245,185,66,.5)}
.ga-mpick .step{width:22px;height:24px;display:flex;align-items:center;justify-content:center;
  border:1px solid rgba(255,255,255,.1);border-radius:6px;background:rgba(255,255,255,.03);color:#aab2c0;cursor:pointer;font-size:12px}
.ga-mpick .step:hover{background:rgba(255,255,255,.08);color:#e6e9ef}

/* —— 详情抽屉 —— */
.ga-drawer-mask{position:absolute;inset:0;background:rgba(4,5,9,.62);backdrop-filter:blur(3px);z-index:40}
.ga-drawer{position:absolute;top:0;right:0;bottom:0;width:min(460px,92%);z-index:41;display:flex;flex-direction:column;
  background:linear-gradient(180deg,#141721,#0e1017);border-left:1px solid rgba(255,255,255,.1);
  box-shadow:-24px 0 60px -20px rgba(0,0,0,.9);animation:ga-in .22s ease}
@keyframes ga-in{from{transform:translateX(24px);opacity:.4}to{transform:none;opacity:1}}
.ga-drawer .hero{position:relative;aspect-ratio:460/215;background:#161922;flex:none}
.ga-drawer .hero img,.ga-drawer .hero .ph{position:absolute;inset:0;width:100%;height:100%}
.ga-drawer .hero img{object-fit:cover}
.ga-drawer .hero .shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.1) 40%,rgba(14,16,23,.98))}
.ga-drawer .hero .x{position:absolute;top:10px;right:10px;width:28px;height:28px;border-radius:8px;display:flex;
  align-items:center;justify-content:center;background:rgba(8,10,16,.6);border:1px solid rgba(255,255,255,.14);cursor:pointer}
.ga-drawer .inner{flex:1;min-height:0;overflow:auto;padding:4px 20px 26px;margin-top:-40px;position:relative}
.ga-drawer h3{margin:0;font-size:19px;font-weight:640;line-height:1.3}
.ga-drawer .meta{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px;font-size:11.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-facts{display:flex;flex-wrap:wrap;gap:6px 10px;margin:12px 0 0;font-size:11.5px;color:var(--dsh-text-2,#a8b0be)}
.ga-facts span{padding:2px 8px;border-radius:6px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.06)}
.ga-kv{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin:16px 0}
.ga-kv div{padding:10px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.06)}
.ga-kv b{display:block;font-size:15px;font-weight:620}
.ga-kv span{font-size:10.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-field{margin-top:14px}
.ga-field>label{display:block;font-size:11px;color:var(--dsh-text-3,#8b90a0);margin-bottom:6px}
.ga-rating{display:flex;gap:3px;align-items:center}
.ga-rating button{background:none;border:0;font-size:21px;line-height:1;cursor:pointer;color:rgba(255,255,255,.18);padding:0 1px}
.ga-rating button.on{color:#f5c451}
.ga-rating span{margin-left:8px;font-size:11.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-ta{width:100%;min-height:76px;padding:9px 11px;border-radius:10px;border:1px solid rgba(255,255,255,.1);
  background:rgba(255,255,255,.035);color:inherit;font-size:12.5px;line-height:1.6;resize:vertical;outline:none;font-family:inherit}
.ga-ta:focus{border-color:rgba(124,92,255,.55)}
.ga-stat-row{display:flex;gap:6px;flex-wrap:wrap}
.ga-mini{padding:6px 10px;border-radius:8px;border:1px solid rgba(255,255,255,.09);background:transparent;cursor:pointer;
  font-size:11.5px;color:var(--dsh-text-3,#8b90a0)}
.ga-mini.on{color:#0b0d13;font-weight:650;border-color:transparent}
.ga-honor-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-top:12px}

.ga-hint{margin-top:7px;font-size:11px;color:var(--dsh-text-3,#8b90a0)}

.ga-tblwrap{display:flex;flex-direction:column;gap:8px}
.ga-tblbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:4px}
.ga-tblcount{font-size:11px;color:var(--dim);margin-left:auto}
.ga-tblhead,.ga-trl{display:grid;grid-template-columns:250px repeat(5,minmax(0,1fr)) 92px 78px;gap:8px;align-items:center}
.ga-tblhead{font-size:11px;color:var(--dim);padding:0 10px 6px;letter-spacing:.04em}
.ga-trl{padding:6px 10px;border-radius:10px;background:rgba(255,255,255,.022);border:1px solid rgba(255,255,255,.05)}
.ga-trl:hover{background:rgba(255,255,255,.04)}
.ga-tname{display:flex;align-items:center;gap:6px;min-width:0}
.ga-tname b{font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ga-tname .chip{flex:none;font-size:9.5px;padding:1px 5px;border-radius:5px}
.ga-tlock{font-style:normal;font-size:10px;color:var(--gold);flex:none}
.ga-in{width:100%;box-sizing:border-box;background:rgba(255,255,255,.03);border:1px solid transparent;border-radius:7px;
  color:var(--text);font-size:12px;padding:5px 7px;font-family:inherit;transition:border-color .15s,background .15s}
.ga-in:hover{border-color:rgba(255,255,255,.12)}
.ga-in:focus{outline:none;border-color:var(--accent);background:rgba(255,255,255,.06)}
.ga-in.blank{color:rgba(255,255,255,.28)}
.ga-in.saved{border-color:rgba(94,214,143,.65);background:rgba(94,214,143,.10)}
.ga-select.ga-curr{padding:5px 6px;font-size:11px;width:100%;box-sizing:border-box}
.ga-more{display:flex;justify-content:center;padding:10px 0}
.ga-synchint{font-size:11px;color:var(--dim);margin-right:2px;white-space:nowrap}
.ga-synchint.due{color:#e8b04b}
.ga-synchint.stale{color:#f0836a}
.ga-note{font-size:11.5px;line-height:1.75;color:var(--dsh-text-3,#8b90a0);margin:2px 0 10px}
.ga-tlist{display:flex;flex-direction:column;gap:8px;margin-bottom:6px}
.ga-titem{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:11px;
  border:1px solid rgba(255,255,255,.07);background:rgba(255,255,255,.026)}
.ga-titem:hover{border-color:rgba(124,156,255,.35);background:rgba(124,156,255,.05)}
.ga-tmain{flex:1;min-width:0}
.ga-tname{font-size:13px;font-weight:580;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ga-tmeta{margin-top:4px;display:flex;gap:8px;flex-wrap:wrap;font-size:11px;color:var(--dsh-text-3,#8b90a0);align-items:center}
.ga-tauto{color:#d8a657}
.ga-tbtns{display:flex;align-items:center;gap:6px;flex:none}
.ga-btn.tiny{padding:5px 10px;font-size:11.5px;border-radius:8px}
.ga-month{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.12);color:inherit;
  border-radius:8px;padding:4px 7px;font-size:11.5px;font-family:inherit}
.ga-dash{color:var(--dsh-text-3,#8b90a0);font-size:11px}
.ga-months{display:grid;grid-template-columns:repeat(auto-fill,minmax(38px,1fr));gap:5px;align-items:end;
  height:120px;padding:10px 2px 0}
.ga-month-bar{display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%;gap:4px}
.ga-month-bar .f{width:100%;border-radius:4px 4px 2px 2px;
  background:linear-gradient(180deg,#7c9cff,#5ad1a088)}
.ga-month-bar span{font-size:9px;color:var(--dsh-text-3,#8b90a0);white-space:nowrap}
.ga-empty.sm{padding:14px;font-size:12px}
.ga-empty{padding:70px 20px;text-align:center;color:var(--dsh-text-3,#8b90a0);font-size:12.5px}
.ga-empty b{display:block;font-size:15px;color:var(--dsh-text-1,#e8eaf1);margin-bottom:8px}
.ga-syncline{margin-top:10px;font-size:11.5px;color:var(--dsh-text-3,#8b90a0);line-height:1.7;
  padding:10px 12px;border-radius:10px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);
  max-height:170px;overflow:auto;white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
`;

    function Stars({ value }) {
      if (!value) return null;
      const full = Math.round(value / 2);
      return h('span', { className: 'ga-stars', title: `${value} / 10` }, '★'.repeat(full) + '☆'.repeat(5 - full));
    }

    /** 只吐内容（占位块 + 图），容器和遮罩交给调用方，层级才对。 */
    function Cover({ game, eager }) {
      const [broken, setBroken] = useState(false);
      const src = cover(game.cover);
      const tint = PLATFORM[game.platform]?.color || '#7d8aa8';
      const ph = h('div', {
        className: 'ph',
        style: {
          background: `radial-gradient(circle at 26% 20%, ${tint}30, transparent 62%),`
            + `linear-gradient(140deg,hsl(${hueOf(game.name)} 48% 20%),hsl(${(hueOf(game.name) + 46) % 360} 52% 11%))`,
        },
      }, initialOf(game.name));
      if (!src || broken) return ph;
      // 竖版盒图（Wikipedia 盒装封面）：留边显示，背后垫一层同图虚化，别硬裁成横条
      if (game.coverFit === 'contain') {
        return h(React.Fragment, null,
          h('div', { className: 'ph cover-blur', style: { backgroundImage: `url(${src})` } }),
          h('img', {
            src, alt: game.name, loading: eager ? 'eager' : 'lazy', className: 'contain-img',
            onError: () => setBroken(true),
          }));
      }
      return h(React.Fragment, null, ph,
        h('img', { src, alt: game.name, loading: eager ? 'eager' : 'lazy', onError: () => setBroken(true) }));
    }

    function PlatformChip({ platform }) {
      const p = PLATFORM[platform] || { color: '#888', label: platform };
      return h('span', { className: 'ga-plat', style: { color: p.color } }, p.label);
    }

    function Card({ game, onOpen, index }) {
      const st = STATUS[game.status] || STATUS.playing;
      const tier = awardTier(game);
      const n = (game.awards || []).length;
      const tierClass = tier === 'gold' ? 'goty' : tier === 'silver' ? 'silver' : tier === 'copper' ? 'copper' : '';
      return h('div', { className: 'ga-card' + (tierClass ? ' ' + tierClass : ''), onClick: () => onOpen(game), title: dn(game) },
        h('div', { className: 'ga-cover' },
          h(Cover, { game }),
          h('div', { className: 'shade' }),
          h(PlatformChip, { platform: game.platform }),
          tier ? h('span', {
            className: `ga-award ${tier}` + (n > 1 ? ' multi' : ''),
            title: tier === 'copper'
              ? `TGA ${game.gotyNom} 年度游戏提名`
              : `TGA ${game.awardYear} ${(game.awards || []).join(' / ')}`,
          }, tier === 'gold' ? `★ 年度游戏${n > 1 ? ' ×' + n : ''}`
            : tier === 'silver' ? `★ 获奖${n > 1 ? ' ×' + n : ''}`
              : '★ 提名') : null,
          game.hours > 0 ? h('span', { className: 'ga-hours' }, fmtHours(game.hours)) : null),
        h('div', { className: 'ga-card-body' },
          h('div', { className: 'ga-card-name' }, dn(game)),
          dnAlt(game) ? h('div', { className: 'ga-alt' }, dnAlt(game)) : null,
          h('div', { className: 'ga-card-meta' },
            h('i', { className: 'ga-dot', style: { background: st.color } }),
            h('span', null, statusText(game)),
            game.progressPct !== null ? h('span', null, `· ${game.progressPct}%`) : null,
            game.rating ? h(Stars, { value: game.rating }) : null),
          (game.release || typeof game.metacritic === 'number')
            ? h('div', { className: 'ga-card-sub' },
              game.release ? h('span', null, fmtRelease(game.release)) : null,
              typeof game.metacritic === 'number' ? h('span', { className: 'mc' }, `M${game.metacritic}`) : null)
            : null,
          game.progressPct !== null
            ? h('div', { className: 'ga-prog' }, h('i', { style: { width: `${Math.min(100, game.progressPct)}%` } }))
            : null));
    }

    function Row({ game, onOpen, index }) {
      const st = STATUS[game.status] || STATUS.playing;
      return h('div', { className: 'ga-row', onClick: () => onOpen(game) },
        h('span', { className: 'idx' }, index + 1),
        h('div', { className: 'thumb' }, h(Cover, { game })),
        h('div', { className: 'nm' },
          h('b', null, dn(game)), dnAlt(game) ? h('i', { className: 'ga-alt-i' }, dnAlt(game)) : null,
          h('span', null, [
            PLATFORM[game.platform]?.label || game.platform,
            game.release ? fmtRelease(game.release) : '',
            game.genre || '',
            game.metacritic ? fmtMeta(game.metacritic) : '',
            game.last ? `上次 ${game.last}` : '',
            (game.awards || []).length
              ? `★ TGA ${game.awardYear}${(game.awards || []).length > 1 ? ' ×' + game.awards.length : ''}`
              : (game.gotyNom ? `★ ${game.gotyNom} 年度游戏提名` : ''),
          ].filter(Boolean).join(' · '))),
        h('div', { className: 'hrs' }, fmtHours(game.hours)),
        h('div', { className: 'pg' },
          h('div', { className: 'bar' }, h('i', { style: { width: `${game.progressPct || 0}%` } })),
          h('span', null, game.progressPct !== null ? `${game.progressPct}%` : '')),
        h('div', { style: { fontSize: 11, color: st.color, textAlign: 'right' } }, statusText(game)));
    }

    /** 奖项行：年份做成灰字标记（它不是奖），奖项分三档——年度游戏金 / 其他奖项银 / 年度游戏提名铜。 */
    function HonorRow({ game }) {
      const list = game.awards || [];
      const gold = list.includes('年度游戏');
      const others = list.filter((a) => a !== '年度游戏')
        .map((a, i) => ({ a, i }))
        .sort((x, y) => (catRank({ category: x.a }) - catRank({ category: y.a })) || (x.i - y.i))
        .map((x) => x.a);
      const yearA = game.awardYear || null;
      const nomYear = game.gotyNom || null;
      // 提名是另一码事：拿了年度游戏就不再重复提；年份相同就不重复写一次
      const showNom = !!nomYear && !gold;
      if (!list.length && !showNom) return null;
      const yearTag = (y, key) => h('span', { className: 'ga-tga-year', key: 'y' + key },
        h('em', null, 'TGA'), h('b', null, y));
      return h('div', { className: 'ga-honor-row' },
        list.length ? yearTag(yearA || nomYear, 'a') : null,
        gold ? h('span', { className: 'ga-honor gold', key: 'gold' }, '年度游戏') : null,
        others.map((a, i) => h('span', { className: 'ga-honor silver', key: 'h' + i }, a)),
        showNom && (!list.length || nomYear !== yearA) ? yearTag(nomYear, 'b') : null,
        showNom ? h('span', { className: 'ga-honor copper', key: 'nom' }, '年度游戏提名') : null);
    }

    function Drawer({ game, onClose, onSave }) {
      const [rating, setRating] = useState(game.rating || 0);
      const [status, setStatus] = useState(game.status);
      const [review, setReview] = useState(game.review || '');
      const [saved, setSaved] = useState('');
      const timer = useRef(null);
      useEffect(() => { setRating(game.rating || 0); setStatus(game.status); setReview(game.review || ''); }, [game.id]);
      const commit = useCallback((patch, note) => {
        onSave(game.id, patch);
        setSaved(note || '已保存');
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setSaved(''), 1600);
      }, [game.id, onSave]);
      useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
      return h(React.Fragment, null,
        h('div', { className: 'ga-drawer-mask', onClick: onClose }),
        h('div', { className: 'ga-drawer' },
          h('div', { className: 'hero' },
            h(Cover, { game }),
            h('div', { className: 'shade' }),
            h('div', { className: 'x', onClick: onClose, title: '关闭 (Esc)' }, '✕')),
          h('div', { className: 'inner' },
            h('h3', null, dn(game)),
            dnAlt(game) ? h('p', { className: 'ga-alt-p' }, dnAlt(game)) : null,
            h('div', { className: 'meta' },
              h('span', { style: { color: PLATFORM[game.platform]?.color } }, PLATFORM[game.platform]?.label || game.platform),
              game.last ? h('span', null, `上次 ${game.last}`) : null,
              game.progressPct !== null ? h('span', null, `完成度 ${game.progressPct}%`) : null,
              game.ach ? h('span', null, game.ach) : null),
            h(HonorRow, { game }),
            h('div', { className: 'ga-facts' },
              game.release ? h('span', null, `发售 ${fmtRelease(game.release)}`) : null,
              game.genre ? h('span', null, game.genre) : null,
              typeof game.metacritic === 'number' ? h('span', null, `M 站 ${game.metacritic}`) : null,
              game.price ? h('span', null,
                `原价 ${fmtPrice(game.price)}`
                + (game.price.free ? '' : game.price.discount ? `（-${Math.round((1 - game.price.final / game.price.initial) * 100)}%）` : '')
                + (game.price.original ? `　原 ${game.price.original.currency} ${Math.round(game.price.original.initial).toLocaleString('zh-CN')}` : '')) : null),
            h('div', { className: 'ga-kv' },
              h('div', null, h('b', null, fmtHours(game.hours)), h('span', null, '总时长')),
              h('div', null, h('b', null, game.progressPct !== null ? `${game.progressPct}%` : '—'), h('span', null, '完成度')),
              h('div', null, h('b', null, game.rating ? `${game.rating}/10` : '—'), h('span', null, '我的评分'))),
            h('div', { className: 'ga-field' },
              h('label', null, '状态'),
              h('div', { className: 'ga-stat-row' }, STATUS_ORDER.map((k) => [k, STATUS[k]]).map(([k, v]) => h('button', {
                key: k, className: 'ga-mini' + (status === k ? ' on' : ''),
                style: status === k ? { background: v.color } : null,
                onClick: () => { setStatus(k); commit({ status: k }); },
              }, v.label))),
              h('div', { className: 'ga-hint' },
                game.statusAuto
                  ? `当前：${statusText(game)}（机器判定，点一下按钮就固定下来）`
                  : `当前：${statusText(game)}（你标的）`)),
            h('div', { className: 'ga-field' },
              h('label', null, '评分'),
              h('div', { className: 'ga-rating' },
                Array.from({ length: 10 }, (_, i) => i + 1).map((n) => h('button', {
                  key: n, className: n <= rating ? 'on' : '',
                  onClick: () => { setRating(n); commit({ rating: n }); },
                  title: `${n} / 10`,
                }, n <= rating ? '★' : '☆')),
                h('span', null, rating ? `${rating}/10` : '未评分'))),
            h('div', { className: 'ga-field' },
              h('label', null, '短评'),
              h('textarea', {
                className: 'ga-ta', value: review, placeholder: '记一句。通关感想、弃坑理由、下次想干嘛……',
                onChange: (e) => setReview(e.target.value),
                onBlur: () => commit({ review }),
              })),
            game.note ? h('div', { style: { marginTop: 12, fontSize: 11, color: 'var(--dsh-text-3,#8b90a0)' } }, `数据说明：${game.note}`) : null,
            h('div', { style: { marginTop: 14, display: 'flex', gap: 8, alignItems: 'center' } },
              h('button', { className: 'ga-btn', onClick: () => commit({ reset: true }, '已恢复自动判定') }, '恢复自动状态'),
              h('button', { className: 'ga-btn', onClick: () => commit({ hidden: true }, '已从档案隐藏') }, '从档案隐藏'),
              h('span', { style: { fontSize: 11, color: '#5ad1a0' } }, saved)))));
    }

    /** 4 项数字的折叠列表：默认 6 个，展开后全给，展开状态记在 localStorage。 */
    function FoldGrid({ items, storageKey, onOpen, total }) {
      const KEY = `ga-fold:${storageKey}`;
      const [open, setOpen] = useState(() => {
        try { return localStorage.getItem(KEY) === '1'; } catch { return false; }
      });
      const toggle = () => setOpen((v) => {
        const next = !v;
        try { localStorage.setItem(KEY, next ? '1' : '0'); } catch { /* 忽略 */ }
        return next;
      });
      const shown = open ? items : items.slice(0, 6);
      return h('div', null,
        h('div', { className: 'ga-grid top6' },
          shown.map((g) => h(Card, { key: g.id, game: g, onOpen, index: 0 }))),
        items.length > 6 ? h('div', { className: 'ga-fold' },
          h('button', { onClick: toggle },
            open ? `收起（只看前 6 款）` : `展开全部 ${items.length} 款 · 还有 ${items.length - shown.length} 款`)) : null);
    }

    function Overview({ data, onGo }) {
      const { stats } = data;
      const max = Math.max(1, ...stats.platforms.map((p) => p.hours));
      const byHours = useMemo(() => [...data.games].sort((a, b) => b.hours - a.hours).slice(0, 24), [data.games]);
      const byRecent = useMemo(() => data.games
        .filter((g) => (g.hours || 0) > 0 && g.lastEffective)
        .sort((a, b) => String(b.lastEffective).localeCompare(String(a.lastEffective)))
        .slice(0, 24), [data.games]);
      const val = data.value || null;
      const [vOpen, setVOpen] = useState(false);
      const money = (obj) => (val && obj
        ? Object.entries(obj).map(([c, v]) => `${CUR_SYM[c] ?? ''}${Math.round(v).toLocaleString('zh-CN')}${CUR_SYM[c] ? '' : ' ' + c}`).join(' + ')
        : '—');
      return h('div', null,
        h('div', { className: 'ga-hero' },
          h('div', { className: 'ga-stat' }, h('b', null, Math.round(stats.hours).toLocaleString('zh-CN')), h('span', null, '总时长（小时）')),
          h('div', { className: 'ga-stat' }, h('b', null, stats.total), h('span', null, '档案里的游戏')),
          h('div', { className: 'ga-stat' }, h('b', null, stats.played), h('span', null, '真开过的')),
          h('div', { className: 'ga-stat' }, h('b', null, stats.awards), h('span', null, 'TGA 获奖作品')),
          h('div', { className: 'ga-stat' }, h('b', null, stats.buckets.backlog || 0), h('span', null, '还没碰过'))),
        h('div', { className: 'ga-bars' },
          stats.platforms.map((p) => h('div', { className: 'ga-bar', key: p.platform },
            h('span', { className: 'n' }, p.platform),
            h('div', { className: 't' }, h('div', {
              className: 'f',
              style: { width: `${Math.max(2, (p.hours / max) * 100)}%`, background: `linear-gradient(90deg,${PLATFORM[p.platform]?.color || '#888'},${PLATFORM[p.platform]?.color || '#888'}66)` },
            })),
            h('span', { className: 'v' }, `${fmtHours(p.hours)} · ${p.count} 款`)))),

        val ? h('div', { className: 'ga-value' },
          h('div', { className: 'ga-value-h', onClick: () => setVOpen((v) => !v) },
            h('div', null,
              h('b', null, '库价值 '),
              h('span', { className: 'big' }, money(val.total)),
              h('div', { className: 'sub' },
                `${val.games} 款里有价格的是 ${val.games - val.missing} 款；白送的那部分原价 ${money(val.freeValue)}`,
                val.missing ? `；${val.missing} 款没取到价格（显示 —）` : '')),
            h('span', { className: 'sub' }, vOpen ? '收起 ▲' : '按平台 / 类型 / 状态看 ▼')),
          vOpen ? h('div', { className: 'ga-value-b' },
            [['platform', '按平台'], ['genre', '按类型'], ['status', '按库状态']].map(([dim, title]) =>
              h('div', { key: dim },
                h('div', { className: 'ga-vtitle' }, title),
                h('table', { className: 'ga-vtable' },
                  h('thead', null, h('tr', null,
                    h('th', null, '分组'), h('th', { style: { textAlign: 'right' } }, '款数'), h('th', { style: { textAlign: 'right' } }, '原价合计'))),
                  h('tbody', null, (val[dim] || []).slice(0, 8).map((r) => h('tr', { key: r.key },
                    h('td', null, dim === 'status' ? (STATUS[r.key]?.label || r.key) : r.key),
                    h('td', { className: 'num' }, r.games),
                    h('td', { className: 'num' }, money(r.total))))))))) : null) : null,

        h('div', { className: 'ga-section-title' }, '状态分布'),
        h('div', { className: 'ga-chips' },
          STATUS_ORDER.map((k) => h('div', {
            className: 'ga-chip btn',
            key: k,
            title: `点一下看「${STATUS[k].label}」的全部`,
            onClick: () => onGo.filter({ status: k }),
          },
            h('i', { style: { background: STATUS[k].color } }),
            k === 'finished'
              ? `通关 ${data.stats.finishedTotal ?? data.stats.buckets.finished ?? 0}`
              : `${STATUS[k].label} ${data.stats.buckets[k] || 0}`,
            k === 'finished'
              ? h('em', { style: { fontStyle: 'normal', opacity: .55, marginLeft: 4, fontSize: 10 } }, '含白金')
              : null))),

        h('div', { className: 'ga-section-title' }, `最常玩 · 前 ${byHours.length} 款`),
        h(FoldGrid, { items: byHours, storageKey: 'top', onOpen: onGo.open, total: data.games.length }),

        h('div', { className: 'ga-section-title' }, `最近在玩 · 前 ${byRecent.length} 款`),
        byRecent.length
          ? h(FoldGrid, { items: byRecent, storageKey: 'recent', onOpen: onGo.open })
          : h('div', { className: 'ga-empty sm' }, '没有带日期的游玩记录。'));
    }


    /* ── 明细：一张能直接改的表，专治缺字段 ────────────────── */
    function DetailTable({ data, onField }) {
      const [onlyMissing, setOnlyMissing] = useState(true);
      const [q, setQ] = useState('');
      const [platform, setPlatform] = useState('');
      const [limit, setLimit] = useState(80);
      const [flash, setFlash] = useState({});

      const CURR = ['CNY', 'USD', 'JPY', 'HKD', 'EUR', 'TWD'];
      const fieldsOf = (g) => {
        const p = g.priceRaw || g.price || {};
        return {
          cn: !!g.cn, en: !!g.en, release: !!g.release,
          metacritic: !!g.metacritic, genre: !!g.genre, price: !!p.initial,
        };
      };

      const list = useMemo(() => {
        const terms = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
        return (data.games || []).filter((g) => {
          if (platform && g.platform !== platform) return false;
          if (terms.length) {
            const hay = [g.name, g.cn, g.en].filter(Boolean).join(' ').toLowerCase();
            if (!terms.every((t) => hay.includes(t))) return false;
          }
          if (onlyMissing) {
            const f = fieldsOf(g);
            if (f.cn && f.en && f.release && f.metacritic && f.genre && f.price) return false;
          }
          return true;
        });
      }, [data.games, q, platform, onlyMissing]);

      const plats = useMemo(() => {
        const seen = new Map();
        for (const g of data.games || []) {
          const k = g.platform;
          if (!k) continue;
          seen.set(k, (seen.get(k) || 0) + 1);
        }
        return [...seen.entries()]
          .sort((a, b) => b[1] - a[1])
          .map(([k, count]) => ({ key: k, count, label: PLATFORM[k]?.label || k }));
      }, [data.games]);

      const missingCount = useMemo(() => (data.games || []).filter((g) => {
        const f = fieldsOf(g);
        return !(f.cn && f.en && f.release && f.metacritic && f.genre && f.price);
      }).length, [data.games]);

      const commit = useCallback(async (g, key, value, currency) => {
        const res = await onField(g.id, key, value, currency);
        if (res && res.ok) {
          setFlash((f) => ({ ...f, [g.id + key]: Date.now() }));
          setTimeout(() => setFlash((f) => { const n = { ...f }; delete n[g.id + key]; return n; }), 1600);
        }
      }, [onField]);

      const cell = (g, key, cur, opts) => {
        const value = cur === undefined || cur === null ? '' : String(cur);
        const dirty = flash[g.id + key];
        return h('input', {
          className: 'ga-in' + (dirty ? ' saved' : '') + (value ? '' : ' blank'),
          defaultValue: value,
          placeholder: opts?.placeholder || '—',
          inputMode: opts?.num ? 'numeric' : undefined,
          onBlur: (e) => {
            const v = e.target.value.trim();
            if (v === value) return;
            commit(g, key, v, opts?.currency);
          },
          onKeyDown: (e) => { if (e.key === 'Enter') e.currentTarget.blur(); },
        });
      };

      const rows = list.slice(0, limit);

      return h('div', { className: 'ga-tblwrap' },
        h('div', { className: 'ga-tblbar' },
          h('div', { className: 'ga-search' },
            h('svg', { width: 13, height: 13, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 },
              h('circle', { cx: 11, cy: 11, r: 7 }), h('path', { d: 'M20 20l-3.5-3.5' })),
            h('input', { placeholder: '搜游戏名…（中英都行）', value: q, onChange: (e) => setQ(e.target.value) })),
          h('select', { className: 'ga-select', value: platform, onChange: (e) => setPlatform(e.target.value) },
            h('option', { value: '' }, '全部平台'),
            plats.map((p) => h('option', { key: p.key, value: p.key }, `${p.label}（${p.count}）`))),
          h('button', {
            className: 'ga-chip btn' + (onlyMissing ? ' on' : ''),
            onClick: () => setOnlyMissing((v) => !v),
          }, `只看缺的 ${missingCount}`),
          h('span', { className: 'ga-tblcount' }, `${rows.length} / ${list.length} 款 · 改完自动存`)),
        h('div', { className: 'ga-tblhead' },
          h('span', null, '游戏'), h('span', null, '中文名'), h('span', null, '英文名'),
          h('span', null, '发售日'), h('span', null, 'M 站'), h('span', null, '类型'),
          h('span', null, '发售价'), h('span', null, '币种')),
        rows.length ? rows.map((g) => {
          const p = g.priceRaw || g.price || {};
          return h('div', { className: 'ga-trl', key: g.id },
            h('div', { className: 'ga-tname' },
              h('span', { className: 'chip ' + g.platform.toLowerCase() }, g.platform),
              h('b', null, g.cn || g.en || g.name),
              (g.manual || []).length ? h('i', { className: 'ga-tlock', title: '有人工填写的内容' }, '✎') : null),
            cell(g, 'cn', g.cn),
            cell(g, 'en', g.en),
            cell(g, 'release', g.release, { placeholder: 'YYYY-MM-DD' }),
            cell(g, 'metacritic', g.metacritic, { num: true }),
            cell(g, 'genre', g.genre),
            cell(g, 'price', p.initial, { num: true, placeholder: '原价', currency: p.currency || 'CNY' }),
            h('select', {
              className: 'ga-select ga-curr', defaultValue: p.currency || 'CNY',
              onChange: (e) => commit(g, 'price', (g.priceRaw && g.priceRaw.initial) || 0, e.target.value),
            }, CURR.map((c) => h('option', { key: c, value: c }, c))));
        }) : h('div', { className: 'ga-empty' }, '没有缺字段的，或者筛选太严了'),
        list.length > rows.length ? h('div', { className: 'ga-more' },
          h('button', { className: 'ga-btn', onClick: () => setLimit((n) => n + 120) }, `再显示 120 款（还有 ${list.length - rows.length}）`)) : null,
        h('div', { className: 'ga-note' },
          '改一格就存一格，写进 manual.json——这些值以后不会被自动同步覆盖。清空单元格（或填 -）就是删除人工值、放回自动结果。'));
    }

    function Library({ data, state, setState, onOpen }) {
      const rows = useMemo(() => {
        const terms = String(state.q || '').trim().toLowerCase().split(/\s+/).filter(Boolean);
        let out = data.games.filter((g) => {
          if (state.platform && g.platform !== state.platform) return false;
          if (state.status) {
            // 白金也是通关 —— 筛「通关」时把白金一起算进来
            const ok = state.status === 'finished'
              ? (g.status === 'finished' || g.status === 'platinum')
              : g.status === state.status;
            if (!ok) return false;
          }
          if (state.awarded && !(g.awards || []).length) return false;
          if (!terms.length) return true;
          const name = [g.name, g.cn, g.en].filter(Boolean).join(' ').toLowerCase();
          const tags = (Array.isArray(g.tags) ? g.tags : []).map((t) => String(t).toLowerCase());
          const rest = `${g.note || ''} ${g.platform || ''}`.toLowerCase();
          return terms.every((t) => name.includes(t) || tags.some((x) => x.includes(t)) || rest.includes(t));
        });
        const sorters = {
          release: (a, b) => String(b.release || '').localeCompare(String(a.release || '')),
          hours: (a, b) => b.hours - a.hours,
          last: (a, b) => String(b.last).localeCompare(String(a.last)),
          progress: (a, b) => (b.progressPct || -1) - (a.progressPct || -1),
          rating: (a, b) => (b.rating || -1) - (a.rating || -1),
          meta: (a, b) => (b.metacritic || -1) - (a.metacritic || -1),
          price: (a, b) => (b.price?.initial || -1) - (a.price?.initial || -1),
          name: (a, b) => a.name.localeCompare(b.name, 'zh-Hans-CN'),
        };
        return out.sort(sorters[state.sort] || sorters.release);
      }, [data, state.platform, state.status, state.q, state.sort, state.awarded]);

      const listKey = [state.platform, state.status, state.q, state.awarded, state.sort].join('|');

      return h('div', null,
        h('div', { className: 'ga-tools' },
          h('div', { className: 'ga-search' },
            h('svg', { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 },
              h('circle', { cx: 11, cy: 11, r: 7 }), h('path', { d: 'm20 20-3.5-3.5' })),
            h('input', { value: state.q, placeholder: '搜游戏名 / 标签…', onChange: (e) => setState({ q: e.target.value }) })),
          h('select', { className: 'ga-select', value: state.platform, onChange: (e) => setState({ platform: e.target.value }) },
            h('option', { value: '' }, '全部平台'),
            Object.keys(PLATFORM).map((k) => h('option', { key: k, value: k }, k))),
          h('select', { className: 'ga-select', value: state.status, onChange: (e) => setState({ status: e.target.value }) },
            h('option', { value: '' }, '全部状态'),
            STATUS_ORDER.map((k) => h('option', { key: k, value: k }, STATUS[k].label))),
          h('select', { className: 'ga-select', value: state.sort, onChange: (e) => setState({ sort: e.target.value }) },
            h('option', { value: 'release' }, '按发售时间'),
            h('option', { value: 'hours' }, '按时长'),
            h('option', { value: 'last' }, '按最近玩'),
            h('option', { value: 'progress' }, '按完成度'),
            h('option', { value: 'meta' }, '按 M 站评分'),
            h('option', { value: 'price' }, '按原价'),
            h('option', { value: 'rating' }, '按我的评分'),
            h('option', { value: 'name' }, '按名称')),
          h('button', {
            className: 'ga-pill' + (state.awarded ? ' on' : ''),
            style: state.awarded ? { background: 'linear-gradient(135deg,#ffe08a,#f5b942)' } : null,
            onClick: () => setState({ awarded: !state.awarded }),
          }, '★ TGA'),
          (state.q || state.platform || state.status || state.awarded)
            ? h('button', {
              className: 'ga-pill',
              title: '把搜索、平台、状态、TGA 一起清掉',
              onClick: () => setState({ q: '', platform: '', status: '', awarded: false }),
            }, '清空筛选')
            : null,
          h('div', { className: 'ga-seg' },
            h('button', { className: state.mode === 'grid' ? 'on' : '', onClick: () => setState({ mode: 'grid' }) }, '网格'),
            h('button', { className: state.mode === 'list' ? 'on' : '', onClick: () => setState({ mode: 'list' }) }, '列表')),
          h('span', { style: { marginLeft: 'auto', fontSize: 11.5, color: 'var(--dsh-text-3,#8b90a0)' } }, `${rows.length} 款`)),
        rows.length === 0
          ? h('div', { className: 'ga-empty' }, h('b', null, '没有匹配的游戏'), '换个关键词，或者把筛选清掉。')
          : state.mode === 'grid'
            ? h('div', { className: 'ga-grid', key: `g:${listKey}` }, rows.map((g, i) => h(Card, { key: g.id, game: g, onOpen, index: i })))
            : h('div', { className: 'ga-rows', key: `r:${listKey}` }, rows.map((g, i) => h(Row, { key: g.id, game: g, onOpen, index: i }))));
    }

    function Recommend({ data }) {
      const rec = data.recommend;
      if (!rec) {
        return h('div', { className: 'ga-empty' },
          h('b', null, '还没跑过推荐'),
          '在终端跑一次 python3 tools/recommend.py，生成的 recommend.json 会出现在这里。这份内容不会自动更新。');
      }
      const items = rec.items || [];
      const basis = rec.basis || {};
      return h('div', null,
        h('div', { style: { marginBottom: 12, fontSize: 12, color: 'var(--dsh-text-3,#8b90a0)', lineHeight: 1.75 } },
          `基于库里 ${basis.library || '?'} 款 · 只推 ${basis.minYear || 2017} 年后发售 · 数据源 ${basis.source || 'TGA + Metacritic'} · 生成于 ${rec.updated || '?'}`,
          h('br'),
          '你投入最多的类型：',
          (basis.topGenres || []).map((t) => `${t.genre} ${Math.round(t.share * 100)}%`).join(' · '),
          '。要更新这份榜单，在终端跑一次 ',
          h('code', { style: { background: 'rgba(255,255,255,.08)', padding: '1px 5px', borderRadius: 4 } }, 'python3 tools/recommend.py'),
          '。'),
        items.length ? h('div', { className: 'ga-nextlist' }, items.map((g, i) => h('div', { className: 'ga-nrow rec', key: g.name },
          h('span', { className: 'ga-nrank' + (i < 3 ? ' hot' : '') }, i + 1),
          h('div', { className: 'ga-nthumb' }, g.cover
            ? h('img', { src: cover(g.cover), loading: i < 8 ? 'eager' : 'lazy', alt: '' })
            : h('div', { className: 'ph' }, initialOf(g.cn || g.name))),
          h('div', { className: 'ga-nmain' },
            h('div', { className: 'ga-nline' },
              h('span', { className: 'ga-nname' }, g.cn || g.name),
              g.cn && g.cn !== g.name ? h('span', { className: 'ga-alt-i' }, g.name) : null),
            h('div', { className: 'ga-nhook' }, g.why ? g.why[0] : ''),
            h('div', { className: 'ga-nmeta' },
              g.why ? g.why.slice(1).map((w, k) => h('span', { key: k }, w)) : null)),
          h('div', { className: 'ga-nright' },
            h('span', { className: 'ga-nscore' }, g.score),
            h('span', { className: 'ga-nscorel' }, '分')))))
          : h('div', { className: 'ga-empty' }, '这次没跑出结果。'));
    }

    function NextUp({ data, onOpen }) {
      const list = data.next || [];
      if (!list.length) {
        return h('div', { className: 'ga-empty' }, h('b', null, '没有该接着玩的'), '要么都通关了，要么都刚开过。');
      }
      return h('div', null,
        h('div', { style: { marginBottom: 12, fontSize: 12, color: 'var(--dsh-text-3,#8b90a0)', lineHeight: 1.75 } },
          `按「玩得久 × 进度靠后 × 口碑好 × 有 TGA 奖项 × 荒了一阵」算的，共 ${list.length} 款，不截断。点开可以直接改状态或记一笔。`),
        h('div', { className: 'ga-nextlist' }, list.map((g, i) => {
          const tier = awardTier(g);
          return h('div', { className: 'ga-nrow', key: g.id, onClick: () => onOpen(g) },
            h('span', { className: 'ga-nrank' + (i < 3 ? ' hot' : '') }, i + 1),
            h('div', { className: 'ga-nthumb' }, h(Cover, { game: g, eager: true })),
            h('div', { className: 'ga-nmain' },
              h('div', { className: 'ga-nline' },
                h('span', { className: 'ga-nname' }, dn(g)),
                dnAlt(g) ? h('span', { className: 'ga-alt-i' }, dnAlt(g)) : null,
                tier ? h('span', { className: 'ga-honor ' + tier },
                  tier === 'gold' ? '年度游戏' : (g.gotyNom ? '年度提名' : `TGA×${g.awards.length}`)) : null),
              h('div', { className: 'ga-nhook' }, g.hook),
              h('div', { className: 'ga-nmeta' },
                h('span', { className: 'ga-plat-i', style: { color: PLATFORM[g.platform]?.color } }, PLATFORM[g.platform]?.label),
                h('span', null, fmtHours(g.hours)),
                g.progressPct !== null ? h('span', null, `完成 ${g.progressPct}%`) : null,
                g.metacritic ? h('span', null, `M${g.metacritic}`) : null,
                g.daysSincePlay !== null ? h('span', null, `荒了 ${fmtSpan(g.daysSincePlay)}`) : null,
                g.release ? h('span', null, fmtRelease(g.release)) : null)),
            h('div', { className: 'ga-nright' },
              h('span', { className: 'ga-nscore' }, g.score),
              h('span', { className: 'ga-nscorel' }, '分')));
        })));
    }


    const MONTHS = Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, '0'));
    const addMonths = (ym, delta) => {
      const m = /^(\d{4})-(\d{2})$/.exec(String(ym || ''));
      if (!m) return ym;
      let y = Number(m[1]);
      let mo = Number(m[2]) - 1 + delta;
      y += Math.floor(mo / 12);
      mo = ((mo % 12) + 12) % 12;
      return `${y}-${String(mo + 1).padStart(2, '0')}`;
    };

    /** 年月选择器：两个下拉 + 「整年」+ 前后挪一个月，比原生 type=month 好点。 */
    function MonthPick({ from, to, onChange, defaultYear }) {
      const years = [];
      for (let y = 2028; y >= 1995; y--) years.push(String(y));
      const parts = (ym) => {
        const m = /^(\d{4})-(\d{2})$/.exec(String(ym || ''));
        return m ? { y: m[1], m: m[2] } : { y: '', m: '' };
      };
      const f = parts(from);
      const t = parts(to);
      const setY = (side, y) => {
        const cur = side === 'from' ? f : t;
        const mo = cur.m || '01';
        const next = `${y}-${mo}`;
        if (side === 'from') onChange(next, to && next > to ? next : to);
        else onChange(from && next < from ? next : from, next);
      };
      const setM = (side, mo) => {
        const cur = side === 'from' ? f : t;
        const y = cur.y || defaultYear || String(new Date().getFullYear());
        const next = `${y}-${mo}`;
        if (side === 'from') onChange(next, to && next > to ? next : to);
        else onChange(from && next < from ? next : from, next);
      };
      const wholeYear = () => {
        const y = f.y || defaultYear || String(new Date().getFullYear());
        onChange(`${y}-01`, `${y}-12`);
      };
      return h('div', { className: 'ga-mpick' },
        h('select', { value: f.y || '', onChange: (e) => setY('from', e.target.value) },
          h('option', { value: '' }, '年'), years.map((y) => h('option', { key: y, value: y }, y))),
        h('select', { value: f.m || '', onChange: (e) => setM('from', e.target.value) },
          h('option', { value: '' }, '月'), MONTHS.map((m) => h('option', { key: m, value: m }, `${Number(m)} 月`))),
        h('span', { className: 'ga-dash' }, '→'),
        h('select', { value: t.y || '', onChange: (e) => setY('to', e.target.value) },
          h('option', { value: '' }, '年'), years.map((y) => h('option', { key: y, value: y }, y))),
        h('select', { value: t.m || '', onChange: (e) => setM('to', e.target.value) },
          h('option', { value: '' }, '月'), MONTHS.map((m) => h('option', { key: m, value: m }, `${Number(m)} 月`))),
        h('button', { className: 'ga-btn tiny', title: '整年：1 月到 12 月', onClick: wholeYear }, '整年'),
        h('button', {
          className: 'ga-btn tiny',
          title: '把结束月往后挪一个月',
          disabled: !to,
          onClick: () => onChange(from, addMonths(to, 1)),
        }, '+1 月'));
    }

    /** 待确认：机器拿不准的状态 + 缺月份的游戏，一次点完。 */
    function Triage({ data, onSave, onReload }) {
      const tri = data.triage || { needStatus: [], needMonths: [], remain: 0 };
      const [draft, setDraft] = useState({});
      const [busy, setBusy] = useState('');

      const decide = async (id, status) => {
        setBusy(id);
        await onSave(id, { status });
        setBusy('');
      };
      const fill = async (id, from, to) => {
        if (!from || !to) return;
        setBusy(id);
        await onSave(id, { months: { from, to } });
        setDraft((s2) => { const n = { ...s2 }; delete n[id]; return n; });
        setBusy('');
      };
      const setRange = (id, from, to) => setDraft((s2) => ({ ...s2, [id]: { from: from || '', to: to || '' } }));

      return h('div', { className: 'ga-triage' },
        h('div', { className: 'ga-note' },
          '机器只按「开没开过 / 完成度 / 荒了多久」推，猜不出你心里的打算。下面两类是它拿不准的，点一下就算你说了。',
          tri.needStatus.length ? ` 这里先列投入最多的 ${tri.needStatus.length} 款。` : '',
          !tri.needStatus.length && tri.remain > 0
            ? ` 另有 ${tri.remain} 款机器判为「已荒废」，投入都不大、日期也清楚，可以在「库」里按状态筛出来批量点。`
            : ''),

        h('div', { className: 'ga-section-title' }, `状态拿不准 · ${tri.needStatus.length} 款`),
        tri.needStatus.length ? h('div', { className: 'ga-tlist' }, tri.needStatus.map((g) => {
          const auto = STATUS[g.status] || STATUS.playing;
          const reason = g.daysSincePlay === null
            ? '有游玩时长，但平台没给日期'
            : `最后游玩 ${g.last || '未知'}（${fmtSpan(g.daysSincePlay)}前）`;
          return h('div', { className: 'ga-titem', key: g.id },
            h('div', { className: 'ga-tmain' },
              h('div', { className: 'ga-tname' }, g.name),
              h('div', { className: 'ga-tmeta' },
                h('span', { className: 'ga-plat', style: { position: 'static', color: PLATFORM[g.platform]?.color } }, PLATFORM[g.platform]?.label),
                h('span', null, fmtHours(g.hours)),
                h('span', { className: 'ga-tauto' }, `机器猜：${auto.label}`),
                g.progressPct !== null ? h('span', null, `完成度 ${g.progressPct}%`) : null,
                h('span', null, reason))),
            h('div', { className: 'ga-tbtns' },
              h('button', { className: 'ga-btn tiny', disabled: busy === g.id, onClick: () => decide(g.id, 'dropped') }, '弃坑'),
              h('button', { className: 'ga-btn tiny', disabled: busy === g.id, onClick: () => decide(g.id, 'shelved') }, '已荒废'),
              h('button', { className: 'ga-btn tiny', disabled: busy === g.id, onClick: () => decide(g.id, 'finished') }, '通关'),
              h('button', { className: 'ga-btn tiny', disabled: busy === g.id, onClick: () => decide(g.id, 'platinum') }, '白金')));
        })) : h('div', { className: 'ga-empty sm' }, '都确认过了。'),

        h('div', { className: 'ga-section-title' }, `时间拿不准 · ${tri.needMonths.length} 款`),
        h('div', { className: 'ga-note' }, '这些只知道年份、或者根本没有日期。来源差别在这：Steam / PSN / Xbox 一般给到具体某天，Switch 只肯说「N 年前」、只能换算成整年，Epic 没有时长所以不列。填一个起止月，时长会按月平均摊开，年度回顾立刻变准。'),
        tri.needMonths.length ? h('div', { className: 'ga-tlist' }, tri.needMonths.map((g) => {
          const d = draft[g.id] || {};
          const from = d.from ?? (g.suggest ? g.suggest.from : '');
          const to = d.to ?? (g.suggest ? g.suggest.to : '');
          const guess = g.yearOnly
            ? `平台只给了 ${g.yearOnly} 年（先按整年填好，改月即可）`
            : /^\d{4}$/.test(String(g.last || '')) ? `只知道 ${g.last} 年` : '平台没给日期';
          return h('div', { className: 'ga-titem', key: g.id },
            h('div', { className: 'ga-tmain' },
              h('div', { className: 'ga-tname' }, g.name),
              h('div', { className: 'ga-tmeta' },
                h('span', { className: 'ga-plat', style: { position: 'static', color: PLATFORM[g.platform]?.color } }, PLATFORM[g.platform]?.label),
                h('span', null, fmtHours(g.hours)),
                h('span', { className: 'ga-tauto' }, guess))),
            h('div', { className: 'ga-tbtns' },
              h(MonthPick, {
                from,
                to,
                defaultYear: g.yearOnly || String(g.last || '').slice(0, 4) || null,
                onChange: (a, b) => setRange(g.id, a, b),
              }),
              h('button', {
                className: 'ga-btn tiny primary',
                disabled: busy === g.id || !from || !to,
                onClick: () => fill(g.id, from, to),
              }, '保存')));
        })) : h('div', { className: 'ga-empty sm' }, '没有需要补录的了。'));
    }

    function Yearly({ data }) {
      const rows = data.yearly;
      if (!rows.length) return h('div', { className: 'ga-empty' }, h('b', null, '没有日期数据'), '同步一次就有了。');
      const max = Math.max(1, ...rows.map((r) => r.hours));
      return h('div', null,
        h('div', { style: { fontSize: 11.5, color: 'var(--dsh-text-3,#8b90a0)', lineHeight: 1.7 } },
          '补录过月份的游戏，时长按那几个月平摊后计入对应年份；没补录的按「最后游玩年份」一次性归档 —— 所以年份越久远，数字越接近大概。'),
        null,
        h('div', { className: 'ga-years' }, rows.map((r) => h('div', { className: 'ga-year', key: r.year, title: `${r.year}：${r.games} 款 · ${fmtHours(r.hours)}` },
          h('div', { className: 'hh' }, r.hours >= 10 ? Math.round(r.hours) : r.hours.toFixed(1)),
          h('div', { className: 'col', style: { height: `${Math.max(3, (r.hours / max) * 100)}%` } }),
          h('div', { className: 'lb' }, r.year)))),
        h('table', { className: 'ga-yeartable' },
          h('thead', null, h('tr', null,
            h('th', null, '年份'), h('th', null, '游戏数'), h('th', null, '时长'), h('th', null, '当年通关（含白金）'))),
          h('tbody', null, [...rows].reverse().map((r) => h('tr', { key: r.year },
            h('td', null, r.year), h('td', null, r.games), h('td', null, fmtHours(r.hours)), h('td', null, r.finished))))));
    }

    /** 名字归一：跨平台对名单用（和 Host 端 applyAwards 的口径一致）。 */
    const normName = (v) => String(v || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');

    /** TGA 陈列室：历年全部奖项（获奖 + 提名），把库里有的标出来。 */
    function Awards({ data, onOpen }) {
      const years = (data.tga && data.tga.years) || [];
      const [year, setYear] = useState(null);
      const [onlyMine, setOnlyMine] = useState(false);
      const [hideNoms, setHideNoms] = useState(false);
      const owned = useMemo(() => {
        const map = new Map();
        for (const g of data.games) {
          const k = normName(g.name);
          const prev = map.get(k);
          if (!prev || (g.hours || 0) > (prev.hours || 0)) map.set(k, g);
        }
        return map;
      }, [data.games]);
      if (!years.length) {
        return h('div', { className: 'ga-empty' }, h('b', null, '还没有 TGA 名单'),
          '插件自带的 data/tga-history.json 没载入，重新打开一次面板。');
      }
      const sorted = [...years].sort((a, b) => b.year - a.year);
      const cur = sorted.find((y) => y.year === year) || sorted[0];
      const alias = (data.tga && data.tga.alias) || {};
      const media = (data.tga && data.tga.media) || {};
      const meta = (n) => media[n] || {};
      const nameOf = (n) => meta(n).cn || alias[n] || n;
      const isCn = (n) => nameOf(n) !== n;
      const coverOf = (n) => meta(n).cover || '';
      const fitOf = (n) => meta(n).fit === 'contain';
      const lookup = (n) => {
        const direct = owned.get(normName(n));
        if (direct) return direct;
        for (const key of [nameOf(n), alias[n]]) {
          if (!key) continue;
          const g = owned.get(normName(key));
          if (g) return g;
        }
        return null;
      };
      // 封面挂了（老作品图失效、新作还没上架）就退回首字占位，别留一块空白
      const Thumb = ({ name, big }) => {
        const src = coverOf(name);
        const [broken, setBroken] = useState(false);
        useEffect(() => { setBroken(false); }, [src]);
        return h('div', { className: 'ga-th' + (big ? ' big' : '') },
          src && !broken
            ? h('img', {
              src,
              loading: big ? 'eager' : 'lazy',
              alt: '',
              className: fitOf(name) ? 'contain' : '',
              onError: () => setBroken(true),
            })
            : h('div', { className: 'ph' }, initialOf(nameOf(name))));
      };
      const Badge = ({ game }) => game
        ? h('span', { className: 'own' + ((game.hours || 0) > 0 ? ' play' : '') },
          (game.hours || 0) > 0 ? `我玩过 ${fmtHours(game.hours)}` : '我库里有')
        : null;
      const cats = orderCats(cur.categories.filter((c) => SHOW_CATS.has(c.category)));
      // 获奖者还没公布（wiki 上常把当年的表格先填满假值，只认明确写的 TBD/TBA）
      const pendingOf = (s) => /^(tbd|tba|待定|未定|待公布)$/i.test(String(s == null ? '' : s).trim());
      const pendingCats = cats.filter((c) => pendingOf(c.winner)).length;
      const totalEntries = cats.reduce((n, c) => n + (pendingOf(c.winner) ? 0 : 1) + (c.nominees || []).length, 0);

      // wiki 抓下来的分类名偶尔带 "}}|"l":0}}}}/> " 这类尾巴垃圾，显示前统一清一道
      const cleanCat = (s) => String(s == null ? '' : s)
        .split('/>').pop().replace(/\\'/g, "'").replace(/^[\s'"}\]]+/, '').trim();

      const catCard = (c, ci) => {
        const pending = pendingOf(c.winner);
        const w = pending ? null : lookup(c.winner);
        const catName = cleanCat(c.category);
        const gold = catName === '年度游戏';
        const nomList = hideNoms ? [] : (c.nominees || []);
        if (pending && hideNoms) return null;
        if (onlyMine && !w && !(c.nominees || []).some((n) => lookup(n))) return null;
        const noms = nomList.length
          ? nomList.map((n, i) => {
            const g = lookup(n);
            return h('div', {
              className: 'ga-nom' + (g ? '' : ' dim'),
              key: i,
              onClick: g ? () => onOpen(g) : null,
              style: g ? { cursor: 'pointer' } : null,
              title: isCn(n) ? `${n} · ${nameOf(n)}` : n,
            },
              h(Thumb, { name: n }),
              h('span', { className: 'ga-nom-t' }, nameOf(n)),
              g ? h('span', { className: 'own' + ((g.hours || 0) > 0 ? ' play' : '') },
                (g.hours || 0) > 0 ? '玩过' : '有') : null);
          })
          : [h('div', { className: 'ga-nom dim', key: 'none' },
            h('span', { className: 'ga-nom-t' }, '（这一届没有提名名单）'))];
        if (onlyMine && !w) {
          const hitNoms = nomList.filter((n) => lookup(n));
          if (!hitNoms.length) return null;
        }
        return h('div', { className: 'ga-cat2' + (gold ? ' gold' : ''), key: ci },
          h('div', {
            className: 'ga-win' + (w ? ' mine' : ''),
            onClick: w ? () => onOpen(w) : null,
            style: w ? { cursor: 'pointer' } : null,
          },
            pending
              ? h('div', { className: 'ga-win-pending' }, 'TBD')
              : h(Thumb, { name: c.winner, big: true }),
            h('div', { className: 'ga-win-body' },
              h('span', { className: 'ga-cat-tag' + (gold ? ' gold' : '') }, catName),
              h('div', { className: 'ga-win-name' }, pending ? '获奖者待公布' : nameOf(c.winner)),
              !pending && isCn(c.winner) ? h('div', { className: 'ga-win-en' }, c.winner) : null,
              h(Badge, { game: w }))),
          h('div', { className: 'ga-noms' }, noms));
      };

      const cards = cats.map(catCard).filter(Boolean);
      return h('div', { className: 'ga-hall' },
        h('div', { className: 'ga-hall-years' },
          sorted.map((y) => h('button', {
            key: y.year,
            className: y.year === cur.year ? 'on' : '',
            onClick: () => setYear(y.year),
          }, y.year))),
        h('div', { className: 'ga-hall-body' },
          h('div', { className: 'ga-hall-head' },
            h('b', null, `${cur.year} 年度 TGA`),
            h('span', null, pendingCats === cats.length
              ? `${cats.length} 个奖项 · ${totalEntries} 条提名 · 获奖待公布`
              : pendingCats
                ? `${cats.length} 个奖项 · ${totalEntries} 条记录（${pendingCats} 项待公布）`
                : `${cats.length} 个奖项 · ${totalEntries} 条获奖与提名`),
            h('div', { className: 'ga-hall-tools' },
              h('button', {
                className: 'ga-chip btn' + (onlyMine ? ' on' : ''),
                onClick: () => setOnlyMine((v) => !v),
              }, '只看我有的'),
              h('button', {
                className: 'ga-chip btn' + (hideNoms ? ' on' : ''),
                onClick: () => setHideNoms((v) => !v),
              }, '只留获奖'))),
          cards.length ? cards : h('div', { className: 'ga-hall-empty' },
            pendingCats === cats.length
              ? '这一届只有提名，获奖结果还没公布'
              : '当前筛选下没有能显示的分类')));
    }

    function Page() {
      const [data, setData] = useState(null);
      const [error, setError] = useState('');
      const [view, setView] = useState('home');
      const [sel, setSel] = useState(null);
      const [syncing, setSyncing] = useState(false);
      const [syncMsg, setSyncMsg] = useState('');
      const [state, setStateRaw] = useState({ q: '', platform: '', status: '', sort: 'release', mode: 'grid', awarded: false });
      const setState = useCallback((patch) => setStateRaw((s) => ({ ...s, ...patch })), []);

      const load = useCallback(async () => {
        try {
          const r = await fetch(`${BASE}data`, { cache: 'no-store' });
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          setData(await r.json());
          setError('');
        } catch (e) {
          setError(String(e.message || e));
        }
      }, []);

      useEffect(() => { load(); }, [load]);

      useEffect(() => {
        const onKey = (e) => {
          if (e.key !== 'Escape') return;
          if (sel) setSel(null); else closePanel();
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
      }, []);

      const save = useCallback(async (id, patch) => {
        await fetch(`${BASE}edit`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id, ...patch }) }).catch(() => {});
        await load();
      }, [load]);

      const sync = useCallback(async () => {
        setSyncing(true); setSyncMsg('');
        try {
          const r = await fetch(`${BASE}sync`, { method: 'POST' });
          const j = await r.json();
          if (j.payload) setData(j.payload);
          setSyncMsg((j.tail || []).join('\n') || (j.ok ? '同步完成' : `失败：${j.error}`));
        } catch (e) {
          setSyncMsg(`同步失败：${String(e.message || e)}`);
        } finally {
          setSyncing(false);
        }
      }, []);

      const field = useCallback(async (id, key, value, currency) => {
        try {
          const r = await fetch(`${BASE}field`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ id, key, value, currency }),
          });
          const j = await r.json();
          if (!j.ok) return { ok: false, error: j.error };
          await load();
          return { ok: true };
        } catch (e) {
          return { ok: false, error: String(e.message || e) };
        }
      }, [load]);

      const daysSinceSync = (() => {
        const t = data?.sync?.lastRun;
        if (!t) return null;
        const d = Math.floor((Date.now() - new Date(t).getTime()) / 86400000);
        return Number.isFinite(d) ? d : null;
      })();
      const syncHint = h('span', {
        className: 'ga-synchint' + (daysSinceSync === null ? '' : daysSinceSync >= 14 ? ' stale' : daysSinceSync >= 7 ? ' due' : ''),
        title: '同步只在你点按钮时跑，没有后台定时任务',
      }, daysSinceSync === null ? '还没同步过'
        : daysSinceSync === 0 ? '今天同步过'
          : `距上次同步 ${daysSinceSync} 天`);

      const selLive = sel ? (data?.games.find((g) => g.id === sel.id) || sel) : null;

      return h('div', { className: 'ga-root' },
        h('style', null, CSS),
        h('div', { className: 'ga-head' },
          h('div', null,
            h('h2', { className: 'ga-title' }, '游戏档案'),
            h('div', { className: 'ga-sub' },
              data ? h('span', null, `${data.stats.total} 款 · ${Math.round(data.stats.hours).toLocaleString('zh-CN')} 小时 · ${data.stats.platforms.length} 个平台`) : h('span', null, '读取中…'),
              data?.updated ? h('span', null, `数据 ${data.updated}`) : null,
              data?.sync?.lastRun ? h('span', null, `上次同步 ${new Date(data.sync.lastRun).toLocaleString('zh-CN')}`) : null)),
          h('div', { className: 'ga-head-right' },
            h('button', { className: 'ga-btn ga-back', onClick: () => closePanel(), title: '返回对话 (Esc)' }, '← 返回对话'),
            h('button', { className: 'ga-btn', onClick: load, title: '从磁盘重读' }, '刷新'),
            syncHint,
            h('button', { className: 'ga-btn primary', onClick: sync, disabled: syncing }, syncing ? '同步中…' : '同步五平台'))),
        h('div', { className: 'ga-tabs' }, VIEWS.map((v) => h('div', {
          key: v.id, className: 'ga-tab' + (view === v.id ? ' on' : ''), onClick: () => setView(v.id),
        }, v.label))),
        h('div', { className: 'ga-body' },
          error ? h('div', { className: 'ga-empty' }, h('b', null, '读不到数据'), error) : null,
          !data && !error ? h('div', { className: 'ga-empty' }, '读取中…') : null,
          data && view === 'home' ? h(Overview, {
            data,
            onGo: {
              open: setSel,
              // 状态分布点一下 → 跳「库」并筛好该状态
              filter: (patch) => { setState({ status: '', platform: '', awarded: false, q: '', ...patch }); setView('library'); },
            },
          }) : null,
          data && view === 'library' ? h(Library, { data, state, setState, onOpen: setSel }) : null,
          data && view === 'next' ? h(NextUp, { data, onOpen: setSel }) : null,
          data && view === 'recommend' ? h(Recommend, { data }) : null,
          data && view === 'yearly' ? h(Yearly, { data }) : null,
          data && view === 'awards' ? h(Awards, { data, onOpen: setSel }) : null,
          data && view === 'triage' ? h(Triage, { data, onSave: save }) : null,
          data && view === 'table' ? h(DetailTable, { data, onField: field }) : null,
          syncMsg ? h('div', { className: 'ga-syncline' }, syncMsg) : null),
        selLive ? h(Drawer, { game: selLive, onClose: () => setSel(null), onSave: save }) : null);
    }

    function PanelIcon(props) {
      return h('svg', { width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round' },
        h('rect', { x: 2.5, y: 5, width: 19, height: 14, rx: 3 }),
        h('path', { d: 'M7 15V9.5l2.6 3.4L12 9.5V15' }),
        h('path', { d: 'M15.5 15h2.5' }));
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.inject(['layout'], (pageCtx) => pageCtx.slots.inject('main', () => {
          closePanel = () => { try { (pageCtx.layout || ctx.layout)?.selectPanel?.(null); } catch (error) { /* ignore */ } };
          const stopPage = pageCtx.slots.register({ name: 'main', key: PANEL_ID }, Page);
          const stopIcon = pageCtx.slots.inject('sidebar.panellist', () => pageCtx.slots.register({
            name: 'sidebar.panellist', id: PANEL_ID, order: 84, label: '游戏档案',
          }, PanelIcon));
          return () => { stopIcon(); stopPage(); };
        }));
      },
    };
  },
});
