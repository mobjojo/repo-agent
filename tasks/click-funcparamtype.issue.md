# 自定义转换器抛出的 ValueError 信息被丢掉，用户只看到默认文案

复现环境：Windows + Python 3.13 + pytest

---

我们用 `FuncParamType` 包了一个自定义解析函数，函数在参数非法时会抛出**带说明的**
`ValueError`，本意是让用户看到具体哪里写错了：

```python
import click


def parse(value):
    raise ValueError("bad value: nope")


func_type = click.types.FuncParamType(parse)
func_type.convert("nope", None, None)
```

实测：抛出的 `click.BadParameter` 信息里**没有** `bad value: nope` 这段说明，
用户拿到的是一句泛泛的错误，只能靠翻源码才知道哪条规则没过。

期望：错误信息里应当包含自定义函数抛出的那句说明。
注意反向要求：如果函数抛的 `ValueError` 是**空信息**（`ValueError("")`），
那就还退回到原来的行为（用参数值本身作为提示），不能输出空字符串。

约束：只改源码，不要动测试与测试配置。
