# `~=` 的版本段接受了 Unicode 字母

复现环境：Windows + Python 3.13 + pytest

---

PEP 440 的版本号只允许 ASCII 字母数字与点号。下面两个字符串本该被拒，但都被当成了合法 specifier：

```python
from packaging.specifiers import Specifier

Specifier("~=1.2.3prev\u0131ew1")   # 期望 InvalidSpecifier（ı 是拉丁小写无点 i）
Specifier("~=1.2.3po\u017ft1")      # 期望 InvalidSpecifier（ſ 是拉丁小写长 s）
```

实测（修前）：

```
tests\test_specifiers.py:107: in test_specifiers_invalid
    with pytest.raises(InvalidSpecifier):
E   Failed: DID NOT RAISE InvalidSpecifier
        specifier  = '~=1.2.3prev\u0131ew1'

2 failed, 29 passed
```

看起来这两个字符在匹配时被当成了普通的 `i` / `s`，于是 `prevıew1` 变成了合法的预发布标识。

期望：这两条必须抛 `InvalidSpecifier`；其余合法/非法 specifier（含 `~=1.2.3`、`~=1.2.3a1`
这类正常写法）行为不变。

约束：只改源码，不要动测试与测试配置。
