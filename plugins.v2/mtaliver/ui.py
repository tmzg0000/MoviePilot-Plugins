"""MoviePilot FormRender button handlers using its authenticated API client."""
import json

# FormRender evaluates onClick with the current `model` in scope. Use the host's
# API client so its configured base URL, bearer token and reverse proxy work.
_FIELDS = ('enabled', 'notify', 'cron', 'site_url', 'username', 'password', 'email',
           'email_code', 'api_key', 'api_base', 'ratio_warn', 'verify_minutes',
           'interval_days', 'api_verify')


def action_handler(action: str) -> str:
    if action not in ('send_code', 'login', 'refresh_session'):
        raise ValueError('unknown login action')
    return r'''async () => {
      if (model.auth_busy) return;
      model.auth_busy = true;
      model.auth_success = false;
      model.auth_status = ACTION === 'send_code' ? '正在获取验证码，请稍候…' :
        ACTION === 'login' ? '正在登录并保存会话，请稍候…' : '正在刷新登录会话，请稍候…';
      try {
        if (!window.MoviePilotAPI) {
          model.auth_status = '当前 MoviePilot 前端不支持插件按钮接口，请更新 MoviePilot 后重试';
          return;
        }
        const payload = {};
        for (const key of FIELDS) payload[key] = model[key];
        if (ACTION !== 'login') delete payload.email_code;
        const reply = await window.MoviePilotAPI.post(
          'plugin/MtAliver/' + ACTION, payload, {timeout: 240000});
        model.auth_success = Boolean(reply && reply.success);
        model.auth_status = (reply && reply.message) || '接口没有返回结果，请查看插件记录';
      } catch (e) {
        model.auth_status = '请求未完成，请稍后重开结果页核对状态；若未执行，请重试';
      } finally {
        if (ACTION === 'login') model.email_code = '';
        model.auth_busy = false;
      }
    }'''.replace('ACTION', json.dumps(action)).replace('FIELDS', json.dumps(_FIELDS))


def action_button(action: str, label: str, color: str) -> dict:
    return {'component': 'VCol', 'props': {'cols': 12, 'md': 4}, 'content': [{
        'component': 'VBtn', 'text': label, 'props': {
            'color': color, 'block': True, 'type': 'button',
            'disabled': '{{ auth_busy }}', 'loading': '{{ auth_busy }}',
            'onClick': action_handler(action)}}]}
