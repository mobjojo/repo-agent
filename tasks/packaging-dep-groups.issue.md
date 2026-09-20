# 依赖组里出现非法 requirement 时会连累同组的其它错误一起丢失

复现环境：Windows + Python 3.13 + pytest

---

`resolve_dependency_groups` 的卖点是把一个组里的错误**一次性全报出来**（`ExceptionGroup`）。
但只要组里有一个"不是合法 PEP 508 字符串"的条目，原始异常就直接穿出去，
**同时已经把收集到的兄弟错误被丢掉**：

```python
from packaging.dependency_groups import resolve_dependency_groups

groups = {"all": [{}, "this is not a valid requirement!!!"]}
resolve_dependency_groups(groups, "all")
```

实测（修前）：

```
errors     = _ErrorCollector(errors=[InvalidDependencyGroupObject('Invalid dependency group item: {}')])
src\packaging\dependency_groups.py:246: in _parse_group
    elements.append(Requirement(item))
E           packaging.requirements.InvalidRequirement: Expected semicolon (after name with no version specifier) or end
src\packaging\requirements.py:80: InvalidRequirement
```

注意 `InvalidDependencyGroupObject` 在当时**已经被收集了**，却因为后面这一行抛出来而整体丢失。

期望：非法 requirement 字符串和别的失败一样被**收集**，最终抛出的 `ExceptionGroup`
里能同时找到 `InvalidRequirement` 和兄弟错误 `InvalidDependencyGroupObject`
（组级文案仍是 `[dependency-groups] data for 'all' was malformed`）。

约束：只改源码，不要动测试与测试配置。
