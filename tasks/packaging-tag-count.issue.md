# parse_tag 对"组件数不对"的标签抛 ValueError，而不是 InvalidTag

复现环境：Windows + Python 3.13 + pytest

---

一个标签必须有 interpreter / abi / platform 三段。少一段或多一段时，`parse_tag` 抛出的是
**裸的 `ValueError`**（元组解包的报错），而不是本模块自己的 `InvalidTag`：

```python
from packaging import tags

tags.parse_tag("py3-none")             # 期望 InvalidTag
tags.parse_tag("py3-none-any-extra")   # 期望 InvalidTag
```

实测（修前，两个标签都不通过）：

```
component_parts = [['py3'], ['none'], ['any'], ['extra']]
tag        = 'py3-none-any-extra'
>       interpreters, abis, platforms = component_parts
E       ValueError: too many values to unpack (expected 3)
src\packaging\tags.py:289: ValueError
2 failed in 0.34s
```

调用方是照着 `InvalidTag` 的类型与文案来写捕获逻辑的，所以现在这种"半个意外"会让
调用方拿到一个它没打算处理的错误。

期望：组件数不等于 3 时抛 `InvalidTag`，且异常文案里包含 `exactly three components`；
三段齐全时的行为完全不变。

约束：只改源码，不要动测试与测试配置。
