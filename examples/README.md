# 示例说明

本目录只有**生成产物**，不含任何被分析工程的源码（避免把示例工程塞进仓库）。

- `lua-codemap.html` —— 对 **Lua 5.4** 源码生成的自包含代码地图，直接用浏览器打开即可（离线、无外链）。
  它同时是 README 里那几张动图/截图的数据来源。

> 本示例用于演示工具能力，**Lua 源码不随仓库分发**。请按下文自行获取后复现。

## 复现步骤

```bash
# 1) 准备一个 C/C++ 工程（这里以 Lua 5.4 为例）
git clone --depth 1 https://github.com/lua/lua lua

# 2) 生成代码地图（排除测试/合并文件）
codemap -o examples/lua-codemap.html lua "testes/,ltests,onelua"

# 3) 得到三个产物
#    examples/lua-codemap.html   交互式代码地图（人看）
#    examples/lua-codemap.ai.md  面向 AI 的紧凑摘要
#    examples/lua-codemap.ai.json 机器可读数据（供 query / MCP）
```

换成你自己的工程只需替换路径与排除模式，例如：

```bash
codemap -o /tmp/map.html ./src "tests/,third_party/,generated/"
```

## 打开后看什么

1. **总览**：健康度评分、三类 KPI、最复杂函数、重点风险。
2. **依赖矩阵**：默认拓扑序——**上三角标红 = 循环依赖**；切"聚类序"看模块簇；鼠标悬停有十字高亮。
3. **接口全景**：力导向模块地图；点模块看**对外/内部(泄漏)/未接入**接口；连线上的光点表示调用方向。
4. **调用图**：点节点层层展开；游走时**高亮来源路径**；同一调用环同色、环内边橙色加粗。
5. **复杂度 / 调用深度 / 整洁度 / 健康度**：定位热点函数、最长调用链、重复块与维护性指数 MI。

## AI 用法（省 token）

```bash
codemap query callers:luaV_execute     # 谁调用了它
codemap query module:ltable.c          # 模块概览
codemap query hotspots:20              # 复杂度热点
codemap query cycles                   # 调用环
```

或注册 MCP：`codemap mcp --data examples/lua-codemap.ai.json`，让 agent 直接调用
`codemap_overview / codemap_callers / codemap_module / codemap_hotspots / codemap_cycles` 等工具。
