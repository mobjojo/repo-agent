# help 文本为空时，(DEPRECATED) 标记前多出一个空格

复现环境：Windows + Python 3.13 + pytest

---

命令或选项被标记为 deprecated、且自身 help 文本为空时，帮助输出里的标记会多一个前导空格：

```python
from click.testing import CliRunner
import click

@click.command(deprecated=True, help="")
def cli():
    pass

CliRunner().invoke(cli, ["--help"]).output   # 期望 "   (DEPRECATED" 之前正好两个空格
```

实测（修前）：

```
tests\test_commands.py:506: in test_deprecated_empty_help_no_leading_space
    assert "\n  (DEPRECATED" in out
E   AssertionError: assert '\n  (DEPRECATED' in 'Usage: cli [OPTIONS]\n\n   (DEPRECATED)\n\nOptions:...'

tests\test_options.py:72: in test_deprecated_empty_help_no_leading_space
    assert opt.get_help_record(ctx)[1] == expected
E   AssertionError: assert ' (DEPRECATED)' == '(DEPRECATED)'
E     - (DEPRECATED)
E     +  (DEPRECATED)
```

也就是空 help 留下的那个空格没有和标记拼好。

期望：`(DEPRECATED)` 与 `(DEPRECATED: ...)` 在 help 为空时前后不留多余空格；
help 非空时的既有格式（`help 文本  (DEPRECATED: ...)`）不变。

约束：只改源码，不要动测试与测试配置。
