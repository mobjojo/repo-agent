# 时间戳相关的 datetime 处理混用 aware / naive（并用了已弃用 API）

复现环境：Windows + Python 3.13 + pytest

---

`timed.py` 目前用 `datetime.utcfromtimestamp()` 造时间戳，这个 API 已被弃用，而且产生的是
**naive** datetime；调用方拿到的对象带不带时区因此不确定：

```python
from itsdangerous import TimestampSigner
import time

s = TimestampSigner("secret")
s.get_timestamp()          # 期望 timezone-aware UTC
s.unsign(s.sign("x"), max_age=60)
```

实测（修前，测试里 `filterwarnings=error` 直接把它变成失败）：

```
E   DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated and scheduled for
    removal in a future version. Use timezone-aware objects to represent datetimes in UTC:
    datetime.datetime.fromtimestamp(timestamp, datetime.UTC).
src\itsdangerous\timed.py:33: DeprecationWarning

tests/test_itsdangerous/test_timed.py 里 22 个用例失败（测试的基准时间已是 aware UTC）
```

期望：所有对外的 datetime 都是 **timezone-aware 的 UTC**，不再使用已弃用的构造方式；
`max_age`、`BadTimeSignature.date_signed`、`jws` 与 `exc` 里暴露 datetime 的地方行为一致，
`tests/test_itsdangerous/test_timed.py` 全绿，其它测试文件不回归。

约束：只改源码，不要动测试与测试配置。
