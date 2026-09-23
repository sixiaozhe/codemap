#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 codemap.ai.json 做按需查询, 供人或 AI 使用(避免加载整张图)。

用法: query.py <spec> [--data codemap.ai.json]
spec:
  callers:<名>   谁调用了它
  callees:<名>   它调用了谁
  def:<名>       定义位置
  module:<文件>  模块概览
  hotspots[:N]   复杂度热点
  cycles         调用环
  search:<子串>  按名搜索
  files          模块列表
"""
import json
import os
import sys


def load(path):
    d = json.load(open(path, encoding='utf-8'))
    return d


def main():
    argv = sys.argv[1:]
    path = './codemap.ai.json'
    if '--data' in argv:
        i = argv.index('--data')
        path = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        sys.stderr.write(__doc__)
        return 2
    spec = argv[0]
    if not os.path.isfile(path):
        sys.stderr.write('找不到数据文件: %s（先生成 codemap，或 --data 指定）\n' % path)
        return 1
    d = load(path)
    F, FILES, E = d['functions'], d['files'], d['edges']
    name = lambda i: F[i][2]
    loc = lambda i: '%s:%d' % (FILES[F[i][1]]['s'], F[i][3])
    adj, radj = {}, {}
    for a, b in E:
        adj.setdefault(a, []).append(b)
        radj.setdefault(b, []).append(a)

    def resolve(q):
        hits = [f[0] for f in F if f[2] == q]
        if not hits:
            hits = [f[0] for f in F if f[2].lower() == q.lower()]
        if not hits:
            hits = [f[0] for f in F if q.lower() in f[2].lower()]
        return hits[:30]

    def line(i):
        f = F[i]
        return '%-34s %-24s CCN=%-4d 扇入=%-3d 扇出=%-3d%s' % (
            f[2], loc(i), f[4], f[9], f[10], '  [环]' if f[13] else '')

    kind, _, q = spec.partition(':')
    out = None
    if kind == 'callers':
        hits = resolve(q)
        if not hits:
            print('未找到函数:', q); return 1
        print('谁调用了 %s：' % q)
        for i in hits:
            print('— %s (%s)' % (name(i), loc(i)))
            for c in radj.get(i, []):
                print('   ←', line(c))
    elif kind == 'callees':
        hits = resolve(q)
        if not hits:
            print('未找到函数:', q); return 1
        print('%s 调用了谁：' % q)
        for i in hits:
            print('— %s (%s)' % (name(i), loc(i)))
            for c in adj.get(i, []):
                print('   →', line(c))
    elif kind == 'def':
        hits = resolve(q)
        print('\n'.join(loc(i) for i in hits) if hits else '未找到函数: ' + q)
    elif kind == 'module':
        matches = [m for m in FILES if m['s'] == q or q in m['p']]
        if not matches:
            print('未找到模块:', q); return 1
        for m in matches[:5]:
            fi = FILES.index(m)
            fns = sorted([f for f in F if f[1] == fi], key=lambda x: -x[4])
            print('== %s (%s) ==' % (m['s'], m['p']))
            print('函数 %d · NLOC %d · 平均/最高CCN %s/%s · Ca/Ce %d/%d · I %s · 注释%% %s%s' % (
                m['f'], m['n'], m['c'], m['x'], m['ca'], m['ce'], m['i'],
                m.get('cmt', 0), ' · 位于调用环' if m.get('cyc') else ''))
            ext = [f for f in fns if f[16]]
            print('对外接口:', ', '.join('%s(CCN%d)' % (f[2], f[4]) for f in ext[:12]) or '(无)')
            print('函数:', ', '.join('%s(CCN%d)' % (f[2], f[4]) for f in fns[:15]))
    elif kind == 'hotspots':
        n = int(q) if q.isdigit() else 30
        print('复杂度热点 Top %d：' % n)
        for i in sorted(range(len(F)), key=lambda k: -F[k][4])[:n]:
            print(' ', line(i))
    elif kind == 'cycles':
        cs = sorted(d.get('cycles', []), key=lambda c: -len(c))
        print('调用环 %d 个：' % len(cs))
        for k, c in enumerate(cs):
            print(' 环 #%d (%d): %s%s' % (k + 1, len(c),
                  ', '.join(name(i) for i in c[:20]), ' …' if len(c) > 20 else ''))
    elif kind == 'search':
        hits = [f[0] for f in F if q.lower() in f[2].lower()][:50]
        print('\n'.join(line(i) for i in hits) if hits else '无匹配: ' + q)
    elif kind == 'files':
        for m in sorted(FILES, key=lambda x: -x['f']):
            print('%-24s 函数=%-4d NLOC=%-6d CCNavg=%-5s Ca/Ce=%d/%d' % (
                m['s'], m['f'], m['n'], m['c'], m['ca'], m['ce']))
    else:
        sys.stderr.write('未知查询: %s\n' % spec)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
