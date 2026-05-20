"""测试躺平抽奖 970 次 — 批次分解 + 通知效果验证"""
import requests, json, time, os, urllib3
from collections import Counter
urllib3.disable_warnings()

proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
proxies = {"http": proxy, "https": proxy} if proxy else None

COOKIE = 'c_secure_pass=eyJ1c2VyX2lkIjoiMTAzODIiLCJleHBpcmVzIjoxNzk4MTMyNTc3fS44NDczOTkxNzY2ZTM2MmI4ZTcxNDU1YmExY2NhOTU4OTEzZGM1ZTk3MmYxNWJkNzg4YzQ2NWQ4M2UyZWMxNmI3'
ALLOWED = [100, 50, 20, 10, 1]
TARGET = 970
MAX_BATCH = 100

def decompose(n, mx=100):
    batches = []
    r = n
    for s in ALLOWED:
        if s > mx:
            continue
        while r >= s:
            batches.append(s)
            r -= s
    return batches

def do_draw(count):
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "x-requested-with": "XMLHttpRequest",
        "referer": "https://www.tangpt.top/omnibot_lottery.php",
        "cookie": COOKIE,
        "user-agent": "Mozilla/5.0"
    }
    r = requests.post("https://www.tangpt.top/web/omnibot/lottery/draw",
        headers=headers, data={"count": str(count)}, timeout=30, verify=False, proxies=proxies)
    if r.status_code != 200:
        return {"success": False, "message": f"HTTP {r.status_code}"}
    try:
        result = r.json()
    except Exception:
        return {"success": False, "message": f"JSON parse fail: {r.text[:200]}"}

    if result.get("ok"):
        prizes = []
        for item in result.get("results", []):
            name = item.get("prize_name", "")
            if name:
                prizes.append(name.strip())
        return {
            "success": True,
            "prizes": prizes,
            "total_cost": result.get("total_cost", 0),
            "total_compensated": result.get("total_compensated_bonus", 0),
            "total_awarded": result.get("total_awarded_bonus", 0),
        }
    else:
        return {"success": False, "message": result.get("msg", "unknown")}

batches = decompose(TARGET, MAX_BATCH)
print(f"目标: {TARGET}次  批次: {len(batches)}批  {batches}")
print(f"预计消耗魔力: {TARGET * 10000:,}")
print("=" * 60)

all_prizes = []
total_cost = 0
total_comp = 0
total_award = 0
completed = 0
errors = 0

for i, batch in enumerate(batches):
    print(f"[{i+1}/{len(batches)}] 抽 {batch} 次...", end=" ", flush=True)
    result = do_draw(batch)
    if not result["success"]:
        print(f"FAIL: {result['message']}")
        errors += 1
        if errors >= 3:
            print("Too many errors, stopping")
            break
        time.sleep(2)
        continue

    prizes = result["prizes"]
    all_prizes.extend(prizes)
    completed += batch
    total_cost += result["total_cost"]
    total_comp += result["total_compensated"]
    total_award += result["total_awarded"]
    pc = Counter(prizes)
    summary = ", ".join([f"{n}×{c}" for n, c in pc.most_common()])
    print(f"OK  奖品: {summary}")

    vip = any("VIP" in p or "vip" in p for p in prizes)
    if vip:
        print("*** VIP! Stopping ***")
        break

    time.sleep(1.5)

print("=" * 60)
print(f"完成: {completed}/{TARGET}  请求: {len(batches)}批  错误: {errors}")
print(f"花费: {total_cost:,}  返还: {total_comp:,}  奖品价值: {total_award:,}")
print(f"净支出: {total_cost - total_comp - total_award:,}")
print()

# ===== Notification Simulation =====
prize_counter = Counter(all_prizes)
total_prizes = len(all_prizes)
winning_count = sum(1 for p in all_prizes if p not in ("谢谢参与", "thanks", "谢谢惠顾", "惠顾"))
win_rate = f"{(winning_count / total_prizes * 100):.1f}%" if total_prizes > 0 else "0%"

def group(category, keyword, emoji):
    items = [p for p in all_prizes if keyword.lower() in p.lower()]
    if not items:
        return ""
    grouped = Counter(items)
    parts = []
    for name, cnt in grouped.most_common():
        short = name.split(": ")[-1] if ": " in name else name
        parts.append(f"{short}×{cnt}")
    return f"  {emoji} {category}：{', '.join(parts)}"

thank_kw = ["谢谢参与", "thanks", "谢谢惠顾", "惠顾"]
thank_count = sum(prize_counter.get(k, 0) for k in thank_kw)

cat_lines = []
cat_lines.append(group("VIP", "vip", "👑"))
cat_lines.append(group("魔力值", "魔力", "✨"))
cat_lines.append(group("邀请", "邀请", "📨"))
cat_lines.append(group("勋章", "勋章", "🏅"))
cat_lines.append(group("道具", "道具", "🎁"))
if thank_count > 0:
    cat_lines.append(f"  💤 谢谢惠顾：{thank_count}次")
all_kw = ["vip", "魔力", "邀请", "勋章", "道具", "谢谢", "thanks", "惠顾"]
other = [p for p in all_prizes if not any(k in p.lower() for k in all_kw)]
if other:
    oc = Counter(other)
    cat_lines.append(f"  📦 其他：{', '.join([f'{n}×{c}' for n, c in oc.most_common()])}")
prize_block = "\n".join([l for l in cat_lines if l]) or "  无奖品记录"

total_back = total_comp + total_award
net = total_cost - total_back

print("=" * 60)
print("飞书推送效果预览".center(60))
print("=" * 60)
print(f"""
【躺平自动抽奖助手】

📅 日期：{__import__('datetime').datetime.now().strftime('%Y-%m-%d')}
🎯 抽奖次数：{completed}/{TARGET}  状态：已达成
🎉 中奖率：{win_rate} ({winning_count}/{total_prizes})
💰 花费：{total_cost:,}  返还：{total_comp:,}  奖品价值：{total_award:,}  净支出：{net:,}

📊 奖品汇总：
{prize_block}
""")