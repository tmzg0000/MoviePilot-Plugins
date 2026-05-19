"""
TangptLottery 通知格式美化 — Mock 调试套件
复现当前输出 vs 改进方案对比
"""
from collections import Counter

print("=" * 70)
print("TangptLottery 通知格式美化 — Before/After 对比")
print("=" * 70)

# ============================================================
# 模拟抽奖数据
# ============================================================
mock_record = {
    "date": "2026-05-19",
    "target_count": 1000,
    "completed_count": 1000,
    "total_cost": 0,
    "total_compensated": 0,
    "status": "completed",
}

mock_prizes = [
    "魔力值 x50", "魔力值 x50", "魔力值 x50",
    "魔力值 x100", "魔力值 x100",
    "魔力值 x200",
    "VIP 3天", "VIP 3天",
    "邀请 x1", "邀请 x1", "邀请 x1", "邀请 x1",
    "道具: 卡券 x1", "道具: 卡券 x1", "道具: 卡券 x1",
    "道具: 道具包 x1", "道具: 道具包 x1",
    "道具: 抽奖券 x1",
    "道具: 道具兑换券 x1",
    "谢谢参与", "谢谢参与", "谢谢参与", "谢谢参与", "谢谢参与",
    "谢谢参与", "谢谢参与", "谢谢参与", "谢谢参与", "谢谢参与",
    "谢谢参与", "谢谢参与", "谢谢参与",
]

mock_slot_results = [
    {"reels": [{"name": "🍒"}, {"name": "🍒"}, {"name": "🍒"}], "result": "三连", "payout": 6250},
    {"reels": [{"name": "🍋"}, {"name": "🍋"}, {"name": "🔔"}], "result": "二连", "payout": 1875},
    {"reels": [{"name": "🔔"}, {"name": "⭐"}, {"name": "🍒"}], "result": "未中", "payout": 0},
    {"reels": [{"name": "🍒"}, {"name": "🍒"}, {"name": "🍒"}], "result": "三连", "payout": 6250},
    {"reels": [{"name": "🍋"}, {"name": "🍋"}, {"name": "🍒"}], "result": "二连", "payout": 1875},
    {"reels": [{"name": "⭐"}, {"name": "🍒"}, {"name": "🔔"}], "result": "未中", "payout": 0},
    {"reels": [{"name": "🍒"}, {"name": "🍒"}, {"name": "🍒"}], "result": "三连", "payout": 6250},
    {"reels": [{"name": "🔔"}, {"name": "🔔"}, {"name": "🔔"}], "result": "三连", "payout": 6250},
]

mock_slot_record = {
    "date": "2026-05-19",
    "total_spins": 8,
    "free_used": 2,
    "wins": 4,
    "losses": 4,
    "total_cost": 30000,
    "total_payout": 22750,
    "net": -7250,
    "jackpot_hit": False,
    "jackpot_pool": 500000,
    "ev_detail": "底注5000: EV=-3.2, RTP=99.5%\nJackpot池500000: EV=+2.1\n综合EV=-1.1",
    "ev": -1.1,
}

# ============================================================
# 当前通知格式 (BEFORE)
# ============================================================
print("\n" + "=" * 70)
print("BEFORE — 当前抽奖通知")
print("=" * 70)

prize_counter = Counter(mock_prizes)
prize_text = "\n".join([f"  {name}: {count}次" for name, count in prize_counter.most_common()])

current_lottery = (
    f"日期：{mock_record.get('date')}\n"
    f"完成：{mock_record.get('completed_count', 0)}/{mock_record.get('target_count', 0)}\n"
    f"状态：已完成\n"
    f"奖品：\n{prize_text}"
)
print(current_lottery)

print("\n" + "=" * 70)
print("BEFORE — 当前老虎机通知")
print("=" * 70)

ev_text = f"期望收益: {mock_slot_record['ev']:+.2f}/每次 (底注5,000, 奖池500,000)"
spin_results = []
for r in mock_slot_results:
    reels_icons = " | ".join([reel.get("name", "?") for reel in r.get("reels", [])])
    sr = r.get("result", "?")
    payout = r.get("payout", 0)
    spin_results.append(f"  [{reels_icons}] {sr}, 派彩{payout:,}")

current_slot = (
    f"日期：{mock_slot_record.get('date')}\n"
    f"{ev_text}\n"
    f"EV明细: {mock_slot_record.get('ev_detail')}\n"
    f"旋转：{mock_slot_record.get('total_spins')} 转 (免费{mock_slot_record.get('free_used')}+付费{6})\n"
    f"结果：赢{mock_slot_record.get('wins')} / 输{mock_slot_record.get('losses')}\n"
    f"花费：{mock_slot_record.get('total_cost'):,}  派彩：{mock_slot_record.get('total_payout'):,}\n"
    f"净收益：{mock_slot_record.get('net'):+,}\n\n"
    f"详情：\n" + "\n".join(spin_results)
)
print(current_slot)

# ============================================================
# 改进通知格式 (AFTER)
# ============================================================
print("\n" + "=" * 70)
print("AFTER — 改进后抽奖通知")
print("=" * 70)

# 分类汇总奖品
vip_prizes = [p for p in mock_prizes if "VIP" in p or "vip" in p]
magic_prizes = [p for p in mock_prizes if "魔力值" in p]
invite_prizes = [p for p in mock_prizes if "邀请" in p]
item_prizes = [p for p in mock_prizes if "道具" in p]
thanks_prizes = [p for p in mock_prizes if "谢谢" in p or "参与" in p]
other = [p for p in mock_prizes if p not in vip_prizes + magic_prizes + invite_prizes + item_prizes + thanks_prizes]

def build_category(name, emoji, prizes):
    if not prizes:
        return ""
    counter = Counter(prizes)
    items = "、".join([f"{n}x{c}" for n, c in counter.most_common()])
    return f"  {emoji} {name}：{items}"

cat_lines = []
cat_lines.append(build_category("VIP奖品", "👑", vip_prizes))
cat_lines.append(build_category("魔力值", "✨", magic_prizes))
cat_lines.append(build_category("邀请", "📨", invite_prizes))
cat_lines.append(build_category("道具", "🎁", item_prizes))
cat_lines.append(build_category("其他", "📦", other))
cat_lines.append(build_category("谢谢参与", "💤", thanks_prizes))
cat_text = "\n".join([l for l in cat_lines if l])

total_prizes = len([p for p in mock_prizes if "谢谢" not in p and "参与" not in p])

improved_lottery = (
    f"📅 日期：{mock_record.get('date')}\n"
    f"🎯 抽奖次数：{mock_record.get('completed_count', 0)}/{mock_record.get('target_count', 0)}  状态：✅ 已完成\n"
    f"🎉 中奖次数：{total_prizes} 次 / {len(mock_prizes)} 次 (中奖率 {total_prizes/len(mock_prizes)*100:.1f}%)\n\n"
    f"📊 奖品汇总：\n{cat_text}"
)
print(improved_lottery)

print("\n" + "=" * 70)
print("AFTER — 改进后老虎机通知")
print("=" * 70)

total = mock_slot_record.get("total_spins")
free = mock_slot_record.get("free_used")
paid = total - free
wins = mock_slot_record.get("wins")
losses = mock_slot_record.get("losses")
cost = mock_slot_record.get("total_cost")
payout = mock_slot_record.get("total_payout")
net = mock_slot_record.get("net")
pool = mock_slot_record.get("jackpot_pool")
ev = mock_slot_record.get("ev")

win_rate = f"{wins/total*100:.0f}%" if total > 0 else "0%"
net_icon = "📈" if net > 0 else "📉" if net < 0 else "➡️"
ev_icon = "🟢" if ev > 0 else "🔴" if ev < 0 else "🟡"

# 简化的旋转详情表
detail_lines = []
for r in mock_slot_results:
    icons = "".join([reel.get("name", "?") for reel in r.get("reels", [])])
    sr = r.get("result", "?")
    payout_str = r.get("payout", 0)
    if payout_str > 0:
        detail_lines.append(f"  {icons} {sr}(+{payout_str:,})")
    else:
        detail_lines.append(f"  {icons} {sr}")

improved_slot = (
    f"🎰 躺平老虎机 · {mock_slot_record.get('date')}\n\n"
    f"{ev_icon} 期望收益：{ev:+,.1f}/次 (底注5,000, 奖池{pool:,})\n"
    f"🎲 旋转次数：{total} 次 (免费{free} + 付费{paid})\n"
    f"🎯 胜负统计：赢 {wins} / 输 {losses} (胜率{win_rate})\n"
    f"💰 花费：{cost:,}  派彩：{payout:,}\n"
    f"{net_icon} 净收益：{net:+,}\n\n"
    f"🎬 旋转详情：\n" + "\n".join(detail_lines)
)
print(improved_slot)

# ============================================================
# 页面描述改进对比
# ============================================================
print("\n" + "=" * 70)
print("BEFORE — 当前老虎机页面描述 (EV说明)")
print("=" * 70)
print("""
  期望值(EV)计算说明
  RTP(Return To Player) = 玩家回报率，即每投入100元平均能拿回多少。
  EV(Expected Value) = 期望值，即每次旋转平均盈亏。
  计算方式：EV = Σ(每种结果概率 × 该结果派彩金额) - 底注
  例如底注5000时，三连概率7.05%派彩6250，二连概率~25%派彩1875，未中奖概率67.95%派彩0。
  加上Jackpot期望后得出综合EV。若EV为负(期望亏损)，启用\"仅期望盈利时抽\"则跳过付费旋转。
""")

print("=" * 70)
print("AFTER — 改进后老虎机页面描述")
print("=" * 70)
print("""
  老虎机玩法与策略指南

  🎰 基础机制
  每次旋转将消耗底注（默认 5,000 魔力值）。每日有免费旋转次数。
  三个转轮图案一致即为中奖，根据图案组合获得不同倍数的派彩。

  📊 期望值(EV)计算
  EV = Σ(每种中奖组合的概率 × 该组合的派彩) − 底注 + Jackpot期望分摊
  · EV > 0：长期盈利，建议全力旋转
  · EV < 0：长期亏损，建议只使用免费次数或跳过

  🔢 示例（底注 5,000）
  · 三连(图案全等)  概率 ~7%   派彩 6,250  (赚 +1,250)
  · 二连(两个相同)  概率 ~25%  派彩 1,875  (亏 −3,125)
  · 未中奖            概率 ~68%  派彩 0      (亏 −5,000)

  ⚙️ 开关建议
  ·「仅期望盈利时抽」开启 → 只在 EV > 0 时付费旋转（稳健策略）
  ·「仅期望盈利时抽」关闭 → 无论 EV 正负都全力旋转（追求 Jackpot）

  💡 小贴士
  EV 受奖池累积影响，奖池越大期望值越高。关注 EV 变化，在 EV 转正时加大力度。
""")

print("=" * 70)
print("对比总结")
print("=" * 70)
print("""
抽奖通知改进:
  ✅ 按类别分组（VIP/魔力值/邀请/道具）
  ✅ 显示中奖率统计
  ✅ 使用 emoji 图标区分类别
  ✅ 结构化层级，一目了然

老虎机通知改进:
  ✅ emoji 图标美化视觉
  ✅ 净收益用箭头指示盈亏方向
  ✅ EV 红/绿/黄三色标识
  ✅ 旋转详情紧凑排版（图标连排）
  ✅ 胜率百分比

页面描述改进:
  ✅ 分小节: 基础机制 → EV计算 → 示例 → 建议 → 小贴士
  ✅ RTP 概念（定义了但未使用）→ 移除
  ✅ 表格化概率/派彩对比
  ✅ 开关含义解释清楚
  ✅ 增加小贴士板块
""")