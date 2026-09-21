#!/bin/bash
# Weekly integrity check for the node-reject-mirror ruleset (Surge).
# Compares the jsdelivr-served copy against the last pushed version (git HEAD).
set -u
cd "$(dirname "$0")" || exit 1
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
URL="https://cdn.jsdelivr.net/gh/prur/surge-rulesets@main/node-reject-mirror.list"
if ! curl -s -m 45 -o "$TMP" "$URL" || [ ! -s "$TMP" ]; then
  echo "⚠️ Surge 镜像规则集校验: 无法获取 jsdelivr 副本（网络或代理异常），本次跳过"
  exit 1
fi
EXP=$(git show HEAD:node-reject-mirror.list | shasum -a 256 | awk '{print $1}')
GOT=$(shasum -a 256 "$TMP" | awk '{print $1}')
ROWS=$(wc -l < "$TMP" | tr -d ' ')
if [ "$EXP" = "$GOT" ]; then
  echo "✅ Surge 镜像规则集校验: MATCH（${ROWS} 行, sha ${GOT:0:12}…）"
else
  echo "🚨 Surge 镜像规则集校验: MISMATCH！served ≠ git HEAD（可能被篡改或缓存滞后，请人工核查）"
  echo "   HEAD:   $EXP"
  echo "   served: $GOT"
  exit 2
fi
