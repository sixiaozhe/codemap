---
name: codemap
description: >-
  用 codemap 工具包离线分析 C/C++ 工程的结构与质量，快速建立全局认知并做定点检索。
  当用户需要在**离线/内网服务器**上理解或导航 C/C++ 代码库、评估圈复杂度/耦合/调用深度/调用环/公开接口/重复率/可维护性(MI)/代码整洁度、规划重构或改动影响面，或者"读整个仓库太费 token"时，都应使用本 skill。
  触发场景包括：用户说"看看这个模块的代码""这代码质量怎么样""哪些函数最复杂""谁调用了 X""模块依赖关系""画出代码地图/生成 codemap"，或提到 lizard、cscope、圈复杂度、调用图。
  覆盖：生成 `codemap.html` + `codemap.ai.md` + `codemap.ai.json`，用 `codemap query` 定点查询，以及注册 `codemap mcp` 让 agent 直接调用工具。即使没明说 "codemap"，只要任务涉及理解或导航 C/C++ 代码库的结构，就用本 skill。
---

# codemap：C/C++ 代码地图与按需查询

## 它是什么

`codemap` 是一个**离线、零联网依赖**的 C/C++ 代码分析工具包（打包了静态 `cscope`、单文件 `lizard.pyz`、以及纯 Python 的解析/汇总脚本）。它把整个工程汇总成：

- `codemap.html` —— 给人看的交互式代码地图（总览/依赖矩阵/接口全景/调用图/复杂度/调用深度/整洁度/健康度）；
- `codemap.ai.md` —— **给模型看的紧凑摘要**（约十几 KB）；
- `codemap.ai.json` —— 机器可读数据，供 `query` 与 MCP 使用。

**核心价值**：不必把成百上千个源文件读进上下文，就能得到结构（调用图、模块依赖、环、接口）与质量（CCN、深度、重复、MI、卫生）的全貌；随后用 `query`/MCP **按需**取用局部细节。

## 何时用 / 何时不用

**用**：理解陌生模块、评估复杂度/耦合/健康度、找热点与死代码、查"谁调用了 X / X 调用了谁"、规划重构或估算影响面、为后续改动建立地图。

**不必用**：只看单个小函数、或仅需读某几行源码——直接读文件更省事。代码库很小（几个文件）时价值有限。

## 前置条件

工具已安装（`codemap` 在 PATH）。若未安装：

```bash
tar xzf codemap-toolkit-*.tar.gz
cd codemap-toolkit-*
./install.sh                 # 默认装到 ~/.local，无需 root
export PATH="$HOME/.local/bin:$PATH"
```

要求：Linux x86_64（内置 cscope 为静态二进制）+ `python3`（≥3.6）。全程离线。

## 工作流

### 1. 生成（一次性，可能较慢）

```bash
cd <工程目录>
codemap .                                   # 生成 ./codemap.html/.ai.md/.ai.json
codemap -o /tmp/map.html ./src "tests/,third_party/"   # 指定输出 + 排除子串
```

大工程会慢（要跑 lizard + cscope + 重复检测）；排除测试/第三方能显著提速。生成后勿随意改动源码，否则结果会过期——**改了代码就重新生成**。

### 2. 先读 `codemap.ai.md` 建立全局认知

这是最高性价比的一步：**先读摘要，不要读 HTML**。摘要含：概览（规模/平均与最高 CCN/环/最深链）、热点函数 Top、模块表、调用环、最长调用链、各模块公开接口、重复与卫生问题。

### 3. 用 `codemap query` 做定点检索（省 token）

不要一次读完 `ai.json`；用查询只取需要的片段：

```bash
codemap query callers:<函数>     # 谁调用了它（含 file:line、CCN、扇入出、是否在环）
codemap query callees:<函数>     # 它调用了谁
codemap query def:<函数>         # 定义位置
codemap query module:<文件>      # 模块概览（函数/接口/耦合/注释率）
codemap query hotspots:20        # 复杂度热点
codemap query cycles             # 调用环（强连通分量）
codemap query search:<子串>      # 按名搜索
codemap query files              # 模块列表
# 默认读 ./codemap.ai.json；可 --data <路径> 指定
```

查询输出带 `file:line` 锚点——**用这些锚点只读相关源码片段**（例如 `lvm.c:1204`），而不是整文件。

### 4. 需要多轮交互时，注册 MCP

让 agent 把 codemap 当作工具直接调用（比每次拼 shell 命令更高效）：

```bash
codemap mcp --data ./codemap.ai.json
```

在支持 MCP 的客户端（Claude Desktop / VSCode 等）中注册该 stdio 命令。暴露工具：
`codemap_overview`、`codemap_find_symbol`、`codemap_callers`、`codemap_callees`、`codemap_module`、`codemap_hotspots`、`codemap_cycles`。

## 指标速查

| 指标 | 含义 | 参考阈值 |
|---|---|---|
| CCN | 圈复杂度 = 1 + 判定点数 | ≤10 严 / ≤15 松 |
| NLOC | 函数内非空非注释行 | 函数 ≤30–50 |
| 参数 / 嵌套深度 | 形参个数 / 控制结构最大嵌套 | ≤4–5 / ≤3–4 |
| 扇入(内/外) | 被多少函数调用（同文件/跨文件） | — |
| 深度 / 子树深度 | 到入口层数 / 到叶子层数（按 SCC 缩点） | — |
| Ca/Ce/I | 被依赖/依赖/不稳定性 `I=Ce/(Ca+Ce)` | I 越靠近 0 越稳定 |
| 对外接口 | 被其他模块调用的函数 | — |
| 内部接口(泄漏) | 非 static 却只在本模块内用 | 建议收敛为 static |
| 未接入接口 | 非 static 但工程内无调用 | 入口/回调或死代码 |
| 环 | 强连通分量（互相调用） | 越少越好 |
| MI | 维护性指数（Halstead/CCN/NLOC） | ≥85 好 / <65 差 |
| 重复率 | 克隆代码占比 | <3–5% |

## 置信度与陷阱（重要）

- **调用关系是启发式的**：来源 = cscope + 内置词法解析 + 线程/回调匹配；**不含**宏展开、函数指针、虚函数动态分派。用于导航很有效，但**下结论前应结合源码复核**。
- **外部符号不计入**；线程/回调类调用（`pthread_create`/`std::thread`/`CreateThread` 等）会被补上，可用 `spawn.conf` 扩展平台 API。
- **数据是快照**：代码变更后需重新生成。
- **`#if 0` 已剔除**；`#else/#elif` 有效分支保留。
- **大工程**：模块很多时依赖矩阵会自动降级为稀疏列表、接口全景限流——属正常，会在界面提示。

## 建议给用户/自己的产出

1. 一张 `codemap.html`（人看）；
2. 一份 `codemap.ai.md`（模型快速认知）；
3. 基于 `query`/`file:line` 的**定位结论**，而非泛读源码。

## 示例

用户："帮我评估下 `anrLib` 这个模块的代码质量，重点看复杂度高的地方。"

做法：
```bash
codemap ./anrLib "test/"
head -30 codemap.ai.md            # 概览 + 热点
codemap query module:anr_sdk_dev.c
codemap query callers:anr_play_exchange_task
```
然后只读热点函数的 `file:line` 片段给出结论；如需细看调用关系，再用 `codemap query callees:<热点函数>`。
