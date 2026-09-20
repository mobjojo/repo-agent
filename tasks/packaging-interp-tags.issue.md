# 非法的 interpreter 标签与带非法标签的 wheel 文件名没有被拒绝

复现环境：Windows + Python 3.13 + pytest

---

标签的第一段（interpreter）必须是合法形式，但我们发现一批明显不合法的写法被照单全收：

```python
from packaging import tags
from packaging.utils import parse_wheel_filename

tags.parse_tag("2.7.6-none-any")        # 期望 InvalidTag
tags.parse_tag("2-none-any")            # 期望 InvalidTag
tags.parse_tag("py3.2-none-any")        # 期望 InvalidTag
tags.parse_tag("py+3-none-any")         # 期望 InvalidTag

parse_wheel_filename("playlyfe-0.1.1-2.7.6-none-any.whl")   # 期望 InvalidWheelFilename
```

实测（修前）：

```
tests\test_tags.py:247: in test_invalid_interpreter_raises
    with pytest.raises(tags.InvalidTag, match="invalid interpreter"):
E   Failed: DID NOT RAISE InvalidTag
        tag        = '2.7.6-none-any'

tests\test_utils.py:207: in test_parse_wheel_invalid_filename
    with pytest.raises(InvalidWheelFilename):
E   Failed: DID NOT RAISE InvalidWheelFilename
        filename   = 'playlyfe-0.1.1-2.7.6-none-any.whl'

5 failed, 13 passed
```

注意 wheel 文件名那条和标签是同一个毛病：`2.7.6-none-any` 里的 interpreter 是 `2.7.6`。

期望：interpreter 段只接受合法形式，上述四种标签与那个 wheel 文件名都要被拒绝
（标签抛 `InvalidTag` 且文案含 `invalid interpreter`，文件名抛 `InvalidWheelFilename`）；
`py3-none-any`、`cp310-cp310-win_amd64`、`py2.py3-none-any` 这类合法取值行为不变。

约束：只改源码，不要动测试与测试配置。
