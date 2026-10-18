import os
import sys
import tempfile

# 测试用独立 SQLite，且必须在导入 app 之前设置
_tmpdir = tempfile.mkdtemp(prefix="jobhunting-test-")
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test.db")
os.environ["AI_BUILDER_TOKEN"] = "test-token"
# 验证 env 注入的黑名单机制（真实敏感词经部署 env 配置，不入代码库）
os.environ["BLACKLIST_EXTRA"] = "测试敏感词=安全替换"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
