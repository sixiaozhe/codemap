<div align="center">

<img src="docs/logo.svg" width="360" alt="codemap">

# codemap · C/C++ Code Map

**Offline, zero-dependency. Understand a C/C++ codebase's structure and quality at a glance.**

Turn an entire project into an interactive code map: module dependencies, symbol call graph, cyclomatic complexity,
call depth, call cycles, public interfaces, duplication and maintainability — plus a **compact summary for AI** and a
**query CLI / MCP server**.

![demo](docs/demo.gif)

![platform](https://img.shields.io/badge/platform-Linux%20x86__64-4d4d4d)
![python](https://img.shields.io/badge/python-3.6%2B-3572a5)
![offline](https://img.shields.io/badge/network-not%20required-4ec9b0)
![license](https://img.shields.io/badge/license-MIT-4daafc)
[![release](https://github.com/sixiaozhe/codemap/actions/workflows/release.yml/badge.svg)](https://github.com/sixiaozhe/codemap/actions/workflows/release.yml)

[中文](README.md) · [**English**](README.en.md)

</div>

---

## ✨ Highlights

- **Fully offline**: ships a static `cscope` and a single-file `lizard`. No network, no `pip`, no `apt`, no root.
- **No headers / compile database needed**: parses source directly (lizard + cscope + a built-in lexer), works for C and C++.
- **One HTML shows it all**: 8 interactive tabs, a single self-contained file you can just open in a browser.
- **AI-friendly**: also emits `codemap.ai.md` / `codemap.ai.json`, with a `codemap query` CLI and a `codemap mcp` server to cut an agent's round-trips and token usage.
- **VSCode Dark Modern UI**: left icon rail, collapsible, theme-consistent.
- **Built for large codebases**: sparse dependency matrix, graceful degradation, parallel parsing, explicit truncation warnings.

## 🗺️ Features

### Overview (annotated)

![Overview](docs/overview-annotated.png)

① KPIs in three groups (size / complexity / coupling)　② Health score with deduction breakdown　③ CCN threshold (globally drives colors, hotspots, score)　④ Most complex functions　⑤ Left icon rail (collapsible)

### Dependency matrix (annotated)

![Dependency matrix](docs/matrix-annotated.png)

① Mode / ordering / export / stats　② Dependency strength color scale　③ Red cells in the upper triangle = reverse calls (cycles)　④ Hovering a cell highlights its whole row and column

| Tab | Content |
|---|---|
| **Overview** | Health score, KPIs, most complex functions, top risks |
| **Dependency Matrix** | Module×module DSM heatmap, **topological order by default** (upper triangle = cycles), cluster order available; only modules with dependencies are shown |
| **Interface Panorama** | Force-directed module map: cards = module scope, links = dependencies, moving dots show direction, magenta = mutual; click a module for **exported / internal-leak / unused** interfaces |
| **Call Graph** | Layered call graph (callers left / callees right), smooth animation, edge routing around nodes, **walk highlights the source path**, **same color = same call cycle** |
| **Complexity** | Full function table, sortable/filterable/paginated, CSV export |
| **Call Depth** | Depth distribution, longest call chain, per-function longest chain |
| **Cleanliness** | **Maintainability Index (MI)**, Halstead, **nesting depth**, **duplicate blocks**, comment ratio, TODO/long lines, include hygiene |
| **Health** | Score breakdown (adjustable weights), module scorecards, cycle details, risk list |

### Interface panorama (moving dots, cycle highlight, module detail)

![Interface panorama](docs/panorama.gif)

### Call graph (walk highlights the source path, cycles share a color, edges route around nodes)

![Call graph](docs/callgraph.gif)

### Dependency matrix (topological order, upper triangle = cycles, crosshair highlight)

![Dependency matrix](docs/matrix.gif)

### On-demand CLI queries (fewer round-trips, fewer tokens)

![CLI query](docs/cli.gif)

> All animations are captured from the **real tool output** (Lua 5.4), not mockups.

### Cleanliness (maintainability index / nesting depth / duplicate blocks / hygiene)

![Cleanliness](docs/cleanliness.png)

## 📂 Examples

`examples/` contains a sample map generated for **Lua 5.4** (a self-contained HTML). It does **not** contain the
analyzed project's source. See [`examples/README.md`](examples/README.md) to reproduce.

## 🚀 Quick start

```bash
tar xzf codemap-toolkit-*.tar.gz
cd codemap-toolkit-*
./install.sh                       # installs to ~/.local (no root needed)
export PATH="$HOME/.local/bin:$PATH"

cd /path/to/your/project
codemap .                          # generates ./codemap.html and the AI summary
codemap -o /tmp/map.html ./src "tests/,third_party/"   # custom output + excludes
```

Requirements: **Linux x86_64** + **Python 3.6+** (the bundled cscope is a static binary; everything else is pure Python).

## 🔎 Commands

```bash
# Generate (HTML + AI summary)
codemap [-o out.html] <project-dir> [excludes(comma-separated)]

# On-demand queries (token- and round-trip-efficient) — reads ./codemap.ai.json by default
codemap query callers:<fn>       # who calls it
codemap query callees:<fn>       # what it calls
codemap query def:<fn>           # definition location
codemap query module:<file>      # module overview
codemap query hotspots[:N]       # complexity hotspots
codemap query cycles             # call cycles
codemap query search:<substr>    # search by name

# MCP server (let an AI call the tools directly)
codemap mcp --data ./codemap.ai.json
```

## 🤖 For AI

Generation also produces two machine/model-friendly artifacts (same basename as the HTML):

- `codemap.ai.md` — a compact summary (~tens of KB): overview / hotspots / modules / cycles / longest chain / interfaces / hygiene. **Read this first, not the HTML.**
- `codemap.ai.json` — machine-readable data used by `query` and MCP.

Instead of dumping the whole map into context, **read the summary, then query on demand**, and use the returned
`file:line` to read only the relevant source.

Tools exposed over MCP: `codemap_overview`, `codemap_find_symbol`, `codemap_callers`, `codemap_callees`,
`codemap_module`, `codemap_hotspots`, `codemap_cycles`.

`skill/codemap/SKILL.md` is an agent skill; install it so an agent auto-loads it for related tasks:

```bash
cp -r skill/codemap ~/.opencode/skills/        # opencode
cp -r skill/codemap ~/.claude/skills/          # Claude Code
```

## 📊 Metrics

| Metric | Meaning | Reference |
|---|---|---|
| CCN | Cyclomatic complexity = 1 + decision points | ≤10 strict / ≤15 loose |
| NLOC / params / nesting | Non-comment lines / parameters / max nesting | ≤30–50 / ≤4–5 / ≤3–4 |
| Fan-in(out) · Fan-out(out) | Callers / callees (same-file / cross-file) | — |
| Depth / subtree depth | Levels to entry / to leaf (SCC-condensed) | — |
| Ca / Ce / I | Afferent / efferent / instability `I=Ce/(Ca+Ce)` | closer to 0 = more stable |
| Exported / internal-leak / unused iface | called externally / non-static used only in-module / non-static unused | leak should become `static` |
| Cycles | Call cycles (strongly connected components) | fewer is better |
| MI | Maintainability Index (Halstead volume + CCN + NLOC) | ≥85 good / <65 poor |
| Duplication | Clone ratio | <3–5% |

## 🧩 How it works

- **Complexity / size / nesting / Halstead / duplication**: `lizard` (`--csv -Ehalstead -ENS`, plus `-Eduplicate`).
- **Symbols & call relations**: `cscope` + a **pure-Python lexer** (fills C++ in-class/qualified-name gaps) + **thread/callback matching** (`pthread_create`/`std::thread`/`CreateThread`… extensible via `spawn.conf`).
- **Derived metrics**: module dependency matrix, fan-in/out, call depth, SCCs (cycles), public interfaces, MI, include hygiene — all computed by `analyze.py`.
- **Presentation**: `template.html` + `build_html.py` produce a single self-contained interactive HTML (no external links, offline).

## 📁 Layout

```
codemap/
├── bin/                  # cscope (static), lizard.pyz, codemap CLI
├── share/codemap/        # analyze / ai_export / query / mcp / build_html + template + spawn.conf
├── skill/codemap/        # agent skill
├── examples/             # sample output (Lua 5.4 map) + how to reproduce
├── docs/                 # images/GIFs used by the README
├── scripts/package.sh    # build the release tarball
├── .github/workflows/    # tag -> release
├── install.sh
└── uninstall.sh
```

## 📦 Packaging & release

```bash
sh scripts/package.sh 7.1.0          # -> dist/codemap-toolkit-7.1.0.tar.gz
```

Pushing a `v*` tag triggers GitHub Actions to build and publish a Release:

```bash
git tag v7.1.0 && git push origin v7.1.0
```

## ⚠️ Limitations

- Call relations are **heuristic**: no macro expansion, function pointers, or virtual dispatch; thread/callback calls are recognized. Great for navigation — verify against source before drawing conclusions.
- `#if 0` blocks are excluded; `#else/#elif` branches are kept.
- The bundled `cscope` is an **x86_64 static binary**; ARM/MIPS need their own build.
- Results are a **snapshot**; regenerate after code changes.
- Large codebases: the matrix degrades to a sparse list and the panorama is capped (the UI tells you).

## 📄 License

MIT. Bundled components: `cscope` (BSD), `lizard` (MIT). See `LICENSE`.
