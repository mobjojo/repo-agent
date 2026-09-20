# 夹具：itsdangerous-126

`test.patch` / `gold.patch` 取自上游已合并的修复，照下面的命令即可重建，不需要走 GitHub API
（本机 GitHub API 常被限流，`git clone` 与 `git show` 不受影响）。

| 项 | 值 |
| --- | --- |
| 上游仓库 | https://github.com/pallets/itsdangerous |
| Issue / PR | #126 / #133 |
| base commit | `1a9b8d1`（Merge pull request #151） |
| gold 修复 | 上游提交 `c30678d` 的 `src/` 部分：`age < 0` 也要抛 `SignatureExpired` |
| 夹具提交 | `a11b716`（base + `test.patch`） |
| 夹具自检 | 206 个可达提交、无 remote、无未来历史；`--forbid c30678d` 通过 |

## 重建

```powershell
cd D:\repo-agent
git clone --config core.autocrlf=false https://github.com/pallets/itsdangerous work\itsdangerous-full
.\.venv\Scripts\python.exe tools\make_fixture.py `
  --source work\itsdangerous-full `
  --commit 1a9b8d1 `
  --dest .repos\itsdangerous-126 `
  --test-patch tasks\fixtures\itsdangerous-126\test.patch `
  --forbid c30678d `
  --force `
  --message "task fixture: add failing test for future timestamps (#126)"
```

`--forbid` 是硬性要求：夹具里**不能**留着上游未来的提交，否则答案就躺在工作区里，
harness 打出来的所有分数都不作数。这个夹具最初就是直接 `git clone` 出来的，
带着 679 个提交和 `origin/main`，是后来用 `make_fixture.py` 重建的。

## 自检

```powershell
cd D:\repo-agent
.\.venv\Scripts\python.exe -m harness.run_eval --tasks tasks\golden.jsonl --limit 1 --check-only
```

依赖：`pytest`（已在本项目 venv 中）；测试通过 `env.PYTHONPATH=src` 导入 src 布局的包。
