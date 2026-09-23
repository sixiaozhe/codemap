#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简 MCP (Model Context Protocol) stdio 服务: 把代码地图暴露成 AI 可调用的工具。

用法: mcp_server.py [--data codemap.ai.json]
在 VSCode / Claude Desktop 等 MCP 客户端里配置该命令即可。
消息为按行分隔的 JSON-RPC 2.0。
"""
import json
import os
import sys

DATA = './codemap.ai.json'
for i, a in enumerate(sys.argv):
    if a == '--data' and i + 1 < len(sys.argv):
        DATA = sys.argv[i + 1]
DATA = os.environ.get('CODEMAP_DATA', DATA)

_D = None


def load():
    global _D
    if _D is None:
        _D = json.load(open(DATA, encoding='utf-8'))
    return _D


def resolve(F, q):
    hits = [f[0] for f in F if f[2] == q] or \
           [f[0] for f in F if f[2].lower() == q.lower()] or \
           [f[0] for f in F if q.lower() in f[2].lower()]
    return hits[:30]


def overview():
    d = load(); m = d['meta']; h = d.get('health', {})
    files = d['files']
    n_cyc = len(d.get('cycles', []))
    return ('项目 %s · 模块 %d · 函数 %d · 调用边 %d\n'
            '平均CCN %s · 最高CCN %s · 调用环 %d 个 · 最长调用链 %d 层\n'
            '来源: cscope+词法+线程回调(启发式), 不含宏/函数指针/虚分派\n'
            '提示: 用 codemap_* 工具按需查询函数/模块/环/热点。'
            % (m.get('project'), m.get('files'), m.get('functions'), m.get('edges'),
               h.get('avg_ccn'), h.get('max_ccn'), n_cyc, len(d.get('longest_path', []))))


def find_symbol(q):
    d = load(); F, FILES = d['functions'], d['files']
    hits = resolve(F, q)
    if not hits:
        return '未找到符号: ' + q
    out = []
    for i in hits:
        f = F[i]
        out.append('%s  %s:%d  CCN=%d NLOC=%d 扇入=%d 扇出=%d%s'
                   % (f[2], FILES[f[1]]['s'], f[3], f[4], f[5], f[9], f[10],
                      ' [环]' if f[13] else ''))
    return '\n'.join(out)


def relations(q, direction):
    d = load(); F, FILES, E = d['functions'], d['files'], d['edges']
    hits = resolve(F, q)
    if not hits:
        return '未找到符号: ' + q
    rel = {}
    for a, b in E:
        key = a if direction == 'callees' else b
        rel.setdefault(key, []).append(b if direction == 'callees' else a)
    out = []
    for i in hits:
        out.append('%s (%s:%d):' % (F[i][2], FILES[F[i][1]]['s'], F[i][3]))
        for c in rel.get(i, []):
            out.append('  %s %s (%s:%d, CCN=%d)' % ('→' if direction == 'callees' else '←',
                       F[c][2], FILES[F[c][1]]['s'], F[c][3], F[c][4]))
        if not rel.get(i):
            out.append('  (无)')
    return '\n'.join(out)


def module(q):
    d = load(); F, FILES = d['functions'], d['files']
    ms = [m for m in FILES if m['s'] == q or q in m['p']]
    if not ms:
        return '未找到模块: ' + q
    out = []
    for m in ms[:5]:
        fi = FILES.index(m)
        fns = sorted([f for f in F if f[1] == fi], key=lambda x: -x[4])
        out.append('== %s (%s) ==' % (m['s'], m['p']))
        out.append('函数 %d · NLOC %d · 平均/最高CCN %s/%s · Ca/Ce %d/%d · I %s · 注释%% %s%s'
                   % (m['f'], m['n'], m['c'], m['x'], m['ca'], m['ce'], m['i'],
                      m.get('cmt', 0), ' · 位于调用环' if m.get('cyc') else ''))
        out.append('对外接口: ' + (', '.join('%s(CCN%d)' % (f[2], f[4])
                   for f in fns if f[16]) or '(无)'))
        out.append('函数: ' + ', '.join('%s(CCN%d)' % (f[2], f[4]) for f in fns[:15]))
    return '\n'.join(out)


def hotspots(limit=30):
    d = load(); F, FILES = d['functions'], d['files']
    out = []
    for i in sorted(range(len(F)), key=lambda k: -F[k][4])[:limit]:
        f = F[i]
        out.append('%s  %s:%d  CCN=%d NLOC=%d 扇入=%d 扇出=%d%s'
                   % (f[2], FILES[f[1]]['s'], f[3], f[4], f[5], f[9], f[10],
                      ' [环]' if f[13] else ''))
    return '\n'.join(out)


def cycles():
    d = load(); F = d['functions']
    cs = sorted(d.get('cycles', []), key=lambda c: -len(c))
    if not cs:
        return '没有调用环。'
    out = []
    for k, c in enumerate(cs):
        out.append('环 #%d (%d): %s%s' % (k + 1, len(c),
                   ', '.join(F[i][2] for i in c[:20]), ' …' if len(c) > 20 else ''))
    return '\n'.join(out)


TOOLS = [
    ('codemap_overview', '项目总览（规模/复杂度/环/来源）', {}),
    ('codemap_find_symbol', '按名查找函数（位置/CCN/扇入出）',
     {'name': {'type': 'string', 'description': '函数名（支持子串）'}}),
    ('codemap_callers', '谁调用了该函数',
     {'name': {'type': 'string', 'description': '函数名'}}),
    ('codemap_callees', '该函数调用了谁',
     {'name': {'type': 'string', 'description': '函数名'}}),
    ('codemap_module', '模块概览（函数/接口/耦合/注释率）',
     {'file': {'type': 'string', 'description': '模块标签或路径'}}),
    ('codemap_hotspots', '复杂度热点函数',
     {'limit': {'type': 'integer', 'description': '数量，默认30'}}),
    ('codemap_cycles', '调用环（强连通分量）', {}),
]


def call(name, args):
    args = args or {}
    if name == 'codemap_overview':
        return overview()
    if name == 'codemap_find_symbol':
        return find_symbol(args.get('name', ''))
    if name == 'codemap_callers':
        return relations(args.get('name', ''), 'callers')
    if name == 'codemap_callees':
        return relations(args.get('name', ''), 'callees')
    if name == 'codemap_module':
        return module(args.get('file', ''))
    if name == 'codemap_hotspots':
        return hotspots(int(args.get('limit', 30)))
    if name == 'codemap_cycles':
        return cycles()
    raise ValueError('unknown tool: ' + name)


def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get('method')
        mid = msg.get('id')
        if method == 'initialize':
            send({'jsonrpc': '2.0', 'id': mid, 'result': {
                'protocolVersion': (msg.get('params') or {}).get('protocolVersion', '2024-11-05'),
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'codemap', 'version': '1.0.0'}}})
        elif method == 'tools/list':
            send({'jsonrpc': '2.0', 'id': mid, 'result': {'tools': [
                {'name': t[0], 'description': t[1],
                 'inputSchema': {'type': 'object', 'properties': t[2]}} for t in TOOLS]}})
        elif method == 'tools/call':
            p = msg.get('params') or {}
            try:
                text = call(p.get('name'), p.get('arguments'))
                send({'jsonrpc': '2.0', 'id': mid, 'result': {
                    'content': [{'type': 'text', 'text': text}]}})
            except Exception as e:  # noqa
                send({'jsonrpc': '2.0', 'id': mid, 'result': {
                    'content': [{'type': 'text', 'text': '错误: %s' % e}], 'isError': True}})
        elif method == 'ping':
            send({'jsonrpc': '2.0', 'id': mid, 'result': {}})
        elif mid is not None:      # 请求且未知方法
            send({'jsonrpc': '2.0', 'id': mid,
                  'error': {'code': -32601, 'message': 'method not found: %s' % method}})
        # 通知(id 为 None) 不回复


if __name__ == '__main__':
    main()
