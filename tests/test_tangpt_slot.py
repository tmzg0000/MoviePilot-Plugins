"""测试躺平老虎机 API 响应"""
import requests, json, re, os, urllib3
urllib3.disable_warnings()

proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
proxies = {"http": proxy, "https": proxy} if proxy else None

cookie = 'c_secure_pass=eyJ1c2VyX2lkIjoiMTAzODIiLCJleHBpcmVzIjoxNzk4MTMyNTc3fS44NDczOTkxNzY2ZTM2MmI4ZTcxNDU1YmExY2NhOTU4OTEzZGM1ZTk3MmYxNWJkNzg4YzQ2NWQ4M2UyZWMxNmI3'

headers = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'cookie': cookie,
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

print("=== Step 1: Get slot page for spin_token ===")
try:
    r = requests.get('https://www.tangpt.top/omnibot_slot.php',
        headers=headers, timeout=15, verify=False, proxies=proxies)
    html = r.text
    state_start = html.find('__slotInitialState')
    brace_start = html.find('{', state_start)
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
    state = json.loads(html[brace_start:end_pos])
    spin_token = state.get("user_state", {}).get("spin_token", "")
    print(f"spin_token: {spin_token}")
    slot_config = state.get("config", {})
    print(f"base_cost: {slot_config.get('base_cost')}")
    print(f"daily_free_spins: {slot_config.get('daily_free_spins')}")
    prize_rows = slot_config.get('prize_rows', [])
    for row in prize_rows:
        print(f"  {row.get('name')}: prob={row.get('probability')}%, "
              f"payout_mult={row.get('payout_multiplier')}, rule_type={row.get('rule_type', '')}")

    if spin_token:
        api_headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'x-requested-with': 'XMLHttpRequest',
            'referer': 'https://www.tangpt.top/omnibot_slot.php',
            'cookie': cookie,
            'user-agent': 'Mozilla/5.0'
        }
        print()
        print("=== Step 2: Slot Draw API (multiplier=1) ===")
        for i in range(min(3, slot_config.get('daily_free_spins', 2))):
            r2 = requests.post('https://www.tangpt.top/web/omnibot/slot-machine/draw',
                headers=api_headers, data={'multiplier': '1', 'spin_token': spin_token},
                timeout=15, verify=False, proxies=proxies)
            resp = r2.json()
            print(f"  Spin {i+1}: ok={resp.get('ok')}, result={resp.get('result')}, "
                  f"payout={resp.get('payout')}, total_cost={resp.get('total_cost')}, "
                  f"reward={resp.get('reward')}, is_free_spin={resp.get('is_free_spin')}")
            reels = resp.get('reels', [])
            for reel in reels:
                print(f"    reel: {reel.get('name')} (id={reel.get('symbol_id')}, pos={reel.get('position')})")
            row_info = resp.get('row', {})
            if row_info:
                print(f"    row: {row_info.get('name')}, is_jackpot={row_info.get('is_jackpot')}")
            spin_token = resp.get('spin_token') or spin_token
            if resp.get('is_free_spin'):
                print(f"    FREE SPIN awarded!")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()