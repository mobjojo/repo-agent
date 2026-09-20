# show_default 传字符串时，交互式提示里不显示它

复现环境：Windows + Python 3.13 + pytest

---

我们的选项默认值不适合直接展示（比如是一段超长 JSON），所以用 `show_default`
给用户看一个简短替代文案。`--help` 里显示正常，但**交互式提问时不显示**：

```python
import click
from click.testing import CliRunner


@click.command()
@click.option("--arg1", show_default="custom", prompt=True, default="my-default-value")
def cmd(arg1):
    pass


CliRunner().invoke(cmd, input="my-input", standalone_mode=False)
# 期望提示里出现 "(custom)"，且不出现真实的默认值 "my-default-value"
```

实测：提示里什么都没显示（既不显示 `(custom)`，也不显示真实默认值），
用户不知道有没有默认值可用。

期望：`show_default` 是字符串时，提示里显示这个字符串；
它仍然是原来的语义（括号包起来、位置与真实默认值一致）。
`show_default=True/False` 与 `None` 的行为都不要变。

约束：只改源码，不要动测试与测试配置。
