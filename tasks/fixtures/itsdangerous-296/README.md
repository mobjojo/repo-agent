# 夹具：itsdangerous-296

这个任务对应上游一整个 PR（三个提交），而不是其中一个提交：只取一半会把"修了一半"
的状态当成基线，任务就失去了意义。

| 项 | 值 |
| --- | --- |
| 上游仓库 | https://github.com/pallets/itsdangerous |
| PR | #296（2.1.1 的 "Handle date overflow in timed unsign"） |
| base commit | `3b76264`（start version 2.1.1，即 PR 之前） |
| gold 修复 | `3b76264..177196d` 的 `src/` 部分：`ValueError` 与 `OSError` 都要被接住 |
| 夹具提交 | `a6af56d`（base + `test.patch`） |
| 夹具自检 | 461 个可达提交、无 remote、无未来历史 |
| 特别之处 | 该缺陷在 Windows 上表现为 `OSError`，在 Linux 上是 `ValueError`；本机跑出来的就是 `OSError` 那一支 |

## 重建

```powershell
cd D:\repo-agent
git clone --config core.autocrlf=false https://github.com/pallets/itsdangerous work\itsdangerous-full
.\.venv\Scripts\python.exe tools\make_fixture.py `
  --source work\itsdangerous-full `
  --commit 3b76264 `
  --dest .repos\itsdangerous-296 `
  --test-patch tasks\fixtures\itsdangerous-296\test.patch `
  --forbid 85b1e3b --forbid 37f0997 --forbid 177196d `
  --message "task fixture: add failing test for date overflow in timed unsign (#296)"
```

## 自检

```powershell
cd D:\repo-agent
.\.venv\Scripts\python.exe -m harness.run_eval --tasks tasks\golden.jsonl --limit 3 --check-only
```

依赖：`pytest`（已在本项目 venv 中）；测试通过 `env.PYTHONPATH=src` 导入 src 布局的包。
