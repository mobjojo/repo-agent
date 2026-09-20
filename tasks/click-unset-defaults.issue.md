# 多个选项共享同一个参数名时，默认值取错了那一个

复现环境：Windows + Python 3.13 + pytest

---

我们用"多个 flag 映射到同一个变量名"来做互斥开关（类似 verbosity 那种写法）。
谁写了 `default=True`，谁就应该在没有传参时生效：

```python
import click
from click.testing import CliRunner


@click.command
@click.option("--red", "color", flag_value="red")
@click.option("--green", "color", flag_value="green", default=True)
def prefers_green(color):
    click.echo(color)


@click.command
@click.option("--red", "color", flag_value="red", default=True)
@click.option("--green", "color", flag_value="green")
def prefers_red(color):
    click.echo(color)


runner = CliRunner()
print(runner.invoke(prefers_green, []).output)   # 期望 green
print(runner.invoke(prefers_red, []).output)     # 期望 red
```

实测：`prefers_red` 输出了 `green`——第一个参数解析时把值写成了 `None`，
于是后面那个带 `default=True` 的选项被当成"已经设置过"而直接跳过。
显式传 `--green` / `--red` 时倒是正常，所以问题只在"谁是默认值"的判定上。

期望：共享同一变量名的多个参数之间，**先声明的那个先占位**，但"占位"不能用
`None` 去冒充（`None` 与"未设置"必须区分开），显式传参依旧优先。

约束：只改源码，不要动测试与测试配置。
