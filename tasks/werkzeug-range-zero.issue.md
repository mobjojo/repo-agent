# Range: bytes=-0 被解析成"整个文件"

复现环境：Windows + Python 3.13 + pytest

---

suffix range 的语义是"最后 N 字节"。`N = 0` 没有任何意义，按 HTTP 规范这属于无法满足的
Range，应当直接判定为非法（返回 `None`），但实际被解析成了 `bytes=0-`：

```python
from werkzeug import http

http.parse_range_header("bytes=-0")   # 期望 None
```

实测（修前）：

```
rv = http.parse_range_header("bytes=-0")
>       assert rv is None
E       AssertionError: assert <Range 'bytes=0-'> is None
tests\test_http.py:691: AssertionError
```

`bytes=0-` 的含义是"整个文件"，与客户端想要的"最后 0 字节"完全不是一回事——
下游一旦拿它去切片，就会把整个文件发回去（数据放大的隐患）。

期望：`parse_range_header("bytes=-0")` 返回 `None`；`bytes=-1`、`bytes=0-0` 等
既有合法/非法取值的行为不变。

约束：只改源码，不要动测试与测试配置。
