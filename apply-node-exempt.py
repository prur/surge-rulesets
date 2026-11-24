#!/usr/bin/env python3
"""apply-node-exempt.py — 把 node-exempt.json 的放行规则铺到**整支舰队**的 sing-box route。

问题：节点 route 里有 `{"rule_set":"geosite-cn","action":"reject"}`，而 geosite-cn 收录了
www.gstatic.com / ssl.gstatic.com / g0-g3.gstatic.com / *.googleapis.com 等 Google 前端与 API 域。
客户端把这些域送到节点走代理时，节点按名单直接 reject，客户端表现 `SSL_ERROR_SYSCALL`/秒断。

本脚本在 geosite-cn reject **之前**维持一条
`{"domain_suffix":[...],"action":"route","outbound":"direct"}`，让这些域正常从节点出去。

用法：
  python3 apply-node-exempt.py --verify                  # 只读巡检整支舰队
  python3 apply-node-exempt.py --apply                   # 幂等写入 + sing-box check + 重启
  python3 apply-node-exempt.py --apply --hosts dmit-annual,bandwagon
  python3 apply-node-exempt.py --rollback                # 移除本规则（按标记精确识别）

幂等/收敛：以"outbound=direct 且域列表含 gstatic.com"识别既有规则；
  内容不同 -> 原位规范化（不会叠加第二条）；位置不对 -> 移到 geosite-cn 之前。
顺序要求：先用本脚本铺节点，再 gen-mirror.py --push 收紧镜像（见 mirror-exempt.list 注释）。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
EXEMPT = os.path.join(ROOT, "node-exempt.json")
CONFIG = "/etc/sing-box/config.json"

# 会用到 geosite-cn reject 的代理出口机队（ssh alias）
DEFAULT_HOSTS = [
    "dmit-annual",
    "bandwagon",
    "rfc-jp",
    "po0-hk",
    "bero-kvm18257",
    "greencloud-sg",
    "gcp-us-node",
    "gcp-tw-node",
    "gcp-sg-node",
    "gcp-jp-node",
]

REMOTE = r'''
import json, os, shutil, sys, time
mode, cfg, rule_json = sys.argv[1], sys.argv[2], sys.argv[3]
canonical = json.loads(rule_json)
try:
    c = json.load(open(cfg))
except FileNotFoundError:
    print("NO_CONFIG"); sys.exit(0)
rules = c.get("route", {}).get("rules", [])
geosite_idx = next((i for i, r in enumerate(rules) if r.get("rule_set") == "geosite-cn"), None)

# 含 socks-in (如 sub2api 内部入站) 的节点：仅对常规代理入站放行，防止 socks-in 绕过 post-resolve SSRF 防护
inbound_tags = [ib.get("tag") for ib in c.get("inbounds", []) if ib.get("tag")]
effective = dict(canonical)
if "socks-in" in inbound_tags:
    proxy_inbounds = [t for t in inbound_tags if t != "socks-in"]
    if proxy_inbounds:
        effective["inbound"] = proxy_inbounds

def is_marker(r):
    vals = list(r.get("domain", [])) + list(r.get("domain_suffix", []))
    return r.get("outbound") == "direct" and any(v == "gstatic.com" or v.endswith(".gstatic.com") for v in vals)

def backup_cfg(path):
    st = os.stat(path)
    bak = path + ".bak-%d" % int(time.time())
    shutil.copy2(path, bak)
    try:
        os.chown(bak, st.st_uid, st.st_gid)
    except PermissionError:
        pass
    os.chmod(bak, st.st_mode & 0o7777)

idx = next((i for i, r in enumerate(rules) if is_marker(r)), None)

if mode == "verify":
    if geosite_idx is None:
        print("NO_GEOSITE"); sys.exit(0)
    if idx is None:
        print("ABSENT"); sys.exit(0)
    if idx >= geosite_idx:
        print("PRESENT_WRONG_POSITION"); sys.exit(0)
    print("PRESENT_OK" if rules[idx] == effective else "PRESENT_DRIFT"); sys.exit(0)

if geosite_idx is None:
    print("NO_GEOSITE"); sys.exit(1)

if mode == "rollback":
    if idx is None:
        print("ABSENT"); sys.exit(0)
    backup_cfg(cfg)
    rules.pop(idx)
    json.dump(c, open(cfg, "w"), indent=2, ensure_ascii=False)
    print("ROLLED_BACK_AT", idx); sys.exit(0)

if idx is not None and idx < geosite_idx and rules[idx] == effective:
    print("ALREADY"); sys.exit(0)

backup_cfg(cfg)
if idx is None:
    rules.insert(geosite_idx, effective); print("INSERTED_AT", geosite_idx)
else:
    rules.pop(idx)
    # 重新定位 geosite-cn（删除后下标可能变化）
    geosite_idx = next(i for i, r in enumerate(rules) if r.get("rule_set") == "geosite-cn")
    rules.insert(geosite_idx, effective); print("NORMALIZED_AT", geosite_idx)
json.dump(c, open(cfg, "w"), indent=2, ensure_ascii=False)
'''


def sh(host, cmd, input_text=None, timeout=150):
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=30", host, cmd],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def main():
    args = sys.argv[1:]
    mode = "verify"
    if "--apply" in args:
        mode = "apply"
    elif "--rollback" in args:
        mode = "rollback"
    hosts = DEFAULT_HOSTS
    for i, a in enumerate(args):
        if a == "--hosts" and i + 1 < len(args):
            hosts = [h.strip() for h in args[i + 1].split(",") if h.strip()]

    canonical = json.load(open(EXEMPT, encoding="utf-8"))["rule"]
    rule_json = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    sudo_prefix = 'SUDO=$([ "$(id -u)" -eq 0 ] && echo "" || echo "sudo -n");'
    rc = 0
    for host in hosts:
        try:
            run = sh(host, f"{sudo_prefix} $SUDO python3 - {mode} {CONFIG} '{rule_json}'", input_text=REMOTE)
            if run.returncode != 0 and not run.stdout.strip():
                print(f"{host:16s} SSH_FAIL {run.stderr.strip()[:80]}")
                rc = 1
                continue
            out = run.stdout.strip()
            state = out.splitlines()[-1] if out else "NO_OUTPUT"
            if mode != "verify" and state.split()[0] in ("INSERTED_AT", "NORMALIZED_AT", "ROLLED_BACK_AT"):
                chk = sh(host, f"{sudo_prefix} $SUDO sing-box check -c {CONFIG} && echo CHECK_OK")
                if "CHECK_OK" not in chk.stdout:
                    print(f"{host:16s} {state:22s} CHECK_FAILED {chk.stderr.strip()[-120:]}")
                    rc = 1
                    continue
                rst = sh(host, f"{sudo_prefix} $SUDO systemctl restart sing-box; sleep 2; $SUDO systemctl is-active sing-box")
                active = rst.stdout.strip().splitlines()[-1] if rst.stdout.strip() else "?"
                print(f"{host:16s} {state:22s} restart={'ok' if active == 'active' else 'FAIL(' + active + ')'}")
                if active != "active":
                    rc = 1
            else:
                print(f"{host:16s} {state}")
                # NO_GEOSITE = 该机没有 geosite-cn reject，不需要本规则，非故障
                if state.split()[0] in ("NO_OUTPUT", "ABSENT", "PRESENT_WRONG_POSITION", "PRESENT_DRIFT"):
                    rc = 1
        except Exception as e:
            print(f"{host:16s} ERROR {type(e).__name__}: {e}")
            rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
