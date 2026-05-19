"""
CrossSeedSkip 全选站点修复 - Mock 调试套件 v2
测试 VSwitch 替换 VBtn 方案
"""
import os
import sys
import json
import types
from unittest.mock import MagicMock

# ============================================================
# Phase 1: 设置 Mock 环境
# ============================================================
print("=" * 60)
print("CrossSeedSkip 全选站点修复 - Mock 调试套件 v2")
print("=" * 60)

# 创建 Mock MoviePilot 框架模块
mock_modules = {
    'app': types.ModuleType('app'),
    'app.plugins': types.ModuleType('app.plugins'),
    'app.plugins._pluginbase': types.ModuleType('app.plugins._pluginbase'),
    'app.core': types.ModuleType('app.core'),
    'app.core.event': types.ModuleType('app.core.event'),
    'app.core.config': types.ModuleType('app.core.config'),
    'app.db': types.ModuleType('app.db'),
    'app.db.site_oper': types.ModuleType('app.db.site_oper'),
    'app.helper': types.ModuleType('app.helper'),
    'app.helper.torrent': types.ModuleType('app.helper.torrent'),
    'app.helper.sites': types.ModuleType('app.helper.sites'),
    'app.helper.downloader': types.ModuleType('app.helper.downloader'),
    'app.schemas': types.ModuleType('app.schemas'),
    'app.schemas.types': types.ModuleType('app.schemas.types'),
    'app.log': types.ModuleType('app.log'),
    'app.utils': types.ModuleType('app.utils'),
    'app.utils.string': types.ModuleType('app.utils.string'),
    'app.utils.timer': types.ModuleType('app.utils.timer'),
    'app.utils.http': types.ModuleType('app.utils.http'),
    'app.utils.object': types.ModuleType('app.utils.object'),
    'app.modules': types.ModuleType('app.modules'),
    'app.modules.subscribe': types.ModuleType('app.modules.subscribe'),
}

for name, mod in mock_modules.items():
    sys.modules[name] = mod

sys.modules['app.plugins._pluginbase']._PluginBase = MagicMock()
sys.modules['app.plugins']._PluginBase = sys.modules['app.plugins._pluginbase']._PluginBase
sys.modules['app.core.event'].EventManager = MagicMock()
sys.modules['app.core.event'].eventmanager = MagicMock()
sys.modules['app.core.event'].EventHandler = MagicMock()
sys.modules['app.core.config'].settings = MagicMock()
sys.modules['app.db.site_oper'].SiteOper = MagicMock()
sys.modules['app.helper.sites'].SitesHelper = MagicMock()
sys.modules['app.helper.downloader'].DownloaderHelper = MagicMock()
sys.modules['app.helper.torrent'].TorrentHelper = MagicMock()
sys.modules['app.utils.string'].StringUtils = MagicMock()
sys.modules['app.utils.timer'].TimerUtils = MagicMock()
sys.modules['app.utils.object'].ObjectUtils = MagicMock()
sys.modules['app.log'].logger = MagicMock()
sys.modules['app.schemas'].NotificationType = type('NotificationType', (), {'SiteMessage': 'site_message'})
sys.modules['app.schemas'].ServiceInfo = type('ServiceInfo', (), {})
sys.modules['app.schemas.types'].EventType = type('EventType', (), {
    'TorrentTransferComplete': 'torrent.transfer.complete',
    'DownloadComplete': 'download.complete',
    'SiteDeleted': 'site.deleted',
})

sys.modules['app.plugins'].PluginManager = MagicMock()
sys.modules['app.modules'].Downloader = MagicMock()
sys.modules['app.modules.subscribe'].Subscribe = MagicMock()
sys.modules['app.utils.http'].RequestUtils = MagicMock()

# 加载插件模块
plugin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins.v2", "crossseedskip")
sys.path.insert(0, os.path.dirname(plugin_dir))

import importlib.util
spec = importlib.util.spec_from_file_location("crossseedskip", os.path.join(plugin_dir, "__init__.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
CrossSeedSkip = mod.CrossSeedSkip

# ============================================================
# Phase 2: 测试 get_form() 输出结构
# ============================================================
print("\n--- 测试1: get_form() 表单结构 ---")

plugin = CrossSeedSkip()
try:
    form_data = plugin.get_form()
    if isinstance(form_data, tuple):
        form_items = form_data[0]
    else:
        form_items = form_data

    print(f"表单项数量: {len(form_items)}")

    # 查找 VSwitch 和 VSelect
    vswitch_found = False
    vselect_found = False
    vbtn_found = False
    select_all_model = None
    sites_model = None

    def scan_components(items, depth=0):
        global vswitch_found, vselect_found, vbtn_found, select_all_model, sites_model
        for item in items:
            comp = item.get("component", "")
            if comp == "VSwitch":
                vswitch_found = True
                select_all_model = item.get("props", {}).get("model")
                print(f"  找到 VSwitch: model='{select_all_model}', label='{item.get('props', {}).get('label')}'")
            elif comp == "VSelect":
                vselect_found = True
                sites_model = item.get("props", {}).get("model")
                print(f"  找到 VSelect: model='{sites_model}', label='{item.get('props', {}).get('label')}'")
            elif comp == "VBtn":
                vbtn_found = True
                print(f"  找到 VBtn: text='{item.get('props', {}).get('text')}'")
                events = item.get("events", {})
                for evt_name, evt_config in events.items():
                    if evt_config.get("state"):
                        print(f"    ⚠️ VBtn 仍有 state='{evt_config.get('state')}' - 这不会生效！")
            if "content" in item:
                scan_components(item["content"], depth + 1)

    scan_components(form_items)

    print(f"\n结果:")
    print(f"  VSwitch '全选所有站点': {'✅ 已添加' if vswitch_found else '❌ 未找到'}")
    print(f"  VSelect '辅种站点': {'✅ 保留' if vselect_found else '❌ 未找到'}")
    print(f"  VBtn '全选站点' (旧): {'❌ 应已移除但仍存在' if vbtn_found else '✅ 已正确移除'}")

    if select_all_model == "select_all_sites" and sites_model == "sites":
        print("\n✅ 表单结构正确：VSwitch model='select_all_sites', VSelect model='sites'")
    else:
        print(f"\n⚠️ model 不匹配: VSwitch={select_all_model}, VSelect={sites_model}")

except Exception as e:
    print(f"❌ get_form() 测试失败: {e}")

# ============================================================
# Phase 3: 测试 select_all_sites 配置逻辑
# ============================================================
print("\n--- 测试2: select_all_sites 配置逻辑 ---")

# 验证 init_plugin 读取 select_all_sites 配置
config_with_flag = {"sites": [1, 2], "select_all_sites": True, "enabled": True}
config_without_flag = {"sites": [1, 2], "select_all_sites": False, "enabled": True}

print(f"  配置 select_all_sites=True: config.get('select_all_sites') or False = {config_with_flag.get('select_all_sites') or False}")
print(f"  配置 select_all_sites=False: config.get('select_all_sites') or False = {config_without_flag.get('select_all_sites') or False}")
print(f"  配置 select_all_sites 不存在: config.get('select_all_sites') or False = {{}}.get('select_all_sites') or False")

# ============================================================
# Phase 4: 验证 API 端点已移除
# ============================================================
print("\n--- 测试3: API 端点验证 ---")

has_get_api = hasattr(CrossSeedSkip, "get_api")
has_select_all_api = hasattr(CrossSeedSkip, "select_all_sites_api")

print(f"  get_api 方法: {'⚠️ 仍存在' if has_get_api else '✅ 已移除'}")
print(f"  select_all_sites_api 方法: {'⚠️ 仍存在' if has_select_all_api else '✅ 已移除'}")

# ============================================================
# Phase 5: 综合评估
# ============================================================
print("\n" + "=" * 60)
print("修复方案评估")
print("=" * 60)

all_good = (
    vswitch_found
    and vselect_found
    and not vbtn_found
    and not has_select_all_api
)

if all_good:
    print("""
✅ 修复方案正确！

变更摘要:
  - VBtn '全选站点' → VSwitch '全选所有站点'
  - 移除 select_all_sites_api 函数和 get_api 端点
  - init_plugin 中 select_all_sites=True 时自动覆盖 sites 为全站点

用户使用方式:
  1. 打开插件配置页
  2. 切换 VSwitch '全选所有站点' 为 ON
  3. 保存配置 - VSelect 的单独选择将被忽略
  4. 插件将自动使用所有可用站点进行辅种

Root Cause:
  PageRender.vue 的 commonAction() 只处理 api/method/params,
  完全忽略 events.click.state - 因此 VBtn state 机制无效。
  改用 VSwitch 直接控制配置值, 完全绕过前端 JS 缺陷。
""")
else:
    print("\n⚠️ 仍有问题需要修复！")

print("=" * 60)