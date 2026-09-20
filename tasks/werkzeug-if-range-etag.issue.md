# If-Range 里的弱 ETag 被当成强 ETag 用了

复现环境：Windows + Python 3.13 + pytest

---

`If-Range` 头可以用 ETag 表达"如果资源没变，就把这段 Range 发给我"。
RFC 9110 要求这里的 ETag 必须是**强**校验器：`W/"Test"` 这种弱 ETag 不适用，
应当被丢弃（等价于客户端没提供 ETag），但当前实现把 `W/` 前缀剥掉后当强 ETag 用了：

```python
from werkzeug.datastructures import IfRange

rv = IfRange.from_header('W/"Test"')
rv.etag         # 期望 None
rv.to_header()  # 期望 ""
```

实测（修前）：

```
rv = IfRange.from_header('W/"Test"')
>       assert rv.etag is None
E       assert 'Test' is None
E        +  where 'Test' = <IfRange '"Test"'>.etag
tests\test_http.py:611: AssertionError
```

后果是：客户端拿弱 ETag 请求部分内容，服务端会认为"资源没变"从而回 206，
而弱校验器本身不保证字节级一致，Range 的语义就被破坏了。

期望：`W/` 开头的弱 ETag 整体丢弃（`etag` 为 `None`、`to_header()` 返回空串）；
强 ETag `"Test"` 与未加引号的 `unquoted` 仍按原样接受；日期形式的 `If-Range` 行为不变。

约束：只改源码，不要动测试与测试配置。
