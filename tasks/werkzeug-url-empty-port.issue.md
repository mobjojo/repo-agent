# uri_to_iri / iri_to_uri 丢掉了"空"的 userinfo 和端口 0

复现环境：Windows + Python 3.13 + pytest

---

URL 里的空值是有意义的：`http://u:@d.test` 有用户名 `u` 和**空密码**，`http://d.test:0`
里的 `0` 是一个显式端口。转换函数会把它们当成"没有"，直接删掉：

```python
from werkzeug import urls

urls.uri_to_iri("http://u:@d.test")     # 期望原样返回
urls.uri_to_iri("http://:@d.test")      # 期望原样返回
urls.uri_to_iri("http://d.test:0")      # 期望原样返回
```

实测（修前）：

```
tests\test_urls.py:114: in test_uri_empty_auth
    assert urls.uri_to_iri(value) == value
E   AssertionError: assert 'http://u@d.test' == 'http://u:@d.test'
E   AssertionError: assert 'http://d.test' == 'http://:@d.test'

tests\test_urls.py:119: in test_uri_port_0
    assert urls.uri_to_iri("http://d.test:0") == "http://d.test:0"
E   AssertionError: assert 'http://d.test' == 'http://d.test:0'

4 failed, 1 passed
```

期望：空的用户名/密码、端口 `0` 在 `uri_to_iri` 与 `iri_to_uri` 两个方向上都要保留；
真正没有 userinfo / 没有端口的 URL 行为不变。

约束：只改源码，不要动测试与测试配置。
