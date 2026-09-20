# click.echo 写出空字节串时抛 TypeError

复现环境：Windows + Python 3.13 + pytest

---

我们的输出封装既可能收到 `str` 也可能收到 `bytes`，所以显式指定二进制流。
正常内容都没问题，只有**空字节串**会炸：

```python
from io import BytesIO

import click

b = BytesIO()
click.echo(b"", b)          # 期望写出 b"\n"
print(b.getvalue())
```

实测：`TypeError: a bytes-like object is required, not 'str'`
——写进二进制流的是 `str`，所以报错。把 `b""` 换成 `b"x"` 就正常，
也就是说问题只出在"空"这一种取值上。

期望：`echo(b"", <binary file>)` 写出 `b"\n"`，与写出 `b"x"` 的行为保持一致；
`echo` 对 `str`、`bytes`、`None` 的既有行为不要改变。

约束：只改源码，不要动测试与测试配置。
