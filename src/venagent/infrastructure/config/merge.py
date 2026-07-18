"""配置 mapping 合并工具。"""

from copy import deepcopy
from typing import Any, Mapping


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """返回新 mapping；mapping 递归合并，其他值（包括 list）整体替换。"""

    result = deepcopy(dict(base))
    for key, overlay_value in overlay.items():
        base_value = result.get(key)
        if isinstance(base_value, Mapping) and isinstance(overlay_value, Mapping):
            result[key] = deep_merge(base_value, overlay_value)
        else:
            result[key] = deepcopy(overlay_value)
    return result
