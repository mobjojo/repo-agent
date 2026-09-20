# repo-agent — 仓库级 AI Coding Agent（20 条真实任务 / 4 个上游仓库，pass@1 75–90%）

输入一个 Issue 和一个仓库检出，输出一个**可 `git apply` 的统一 diff**。
M1 是行走骨架（闭环能跑），M2 把它对上真实世界（`pallets/itsdangerous` 3 条，pass@1 3/3），
M3 把任务集扩到 20 条、覆盖 4 个真实仓库（itsdangerous / click / packaging / werkzeug），
同一批任务连跑 5 轮，pass@1 = 75 / 90 / 85 / 90 / 90%（逐任务波动 5 条，**未达 Step 5 的 ≤ 1 条**）。
数字、失败阶段分布与取舍见 `BASELINE.md`，任务清单与造任务流程见 `tasks/README.md`。

设计取舍：框架选 LangGraph（显式状态图 + 条件边 + 预算熔断），模型走 LiteLLM（换模型只是改字符串），
执行走可插拔沙箱（本地 / Docker）。检索、多 Agent、记忆体系都不在这一层。

## 交付契约

唯一被评分的东西是补丁，而且必须同时满足三条：

1. `git apply --check` 在干净检出上通过；
2. 没有触碰受保护文件（默认：`tests/`、`test_*.py`、`*_test.py`、`conftest.py`、`tox.ini`、`pytest.ini`、`setup.cfg`）；
3. 测试集判定：`fail_to_pass` 修前必须失败、修后必须通过，`pass_to_pass` 两次都必须通过。

任务级环境变量（`env`，例如 src 布局仓库需要的 `{"PYTHONPATH": "src"}`）会同时注入 Agent 沙箱
和判定命令，因此不必把环境差异塞进命令行字符串里。

违反任意一条 → harness 记一次 `contract` 阶段失败，补丁不计入 pass@1。Agent 自己也改不了测试：
工具层的 guard 会直接拒绝写测试文件、拒绝路径穿越、拒绝写 `.git/`。

## 目录

| 路径 | 职责 |
| --- | --- |
| `repo_agent/config.py` | `RunConfig` / `Budget`：换成字典配置的入口，预算是硬上限 |
| `repo_agent/state.py` | `AgentState`：图的显式状态契约（messages 走 `add_messages` reducer） |
| `repo_agent/graph.py` | 状态机：`agent → tools → (继续?) → agent ... → finalize`，两条条件边 |
| `repo_agent/tools.py` | 6 个工具（view / create_file / replace_in_file / insert_lines / bash / submit）+ 安全守卫 |
| `repo_agent/guard.py` | 路径与范围守卫：可写白名单、受保护 glob、`.git` 禁写 |
| `repo_agent/sandbox.py` | `LocalSandbox`（开发/测试）与 `DockerSandbox`（生产隔离，命令经 stdin 管道送入容器） |
| `repo_agent/proc.py` | `run_bounded`：独立进程组 + 整树击杀，沙箱与 harness 共用（否则 Windows 上"超时"不约束墙钟） |
| `repo_agent/patch.py` | 补丁契约：采集、解析、受保护文件校验、`git apply --check` |
| `repo_agent/llm.py` | `LiteLLMClient`（真实调用与计费）与 `ScriptedLLM`（离线确定性回放） |
| `repo_agent/runner.py` | 组装一切，返回 `RunResult`，落盘 `patch.diff` / `trace.jsonl` / `NOTES.md` / `result.json` |
| `repo_agent/task.py` | 克隆 + 基线检出 + 仓库概览（`core.autocrlf=false` 在 clone 时传入，否则补丁不可信） |
| `repo_agent/cli.py` | `run` / `eval` 两个子命令 |
| `harness/run_eval.py` | 评估 harness：任务有效性门禁 → 跑 Agent → 契约校验 → 应用到干净检出 → 判定与统计 |
| `tests/` | 42 个离线测试（脚本模型，无需 API key / 网络 / Docker） |
| `tasks/` | 任务集：`golden.jsonl` + Issue 文本 + 夹具补丁；造任务的完整流程与坑见 `tasks/README.md` |
| `tools/` | `make_fixture.py`（造夹具并审计"未来"是否泄漏）、`split_pr_diff.py`（切 PR 补丁）、`md_to_docx.py`（Markdown → Word） |
| `BASELINE.md` | 基线记录：任务集、每次运行的 pass@1 / 步数 / token / 费用 / 变更说明 |
| `工作日志.md` | 追加式日志：每天做了什么、拿到什么数据、修了什么、明天从哪儿接着干 |

## 跑起来

> 文档索引：`计划书.md`（目标、里程碑、验收线）、`实施步骤.md`（逐步操作手册）、`工作日志.md`（当日进展与交接）。
>
> 下面命令以 Windows PowerShell 为例，项目位于 `D:\repo-agent`。

离线自检（不需要任何密钥、网络或 Docker）：

```powershell
cd D:\repo-agent
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

真实模型跑一个任务：

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."      # 密钥只放环境变量，绝不进仓库；LiteLLM 统一路由，换模型只改字符串
.\.venv\Scripts\python.exe -m repo_agent run `
  --repo D:\repo-agent\.repos\itsdangerous-126 `
  --commit <base-commit> `
  --issue-file issue.md `
  --test-command "D:/repo-agent/.venv/Scripts/python.exe -m pytest -q tests/test_itsdangerous/test_timed.py" `
  --model deepseek/deepseek-chat `
  --max-steps 20 --max-cost 2.0
```

生产隔离（Docker 后端，默认禁网、一次性容器）：

```powershell
.\.venv\Scripts\python.exe -m repo_agent run --repo ... --sandbox docker --image python:3.11-slim
```

批量评估：

```powershell
.\.venv\Scripts\python.exe -m repo_agent eval --tasks tasks\golden.jsonl `
  --model deepseek/deepseek-chat --out eval-runs\m2-golden-3
```

任务文件是 JSONL，每个任务的 `fail_to_pass` / `pass_to_pass` 是**命令列表**（成功 = 退出码 0），
所以不绑定 pytest，任意语言的测试命令都能接。示例任务会先用 `tests/make_toy_repo.py` 生成一个带 bug 的玩具仓库。
任务里还能带 `gold_patch`（参考修复），`--check-only` 会顺手证明"这个任务真的能解"：

```powershell
# 修前必失败 + 打上 gold 补丁必转绿 + 无回归；3 条任务约 20 秒、0 token
.\.venv\Scripts\python.exe -m harness.run_eval --tasks tasks\golden.jsonl --check-only
```

## 观测

每次运行在 `run_dir`（默认在**仓库外**的 `<workspace>.runs/<时间戳>`，所以不会污染 diff）产出：

- `trace.jsonl`：逐事件记录模型调用（tokens / 费用 / 耗时 / 工具名）、工具调用（参数、观察结果、是否被拒）、预算熔断、循环检测、最终契约判定。
- `NOTES.md`：把模型的推理文本外置为长期记忆——写进文件，对话窗口里只留一行摘要，避免长任务上下文膨胀。
- `patch.diff` / `result.json`：交付物与结构化结论。

## 已验证 / 未验证

已验证（本机，`python -m unittest discover -s tests -t .` → 42 项全绿）：

- 脚本化闭环：复现 → 读文件 → 精确替换 → 重跑测试 → 提交，产出合法补丁并能应用到干净检出；
- 防作弊：写测试文件被工具层拒绝，`ok=False` 记录在 trace，补丁不含测试文件；
- 预算与循环：步数上限触发 `budget:steps`，重复同一调用触发 `no_progress:repeated_tool_call`；
- 契约：空补丁、改测试、不可应用的补丁都被判失败；
- harness：修好的任务记为 pass；`fail_to_pass` 本来就通过的任务被 `pre_check` 门禁拦下；
  连 gold 补丁都解不开的任务被 `gold_check` 门禁拦下——两种都不浪费模型调用。
- 超时真的会掐断整棵进程树：`shell=True` 时超时只杀得掉 `cmd.exe`，`pytest` 这类**孙进程**
  仍握着 stdout 管道，于是后续读取永久阻塞——"180 秒超时"实际一路挂到人工干预（实测一次
  `pytest -q tests/` 挂了 5 分钟以上）。现在沙箱与 harness 都走 `repo_agent/proc.py` 的
  `run_bounded`（独立进程组 + `taskkill /F /T`），`tests/test_sandbox.py` 用"活得比 shell 久的孙进程"钉住这条。
- prompt 不泄漏出处：issue 文本里出现修复 SHA、PR 号或出处抬头，任务就从"诊断"变成"回忆"。
  `harness.run_eval.issue_leak` 在**克隆之前**拦下（通用出处标记 + 任务级 `leak_terms`），
  计为 `issue_leak` 阶段，既不烧 token 也不会被误记成模型失败；`tests/test_harness.py` 有 4 条离线测试。
- 模型没有"脏"工作区可用：`shell_hint` 曾让模型把临时脚本写到 `%TEMP%`，而 guard 拒绝工作区
  之外的任何路径——**提示词在教模型做工具禁止的事**，模型只能把脚本写进仓库，
  于是 4 个 scratch 文件、91 行调试输出进了补丁。现在 `prepare_workspace` 用
  `.git/info/exclude` 排除 `.repo-agent/`（本地生效、永不进 diff），提示词指向该目录；
  实测同一批 click 任务的补丁新增文件 4 个 / 91 行 → **0 / 0**（`tests/test_patch.py` 钉住）。
- 判定命令不留字节码：Python 会在"mtime 秒未变且文件长度未变"时复用旧 `.pyc`，而 `a - b` → `a + b`
  恰好同长度，于是正确补丁会被旧字节码判成失败、同长度的回归也能被判成通过。
  `run_shell` 现在一律带 `PYTHONDONTWRITEBYTECODE=1`，`tests/test_harness.py` 钉住这条。

真实运行（M3 任务集，20 条 / 4 个仓库）：同一批任务连跑 5 轮，pass@1 = **75% / 90% / 85% / 90% / 90%**
（均值 86%，极差 15 个点），平均 9.3–11.1 步、73k–90k token、$0.0074–$0.0088、28.6–50.4s。
20 条里 **19 条至少成功过一次**，唯一 5 轮全败的是 `click-unset-defaults`。
**逐任务波动 5 条（25%）**——Step 5 的"≤ 1 条"未达标；100 次运行里 21% 是被预算/熔断掐断的，
不是解题结束。单次 pass@1 这个数字本身不可信，诚实口径是区间 75–90%（见 `BASELINE.md` 结论 15–17）。

未验证：`DockerSandbox` 本机没有 Docker，只做了静态实现（命令经 stdin 送入、超时后 `docker rm -f`），
接真实仓库前需要在有 Docker 的机器上先跑通一次。

## 已知限制（下一步）

- 检索仍是最原始的“全仓文件清单 + 模型自己 rg”。M3 才上 Tree-sitter 切片 + BM25 + 向量 + 依赖图。
- 评估是串行的，单任务一次克隆；M3 要加并发、镜像缓存与跨任务复用。
- **评估完整性缺口**：`LocalSandbox` 跑在宿主机上，有网络，模型理论上可以 `git clone` 上游仓库或
  `curl` 原始文件来抄答案（夹具本身已经干净，但网络没堵）。`DockerSandbox` 的 `--network none`
  才真正堵住这条路，本机没有 Docker 所以尚未验证。
- 没有 checkpoint（`StateGraph.compile()` 未挂 checkpointer），中断后不能续跑；M4 接 Redis。
- `LocalSandbox` 无隔离，只能用于可信仓库的开发与测试，不能指向持有真实凭据的环境。
- `LocalSandbox` 在 Windows 上就是 `cmd.exe`：模型必须先被告知这一点（已在提示词里声明，
  见 `BASELINE.md` 的两次 A/B：把"shell 方言 / 已在仓库根目录 / 别写长 `python -c`"讲清楚，
  步数 −41%、token −49%、费用 −54%）。真实任务建议直接走 Docker（Linux + bash）避免方言问题。
- 编辑工具的行尾策略按文件自身保留（LF 文件保持 LF、CRLF 保持 CRLF），`tests/test_editor.py` 守着这条。
- 补丁采集用 `git add -A -N` + `git diff`，所以未跟踪、**且未被 `.gitignore` 覆盖**的临时文件
  会进入补丁（上游仓库通常已忽略 `.pytest_cache/` 之类，但这是运气而不是设计）。
- 任务集 20 条仍然偏易：14 条单文件、参考修复 1–15 行，6 条跨文件（最多 3 个文件）。
  缺"十几个文件的大改"和"必须读懂调用方才能改对"的样本，pass@1 仍有虚高成分。
- 模型习惯顺手跑整仓测试套件（werkzeug 上 `pytest -q tests/` 会撞命令超时，现为 90s），
  延迟因此波动很大；提示词已把这条成本讲明白（见 `BASELINE.md` 的第三次 A/B），但没有硬阻断。
  5 轮里被超时吃掉的墙钟**全部**来自同一条任务（占全部 bash 时间 0%–68%）——限时调小只让浪费便宜，不会消掉冲动。
- 判分粒度是"整条任务全绿"：`itsdangerous-tz-aware` 修前 22 条失败，
  模型漏掉任何一个 datetime 分支就整条失败，看不出"已经修了八成"。要做部分给分得换指标。
- 还没有 GitHub Webhook / Actions 接入，也没有 LangSmith / OTLP 导出；那是 M6–M7。
