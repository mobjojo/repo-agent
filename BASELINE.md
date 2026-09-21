# 基线记录

规则：**同一任务集 + 同一 base commit + 同一模型**才有可比性；每次改动只追加一行，并写清"改了什么"。
单条任务的噪声很大，这里的数字只用来做**单变量对照**和证明链路，不用来宣称效果。

## 任务集（20 条）

出处（仓库 / base / fix）与造任务命令见 `tasks/README.md`；这里只登记"考什么"。

| 任务 | 缺陷类型 | 难度 |
| --- | --- | --- |
| `itsdangerous-126` | 逻辑缺陷：未来时间戳被判为有效 | 低（gold 1 文件 +7） |
| `itsdangerous-124` | 异常属性类型不一致：`date_signed` 是 int | 低（gold 1 文件 +3） |
| `itsdangerous-296` | 日期溢出导致异常逃逸（Windows `OSError` / Linux `ValueError`） | 中（两种异常都要接住） |
| `click-echo-empty` | 空 `bytes` 走文本分支写出 `str`，二进制流出错 | 低 |
| `click-funcparamtype` | 自定义转换器的 `ValueError` 文案被丢掉 | 中 |
| `click-show-default` | `show_default` 传字符串时交互提示不显示 | 中（gold 跨 2 文件） |
| `click-unset-defaults` | 多个选项共享参数名时默认值取错（`UNSET` 归一化过早） | 中 |
| `packaging-wheel-regex` | 正则陷阱：`^[\w._]+$` 的 `$` 允许尾随换行 | 低（gold 1 行，但要点在 `\Z`） |
| `packaging-tag-count` | 组件数不为 3 时抛裸 `ValueError` 而非 `InvalidTag` | 低 |
| `packaging-dep-groups` | 非法 requirement 让同组已收集的兄弟错误一起丢失 | 中（要读懂错误聚合） |
| `werkzeug-range-zero` | `bytes=-0` 被解析成"整个文件" | 低 |
| `werkzeug-if-range-etag` | 弱 ETag 被当强 ETag 用于 `If-Range` | 中（gold 跨 2 文件） |
| `werkzeug-int-url` | 超长数字串让 `<int:>` 抛 `ValueError` 而非 404 | 中（gold 跨 2 文件） |
| `packaging-interp-tags` | interpreter 段未校验：非法标签与被它污染的 wheel 文件名都被接受 | 中（gold 跨 2 文件） |
| `packaging-specifier-group` | Unicode 大小写折叠让 `ı`/`ſ` 冒充 `i`/`s`（版本段必须 ASCII-only） | 低行数 / 高陷阱 |
| `werkzeug-int-str-strict` | `_plain_int` 接受 `0x` 前缀与非 ASCII 空白 | 中（gold 跨 2 文件） |
| `werkzeug-route-sort` | 同段内多个转换器的内部组名按字符串排序 → 参数静默错位 | 中 |
| `werkzeug-url-empty-port` | 空 userinfo / 端口 `0` 被当成"不存在"丢掉 | 中 |
| `click-deprecated-label` | help 为空时 `(DEPRECATED)` 多一个前导空格 | 低 |
| `itsdangerous-tz-aware` | datetime 混用 aware/naive，且用了已弃用的 `utcfromtimestamp` | 高（3 文件 / 修前 22 条失败） |

前四条历史记录跑在**旧夹具**（`7a57910`，带 remote 与上游全部未来历史，见结论 4）上，与后面的数字不可直接比较，
保留它们只是为了记录"提示词/工具改了之后步数如何变化"这个趋势。

## 运行记录

| 日期 | 任务集 | 模型 | 任务数 | pass@1 | 平均步数 | 平均 token | 平均费用 | 平均延迟 | 本次变更 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-09-16 | m2-001（旧夹具） | `deepseek/deepseek-chat` | 1 | 100% | 13 | 71,639 | $0.0135 | 27.6s | 基线：M1 框架首次跑真实任务 |
| 2026-09-16 | m2-001（旧夹具） | 同上 | 1 | 100% | 13 | 71,639 | $0.0135 | 27.6s | 复跑一次，确认可复现 |
| 2026-09-16 | m2-001（旧夹具） | 同上 | 1 | 100% | 12 | 62,781 | $0.0075 | 25.4s | 修 `Path.write_text` 行尾污染（补丁从"整文件重写"变成 7 行最小改动） |
| 2026-09-16 | m2-001（旧夹具） | 同上 | 1 | 100% | 6 | 29,050 | $0.0069 | 21.9s | 提示词声明 shell 方言（单变量 A/B） |
| 2026-09-16 | m2-001（新夹具） | 同上 | 1 | 100% | 10 | 58,589 | $0.0131 | 26.6s | 夹具重建去掉 remote 与未来历史；该次轨迹还顺手改了 `CHANGES.rst`，所以步数回升 |
| 2026-09-16 | golden（3 条） | 同上 | 3 | 100% | 10.67 | 68,501 | $0.0164 | 25.4s | 任务集扩到 3 条；harness 新增"gold 补丁必须能解"门禁（A/B 前的对照） |
| 2026-09-16 | golden（3 条，A/B） | 同上 | 3 | 100% | 6.33 | 34,807 | $0.0076 | 19.3s | 提示词补两条环境事实：命令已在仓库根目录、cmd 下别写长 `python -c` |
| 2026-09-16 | golden（3 条） | 同上 | 3 | 100% | 6.67 | 37,780 | $0.0086 | 20.5s | 修 harness 的过期字节码漏洞后重跑；**这一行才是当前可信基线**（前两行的判定链路有缺陷） |
| 2026-09-18 | golden（13 条） | `deepseek/deepseek-chat` | 13 | 84.62% | 9.00 | 59,388 | $0.0137 | 49.6s | M3 首轮：任务集 3 → 13 条（换入 click / packaging / werkzeug）；issue 正文**带着出处**（结论 9）；沙箱超时缺陷让一条跑到 333.8s |
| 2026-09-18 | golden（13 条） | 同上 | 13 | 84.62% | 9.31 | 72,631 | $0.0150 | 68.8s | **当前可信基线**：issue 正文去掉出处（`issue_leak` 门禁上线）+ 修掉沙箱超时（整树击杀）。三条 werkzeug 各被"整仓测试"吃掉 180s，延迟因此虚高 |
| 2026-09-18 | werkzeug（3 条 A/B） | 同上 | 3 | 100% | 9.67 | 73,186 | $0.0109 | 27.1s | 第三次提示词 A/B：把"单条命令 180s 会被杀 / 整仓套件很慢"写成环境事实 → 整仓测试 3 次 → **0 次**，延迟 −87%（对照=上一行里同三条的 205.3s），token +36% 但都花在真活上 |
| 2026-09-20 | click（4 条 A/B） | `deepseek/deepseek-chat` | 4 | 50.00% | 11.50 | 88,585 | $0.0073 | 26.0s | 第四次单变量改动：把"临时脚本放 `%TEMP%`"改成工作区内、被 `.git/info/exclude` 排除的 `.repo-agent/`——提示词原本在教模型做 guard 禁止的事。补丁新增文件/行数 **4 个 / 91 行 → 0 / 0**；`click-unset-defaults` 被 `pass_to_pass` 拦下（目标用例转绿、`test_options.py` 60 条变红） |
| 2026-09-20 | golden（20 条） | 同上 | 20 | 75.00% | 9.85 | 80,794 | $0.0077 | 47.4s | **Step 4 完成 + 当前可信基线**：任务集 13 → 20 条。失败分布 `fail_to_pass` 3 / `empty_patch` 2；首次真实触发循环熔断（`no_progress:repeated_tool_call`）与 token 预算熔断。整批被超时吃掉的墙钟 361s（占全部 bash 时长 68%），且全部来自同一条任务 |
| 2026-09-20 | golden（20 条，复跑） | 同上 | 20 | 90.00% | 10.10 | 81,965 | $0.0074 | 38.5s | 同配置复跑，用于量化波动：**3 条翻转（15%）**，且全部是"第一轮失败 → 第二轮通过"——三条第一轮失败都源于预算/熔断（`max_steps` 用尽、token 上限 217k、`no_progress:repeated_tool_call`）。两轮都失败的只有 `click-show-default` / `click-unset-defaults`（同仓库同类题）。超时第二轮复现：180.3s 来自同一条任务，占全部 bash 时长 56% |
| 2026-09-20 | golden（20 条，t90） | 同上 | 20 | 85.00% | 9.25 | 73,632 | $0.0077 | 31.7s | 单变量：命令超时 180s → 90s。全部 bash 执行时间 321.5s → 214.7s、整批墙钟 −18%，pass@1 落在 5 轮噪声带内。超时命中仍然全部来自同一条任务（`werkzeug-int-str-strict` 想一次跑 6 个测试文件） |
| 2026-09-20 | golden（20 条，s20） | 同上 | 20 | 90.00% | 9.95 | 83,529 | $0.0074 | 28.6s | 单变量：步数预算 15 → 20（18 条任务）。`click-show-default` 前三轮 3/3 全败、本轮 **20 步一次通过** → 它是被预算饿死，不是不会做；代价是 `werkzeug-int-str-strict` 连撞 3 次 90s 超时、375s 才通过 |
| 2026-09-20 | golden（20 条，w5） | 同上 | 20 | 90.00% | 11.05 | 90,387 | $0.0088 | 50.4s | 单变量：熔断 3 次硬停 → 3 次警告 / 5 次终止。**空结果**：该轮 0 条任务触发 3 连重复（全批 `loop_warning` 事件 0 条），改动没被踩到，90% → 90% 属采样噪声，不能归因 |

## 结论

（1–8 写于 M2 阶段；9–18 是 M3 的新结论。当前可用数字取运行记录最后五行——那五行是同一批任务、同一个框架的连续迭代。）

1. **链路成立**：3 条真实任务全部修好（pass@1 3/3），补丁都通过了契约校验、干净检出应用、
   `fail_to_pass` 转绿、`pass_to_pass` 不回归。其中 `itsdangerous-126` 与 `itsdangerous-124`
   产出的补丁与上游修复**逐字节一致**（blob `2ae0261..656bc16`、`656bc16..178322f`）。
2. **单变量 A/B 有收益（两次）**：
   - 声明 shell 方言 → 步数 −50%、token −54%（旧夹具，任务 1）；
   - 补上"已在仓库根目录，别 `cd`"与"cmd 下别写长 `python -c`" → 平均步数 −41%、token −49%、
     费用 −54%（3 条任务集）。两批补丁语义等价，说明省下来的是纯粹的浪费回合。
3. **零成本门禁先于贵实验**：`--check-only` 跑 3 条任务只要 20 秒、0 token，就能证明
   "修前必失败" 且 "打上 gold 补丁必转绿"。没有这道门禁，"夹具忘了打测试补丁"这类错误
   会伪装成模型失败，一直算在模型头上。
4. **夹具泄题是最隐蔽的评估污染**：原来的夹具是直接 `git clone` 出来的，带着 remote 和
   上游全部 679 个提交——Agent 只要 `git show <fix>` 就能抄到答案，而一切指标看上去正常。
   现在 `tools/make_fixture.py` 强制 `--forbid <fix-sha>`，并在结束时审计可达提交数、
   remote 与目标提交是否真的消失。
5. **判定链路自己也会撒谎：过期字节码。** 这条是靠 harness 的 `gold_check` 门禁**间歇性失败**
   才暴露的：Python 在"源文件 mtime 秒未变 **且** 字节长度未变"时会直接复用旧 `.pyc`，
   而 `a - b` → `a + b` 恰好是同长度。于是预检那次运行写下的旧字节码替补丁后的运行"作答"，
   正确补丁被判失败；反过来，同长度的回归也能藏在旧 `.pyc` 后面被判通过。两个方向都出现过。
   离线测试抓不到它（56 项全绿），因为它只在"判定命令自己写字节码"时发生。
   已修：`run_shell` 一律带 `PYTHONDONTWRITEBYTECODE=1`（与沙箱一致），并加了回归测试
   `test_verification_commands_leave_no_bytecode_behind` 钉住这条。
   **因此上面 A/B 那两行的绝对数字不算数，只有结论 2 的相对变化可用；当前基线取最后一行。**
6. **补丁文本不稳定，行为稳定**：同一任务两次运行的补丁并不逐字节相同
   （`itsdangerous-296` 出现过三种写法：多接住 `OverflowError`、只接 `(ValueError, OSError)`、
   以及把溢出归入既有的"Malformed timestamp"分支），但都通过全部测试。所以判分只认行为，
   不认与 gold patch 的字节一致性——这也是 `pass@1` 能当指标、而"补丁相似度"不能的原因。
7. **离线测试抓不到的 bug，真实运行抓得到**：编辑工具在 Windows 上把 LF 重写成 CRLF，
   一行修复变成整文件 diff；当时离线测试全绿，只有真实运行暴露了它（已补 `tests/test_editor.py`）。
8. **已知的评估完整性缺口**：`LocalSandbox` 跑在宿主机上，有网络——模型理论上可以
   `git clone` 上游仓库或 `curl` 原始文件来抄答案（夹具本身已经干净，但网络没堵）。
   `DockerSandbox` 用 `--network none` 堵住了这条路，本机没有 Docker，所以这条尚未验证。
9. **prompt 泄题——第三类评估污染，而且最难自查。** M3 首轮我给 4 条 issue 写了
   "来源：上游已合并修复 `1c20dc6`（Fix default handling to defer UNSET normalization）"这类抬头。
   模型在第 7 步的笔记里就开始"look at the upstream fix `1c20dc6`"——任务从**诊断**变成**回忆**，
   而产物一点不难看：`click-unset-defaults` 那次它 15 步全用来找答案、最终交白卷（`empty_patch`），
   去掉出处后同一个任务变成"动手改但没改对"（`fail_to_pass`）。**同一个 pass@1（11/13），
   完全不同的行为**，只看汇总数字根本发现不了。
   现在出处只留在 `tasks/README.md`；`harness.run_eval.issue_leak` 在克隆之前用通用出处标记
   （`来源：`/`提交者：`/`已合并修复`）+ 任务级 `leak_terms` 拦下，判定为 `issue_leak`。
10. **"超时"曾经不是超时。** `subprocess.run(shell=True, timeout=180)` 在 Windows 上只杀得掉
    `cmd.exe`；`pytest` 是孙进程，仍握着 stdout 管道，于是后续读取永久阻塞。实测
    `pytest -q tests/` 挂了 5 分钟以上，一条任务的 `duration_s` 记成 333.8s——它既不是模型慢，
    也不是任务难，纯粹是工具在等一个早已被杀掉的壳。改为 `run_bounded`（独立进程组 +
    `taskkill /F /T` 整树击杀）后，超时才真正约束墙钟。
11. **提示词第三次 A/B 依然是最便宜的优化。** 只加一句环境事实（"单条命令 180s 会被杀，
    有些套件比周围代码慢得多，跑窄命令别跑整个套件"），三条 werkzeug 任务的整仓测试次数
    3 → 0，平均延迟 205.3s → 27.1s（**−87%**），pass@1 仍 3/3。代价是 token +36%：
    那 180 秒从"等待"变成了"干活"——花掉的 token 换回了三倍的墙钟时间。
12. **提示词不能在教模型做工具禁止的事。** `shell_hint` 一直写着"把临时脚本写到 `%TEMP%`"，
    而 `Guard.rel()` 明确拒绝工作区之外的任何路径。模型只能退而把脚本写进仓库根目录，
    于是 `click-show-default` / `click-unset-defaults` 两条任务的补丁里各有 2 个 scratch 文件，
    合计 91 行调试输出——其中一条的补丁**全部**是 scratch 文件。
    修法不是"再叮嘱一遍"，而是消掉矛盾：`prepare_workspace` 现在通过 `.git/info/exclude`
    排除 `.repo-agent/`（只对本检出生效，永远进不了 diff），提示词指向该目录。
    同一批任务的补丁新增文件/行数从 **4 / 91 降到 0 / 0**，并且轨迹显示模型真的在用那个目录。
13. **`pass_to_pass` 拦下的不是噪声，是假通过。** M3 第四轮里 `click-unset-defaults` 的补丁只有
    5 行（`src/click/core.py` 里给 `UNSET` 加一个条件），目标用例转绿，但
    `tests/test_options.py` **60 条**变红（`flag_value` / `envvar` 与 default 的交互全被打坏）。
    没有回归门禁，这条会被记成一次漂亮的通过——`fail_to_pass` 只说明"修好了被报告的那个"。
14. **预算与熔断第一次真的生效**（此前只有离线测试）：`packaging-interp-tags` 撞的是 **token**
    上限（217k，改了 `tags.py` 却漏了 `utils.py`，两条 `fail_to_pass` 只绿一条）；
    `werkzeug-url-empty-port` 触发 `no_progress:repeated_tool_call`（7 步就停，空补丁）；
    `werkzeug-int-str-strict` 两次把 180s 的超时跑满（模型要一次跑 6 个测试文件）。
    最后这条也说明第三次 A/B 只是**减少**了整仓跑测试的冲动，没有消除：整批 20 条里被超时吃掉的
    361s 全部来自它，占全部 bash 执行时间的 68%。

15. **5 轮真实批次的总账：pass@1 75 / 90 / 85 / 90 / 90（均值 86%，极差 15 个点）。**
    同一批 20 条任务、同一份代码，只改预算/超时/熔断各一次，连跑 5 轮：**波动 5 条（25%）**，
    Step 5 要求"≤ 1 条"，未达标。但 20 条里 **19 条至少成功过一次**，
    唯一 5 轮全败的是 `click-unset-defaults`（同一仓库同类题 `UNSET`/default 语义）。
    逐任务稳定性：14 条 5/5、5 条不稳定（`itsdangerous-296`、`click-show-default`、
    `packaging-interp-tags`、`werkzeug-int-str-strict`、`werkzeug-url-empty-port`）、1 条 0/5。
    100 次运行合计：`ok` 86、`fail_to_pass` 6、`empty_patch` 8；
    终止原因 `submitted` 78、`budget:steps` 14、`budget:tokens` 5、`no_progress:repeated_tool_call` 2、
    `agent_finished` 1——**21% 的运行是被天花板掐断的，不是解题结束。**
    所以"单次 pass@1"这个数字本身不可信，诚实的口径是**区间 75–90%，均值 86%**。

16. **"稳定失败"和"不会做"是两件事，汇总数字分不出来。** `click-show-default` 在 15 步预算下
    连续 3 轮失败（每次把 13–16 万 token 和 15 步全部用完），看起来像"这题模型就是不会"。
    把预算放宽到 20 步，它一次通过（20 步、20.4 万 token）。同一份代码、同一个模型、
    同一个任务：**唯一变量是预算，结论从"不会"变成"没喂饱"。**
    反面同样成立：`werkzeug-int-str-strict` 在 15 步时"循环熔断、10 步空补丁"，
    在 20 步时"连撞 3 次 90s 超时、375s"才通过——放宽预算不是免费的，它把成本从"失败"挪到了"墙钟"。

17. **超时是症状，不是病；"被预算打断"也不等于失败。** 5 轮里被超时吃掉的墙钟**全部**来自
    `werkzeug-int-str-strict` 一条任务（占全部 bash 时间 68% / 56% / 42% / 0% / 52%），
    它想要的是整仓 pytest（数分钟），提示词只能降低频率、不能消除冲动；把限时 180s → 90s
    只是让这次浪费便宜一半。另一侧：21 次由天花板终止的运行里 **8 次其实已经改对了**，
    只是没走到 `submit`（`stop_reason=budget:steps` 而 `stage=ok`）——`finalize` 在终止时照常
    采集工作区 diff 的设计在这里救回了 8 次误判。真正零产出的是 8 次空补丁，其中 2 次是循环熔断：
    模型重复的是一条**只读探针**（`python -c "print(int('0x7B',16))"`），它在验证 Python 语义而不是死循环，
    被一刀砍掉时手上什么都没有。这就是把硬停改成"第 3 次警告、第 5 次终止"的动机，
    但 w5 那轮没有任务触发它——**改动离线有测试（43 项）、线上无证据**，不能算已验证。
18. **每批 20 条的墙钟构成（测出来的，不是估的）**：模型 30% / bash 44% / 事后验证 26%，
    其中**纯超时浪费占全部墙钟 23%**（5 批 902s），且几乎全部来自同一条任务想跑整仓 pytest
    （`werkzeug-int-str-strict`，5 轮里 4 轮都撞，w5 一轮空等 271s）。
    对照：夹具克隆只有 0.48s/次，准备阶段不是瓶颈——**别优化以为的瓶颈**。
    可压缩空间：硬阻断整仓 pytest（−23%）+ 并发并把验证与下一条任务重叠（÷3），
    一批 975s → 250–300s，成本不变。这也是后面每个 Step 迭代变快的复利所在。

19. **"整批墙钟"曾经是个错的数——而它恰好是并发工作的唯一验收指标。** `tools/daily_report.py`
    把这一列算成逐条 `duration_s` 之和：`--jobs 4` 那行写 674.5s，真实墙钟 171.8s，
    而同一行的说明列还写着"187s"，一行之内自相矛盾。现在改成从 trace 实测
    （首条 `run_start` → 末条 `run_end`），缺 `run_end` 的中断批次退回求和并标 `~`；
    已有批次行按新口径刷新（串行批次也略变小，因为求和把任务之间的间隔也算成了运行时）。
    教训：**汇总口径一错，再好的实验也说不清结论**——并发的收益正是被这个数抹掉的。

20. **凭证/模型名错误会被记成"模型失败"。** 漏设 `DEEPSEEK_API_KEY` 的那一轮，
    模型调用抛 `AuthenticationError` → 循环记 `llm_error` 停止 → 无补丁 → 20 行 `empty_patch`，
    40 秒跑完。表上看起来是"模型一条都没改对"，实际上一次模型都没调到（token 花费为 0）。
    修法两层：`run_one` 把"零 token 就 `llm_error`"判成 `llm_error` 阶段（与 `harness_error` 同类，
    不计入模型失败），并且批次开始前先做一次 16-token 预检，密钥或模型名不对就立刻退出、不写批次
    （模型名写成 `deepseek-v4.1-flash` 会 400，同样属于该拦下的错误）。

21. **每条结果行现在自带 `budget` 字段（当轮生效的上限）。** 今天真出现过一次"任务文件悄悄回到
    默认值、整批在 20 步 / 200k 下跑完、却被当成预算实验"的情况。上限必须跟着结果走，
    不能只留在输入里——否则一个实验批次看起来和另一个一样，实际什么都没改。

22. **并发 4 实测：762.6s → 171.8s（4.4x），pass@1 与串行一致（18/20），0 次超时。**
    `--jobs` 只压缩墙钟：任务级异常单独记 `harness_error`，结果文件按任务集顺序重排，
    所以基线表不会被打乱。同配置复跑一轮（`j4c`）拿到 19/20 ——**同一份代码、同一份任务集、
    同一个模型，两次差 1 条**，这是批次级波动的下限，也是对外只能给区间的原因。

23. **Step 5 收口：预算标定（上限 = 1.5 × 观测成功上限）后波动仍未达标，但归因清楚了。**
    近 7 轮同 20 条任务：15 条 7/7 全胜、4 条波动、1 条全败，pass@1 区间 **85–95%**。
    4 条波动任务的共同点是**几乎每一轮都由天花板终止**：`click-show-default` 7/7 撞线、
    `packaging-interp-tags` 7/7 撞线、`click-unset-defaults` 6/7 撞线（另 1 轮 `agent_finished` 交白卷）、
    `werkzeug-int-str-strict` 2/7（另有一次 `no_progress` 熔断）。反过来，会自己 `submit` 的 16 条
    近 7 轮零波动。**所以波动不是"模型随机"，而是"这一次的终点由天花板决定"**——
    天花板落在哪一步取决于该步的累计 token，是最不可复现的量。
    标定确实摘掉了"靠终止后回收 diff 得到的通过"（这一轮 17 个通过全部以 `submitted` 收尾，
    对照 j4b 的 5 条撞线里 3 条被救回），但它**不能把"不会"变成"会"**：
    `packaging-interp-tags` 用掉 367k token 仍交白卷，`click-unset-defaults` 350k 用尽仍空补丁，
    代价是失败更贵（平均 token 108,511 → 115,393）。下一步的正确动作是让这些任务**能收尾**
    （接近量程时注入"现在必须提交"），而不是继续加量程。

24. **换模型先用探路批回答，再决定要不要换。** `--only` 挑 4 条任务跑一轮只要 $0.03 / 141s，
    足够回答"`deepseek-flash` 值不值得换"：同一样任务 14.0 步 / 16.5 万 token
    （chat 近 7 轮 10.5–12.4 步 / 9.3–11.5 万），输出单价贵 2.9 倍（$1.20/M vs $0.42/M），
    唯一优势是 1M 上下文，而这批任务用不到——**不换**。顺带一个坑：probe 的平均费用
    （$0.0072）比 chat 批次（$0.0080–$0.0108）还低，但那是输入/输出配比与 prompt 缓存命中率
    造成的混合单价差异（实测 chat ~$0.09/M token、flash ~$0.044/M token，都远低于价目表），
    **不能当作"更便宜"的证据**；比较模型要看步数与 token 的分项。

## 复现命令

```powershell
cd D:\repo-agent
$env:DEEPSEEK_API_KEY = "sk-..."
$env:PYTHONUTF8 = "1"

# 只验任务有效性：修前必失败 + gold 补丁必能解，不花 token
.\.venv\Scripts\python.exe -m harness.run_eval --tasks tasks\golden.jsonl --check-only

# 真跑 + 计分（产物保留在 eval-runs\<批次>\artifacts\<任务id>\）
.\.venv\Scripts\python.exe -m repo_agent eval --tasks tasks\golden.jsonl `
  --model deepseek/deepseek-chat --out eval-runs\m3-20260918b

# 并发 4（只压缩墙钟，pass@1 不变；约 3–4 分钟 / $0.22）
.\.venv\Scripts\python.exe -m harness.run_eval --tasks tasks\golden.jsonl `
  --model deepseek/deepseek-chat --jobs 4 --out eval-runs\<批次>

# 定向探路：只跑某几条任务（几分钱），用来确认某个改动真的被触发
.\.venv\Scripts\python.exe -m harness.run_eval --tasks tasks\golden.jsonl `
  --model deepseek/deepseek-chat --only click-unset-defaults --out eval-runs\<批次>

# 重新标定预算：从历史批次反推每条任务的上限
.\.venv\Scripts\python.exe tools\calibrate_budget.py --dry-run --markdown

# 留档：把批次数字写进工作日志的表格（重复运行是替换，不是追加）
.\.venv\Scripts\python.exe tools\daily_report.py <批次> --note "说明"
```
