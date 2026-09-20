# URL 里的超长数字串让路由抛 ValueError，而不是 404

复现环境：Windows + Python 3.13 + pytest

---

Python 从 3.11 起限制了十进制字符串转 `int` 的长度（默认 4300 位）。
`<int:a>` 转换器直接把这个 `ValueError` 放了出来，而路由匹配失败本该表现成 404：

```python
from werkzeug import routing as r

m = r.Map([r.Rule("/<int:a>", endpoint="a")])
a = m.bind("a.test")
a.match("/" + "1" * 5000)   # 期望 NotFound
```

实测（修前）：

```
def to_python(self, value: str) -> t.Any:
    if self.fixed_digits and len(value) != self.fixed_digits:
        raise ValidationError()
>       value_num = self.num_convert(value)
E       ValueError: Exceeds the limit (4300 digits) for integer string conversion: value has 4301 digits; use sys.set_int_max_str_digits() to increase the limit
src\werkzeug\routing\converters.py:155: ValueError
```

任何访客只要往 URL 里塞一长串数字，就能让应用抛 500，而正常整数 URL 的匹配不能受影响。

期望：超长数字段按 `ValidationError` 处理（最终表现为 404 `NotFound`）；
常规 `<int:...>` 的匹配与 `to_url` 行为不变。

约束：只改源码，不要动测试与测试配置。
