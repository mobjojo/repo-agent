# 带尾随换行的 wheel 文件名被当成合法名

复现环境：Windows + Python 3.13 + pytest

---

`parse_wheel_filename` 对"项目名里带换行"的文件名没有报错，而是照常解析出一个项目名：

```python
from packaging.utils import parse_wheel_filename

parse_wheel_filename("foo\n-1.0-py3-none-any.whl")   # 期望抛 InvalidWheelFilename
```

实测（修前）：

```
filename   = 'foo\n-1.0-py3-none-any.whl'
tests\test_utils.py:194: Failed
E       Failed: DID NOT RAISE InvalidWheelFilename
1 failed, 12 passed in 0.24s
```

`foo__bar-1.0-py3-none-any.whl`、`foo#bar-1.0-py3-none-any.whl` 这类非法名都能被正确拒绝，
只有**末尾换行**这一种漏了过去——`"foo\n"` 被当成了合法名 `"foo"`。

期望：`parse_wheel_filename("foo\n-1.0-py3-none-any.whl")` 抛 `InvalidWheelFilename`；
其余合法/非法文件名的既有行为不变（`foo_bár-1.0-py3-none-any.whl` 仍要正常解析）。

约束：只改源码，不要动测试与测试配置。
