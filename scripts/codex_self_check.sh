#!/usr/bin/env bash
# Codex 配置自检（Linux / macOS；本机 WSL 也可用）
# 1) 修复不完整 [model_providers.*]（缺 name 会导致 missing field `name`）
# 2) 校验 config.toml 可被 Python tomllib 解析
# 3) 可选：若已配置 ~/.codex/.env，测试经代理访问 chatgpt.com

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${ROOT}:${PYTHONPATH:-}"

echo "== [1] 修复 ~/.codex/config.toml =="
python3 "${ROOT}/scripts/codex_repair_config.py"

echo ""
echo "== [2] 当前 config.toml（前 40 行） =="
CFG="${HOME}/.codex/config.toml"
if [[ -f "$CFG" ]]; then
  sed -n '1,40p' "$CFG"
else
  echo "未找到 $CFG"
fi

echo ""
echo "== [3] ~/.codex/.env（若存在） =="
if [[ -f "${HOME}/.codex/.env" ]]; then
  grep -v '^#' "${HOME}/.codex/.env" || true
else
  echo "无 .env"
fi

echo ""
echo "== [4] 代理探测（需本机 7890 有 HTTP 代理；失败可忽略） =="
if [[ -f "${HOME}/.codex/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${HOME}/.codex/.env"
  set +a
fi
if [[ -n "${HTTP_PROXY:-}" ]]; then
  curl -sS -I --max-time 12 -x "${HTTP_PROXY}" https://chatgpt.com/ 2>&1 | head -n 5 || echo "curl 失败：检查代理端口或 TUN/系统代理"
else
  echo "未设置 HTTP_PROXY，跳过 curl"
fi

echo ""
echo "插件版 Cursor：请在「用户设置 JSON」中设置"
echo '  "http.proxy": "http://127.0.0.1:7890",'
echo '  "http.proxySupport": "override",'
echo '  "http.proxyStrictSSL": false'
echo "然后 Developer: Reload Window。"
