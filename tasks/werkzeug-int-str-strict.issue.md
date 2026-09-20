# 严格整数解析器接受了十六进制前缀与非 ASCII 空白

复现环境：Windows + Python 3.13 + pytest

---

`werkzeug._internal._plain_int` 的契约是"只吃纯十进制数字串"，但它对这两类输入放行了：

```python
from werkzeug._internal import _plain_int

_plain_int("0x7B", 16)      # 期望 ValueError（十六进制前缀不属于十进制写法）
_plain_int("\u2029123", 10) # 期望 ValueError（U+2029 不是空白）

_plain_int(" 123", 10)      # 必须继续返回 123
_plain_int("\t123", 10)     # 必须继续返回 123
```

实测（修前，两条都该抛却都返回了值）：

```
tests\test_internal.py:56: in test_plain_int
    with pytest.raises(ValueError):
E   Failed: DID NOT RAISE ValueError

FAILED tests/test_internal.py::test_plain_int[0x7B-16-None]
FAILED tests/test_internal.py::test_plain_int[\u2029123-10-None]
2 failed, 11 passed
```

这个函数被用于解析 Host 头里的端口和 `SERVER_PORT`，宽松一点就意味着"看起来像数字"的输入
会被当成数字。

期望：带十六进制前缀、或带非 ASCII 空白的输入抛 `ValueError`；
ASCII 空白（空格/制表符）包裹的十进制串、正负号、`base` 参数 10/16 的既有合法用法都不变。

约束：只改源码，不要动测试与测试配置。
