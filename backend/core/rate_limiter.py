"""公开接口限流：内存滑动窗口（key = IP:agent_id，阈值读 agent 表配置）"""
import time
from collections import defaultdict, deque

# {key: deque[timestamp]}，进程内存储；重启即重置（可接受）
_buckets: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str, limit_per_min: int) -> bool:
    """检查是否允许通过；limit_per_min <= 0 视为不限流"""
    if limit_per_min <= 0:
        return True
    now = time.time()
    window = _buckets[key]
    # 清理窗口外的旧记录
    while window and now - window[0] >= 60:
        window.popleft()
    if len(window) >= limit_per_min:
        return False
    window.append(now)
    return True


def reset_rate_limits() -> None:
    """清空限流桶（测试用）"""
    _buckets.clear()
