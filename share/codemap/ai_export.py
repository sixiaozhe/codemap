#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data.json 导出为面向 AI 的紧凑摘要:
  <base>.ai.json  —— 机器可读(供 query.py / MCP 使用)
  <base>.ai.md    —— LLM 可读的 Markdown 概览(控制体量)

用法: ai_export.py <data.json> <out_base> [top_n]
"""
import json
import os
import sys
import time

TOP = int(sys.argv[3]) if len(sys.argv) > 3 else 50


def main():
    data = json.load(open(sys.argv[1], encoding='utf-8'))
    base = sys.argv[2]
    F, FILES, E = data['functions'], data['files'], data['edges']
    H = data.get('health', {})
    N = len(F)

    # 紧凑函数表: [id,fileIdx,name,line,ccn,nloc,param,token,len,fanin,fanout,depth,sub,cyc,static,exp,mi,nd]
    fns = [[f[0], f[1], f[2], f[9], f[4], f[5], f[6], f[7], f[8],
            f[11], f[12], f[13], f[14], f[15], f[24], f[19],
            f[27], f[26]] for f in F]
    fil = [{'p': m['path'], 's': m['label'], 'f': m['funcs'], 'n': m['nloc'],
            'c': m['avg_ccn'], 'x': m['max_ccn'], 'ca': m['ca'], 'ce': m['ce'],
            'i': m['instability'], 'cyc': 1 if m['in_cycle'] else 0,
            'ifx': m.get('iface_ext', 0), 'ifn': m.get('iface_int', 0),
            'ifu': m.get('iface_unused', 0), 'cmt': m.get('comment_ratio', 0)}
           for m in FILES]

    hotspots = [f[0] for f in sorted(F, key=lambda x: -x[4])[:TOP]]
    cycles = sorted(data.get('cycles', []), key=lambda c: -len(c))
    cyc_out = [c[:30] for c in cycles[:30]]
    src = {'edges': len(E),
           'spawn': len(data.get('spawn_edges', [])),
           'heuristic': len(data.get('heur_edges', []))}
    out = {
        'meta': {
            'project': data['meta'].get('project', ''),
            'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
            'files': len(FILES), 'functions': N, 'edges': len(E),
            'tools': {'lizard': data['meta'].get('lizard', ''),
                      'cscope': data['meta'].get('cscope', '')},
            'sources': src,
            'note': '调用关系为启发式(cscope+词法解析+线程/回调); 不含宏展开、函数指针、虚函数分派',
        },
        'files': fil,
        'functions': fns,
        'edges': data['edges'],
        'cycles': cyc_out,
        'hotspots': hotspots,
        'longest_path': data.get('longest_path', []),
    }
    jpath = base + '.ai.json'
    with open(jpath, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(',', ':'))

    def fq(i):
        f = F[i]
        return '%s@%s:%d' % (f[2], FILES[f[1]]['label'], f[9])

    L = []
    m = out['meta']
    L.append('# 代码地图 · AI 摘要 · %s' % (m['project'] or '(project)'))
    L.append('')
    L.append('> 生成 %s · 模块 %d · 函数 %d · 调用边 %d（线程/回调 %d，启发式 %d）'
             % (m['generated'], m['files'], m['functions'], m['edges'],
                src['spawn'], src['heuristic']))
    L.append('> 调用关系为**启发式**（cscope + 词法解析 + 线程/回调），不含宏展开/函数指针/虚函数分派；需结合源码复核。')
    L.append('')
    L.append('## 概览')
    L.append('- 平均CCN %s · 最高CCN %s · 复杂热点(>%s) %s' %
             (H.get('avg_ccn'), H.get('max_ccn'), data.get('meta', {}).get('ccn_thresh', 15),
              H.get('hotspots')))
    L.append('- 调用环 %s 个 · 最深调用 %s 层 · 模块间调用占比 %s%%' %
             (H.get('cycles'), H.get('deepest'),
              round(100.0 * H.get('inter_edges', 0) / max(1, H.get('edges', 1)))))
    L.append('')

    L.append('## 热点函数（CCN 最高，Top %d）' % min(TOP, len(F)))
    L.append('| 函数 | 位置 | CCN | NLOC | 扇入/扇出 | 深度 | 环 |')
    L.append('|---|---|---|---|---|---|---|')
    for i in hotspots:
        f = F[i]
        L.append('| %s | %s:%d | %d | %d | %d/%d | %d | %s |' % (
            f[2], FILES[f[1]]['label'], f[9], f[4], f[5], f[11], f[12], f[13],
            '是' if f[15] else ''))
    L.append('')

    L.append('## 模块（按函数数）')
    L.append('| 模块 | 函数 | NLOC | 平均/最高CCN | Ca/Ce/I | 对外/泄漏/未接入接口 | 环 |')
    L.append('|---|---|---|---|---|---|---|')
    for mo in sorted(FILES, key=lambda x: -x['funcs'])[:40]:
        L.append('| %s | %d | %d | %s/%s | %d/%d/%s | %d/%d/%d | %s |' % (
            mo['label'], mo['funcs'], mo['nloc'], mo['avg_ccn'], mo['max_ccn'],
            mo['ca'], mo['ce'], mo['instability'], mo.get('iface_ext', 0),
            mo.get('iface_int', 0), mo.get('iface_unused', 0),
            '是' if mo['in_cycle'] else ''))
    L.append('')

    if cycles:
        L.append('## 调用环（强连通分量，互调/递归）')
        for k, c in enumerate(cycles[:15]):
            names = [F[i][2] for i in c[:20]]
            L.append('- 环 #%d（%d 个）：%s%s' % (k + 1, len(c), ', '.join(names),
                                                ' …' if len(c) > 20 else ''))
        L.append('')

    lp = data.get('longest_path', [])
    if lp:
        L.append('## 最长调用链（%d 层）' % len(lp))
        L.append(' → '.join(F[i][2] for i in lp))
        L.append('')

    L.append('## 各模块公开接口（对外 Top 8）')
    for mo in sorted(FILES, key=lambda x: -x.get('iface_ext', 0))[:20]:
        ext = [f for f in F if f[1] == FILES.index(mo) and f[21] > 0]
        ext = sorted(ext, key=lambda x: -x[21])[:8]
        if ext:
            L.append('- **%s**: %s' % (mo['label'],
                     ', '.join('%s(CCN%d)' % (f[2], f[4]) for f in ext)))
    L.append('')

    hyg = data.get('hygiene', {})
    dup = data.get('dup_rate', {})
    L.append('## 卫生 / 重复')
    L.append('- 重复率 %s · 重复块 %d · 缺 include 守卫 %d · include 环 %d · TODO %d · 超长行 %d'
             % (dup.get('dup', '0%'), len(data.get('dup_blocks', [])),
                len(hyg.get('missing_guard', [])), len(hyg.get('include_cycles', [])),
                len(hyg.get('todo', [])), len(hyg.get('long_lines', []))))
    L.append('')
    L.append('## 按需查询')
    L.append('```')
    L.append('codemap query callers:<函数>   # 谁调用它')
    L.append('codemap query callees:<函数>   # 它调用了谁')
    L.append('codemap query def:<函数>       # 定义位置')
    L.append('codemap query module:<文件>    # 模块概览')
    L.append('codemap query hotspots[:N]     # 复杂度热点')
    L.append('codemap query cycles           # 调用环')
    L.append('codemap query search:<子串>    # 按名搜索')
    L.append('```')

    with open(base + '.ai.md', 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    sys.stderr.write('AI 摘要: %s.ai.json / %s.ai.md\n' % (base, base))


if __name__ == '__main__':
    main()
