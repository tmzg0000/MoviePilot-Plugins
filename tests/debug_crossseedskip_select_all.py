"""
CrossSeedSkip 全选站点修复 - Mock 调试套件 v3
测试 VBtn + API 模式（参考 tangptlottery 的 get_cookie 按钮模式）
"""
import os
import sys
import types
from unittest.mock import MagicMock

print("=" * 60)
print("CrossSeedSkip 全选站点修复 - Mock 调试套件 v3")
print("=" * 60)

mock_modules = {
    'pytz': types.ModuleType('pytz'),
    'apscheduler': types.ModuleType('apscheduler'),
    'apscheduler.schedulers': types.ModuleType('apscheduler.schedulers'),
    'apscheduler.schedulers.background': types.ModuleType('apscheduler.schedulers.background'),
    'apscheduler.triggers': types.ModuleType('apscheduler.triggers'),
    'apscheduler.triggers.cron': types.ModuleType('apscheduler.triggers.cron'),
    'bencode': types.ModuleType('bencode'),
    'requests': types.ModuleType('requests'),
    'requests.exceptions': types.ModuleType('requests.exceptions'),
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

class MockPluginBase:
    def __init__(self):
        self._config = {}
    def get_config(self, key=None):
        return self._config
    def update_config(self, data):
        self._config.update(data)
    def stop_service(self):
        pass
    def post_message(self, **kwargs):
        pass

sys.modules['app.plugins._pluginbase']._PluginBase = MockPluginBase
sys.modules['app.plugins']._PluginBase = MockPluginBase
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

sys.modules['apscheduler.schedulers.background'].BackgroundScheduler = MagicMock()
sys.modules['apscheduler.triggers.cron'].CronTrigger = MagicMock()
sys.modules['bencode'].bdecode = MagicMock()
sys.modules['bencode'].bencode = MagicMock()

plugin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugins.v2", "crossseedskip")
sys.path.insert(0, os.path.dirname(plugin_dir))

import importlib.util
spec = importlib.util.spec_from_file_location("crossseedskip", os.path.join(plugin_dir, "__init__.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
CrossSeedSkip = mod.CrossSeedSkip

plugin = CrossSeedSkip()

print("\n--- 测试1: get_form() 表单结构 ---")

result = {"vbtn_select_all": None, "vselect_sites": None}

def scan_components(items, depth=0):
    for item in items:
        comp = item.get("component", "")
        if comp == "VBtn":
            text = item.get("props", {}).get("text", "")
            events = item.get("events", {})
            api = events.get("click", {}).get("api", "")
            if "全选所有站点" in text:
                result["vbtn_select_all"] = {"text": text, "api": api}
                print(f"  找到 VBtn: text='{text}', api='{api}'")
            else:
                print(f"  找到 VBtn: text='{text}'")
        elif comp == "VSelect":
            model = item.get("props", {}).get("model", "")
            label = item.get("props", {}).get("label", "")
            if model == "sites":
                result["vselect_sites"] = {"model": model, "label": label}
            print(f"  找到 VSelect: model='{model}', label='{label}'")
        if "content" in item:
            scan_components(item["content"], depth + 1)

try:
    form_data = plugin.get_form()
    if isinstance(form_data, tuple):
        form_items = form_data[0]
    else:
        form_items = form_data

    print(f"表单项数量: {len(form_items)}")
    scan_components(form_items)

    vbtn_select_all = result["vbtn_select_all"]
    vselect_sites = result["vselect_sites"]

    print(f"\n结果:")
    print(f"  VBtn '全选所有站点': {'✅ 正确' if vbtn_select_all else '❌ 未找到'}")
    if vbtn_select_all:
        print(f"    API: {vbtn_select_all['api']}")
        expected_api = "plugin/CrossSeedSkip/get_all_sites"
        print(f"    API 路径正确: {'✅' if expected_api in vbtn_select_all['api'] else '❌'}")
    print(f"  VSelect '辅种站点': {'✅ 正确' if vselect_sites else '❌ 未找到'}")

except Exception as e:
    print(f"❌ get_form() 测试失败: {e}")
    import traceback
    traceback.print_exc()

print("\n--- 测试2: get_api() 端点注册 ---")

get_all_sites_found = False
try:
    api_list = plugin.get_api()
    print(f"注册的 API 端点数量: {len(api_list)}")

    for api in api_list:
        path = api.get("path", "")
        print(f"  API: path='{path}', methods={api.get('methods', [])}")
        if path == "/get_all_sites":
            get_all_sites_found = True

    print(f"\n  /get_all_sites 端点: {'✅ 已注册' if get_all_sites_found else '❌ 未找到'}")
except Exception as e:
    print(f"❌ get_api() 测试失败: {e}")
    import traceback
    traceback.print_exc()

print("\n--- 测试3: select_all_sites 旧代码已清理 ---")

import inspect
has_select_all_in_init = False
has_select_all_in_update = False
try:
    source = inspect.getsource(CrossSeedSkip.init_plugin)
    has_select_all_in_init = "select_all_sites" in source
    print(f"  init_plugin 中 select_all_sites 残留: {'❌ 仍存在' if has_select_all_in_init else '✅ 已清理'}")

    source_update = inspect.getsource(CrossSeedSkip._CrossSeedSkip__update_config)
    has_select_all_in_update = "select_all_sites" in source_update
    print(f"  __update_config 中 select_all_sites 残留: {'❌ 仍存在' if has_select_all_in_update else '✅ 已清理'}")
except Exception as e:
    print(f"❌ inspect 测试失败: {e}")

print("\n" + "=" * 60)
print("修复方案评估 (VBtn + API 模式)")
print("=" * 60)

all_good = (
    result["vbtn_select_all"] is not None
    and result["vselect_sites"] is not None
    and get_all_sites_found
    and not has_select_all_in_init
    and not has_select_all_in_update
)

if all_good:
    print("""
✅ 修复方案正确！

变更摘要:
  - VSwitch '全选所有站点' → VBtn + API 端点（参考 tangptlottery 模式）
  - 新增 get_api() 注册 /get_all_sites 端点
  - 新增 get_all_sites_api() 返回所有站点 ID
  - 清除 select_all_sites 相关的 init_plugin / __update_config 逻辑

用户使用方式:
  1. 打开插件配置页
  2. 点击 VBtn '全选所有站点'
  3. 前端调用 API 获取所有站点 ID
  4. API 返回 {"sites": [...]}，前端自动更新 VSelect 的选中值
  5. 保存配置即可使用全站点辅种

技术原理:
  MoviePilot VForm 的 VBtn + events.click.api 模式中，
  前端调用 API 后会将响应 JSON 的 key 与 form model 匹配，
  自动更新对应表单字段的值。
  （参照 tangptlottery 的 get_cookie VBtn 实现）
""")
else:
    print("\n⚠️ 仍有问题需要修复！")

print("=" * 60)