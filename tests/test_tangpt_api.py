"""测试躺平站点 API 响应"""
import requests, json, re, os, urllib3
urllib3.disable_warnings()

proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
proxies = {"http": proxy, "https": proxy} if proxy else None

cookie = 'c_secure_pass=eyJ1c2VyX2lkIjoiMTAzODIiLCJleHBpcmVzIjoxNzk4MTMyNTc3fS44NDczOTkxNzY2ZTM2MmI4ZTcxNDU1YmExY2NhOTU4OTEzZGM1ZTk3MmYxNWJkNzg4YzQ2NWQ4M2UyZWMxNmI3'

headers = {
    'accept': 'application/json, text/javascript, */*; q=0.01',
    'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'x-requested-with': 'XMLHttpRequest',
    'referer': 'https://www.tangpt.top/omnibot_lottery.php',
    'cookie': cookie,
    'user-agent': 'Mozilla/5.0'
}

print("=== Test 1: Lottery Draw API ===")
try:
    r = requests.post('https://www.tangpt.top/web/omnibot/lottery/draw',
        headers=headers, data={'count': '10'}, timeout=15, verify=False, proxies=proxies)
    print(f"Status: {r.status_code}")
    resp = r.json()
    print(f"ok: {resp.get('ok')}")
    print(f"draw_count: {resp.get('draw_count')}")
    print(f"cost_per_draw: {resp.get('cost_per_draw')}")
    print(f"total_cost: {resp.get('total_cost')}")
    print(f"total_compensated_bonus: {resp.get('total_compensated_bonus')}")
    print(f"total_awarded_bonus: {resp.get('total_awarded_bonus')}")
    results = resp.get('results', [])
    print(f"results count: {len(results)}")
    for item in results[:5]:
        print(f"  - id={item.get('prize_id')}, name={item.get('prize_name')!r}, "
              f"bonus_delta={item.get('bonus_delta')}, comp_bonus={item.get('comp_bonus')}")
except Exception as e:
    print(f"Error: {e}")

print()
print("=== Test 2: Slot Page HTML ===")
try:
    r2 = requests.get('https://www.tangpt.top/omnibot_slot.php',
        headers={'cookie': cookie, 'user-agent': 'Mozilla/5.0'}, timeout=15, verify=False, proxies=proxies)
    print(f"Status: {r2.status_code}")
    html = r2.text

    # Look for __slotInitialState
    state_start = html.find('__slotInitialState')
    print(f"__slotInitialState found at: {state_start}")

    if state_start >= 0:
        brace_start = html.find('{', state_start)
        if brace_start >= 0:
            depth = 0
            end_pos = brace_start
            for i in range(brace_start, len(html)):
                c = html[i]
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                    if depth == 0:
                        end_pos = i + 1
                        break
            if depth == 0 and end_pos > brace_start:
                config_raw = html[brace_start:end_pos]
                try:
                    state = json.loads(config_raw)
                    user_state = state.get("user_state", {}) or {}
                    spin_token_s = user_state.get("spin_token", "")
                    print(f"spin_token from __slotInitialState: {spin_token_s[:60] if spin_token_s else 'EMPTY'}")
                    slot_config = state.get("config", {})
                    print(f"base_cost: {slot_config.get('base_cost')}")
                    print(f"daily_free_spins: {slot_config.get('daily_free_spins')}")
                    print(f"prize_rows count: {len(slot_config.get('prize_rows', []))}")
                    for row in slot_config.get('prize_rows', [])[:3]:
                        print(f"  - {row.get('name')}: prob={row.get('probability')}%, "
                              f"payout_mult={row.get('payout_multiplier')}")
                    jackpot_pool = slot_config.get('jackpot_pool', 0)
                    print(f"jackpot_pool: {jackpot_pool}")
                except json.JSONDecodeError:
                    print(f"Failed to parse JSON: {config_raw[:200]}...")

    if state_start < 0:
        # Try other patterns
        tests = [
            (r'spin_token["\s:=]+["\']?([a-f0-9]{32})["\']?', "hex32"),
            (r'spin_token\s*=\s*["\']([^"\']+)["\']', "assign"),
            (r'spin_token["\']?\s*:\s*["\']?([a-f0-9]+)["\']?', "json"),
            (r'data-spin-token=["\']([^"\']+)["\']', "data-spin-token"),
        ]
        for pat, label in tests:
            try:
                m = re.search(pat, html)
                if m:
                    print(f"  Found via {label}: {m.group(1)[:60]}")
                else:
                    print(f"  No match: {label}")
            except Exception as e2:
                print(f"  Error {label}: {e2}")

    # Print HTML snippet around key areas
    for kw in ['spin_token', 'spin-token', 'slotInitial']:
        idx = html.find(kw)
        if idx >= 0:
            start = max(0, idx - 50)
            end = min(len(html), idx + 150)
            print(f"\n  Context near '{kw}' at {idx}:")
            print(f"  ...{html[start:end]}...")
            break

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()