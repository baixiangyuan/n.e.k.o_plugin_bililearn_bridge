"""BiliLearn Bridge 插件包入口。

N.E.K.O 运行时把市场/用户插件以 ``plugins.<id>`` 命名空间包导入
（见 N.E.K.O ``plugin/core/host.py``：加载插件时把 ``<data>/plugins`` 的父目录
加入 ``sys.path``，使 ``plugins`` 成为命名空间包，再 ``import plugins.bililearn_bridge``）。

因此入口类必须作为 ``plugins.bililearn_bridge`` 包的属性暴露——这里从子模块 re-export。
注意：子模块顶部 ``from plugin.sdk.plugin import ...`` 依赖 N.E.K.O 的 ``plugin`` 包在路径上，
运行时 / ``check -r`` 环境均满足（不要在这个 __init__ 里做会脱离该环境的导入）。
"""
from .bililearn_bridge import BiliLearnBridgePlugin

__all__ = ["BiliLearnBridgePlugin"]
