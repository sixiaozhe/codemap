#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 data.json 注入 template.html, 生成自包含的 codemap.html。"""
import json
import sys

tpl_path, data_path, out_path = sys.argv[1:4]
tpl = open(tpl_path, encoding='utf-8').read()
data = json.load(open(data_path, encoding='utf-8'))
blob = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
out = (tpl.replace('__DATA_JSON__', blob)
          .replace('__PROJECT__', data['meta']['project'])
          .replace('__LIZARD__', data['meta']['lizard'])
          .replace('__CSCOPE__', data['meta']['cscope'])
          .replace('__NFUNC__', str(len(data['functions'])))
          .replace('__NFILE__', str(len(data['files'])))
          .replace('__NEDGE__', str(len(data['edges']))))
open(out_path, 'w', encoding='utf-8').write(out)
print('wrote %s (%.0f KB)' % (out_path, len(out.encode('utf-8')) / 1024))
