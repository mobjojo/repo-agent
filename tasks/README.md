# 任务集（golden set）

一个"任务"= 一个仓库夹具 + 一段 Issue 文本 + 判定命令。任务不是凭空写的，
而是从**已合并的真实修复**反推出来的，这样 gold patch 与测试都是客观的。

任务集文件是 `tasks/golden.jsonl`（一行一个任务）。单个任务的 issue 正文放在同目录的
`tasks/*.issue.md`，夹具与补丁放在 `tasks/fixtures/<任务id>/`。

## 任务文件的字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | ✅ | 任务标识 |
| `repo` | ✅ | 本地仓库夹具路径（或 clone URL）；**不是**上游原始仓库 |
| `base_commit` | | 夹具里已包含基线，通常留空 |
| `issue` / `issue_file` | ✅ | Issue 正文，或相对本目录的 `.md` 文件 |
| `test_command` | | 给 Agent 看的复现命令（写进提示词） |
| `fail_to_pass` | ✅ | 修前必须失败、修后必须通过的命令列表（用**单个测试节点**） |
| `pass_to_pass` | | 修前修后都必须通过的命令列表（防回归） |
| `gold_patch` | | 参考修复补丁（相对本目录）。只给 harness 用，Agent 看不到；`--check-only` 靠它证明任务可解 |
| `leak_terms` | | 不许出现在 issue 正文里的字符串（修复 SHA、PR 号、修复提交标题）。克隆之前就会被拦下 |
| `env` | | 任务级环境变量，同时注入 Agent 沙箱与判定命令，如 `{"PYTHONPATH": "src"}` |
| `protected_globs` | | 覆盖默认的只读范围（默认已含 `**/tests/**`、`**/test_*.py`、`**/setup.cfg` 等） |
| `model` / `max_steps` | | 单任务覆盖模型或步数预算 |

## 从一条真实修复造一个任务

```powershell
cd D:\repo-agent

# 1) 拉全量历史。GitHub API 经常限流，但 git 不受影响，所以优先走历史而不是 API
git clone --config core.autocrlf=false https://github.com/pallets/itsdangerous work\itsdangerous-full

# 2) 找到"修了什么"：同时改了 src/ 与 tests/ 的提交才是候选
git -C work\itsdangerous-full log --oneline -- src/itsdangerous
git -C work\itsdangerous-full show <fix-sha> --stat
#    CHANGES.rst 里的 :issue:`n` / :pr:`n` 是最可靠的任务出处

# 3) 造夹具：--fix 会自动把 tests/ 切进 test.patch、把 src/ 切进 gold.patch，
#    并且会强制清掉上游的未来。补丁必须写成 LF —— PowerShell 的 | Out-File 会写
#    CRLF，git apply 直接拒绝。
.\.venv\Scripts\python.exe tools\make_fixture.py `
  --source work\pallets-click-full --commit <base> --fix <fix> `
  --dest .repos\<id> --fixtures-dir tasks\fixtures\<id> `
  --message "task fixture: add failing test for <issue>"

# 4) 写任务行到 tasks/golden.jsonl，然后零成本校验：修前必失败 + gold 必能解 + 不回归
.\.venv\Scripts\python.exe -m harness.run_eval --tasks tasks\golden.jsonl --check-only
```

### 三条踩过的坑

**必须打测试补丁。** 如果缺陷是"PR 新增的测试"暴露出来的，而夹具里没有这个测试，
Agent 修完之后 `fail_to_pass` 依然找不到测试文件 → 任务永远不可能通过。

**必须清掉未来。** 直接 `git clone` 出来的夹具带着 remote 和上游全部历史，
Agent 一句 `git show <fix-sha>` 就能抄答案，而所有指标看上去都正常。
`make_fixture.py` 会删 remote、删多余分支与标签、`gc --prune=now`，
最后审计"可达提交数 = 基线祖先数 + 夹具自己的提交数"。

**出处不许进 prompt。** 这一条是 M3 首轮真踩出来的：`click-unset-defaults` 的 issue
首行写着"上游已合并修复 `1c20dc6`（Fix default handling to defer UNSET normalization）"，
模型在笔记里第 7 步就开始"look at the upstream fix `1c20dc6`"——任务从"诊断"变成了"回忆"，
而产物一点也不难看：它表现为一次异常便宜的通过（或一次昂贵的卡死）。
现在出处只留在本文件的表格里；`harness.run_eval.issue_leak` 会在**克隆之前**
用 `leak_terms` + 通用出处标记（`来源：`/`提交者：`/`已合并修复`）拦下，
判定为 `issue_leak` 阶段，既不烧 token 也不会被记成模型失败。

### 一个 PR 拆成多个提交时

按**整个 PR**造任务，不要只取其中一个提交：只取一半会把"修了一半"的状态当成基线。
`itsdangerous-296` 就是这种情况（PR #296 有 3 个提交：先加测试、再接 `ValueError`、再接 `OSError`）。

## 当前任务集（20 条）

表格里的出处只供人造任务时追溯，**不进 prompt**。

| 任务 | 上游出处（repo / base / fix） | 判定（`fail_to_pass` 节点） | 参考修复规模 |
| --- | --- | --- | --- |
| `itsdangerous-126` | itsdangerous / `1a9b8d1` / PR #133 | `test_timed.py::TestTimestampSigner::test_future_age` | 1 文件 +7 |
| `itsdangerous-124` | itsdangerous / `b11475a` / `526b1ea` | `test_timed.py::TestTimestampSigner::test_sig_error_date_signed` | 1 文件 +3 |
| `itsdangerous-296` | itsdangerous / `3b76264` / PR #296 | `test_timed.py::TestTimestampSigner::test_malformed_future_timestamp` | 1 文件 +7 −1 |
| `click-echo-empty` | click / `d42f15b` / `4d3db84` | `test_utils.py::test_echo_custom_file` | 1 文件 +8 −8 |
| `click-funcparamtype` | click / `5b9630f` / `fc6c7c4` | `test_types.py::test_func_param_type_uses_value_error_message` | 1 文件 +9 −6 |
| `click-show-default` | click / `878de46` / `607316f` | `test_options.py::…` **+** `test_termui.py::…`（两个节点） | 2 文件 +12 −5 |
| `click-unset-defaults` | click / `6a1c0d0` / `1c20dc6` | `test_defaults.py::test_shared_param_prefers_first_default` | 1 文件 +11 −5 |
| `packaging-wheel-regex` | packaging / `9c6f09b` / `8af7590` | `test_utils.py::test_parse_wheel_invalid_filename` | 1 文件 +1 −1 |
| `packaging-tag-count` | packaging / `a33b294` / `f0620a9` | `test_tags.py::TestParseTag::test_invalid_component_count_raises` | 1 文件 +10 −4 |
| `packaging-dep-groups` | packaging / `cf100d2` / `30824d9` | `test_dependency_groups.py::test_resolution_collects_invalid_requirement_with_sibling_errors` | 1 文件 +5 −4 |
| `werkzeug-range-zero` | werkzeug / `12abecb2` / `0c419f95` | `test_http.py::TestRange::test_range_parsing` | 1 文件 +5 |
| `werkzeug-if-range-etag` | werkzeug / `cc89c44f` / `8e9105fb` | `test_http.py::TestRange::test_if_range_parsing` | 2 文件 +18 −9 |
| `werkzeug-int-url` | werkzeug / `a2bf38cf` / `ab16e62d` | `test_routing.py::test_int_converter_404` | 2 文件 +8 −3 |
| `packaging-interp-tags` | packaging / `826426fc` / `26fa1d42` | `test_tags.py::TestParseTag::test_invalid_interpreter_raises` **+** `test_utils.py::test_parse_wheel_invalid_filename` | 2 文件 +15 −10 |
| `packaging-specifier-group` | packaging / `de6580e6` / `f14a0933` | `test_specifiers.py::TestSpecifier::test_specifiers_invalid` | 1 文件 +3 −3 |
| `werkzeug-int-str-strict` | werkzeug / `efa80bff` / `b9761b5b` | `test_internal.py::test_plain_int` | 2 文件 +12 −9 |
| `werkzeug-route-sort` | werkzeug / `05ff3fe4` / `6d7c0b4e` | `test_routing.py::test_part_converter_order` | 1 文件 +7 −6 |
| `werkzeug-url-empty-port` | werkzeug / `b2b281be` / `4da3786f` | `test_urls.py::test_uri_empty_auth` **+** `::test_uri_port_0` | 1 文件 +12 −6 |
| `click-deprecated-label` | click / `648d7c40` / `82f377c5` | `test_commands.py::…` **+** `test_options.py::…`（两节点） | 1 文件 +3 −2 |
| `itsdangerous-tz-aware` | itsdangerous / `3703fbde` / `910a7a94` | `test_itsdangerous/test_timed.py`（整文件，修前 22 条失败） | 3 文件 +26 −5 |

20 条全部通过 `--check-only`（修前必失败 + gold 补丁必转绿 + `pass_to_pass` 不回归）。
真实批次数字见 `../BASELINE.md`。

环境依赖：三条 packaging 任务需要 `pretend`；三条 werkzeug 任务的 `tests/conftest.py`
需要 `ephemeral-port-reserve`（连同 `pytest-timeout`、`watchdog`、`cffi`、`cryptography`
一起装进了 `.venv`）。`click`/`packaging`/`werkzeug` 都靠 `env.PYTHONPATH=src` 走夹具内的源码。

### 难度与取向

- 20 条里 14 条是单文件、参考修复 1–15 行，用途是校准链路、提示词与成本，不是压榨模型；
  6 条跨文件（`click-show-default`、`werkzeug-if-range-etag`、`werkzeug-int-url`、
  `packaging-interp-tags`、`werkzeug-int-str-strict`、`itsdangerous-tz-aware`）。
- **陷阱类**（行数不等于难度）：
  - `packaging-wheel-regex`：`^[\w._]+$` 里的 `$` 允许尾随换行，必须写成 `\Z`；
  - `packaging-specifier-group`：Unicode 大小写折叠让 `ı`/`ſ` 伪装成 `i`/`s`，版本段必须 ASCII-only；
  - `werkzeug-int-str-strict`：`int("0x7B", 16)` 本身是合法的，但契约只接受十进制写法；
    而 `\u2029` 在 `str.strip()` 眼里是空白、在 `int()` 眼里不是；
  - `werkzeug-url-empty-port`：空 userinfo 与端口 `0` 是"存在但为空"，不是"不存在"。
- **规模类**：`itsdangerous-tz-aware` 是第一条"整文件级"任务（修前 `test_timed.py` 22 条失败，
  要求把 datetime 全面改成 timezone-aware UTC，跨 `timed.py`/`jws.py`/`exc.py` 三个文件）。
- `itsdangerous-296` 是唯一带平台差异的：Windows 上是 `OSError`、Linux 上是 `ValueError`。
- `pass_to_pass` 能抓到"修好了这个、弄坏了那个"的语义回归：M3 第三轮里 `click-unset-defaults`
  就是这样被拦下的（`fail_to_pass` 转绿、`pass_to_pass` 变红）。
