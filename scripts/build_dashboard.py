#!/usr/bin/env python3
"""Build the static dashboard at docs/index.html from references/mirrors.json.

The JSON is inlined into the HTML so the page works both from GitHub Pages and
straight off the filesystem (no fetch, no CORS, no build tooling).

Usage:
    python3 scripts/build_dashboard.py
"""
import json
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "references", "mirrors.json")
OUT = os.path.join(ROOT, "docs", "index.html")

CATEGORY_LABELS = {
    "docker_community": "Docker 社区镜像",
    "docker_enterprise": "Docker 企业镜像",
    "github": "GitHub 加速",
    "tools": "常用工具源",
    "ai_models": "AI 模型仓库",
    "python": "Python 包管理",
    "dev_registry": "容器仓库镜像",
}

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>accel-mirror · 国内加速源实测看板</title>
<style>
  :root {
    --bg: #fafaf9; --card: #ffffff; --border: rgba(0,0,0,.10);
    --text: #1c1c1a; --muted: #5f5e5a; --hint: #888780;
    --s1: #0f6e56; --s2: #185fa5; --s3: #854f0b; --s4: #a32d2d; --s5: #888780;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17171a; --card: #1f1f23; --border: rgba(255,255,255,.14);
      --text: #f2f2f0; --muted: #b4b2a9; --hint: #8a8a85;
      --s1: #5dcaa5; --s2: #85b7eb; --s3: #ef9f27; --s4: #f09595; --s5: #b4b2a9;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 40px 24px 64px; background: var(--bg); color: var(--text);
    font-family: system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 14px; line-height: 1.6;
  }
  .wrap { max-width: 1080px; margin: 0 auto; }
  h1 { font-size: 22px; font-weight: 600; margin: 0 0 6px; }
  .sub { color: var(--muted); font-size: 13px; margin: 0 0 28px; }
  .sub code { background: rgba(127,127,127,.12); padding: 1px 5px; border-radius: 4px; font-size: 12px; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 32px; }
  .stat { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
  .stat .k { color: var(--muted); font-size: 12px; }
  .stat .v { font-size: 24px; font-weight: 600; margin-top: 2px; }
  section { margin-bottom: 32px; }
  h2 { font-size: 15px; font-weight: 600; margin: 0 0 4px; }
  .cat-meta { color: var(--hint); font-size: 12px; margin: 0 0 12px; }
  .list { background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .row { display: grid; grid-template-columns: 52px 1fr 96px; gap: 12px; align-items: center; padding: 10px 14px; border-top: 1px solid var(--border); }
  .row:first-child { border-top: 0; }
  .row.dead { opacity: .45; }
  .badge { text-align: center; font-size: 13px; font-weight: 600; border-radius: 6px; padding: 3px 0; }
  .nm { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .nm .u { color: var(--hint); font-size: 11px; display: block; overflow: hidden; text-overflow: ellipsis; }
  .ms { color: var(--muted); font-size: 12px; text-align: right; font-variant-numeric: tabular-nums; }
  .bar { height: 100%; border-radius: 3px; }
  .dist { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
  .drow { display: grid; grid-template-columns: 88px 1fr 40px; gap: 10px; align-items: center; margin-bottom: 8px; font-size: 12px; }
  .dtrack { background: rgba(127,127,127,.14); border-radius: 3px; height: 8px; }
  footer { color: var(--hint); font-size: 12px; border-top: 1px solid var(--border); padding-top: 16px; }
  footer a { color: inherit; }
</style>
</head>
<body>
<div class="wrap">
  <h1>accel-mirror · 国内加速源实测看板</h1>
  <p class="sub">数据来自 <code>references/mirrors.json</code>，分数按实测延迟计算 ——
    <code>score = 100 − 20 × log10(1 + 秒 / 0.1)</code>。 __STAMP__</p>
  <div class="stats" id="stats"></div>
  <div id="sections"></div>
  <section>
    <h2>分数分布</h2>
    <p class="cat-meta">全部活跃源按得分区间统计</p>
    <div class="dist" id="dist"></div>
  </section>
  <footer>
    分数是社区实测值（含单机实测），不同运营商与省份会有差异，请当作参考而非绝对排名。<br>
    数据会腐烂 —— 若 <b>last_full_test</b> 超过 7 天，请重新跑
    <code>bash scripts/test_mirrors.sh --type all</code>。<br>
    仓库：<a href="https://github.com/gitfox-enter/accel-mirror">github.com/gitfox-enter/accel-mirror</a>
  </footer>
</div>
<script>
const DATA = __DATA__;
const LABELS = __LABELS__;

function colorFor(score) {
  if (score >= 90) return 'var(--s1)';
  if (score >= 80) return 'var(--s2)';
  if (score >= 70) return 'var(--s3)';
  if (score >= 50) return 'var(--s5)';
  return 'var(--s4)';
}
function bgFor(score) {
  if (score >= 90) return 'rgba(15,110,86,.12)';
  if (score >= 80) return 'rgba(24,95,165,.12)';
  if (score >= 70) return 'rgba(133,79,11,.12)';
  if (score >= 50) return 'rgba(136,135,128,.14)';
  return 'rgba(163,45,45,.12)';
}
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

const mirrors = DATA.mirrors || {};
let all = [];
Object.keys(mirrors).forEach(c => mirrors[c].forEach(m => all.push(m)));
const active = all.filter(m => m.status !== 'deprecated');
const dead = all.length - active.length;
const avg = active.length ? Math.round(active.reduce((a, m) => a + (m.score || 0), 0) / active.length) : 0;

document.getElementById('stats').innerHTML = [
  ['镜像源总数', all.length],
  ['活跃', active.length],
  ['已弃用', dead],
  ['活跃源平均分', avg],
  ['最后全量实测', DATA.last_full_test || '—'],
  ['众包可信度', DATA.crowd
    ? (DATA.crowd.updated_mirrors || 0) + ' 源 / ' + (DATA.crowd.reports || 0) + ' 份上报'
    : '仅单机实测'],
].map(([k, v]) => '<div class="stat"><div class="k">' + k + '</div><div class="v">' + esc(v) + '</div></div>').join('');

const html = Object.keys(mirrors).map(cat => {
  const list = mirrors[cat].slice();
  const live = list.filter(m => m.status !== 'deprecated');
  list.sort((a, b) => {
    if ((a.status === 'deprecated') !== (b.status === 'deprecated')) return a.status === 'deprecated' ? 1 : -1;
    if ((b.score || 0) !== (a.score || 0)) return (b.score || 0) - (a.score || 0);
    return (a.test_time_ms || 1e9) - (b.test_time_ms || 1e9);
  });
  const rows = list.map(m => {
    const s = m.score || 0;
    const dead2 = m.status === 'deprecated' ? ' dead' : '';
    let ms = m.test_time_ms ? m.test_time_ms + ' ms' : '未实测';
    // 众包可信度信息：样本数 + 不稳定信号（既能成功也会失败的源）
    const crowd = [];
    if (m.samples) crowd.push(m.samples + ' 份样本');
    if (m.failed_reports) crowd.push('⚠ 失败 ' + m.failed_reports + ' 次');
    if (crowd.length) ms += ' · ' + crowd.join(' · ');
    return '<div class="row' + dead2 + '">' +
      '<div class="badge" style="color:' + colorFor(s) + ';background:' + bgFor(s) + '">' + s + '</div>' +
      '<div class="nm">' + esc(m.name) + '<span class="u">' + esc(m.url) + '</span></div>' +
      '<div class="ms">' + esc(ms) + '</div>' +
      '</div>';
  }).join('');
  return '<section><h2>' + esc(LABELS[cat] || cat) + '</h2>' +
    '<p class="cat-meta">' + live.length + ' / ' + list.length + ' 活跃</p>' +
    '<div class="list">' + rows + '</div></section>';
}).join('');
document.getElementById('sections').innerHTML = html;

const buckets = [
  ['95–100 极速', m => m.score >= 95],
  ['90–94 优秀', m => m.score >= 90 && m.score < 95],
  ['80–89 良好', m => m.score >= 80 && m.score < 90],
  ['70–79 可用', m => m.score >= 70 && m.score < 80],
  ['50–69 慢', m => m.score >= 50 && m.score < 70],
  ['0–49 不可用', m => m.score < 50],
];
const maxN = Math.max.apply(null, buckets.map(b => active.filter(b[1]).length).concat([1]));
document.getElementById('dist').innerHTML = buckets.map(b => {
  const n = active.filter(b[1]).length;
  const w = Math.round(n / maxN * 100);
  return '<div class="drow"><span>' + b[0] + '</span>' +
    '<span class="dtrack"><span class="bar" style="display:block;width:' + w + '%;background:' + colorFor(b[0].startsWith('0') ? 0 : b[0].startsWith('50') ? 50 : b[0].startsWith('70') ? 70 : b[0].startsWith('80') ? 80 : b[0].startsWith('90-94') ? 90 : 95) + '"></span></span>' +
    '<span style="text-align:right;color:var(--muted)">' + n + '</span></div>';
}).join('');
</script>
</body>
</html>
"""


def main():
    with io.open(DB, encoding="utf-8") as f:
        data = json.load(f)

    # 印章取自库内时间戳而非当前时间，保证「数据不变 → 输出不变」，
    # 这样 CI 重新生成时不会产生无意义的 diff（避免提交循环）。
    stamp = "数据版本 %s · 最后更新 %s · 最后全量实测 %s" % (
        data.get("version", "?"),
        data.get("last_updated") or "未知",
        data.get("last_full_test") or "未知",
    )
    html = TEMPLATE.replace("__STAMP__", stamp)
    html = html.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    html = html.replace("__LABELS__", json.dumps(CATEGORY_LABELS, ensure_ascii=False))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    total = sum(len(v) for v in data.get("mirrors", {}).values())
    print("wrote %s (%d bytes, %d mirrors, %d categories)" % (
        OUT, len(html.encode("utf-8")), total, len(data.get("mirrors", {}))))


if __name__ == "__main__":
    main()
