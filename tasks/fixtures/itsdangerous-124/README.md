# 夹具：itsdangerous-124

`test.patch` / `gold.patch` 取自上游已合并的修复，照下面的命令即可重建，不需要走 GitHub API
（本机 GitHub API 常被限流，`git clone` 与 `git show` 不受影响）。

| 项 | 值 |
| --- | --- |
| 上游仓库 | https://github.com/pallets/itsdangerous |
| Issue | #124（维护者直接提交 `526b1ea`，无 PR） |
| base commit | `b11475a`（Merge pull request #153） |
| gold 修复 | 上游提交 `526b1ea` 的 `src/` 部分：`BadTimeSignature.date_signed` 统一为 `datetime` |
| 夹具提交 | `1c747a1`（base + `test.patch`） |
| 夹具自检 | 212 个可达提交、无 remote、无未来历史 |

## 重建

```powershell
cd D:\repo-agent
git clone --config core.autocrlf=false https://github.com/pallets/itsdangerous work\itsdangerous-full
.\.venv\Scripts\python.exe tools\make_fixture.py `
  --source work\itsdangerous-full `
  --commit b11475a `
  --dest .repos\itsdangerous-124 `
  --test-patch tasks\fixtures\itsdangerous-124\test.patch `
  --forbid 526b1ea `
  --message "task fixture: date_signed must be a datetime (#124)"
```

## 自检

```powershell
cd D:\repo-agent
.\.venv\Scripts\python.exe -m harness.run_eval --tasks tasks\golden.jsonl --limit 2 --check-only
```

依赖：`pytest`（已在本项目 venv 中）；测试通过 `env.PYTHONPATH=src` 导入 src 布局的包。
