# 一个路径段里有 10 个以上转换器时，匹配出来的参数错位

复现环境：Windows + Python 3.13 + pytest

---

同一段里放多个 `<int:...>` 转换器时，生成的内部组名是 `__werkzeug_0`、`__werkzeug_1`……
它们在被排序时按**字符串**比较，于是 `__werkzeug_10` 排到了 `__werkzeug_2` 前面，
匹配结果整体错位：

```python
from werkzeug import routing as r

pattern = "-".join(f"<int:a{i}>" for i in range(11))
m = r.Map([r.Rule(f"/{pattern}", endpoint="a")])
a = m.bind("a.test")
_, args = a.match("/" + "-".join(str(i) for i in range(11)))
args["a10"]    # 期望 10
```

实测（修前）：

```
tests\test_routing.py:841: in test_part_converter_order
    assert args == {f"a{i}": i for i in range(11)}
E   AssertionError: assert {'a0': 0, 'a1... 'a3': 2, ...} == {'a0': 0, 'a1... 'a3': 3, ...}
E     Differing items:
E     {'a10': 9} != {'a10': 10}
E     {'a2': 10} != {'a2': 2}
E     {'a5': 4} != {'a5': 5}
E     {'a7': 6} != {'a7': 7}
```

10 个以上转换器不是常见写法，但一旦出现，参数会静默错位——拿到错误的值比报错更难查。

期望：同一段内的转换器按数值顺序对应 URL 段（`a10` 拿到第 11 段）；
转换器数量较少时的既有匹配行为不变，`test_routing.py` 其余用例保持通过。

约束：只改源码，不要动测试与测试配置。
