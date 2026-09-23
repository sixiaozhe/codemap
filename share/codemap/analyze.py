#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代码地图分析器
用 lizard 取复杂度指标, 用 cscope 取符号调用关系, 计算:
  - 模块(文件)依赖矩阵: 调用矩阵 + include 矩阵
  - 符号调用图, 扇入/扇出
  - 调用深度(最长调用链, SCC 缩点后 DAG 上的最长路径)
  - 循环依赖(强连通分量)
  - 健康度评分
输出 data.json, 供模板生成自包含 HTML。

用法: python3 analyze.py <项目目录> <lizard.csv> <cscope二进制> <输出data.json>
"""
import csv
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict, Counter

sys.setrecursionlimit(100000)

# ---------------------------------------------------------------- 数据结构

class Func(object):
    def __init__(self, fid, file, name, long_name, ccn, nloc, params, token,
                 length, start, end):
        self.id = fid
        self.file = file
        self.name = name
        self.long_name = long_name
        self.ccn = ccn
        self.nloc = nloc
        self.params = params
        self.token = token
        self.length = length
        self.start = start
        self.end = end
        self.fan_in = 0
        self.fan_out = 0
        self.depth = 0          # 从根到它的最长调用深度(边数)
        self.subtree_depth = 0  # 从它往下最长调用链(边数)
        self.scc = -1
        self.in_cycle = False
        self.hvol = 0.0        # Halstead volume
        self.nd = 0            # 最大嵌套深度
        self.mi = -1.0         # 维护性指数(未知为 -1)
        self.is_static = False


def canon(p):
    """规范化路径: 统一分隔符、折叠 . 和 //、去掉前导 ./。"""
    p = os.path.normpath(p.replace('\\', '/')).replace('\\', '/')
    while p.startswith('./'):
        p = p[2:]
    return p


def norm_path(p, root):
    """把 lizard 输出的文件路径归一化成相对项目根目录, 且与 cscope/discover_files 一致。
    兼容三种输入: 绝对路径、相对 cwd 且带项目前缀(如 CommLib/.../anrLib/xxx.c)、
    已经相对项目根(如 xxx.c)。"""
    p = p.replace('\\', '/')
    root = os.path.abspath(root).replace('\\', '/')
    if p == root:
        return canon(os.path.basename(root))
    if p.startswith(root + '/'):
        return canon(p[len(root) + 1:])
    # 项目相对 cwd 的前缀, 如 CommLib/sysmaintenance/spare/src/anrLib
    try:
        rel = os.path.relpath(root, os.getcwd()).replace('\\', '/')
    except ValueError:
        rel = None
    if rel and not rel.startswith('..'):
        for pref in (rel + '/', './' + rel + '/'):
            if p.startswith(pref):
                return canon(p[len(pref):])
    base = os.path.basename(root) + '/'
    for pref in (base, './'):
        if p.startswith(pref):
            p = p[len(pref):]
    return canon(p)


def is_false_expr(expr):
    """判断 #if 的表达式是否是字面 0 (即 #if 0 这类被注释掉的代码)。"""
    s = re.sub(r'/\*.*?\*/', '', expr, flags=re.S)
    s = s.split('//')[0].strip()
    while len(s) >= 2 and s[0] == '(' and s[-1] == ')':
        s = s[1:-1].strip()
    s = re.sub(r'[uUlL]', '', s).strip()
    return re.fullmatch(r'0[xX]0*|0+', s) is not None


_DIR_RE = re.compile(r'^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)$')


def active_lines(text):
    """逐行判断是否处于"有效编译"分支; #if 0 / #if (0) 的块及其嵌套视为无效。
    未知条件(如 #ifdef X)按有效处理, 避免误删。返回布尔列表(与行对应)。"""
    lines = text.split('\n')
    active = [True] * len(lines)
    stack = []          # {'parent': bool, 'taken': bool}
    cur = True
    for i, ln in enumerate(lines):
        m = _DIR_RE.match(ln)
        if m:
            kw, rest = m.group(1), m.group(2)
            if kw in ('if', 'ifdef', 'ifndef'):
                parent = cur
                if kw == 'if' and is_false_expr(rest):
                    branch, taken = False, False
                else:
                    branch, taken = True, True
                stack.append({'parent': parent, 'taken': taken})
                cur = parent and branch
            elif kw == 'elif':
                if stack:
                    f = stack[-1]
                    if f['parent'] and not f['taken']:
                        if is_false_expr(rest):
                            branch = False
                        else:
                            branch = True
                            f['taken'] = True
                    else:
                        branch = False
                    cur = f['parent'] and branch
            elif kw == 'else':
                if stack:
                    f = stack[-1]
                    cur = f['parent'] and not f['taken']
                    f['taken'] = True
            elif kw == 'endif':
                f = stack.pop() if stack else None
                cur = f['parent'] if f else True
        active[i] = cur
    return active


_ACTIVE_CACHE = {}


def get_active(fp, root):
    if fp not in _ACTIVE_CACHE:
        try:
            raw = open(os.path.join(root, fp), encoding='utf-8',
                       errors='replace').read()
        except IOError:
            raw = ''
        _ACTIVE_CACHE[fp] = active_lines(raw)
    return _ACTIVE_CACHE[fp]


def mark_static(funcs, root):
    """标记函数是否为 static(内部链接)。扫定义处签名区域里的 static 关键字。"""
    cache = {}

    def text_of(fp):
        if fp not in cache:
            try:
                raw = open(os.path.join(root, fp), encoding='utf-8',
                           errors='replace').read()
            except IOError:
                raw = ''
            cache[fp] = strip_comments_strings(raw).split('\n')
        return cache[fp]

    for f in funcs:
        lines = text_of(f.file)
        lo = max(0, f.start - 1 - 2)
        buf = []
        for i in range(f.start - 1, min(len(lines), f.start - 1 + 6)):
            buf.append(lines[i])
            if '{' in lines[i]:
                break
        seg = '\n'.join(lines[lo:f.start - 1] + buf)
        f.is_static = re.search(r'\bstatic\b', seg) is not None
    return funcs


def parse_duplicates(path):
    """解析 `lizard -Eduplicate` 的输出: 重复块(每块含多段 file:start~end)与重复率。"""
    blocks, rates = [], {}
    if not path or not os.path.isfile(path):
        return blocks, rates
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except IOError:
        return blocks, rates
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('Duplicate block'):
            if cur:
                blocks.append(cur)
            cur = []
        elif cur is not None and ' ~ ' in line and ':' in line:
            f, rest = line.rsplit(':', 1)
            parts = rest.split('~')
            try:
                cur.append([f.strip(), int(parts[0]), int(parts[1])])
            except ValueError:
                pass
        elif line.startswith('Total duplicate rate'):
            rates['dup'] = line.split(':', 1)[1].strip()
        elif line.startswith('Total unique rate'):
            rates['uniq'] = line.split(':', 1)[1].strip()
        elif not line and cur:
            blocks.append(cur)
            cur = None
    if cur:
        blocks.append(cur)
    return blocks, rates


def find_cycles(nodes, edges):
    """有向图 SCC(迭代 Kosaraju), 返回 size>1 的分量(节点名列表)。"""
    idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)
    adj = [[] for _ in range(n)]
    radj = [[] for _ in range(n)]
    for a, b in edges:
        if a in idx and b in idx:
            adj[idx[a]].append(idx[b])
            radj[idx[b]].append(idx[a])
    seen = [False] * n
    order = []
    for st0 in range(n):
        if seen[st0]:
            continue
        st = [(st0, 0)]
        seen[st0] = True
        while st:
            v, pi = st[-1]
            if pi < len(adj[v]):
                w = adj[v][pi]
                st[-1] = (v, pi + 1)
                if not seen[w]:
                    seen[w] = True
                    st.append((w, 0))
            else:
                order.append(v)
                st.pop()
    comp = [-1] * n
    comps = []
    for s0 in reversed(order):
        if comp[s0] >= 0:
            continue
        cid = len(comps)
        st = [s0]
        comp[s0] = cid
        c = [s0]
        while st:
            v = st.pop()
            for w in radj[v]:
                if comp[w] < 0:
                    comp[w] = cid
                    st.append(w)
                    c.append(w)
        comps.append(c)
    return [[nodes[i] for i in c] for c in comps if len(c) > 1]


def hygiene_scan(files, root, inc_edges):
    """注释率/魔法数字(每文件) + TODO/超长行/重复include/缺守卫/include环。"""
    per_file = {}
    todo, long_lines, dup_includes, missing_guard = [], [], [], []
    todo_re = re.compile(r'\b(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)')
    magic_re = re.compile(r'(?<![\w.])(\d{2,}|0[xX][0-9a-fA-F]{2,})(?![\w.])')
    inc_re = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]')
    for fp in files:
        try:
            text = open(os.path.join(root, fp), encoding='utf-8',
                        errors='replace').read()
        except IOError:
            continue
        lines = text.split('\n')
        ncode = ncomment = magic = 0
        in_block = False
        seen_inc = set()
        for i, ln in enumerate(lines, 1):
            s = ln.strip()
            is_c = False
            if in_block:
                is_c = True
                if '*/' in ln:
                    in_block = False
            elif s.startswith('//'):
                is_c = True
            elif s.startswith('/*'):
                is_c = True
                if '*/' not in s:
                    in_block = True
            if is_c:
                ncomment += 1
            else:
                ncode += 1
            m = todo_re.search(ln)
            if m:
                todo.append([fp, i, m.group(1), m.group(2).strip()[:80]])
            if len(ln) > 120:
                long_lines.append([fp, i, len(ln)])
            mi = inc_re.match(ln)
            if mi:
                h = mi.group(1)
                if h in seen_inc:
                    dup_includes.append([fp, h])
                seen_inc.add(h)
            if not s.startswith('#'):
                magic += len(magic_re.findall(ln))
        per_file[fp] = {'comment_ratio': round(100.0 * ncomment / max(1, ncode + ncomment), 1),
                        'magic': magic}
        if fp.endswith('.h'):
            head = '\n'.join(lines[:40])
            if '#pragma once' not in head:
                mg = re.search(r'#\s*ifndef\s+(\w+)', head)
                if not (mg and re.search(r'#\s*define\s+' + re.escape(mg.group(1)) + r'\b', head)):
                    missing_guard.append(fp)
    return per_file, {'todo': todo, 'long_lines': long_lines,
                      'dup_includes': dup_includes, 'missing_guard': missing_guard,
                      'include_cycles': find_cycles(files, inc_edges)}


def module_labels(files):
    """给每个模块一个显示名; 同名时用最短唯一后缀区分, 避免矩阵出现"重复行列"。"""
    from collections import Counter
    cnt = Counter(os.path.basename(p) for p in files)
    labels = {}
    for p in files:
        base = os.path.basename(p)
        if cnt[base] == 1:
            labels[p] = base
            continue
        parts = p.split('/')
        lab = p
        for k in range(2, len(parts) + 1):
            suf = '/'.join(parts[-k:])
            if sum(1 for q in files if '/'.join(q.split('/')[-k:]) == suf) == 1:
                lab = suf
                break
        labels[p] = lab
    return labels


def load_lizard(csv_path, root):
    funcs = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        for i, row in enumerate(csv.reader(f)):
            if len(row) < 11:
                continue
            nloc, ccn, token, param, length = (int(row[0]), int(row[1]),
                                               int(row[2]), int(row[3]),
                                               int(row[4]))
            file = norm_path(row[6], root)
            name = row[7]
            long_name = row[8]
            start, end = int(row[9]), int(row[10])
            hvol, nd = 0.0, 0
            if len(row) >= 15:
                try:
                    hvol = float(row[11])
                    nd = int(float(row[14]))
                except ValueError:
                    pass
            f = Func(i, file, name, long_name, ccn, nloc, param,
                     token, length, start, end)
            f.hvol = hvol
            f.nd = nd
            funcs.append(f)
    for f in funcs:      # 维护性指数 MI (需要 Halstead volume)
        if f.hvol > 0:
            V, G, L = f.hvol, max(1, f.ccn), max(1, f.nloc)
            f.mi = max(0.0, (171.0 - 5.2 * math.log(V) - 0.23 * G
                             - 16.2 * math.log(L)) * 100.0 / 171.0)
    return funcs


# ---------------------------------------------------------------- cscope 抽边

LINE_RE = re.compile(r'^(\S+)\s+(\S+)\s+(\d+)\s+(.*)$')


def cscope_callees(cscope, db, name):
    """返回 (文件, 被调函数名, 行号) 列表。cscope -2 name = name 调用了哪些函数。"""
    try:
        out = subprocess.run([cscope, '-d', '-f', db, '-L', '-2', name],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=30).stdout.decode('utf-8', 'replace')
    except Exception:
        return []
    res = []
    for line in out.splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        f, callee, ln = m.group(1), m.group(2), int(m.group(3))
        if callee in ('<global>', '<unknown>') or f == '<unknown>':
            continue
        res.append((f.replace('\\', '/'), callee, ln))
    return res


# ------------------------------------------------- 线程/回调等间接调用

# 线程/回调等间接调用的 API 表: 名称 -> 入口函数的参数序号(0 起);
# -1 表示未知, 自动扫描所有参数, 命中的项目内函数都算依赖。
DEFAULT_SPAWN = {
    'pthread_create': 2, 'thrd_create': 1,
    'CreateThread': 2, '_beginthreadex': 2, 'CreateRemoteThread': 3,
    'signal': 1, 'atexit': 0,
    # 平台/项目特有(签名未知时用 -1 自动识别):
    'pthreadSpawn': -1, 'pthreadSpawn_ex': -1,
    'HPR_ThreadDetached_Create': -1, 'HPR_Thread_Create': -1,
}


def load_spawn_table(root):
    """合并内置线程 API 表与配置文件(spawn.conf):
       每行  '名称 [参数序号]',  # 注释; 序号省略或 -1 表示自动扫描参数。"""
    table = dict(DEFAULT_SPAWN)
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, 'spawn.conf'), os.path.join(root, 'spawn.conf')):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    line = line.split('#')[0].strip()
                    if not line:
                        continue
                    parts = line.replace(',', ' ').split()
                    if not parts:
                        continue
                    idx = -1
                    if len(parts) > 1 and parts[1].lstrip('-').isdigit():
                        idx = int(parts[1])
                    table[parts[0]] = idx
        except IOError:
            pass
    return table
_CALL_RE = re.compile(r'([A-Za-z_]\w*)\s*\(')
# std::thread / boost::thread 变量声明式: std::thread t(worker)
_THREAD_DECL = re.compile(
    r'(?:std|boost)::j?thread\s*(?:<[^>]*>)?\s*(?:[A-Za-z_]\w*\s*)?\(\s*&?\s*([A-Za-z_]\w*)')
_ASYNC_RE = re.compile(
    r'std::async\s*\(\s*(?:std::launch::\w+\s*,\s*)?&?\s*([A-Za-z_]\w*)')


def _iter_calls(text):
    n = len(text)
    for m in _CALL_RE.finditer(text):
        i, depth = m.end(), 1
        while i < n and depth:
            c = text[i]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
            i += 1
        if depth:
            continue
        yield m.group(1), text[m.end():i - 1], m.start()


def _split_args(s):
    out, depth, cur = [], 0, ''
    for c in s:
        if c in '([{':
            depth += 1
        elif c in ')]}':
            depth -= 1
        if c == ',' and depth == 0:
            out.append(cur)
            cur = ''
        else:
            cur += c
    if cur.strip():
        out.append(cur)
    return out


_KW = {'if', 'for', 'while', 'switch', 'return', 'sizeof', 'do', 'else',
       'case', 'goto', 'typedef', 'struct', 'union', 'enum'}


def strip_comments_strings(text):
    """去掉注释和字符串/字符字面量(保留换行), 便于可靠地做括号配对。"""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '/' and i + 1 < n and text[i + 1] == '/':
            while i < n and text[i] != '\n':
                i += 1
        elif c == '/' and i + 1 < n and text[i + 1] == '*':
            i += 2
            while i < n and not (text[i] == '*' and i + 1 < n and text[i + 1] == '/'):
                if text[i] == '\n':
                    out.append('\n')
                i += 1
            i += 2
        elif c in '"\'':
            q, i = c, i + 1
            while i < n and text[i] != q:
                if text[i] == '\\':
                    i += 1
                if i < n and text[i] == '\n':
                    out.append('\n')
                i += 1
            i += 1
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def brace_functions(text):
    """不依赖 lizard, 用大括号配对粗略找出函数定义 (start,end,name)。"""
    lines = text.split('\n')
    depth = 0
    cur = None
    funcs = []
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith('#'):          # 预处理行不计入括号结构
            continue
        if depth == 0 and cur is None:
            if s and ('{' in ln or (';' not in ln and '=' not in ln)):
                m = re.search(r'\b([A-Za-z_]\w*)\s*\(', ln)
                if m and m.group(1) not in _KW:
                    cur = [i, None, m.group(1)]
        prev = depth
        depth += ln.count('{') - ln.count('}')
        if cur is not None and cur[1] is None:
            if depth == 0 and '{' in ln and '}' in ln:   # 单行函数体 { ... }
                funcs.append((i, i, cur[2]))
                cur = None
                depth = 0
                continue
            if prev == 0 and depth > 0:
                cur[0] = i
        if cur is not None and depth <= 0 and prev > 0:
            cur[1] = i
            funcs.append((cur[0], cur[1], cur[2]))
            cur = None
            depth = 0
    if cur is not None:
        funcs.append((cur[0], len(lines), cur[2]))
    return funcs


def detect_spawn_edges(funcs, files, root):
    """识别 pthread_create/std::thread/CreateThread/signal 等间接调用,
    返回 [(caller_id, callee_id, 调用名), ...]。
    设环境变量 CODEMAP_DEBUG=1 会打印每个命中点的判定过程, 便于排查漏报。"""
    import bisect
    DEBUG = bool(os.environ.get('CODEMAP_DEBUG'))
    by_name = defaultdict(list)
    by_file_name = defaultdict(list)
    for f in funcs:
        by_name[f.name].append(f)
        by_file_name[(f.file, f.name)].append(f)

    def resolve(name, file):
        c = by_name.get(name)
        if not c:
            return None
        if len(c) == 1:
            return c[0]
        s = by_file_name.get((file, name))
        return s[0] if s else c[0]

    ranges = defaultdict(list)
    for f in funcs:
        ranges[f.file].append((f.start, f.end, f.id))
    for k in ranges:
        ranges[k].sort()

    def caller_of(fp, line):
        # 只认"行号精确落在函数范围内"的调用者, 避免把全局/宏里的调用误算到别的函数
        best = None
        for (s, e, fid) in ranges.get(fp, ()):
            if s <= line <= e and (best is None or s > best[0]):
                best = (s, fid)
        return (best[1], True) if best else (None, False)

    table = load_spawn_table(root)
    if DEBUG:
        sys.stderr.write('  [spawn] 线程API表(%d): %s\n'
                         % (len(table), ', '.join(sorted(table))))
    result = []
    hits = Counter()
    scanned = 0
    for fp in files:
        try:
            text = open(os.path.join(root, fp), encoding='utf-8',
                        errors='replace').read()
        except IOError:
            continue
        scanned += 1
        if '(' not in text:
            continue
        nl = [i for i, ch in enumerate(text) if ch == '\n']
        cands = []          # (调用名, 参数文本, 位置)
        for name, args, pos in _iter_calls(text):
            if name in table:
                a = _split_args(args)
                idx = table[name]
                if idx >= 0:
                    if len(a) > idx:
                        cands.append((name, a[idx], pos))
                else:                       # 签名未知: 扫描所有参数
                    for arg in a:
                        cands.append((name, arg, pos))
            elif name == 'async' and re.search(r'std::\s*$', text[max(0, pos - 14):pos]):
                a = _split_args(args)
                if a:
                    arg = a[1] if (len(a) > 1 and a[0].strip().startswith('std::launch')) else a[0]
                    cands.append(('std::async', arg, pos))
        for m in _THREAD_DECL.finditer(text):
            cands.append(('std::thread', m.group(1), m.start()))
        for m in _ASYNC_RE.finditer(text):
            cands.append(('std::async', m.group(1), m.start()))
        if cands and DEBUG and fp not in ranges:
            same = [k for k in ranges if os.path.basename(k) == os.path.basename(fp)]
            if same:
                sys.stderr.write('  [spawn] 注意: %s 无函数记录, 但存在同名的其它键 %s (路径不一致)\n'
                                 % (fp, same))
            else:
                sys.stderr.write('  [spawn] 注意: %s 未解析出任何函数(lizard 跳过了该文件)\n' % fp)
        bfuncs = brace_functions(strip_comments_strings(text)) if cands else []
        act = get_active(fp, root)
        for kind, arg, pos in cands:
            line = bisect.bisect_left(nl, pos) + 1
            hits[kind] += 1
            if not (0 < line <= len(act) and act[line - 1]):
                continue                  # #if 0 里的调用
            mm = re.match(r'^\s*&?\s*(?:\([^()]*\)\s*)*([A-Za-z_]\w*)\s*$', arg)
            if not mm:
                if DEBUG:
                    sys.stderr.write('  [spawn] %s:%d %s 参数非纯函数名: %r\n'
                                     % (fp, line, kind, arg.strip()[:60]))
                continue
            callee = mm.group(1)
            caller, exact = caller_of(fp, line)
            if caller is None:          # 兜底: 用大括号配对定位所在函数
                bname = None
                for (s, e, nm) in bfuncs:
                    if s <= line <= e:
                        bname = nm
                        break
                if bname:
                    c = by_file_name.get((fp, bname)) or by_name.get(bname)
                    if c:
                        caller, exact = c[0], False
            if caller is None:
                if DEBUG:
                    sys.stderr.write('  [spawn] %s:%d %s -> %s  X 未找到所在函数'
                                     '(该函数未被 lizard 识别)\n' % (fp, line, kind, callee))
                continue
            tgt = resolve(callee, fp)
            if tgt is None:
                if DEBUG:
                    sys.stderr.write('  [spawn] %s:%d %s -> %s  X 目标不在函数集'
                                     '(lizard 未识别或文件未扫描)\n' % (fp, line, kind, callee))
                continue
            if tgt.id == caller:
                continue
            if DEBUG:
                sys.stderr.write('  [spawn] %s:%d %s -> %s  OK%s\n'
                                 % (fp, line, kind, callee, '' if exact else ' (括号法定位调用者)'))
            result.append((caller, tgt.id, kind))
    if DEBUG:
        sys.stderr.write('  [spawn] 已扫描文件 %d/%d 个; 命中线程API: %s\n'
                         % (scanned, len(files), dict(hits) or '无'))
    return result


_CALLQ_RE = re.compile(r'((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*\(')
_CALL_KW = set('''if for while switch return sizeof do else case goto catch new delete
throw static_cast dynamic_cast const_cast reinterpret_cast decltype alignof noexcept
typeid and or not xor defined break continue default try typedef namespace class struct
template operator this __attribute__ __extension__ __declspec __asm asm'''.split())


def builtin_calls(funcs, files, root):
    """不依赖 cscope 的调用抽取: 用 lizard 给出的函数范围 + 词法扫描。
    支持 C++: 类外定义、类内联方法、限定名 Class::method/ns::func。"""
    by_full = defaultdict(list)
    by_seg = defaultdict(list)
    for f in funcs:
        by_full[f.name].append(f)
        by_seg[f.name.split('::')[-1]].append(f)

    cache = {}

    def get(fp):
        if fp not in cache:
            try:
                raw = open(os.path.join(root, fp), encoding='utf-8',
                           errors='replace').read()
            except IOError:
                raw = ''
            st = strip_comments_strings(raw)
            offs = [0]
            for i, ch in enumerate(st):
                if ch == '\n':
                    offs.append(i + 1)
            cache[fp] = (st, offs)
        return cache[fp]

    def resolve(full, file):
        c = by_full.get(full)
        if c:
            if len(c) == 1:
                return c[0]
            same = [x for x in c if x.file == file]
            return same[0] if same else c[0]
        c = by_seg.get(full.split('::')[-1])
        if not c:
            return None
        same = [x for x in c if x.file == file]
        if same:
            return same[0]
        return c[0] if len(c) == 1 else None

    edges = set()
    for f in funcs:
        st, offs = get(f.file)
        if not st:
            continue
        a = offs[f.start - 1] if 0 <= f.start - 1 < len(offs) else None
        if a is None:
            continue
        b = offs[f.end] if f.end < len(offs) else len(st)
        region = st[a:b]
        k = region.find('{')          # 从函数体开始扫, 跳过签名
        if k < 0:
            continue
        body = region[k:]
        act = get_active(f.file, root)
        for m in _CALLQ_RE.finditer(body):
            line = f.start + body.count('\n', 0, m.start())
            if not (0 < line <= len(act) and act[line - 1]):
                continue                  # #if 0 里的调用
            full = m.group(1)
            if full in _CALL_KW or full.split('::')[-1] in _CALL_KW:
                continue
            tgt = resolve(full, f.file)
            if tgt is None or tgt.id == f.id:
                continue
            edges.add((f.id, tgt.id))
    return edges


def build_graph(funcs, files, root, cscope, db):
    by_name = defaultdict(list)
    by_file_name = defaultdict(list)
    for f in funcs:
        by_name[f.name].append(f)
        by_file_name[(f.file, f.name)].append(f)

    def resolve_caller(name, file):
        # -2 输出的第一列是该函数所在文件, 用来消歧
        c = by_file_name.get((file, name))
        if c:
            return c[0]
        c = by_name.get(name)
        return c[0] if c else None

    def resolve_callee(name, file):
        c = by_name.get(name)
        if not c:
            return None            # 项目外的符号(memcpy 等), 丢弃
        if len(c) == 1:
            return c[0]
        same = by_file_name.get((file, name))
        if same:
            return same[0]
        return c[0]

    def active_at(fp, ln):
        a = get_active(fp, root)
        return 0 < ln <= len(a) and a[ln - 1]

    edges = set()
    external = Counter()
    names = sorted(by_name.keys())
    # 并行查询 cscope (只读同一索引, 多进程/线程安全), 大工程可显著提速
    from concurrent.futures import ThreadPoolExecutor
    workers = min(8, (os.cpu_count() or 4))

    def _query(name):
        return name, cscope_callees(cscope, db, name)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        done = 0
        for name, res in ex.map(_query, names):
            for file, callee, ln in res:
                if not active_at(file, ln):    # 跳过 #if 0 里的调用
                    continue
                caller = resolve_caller(name, file)
                if caller is None:
                    continue
                target = resolve_callee(callee, file)
                if target is None:
                    external[caller.id] += 1
                elif target.id != caller.id:
                    edges.add((caller.id, target.id))
            done += 1
            if done % 500 == 0:
                sys.stderr.write('  cscope 进度 %d/%d\n' % (done, len(names)))

    # 内置词法解析: 补齐 cscope 对 C++(类内联方法/限定名) 的盲区
    builtin = builtin_calls(funcs, files, root)
    heur = sorted(builtin - edges)          # 仅内置解析发现的边(cscope 未见, 启发式)
    edges |= builtin
    sys.stderr.write('  内置解析调用边: %d (其中 cscope 未见的启发式边 %d)\n'
                     % (len(builtin), len(heur)))

    # 间接调用: 线程/回调等 (cscope 看不到函数指针目标)
    spawn_pairs = []
    for a, b, kind in detect_spawn_edges(funcs, files, root):
        edges.add((a, b))
        spawn_pairs.append([a, b, kind])
    sys.stderr.write('  线程/回调边: %d\n' % len(spawn_pairs))

    adj = defaultdict(set)
    radj = defaultdict(set)
    for a, b in edges:
        adj[a].add(b)
        radj[b].add(a)
    for f in funcs:
        ins = radj.get(f.id, ())
        outs = adj.get(f.id, ())
        f.fan_in = len(ins)
        f.fan_out = len(outs)
        f.in_int = sum(1 for x in ins if funcs[x].file == f.file)   # 同文件调用者
        f.out_int = sum(1 for x in outs if funcs[x].file == f.file)  # 同文件被调用
        f.in_ext = f.fan_in - f.in_int                               # 跨文件调用者
        f.out_ext = f.fan_out - f.out_int                            # 跨文件被调用
    return edges, adj, radj, external, spawn_pairs, heur


# ---------------------------------------------------------------- 强连通分量

def tarjan(funcs, adj):
    index = [0]
    stack = []
    on = set()
    idx = {}
    low = {}
    comps = []

    def strong(v):
        idx[v] = low[v] = index[0]
        index[0] += 1
        stack.append(v)
        on.add(v)
        for w in adj.get(v, ()):
            if w not in idx:
                strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            comps.append(comp)

    # 迭代式避免深递归爆栈
    for f in funcs:
        if f.id not in idx:
            strong(f.id)
    return comps


def compute_depths(funcs, comps, adj):
    comp_of = {}
    for ci, comp in enumerate(comps):
        for v in comp:
            comp_of[v] = ci
    cyc = [len(c) > 1 or (len(c) == 1 and c[0] in adj.get(c[0], ()))
           for c in comps]
    cadj = defaultdict(set)
    for v, ws in adj.items():
        for w in ws:
            a, b = comp_of[v], comp_of[w]
            if a != b:
                cadj[a].add(b)
    n = len(comps)
    # 拓扑排序(缩点后是 DAG)
    indeg = [0] * n
    for a in cadj:
        for b in cadj[a]:
            indeg[b] += 1
    order = []
    from collections import deque
    dq = deque([i for i in range(n) if indeg[i] == 0])
    while dq:
        u = dq.popleft()
        order.append(u)
        for w in cadj[u]:
            indeg[w] -= 1
            if indeg[w] == 0:
                dq.append(w)
    # 从根往下的最长路径 = 调用深度
    down = [0] * n
    for u in order:
        for w in cadj[u]:
            down[w] = max(down[w], down[u] + 1)
    # 从下往上的最长路径 = 子树深度
    up = [0] * n
    for u in reversed(order):
        for w in cadj[u]:
            up[u] = max(up[u], up[w] + 1)
    for f in funcs:
        c = comp_of[f.id]
        f.scc = c
        f.in_cycle = cyc[c]
        f.depth = down[c]
        f.subtree_depth = up[c]
    cycles = [[funcs[v].id for v in c] for c in comps if cyc[comp_of[c[0]]]]
    return comps, comp_of, cycles


# ---------------------------------------------------------------- include 依赖

INC_RE = re.compile(r'^\s*#\s*include\s*"([^"]+)"')


def longest_chain(funcs, comps, comp_of, adj):
    """在缩点后的 DAG 上取最长路径(调用深度), 每个分量用最复杂的函数代表。"""
    from collections import deque
    cadj = defaultdict(set)
    for v, ws in adj.items():
        for w in ws:
            a, b = comp_of[v], comp_of[w]
            if a != b:
                cadj[a].add(b)
    n = len(comps)
    indeg = [0] * n
    for a in cadj:
        for b in cadj[a]:
            indeg[b] += 1
    dq = deque([i for i in range(n) if indeg[i] == 0])
    order = []
    while dq:
        u = dq.popleft()
        order.append(u)
        for w in cadj[u]:
            indeg[w] -= 1
            if indeg[w] == 0:
                dq.append(w)
    if not order:
        return [], []
    dist = [0] * n
    pred = [-1] * n
    for u in order:
        for w in cadj[u]:
            if dist[u] + 1 > dist[w]:
                dist[w] = dist[u] + 1
                pred[w] = u
    end = max(range(n), key=lambda i: dist[i])
    sp, x = [], end
    while x != -1:
        sp.append(x)
        x = pred[x]
    sp.reverse()
    reps = [max(comps[ci], key=lambda vid: funcs[vid].ccn) for ci in sp]
    sizes = [len(comps[ci]) for ci in sp]
    return reps, sizes


SRC_EXT = ('.c', '.h', '.cpp', '.hpp', '.cc', '.cxx', '.cu')


def discover_files(root, excl=()):
    files = []
    for dp, dn, names in os.walk(root):
        dn[:] = [d for d in dn if d not in ('.git', 'docs', 'node_modules')]
        for n in names:
            if not n.endswith(SRC_EXT):
                continue
            rel = canon(os.path.relpath(os.path.join(dp, n), root))
            if any(e and e in rel for e in excl):
                continue
            files.append(rel)
    return sorted(set(files))


def include_edges(files, root):
    basename = {}
    for fp in files:
        basename.setdefault(os.path.basename(fp), []).append(fp)
    edges = set()
    for fp in files:
        full = os.path.join(root, fp)
        try:
            with open(full, encoding='utf-8', errors='replace') as fh:
                act = get_active(fp, root)
                for i, line in enumerate(fh):
                    if not (i < len(act) and act[i]):
                        continue                  # #if 0 里的 include
                    m = INC_RE.match(line)
                    if not m:
                        continue
                    for tgt in basename.get(m.group(1), ()):
                        if tgt != fp:
                            edges.add((fp, tgt))
        except IOError:
            pass
    return files, edges


def header_prototypes(files, root):
    """从头文件里抽取函数声明名, 作为"公开接口"的候选。"""
    names = set()
    pat = re.compile(r'([A-Za-z_]\w*)\s*\(')
    for fp in files:
        if not fp.endswith('.h'):
            continue
        try:
            with open(os.path.join(root, fp), encoding='utf-8', errors='replace') as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line[0] in '#/' or line[0] not in \
                            'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_':
                        continue
                    if not line.endswith(';') or '=' in line or '{' in line or '}' in line:
                        continue
                    if 'typedef' in line:
                        continue
                    m = pat.search(line)
                    if m:
                        names.add(m.group(1))
        except IOError:
            pass
    return names


# ---------------------------------------------------------------- 主流程

def main():
    root, lizard_csv, cscope, out_json = sys.argv[1:5]
    dup_path = sys.argv[6] if len(sys.argv) > 6 else None
    root = os.path.abspath(root)
    db = os.path.join(root, 'cscope.out')

    excl = [e for e in (sys.argv[5].split(',') if len(sys.argv) > 5 and sys.argv[5] else []) if e]
    funcs = load_lizard(lizard_csv, root)
    funcs = [f for f in funcs if not any(e in f.file for e in excl)]
    # 去掉 #if 0 中被注释掉的函数
    kept = []
    for f in funcs:
        a = get_active(f.file, root)
        if 0 < f.start <= len(a) and a[f.start - 1]:
            kept.append(f)
    funcs = kept
    for i, f in enumerate(funcs):   # 过滤后重排 id, 保证 funcs[id] 有效
        f.id = i
    mark_static(funcs, root)
    files = discover_files(root, excl)
    have = set(files)
    for f in funcs:
        if f.file not in have:
            files.append(f.file)
            have.add(f.file)
    files = sorted(set(files))
    labels = module_labels(files)
    sys.stderr.write('函数数: %d, 模块数: %d\n' % (len(funcs), len(files)))

    if not os.path.exists(db):
        with open(os.path.join(root, 'cscope.files'), 'w') as fh:
            fh.write('\n'.join(files) + '\n')
        subprocess.run([cscope, '-bq', '-i', 'cscope.files'], cwd=root,
                       check=True)

    import time
    t0 = time.time()
    edges, adj, radj, external, spawn_pairs, heur_edges = build_graph(funcs, files, root, cscope, db)
    sys.stderr.write('调用边: %d (%.1fs)\n' % (len(edges), time.time() - t0))

    comps = tarjan(funcs, adj)
    comps, comp_of, cycles = compute_depths(funcs, comps, adj)

    # 文件/模块
    fidx = {p: i for i, p in enumerate(files)}
    _, inc_edges = include_edges(files, root)
    per_file, hyg = hygiene_scan(files, root, inc_edges)

    # 稀疏存储: 只记录非零的模块对 (大工程下密集 MxM 会让 HTML 爆掉)
    call_cnt, inc_cnt = defaultdict(int), defaultdict(int)
    for a, b in edges:
        call_cnt[(fidx[funcs[a].file], fidx[funcs[b].file])] += 1
    for a, b in inc_edges:
        inc_cnt[(fidx[a], fidx[b])] += 1
    call_links = [[i, j, w] for (i, j), w in call_cnt.items()]
    include_links = [[i, j, w] for (i, j), w in inc_cnt.items()]

    # 接口识别: 头文件声明 或 被其他模块调用
    proto = header_prototypes(files, root)
    ffile = [f.file for f in funcs]
    cin, cout = defaultdict(set), defaultdict(set)
    for a, b in edges:
        if ffile[a] != ffile[b]:
            cout[a].add(ffile[b])
            cin[b].add(ffile[a])
    for f in funcs:
        f.cross_in = len(cin.get(f.id, ()))
        f.cross_out = len(cout.get(f.id, ()))
        f.exported = (f.name in proto) or f.cross_in > 0

    # 每个模块的耦合度
    mod = []
    for p in files:
        of = [f for f in funcs if f.file == p]
        ce = sum(1 for a, b in edges if funcs[a].file == p and funcs[b].file != p)
        ca = sum(1 for a, b in edges if funcs[b].file == p and funcs[a].file != p)
        ccn = [f.ccn for f in of] or [0]
        incyc = any(f.in_cycle for f in of)
        # 对外接口 = 被其他模块调用; 内部接口(泄漏符号) = 非 static 却只在本模块内用
        ext = [f for f in of if f.in_ext > 0]
        leaked = [f for f in of if (not f.is_static) and f.in_ext == 0 and f.in_int > 0]
        unused = [f for f in of if (not f.is_static) and f.in_ext == 0 and f.in_int == 0]
        iface = [f.id for f in ext] + [f.id for f in leaked]
        iface_ext = len(ext)
        iface_int = len(leaked)
        mod.append({
            'path': p, 'short': p.split('/')[-1], 'label': labels[p],
            'funcs': len(of), 'nloc': sum(f.nloc for f in of),
            'avg_ccn': round(sum(ccn) / len(ccn), 2), 'max_ccn': max(ccn),
            'ca': ca, 'ce': ce,
            'instability': round(ce / (ca + ce), 2) if (ca + ce) else 0.0,
            'in_cycle': incyc,
            'iface': len(iface), 'iface_ids': iface,
            'iface_ext': iface_ext, 'iface_int': iface_int,
            'iface_unused': len(unused),
            'comment_ratio': per_file.get(p, {}).get('comment_ratio', 0.0),
            'magic': per_file.get(p, {}).get('magic', 0),
        })

    # 健康度
    all_ccn = [f.ccn for f in funcs]
    hotspots = [f for f in funcs if f.ccn > 15]
    cyc_funcs = sum(1 for f in funcs if f.in_cycle)
    avg_ccn = sum(all_ccn) / len(all_ccn)
    max_ccn = max(all_ccn)
    deepest = max(f.depth for f in funcs)
    avg_fanout = sum(f.fan_out for f in funcs) / len(funcs)
    avg_fanin = sum(f.fan_in for f in funcs) / len(funcs)

    def clamp(x):
        return max(0.0, min(1.0, x))

    score = 100.0
    score -= 25 * clamp(avg_ccn / 15.0)
    score -= 20 * clamp(max_ccn / 50.0)
    score -= 15 * clamp(cyc_funcs / max(1, len(funcs)) * 5)
    score -= 15 * clamp(avg_fanout / 10.0)
    score -= 15 * clamp(deepest / 20.0)
    score -= 10 * clamp(len(hotspots) / len(funcs) * 3)
    score = round(max(0.0, score), 1)

    health = {
        'score': score,
        'files': len(files), 'functions': len(funcs),
        'nloc': sum(f.nloc for f in funcs),
        'avg_ccn': round(avg_ccn, 2), 'max_ccn': max_ccn,
        'hotspots': len(hotspots), 'hotspot_pct': round(100.0 * len(hotspots) / len(funcs), 1),
        'cycles': len(cycles), 'cycle_funcs': cyc_funcs,
        'deepest': deepest, 'avg_fanout': round(avg_fanout, 2),
        'avg_fanin': round(avg_fanin, 2), 'edges': len(edges),
        'spawn_edges': len(spawn_pairs),
        'inter_edges': sum(1 for a, b in edges if funcs[a].file != funcs[b].file),
        'intra_edges': sum(1 for a, b in edges if funcs[a].file == funcs[b].file),
        'iface_funcs': sum(1 for f in funcs if f.exported),
    }

    chain_ids, chain_sizes = longest_chain(funcs, comps, comp_of, adj)

    fn = []
    for f in sorted(funcs, key=lambda x: x.id):
        fn.append([f.id, fidx[f.file], f.name, f.long_name.strip()[:160], f.ccn,
                   f.nloc, f.params, f.token, f.length, f.start, f.end,
                   f.fan_in, f.fan_out, f.depth, f.subtree_depth,
                   1 if f.in_cycle else 0, f.scc,
                   f.cross_in, f.cross_out, 1 if f.exported else 0,
                   f.in_int, f.in_ext, f.out_int, f.out_ext,
                   1 if f.is_static else 0,
                   round(f.hvol, 1), f.nd, round(f.mi, 1)])
    data = {
        'meta': {
            'project': os.path.basename(root.rstrip('/')),
            'root': root,
            'lizard': '1.24.0', 'cscope': '15.9',
        },
        'files': mod,
        'functions': fn,
        'edges': sorted([list(e) for e in edges]),
        'call_links': call_links,
        'include_links': include_links,
        'cycles': cycles,
        'spawn_edges': spawn_pairs,
        'heur_edges': [[a, b] for a, b in heur_edges],
        'dup_blocks': parse_duplicates(dup_path)[0],
        'dup_rate': parse_duplicates(dup_path)[1],
        'hygiene': hyg,
        'health': health,
        'longest_path': chain_ids,
        'longest_scc_sizes': chain_sizes,
        'roots': [f.id for f in funcs if f.fan_in == 0],
        'hotspot_ids': [f.id for f in sorted(funcs, key=lambda x: -x.ccn)
                        if f.ccn > 15],
    }
    with open(out_json, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
    sys.stderr.write('健康度 %.1f, 环 %d, 热点 %d, 已写 %s\n' % (
        score, len(cycles), len(hotspots), out_json))


if __name__ == '__main__':
    main()
