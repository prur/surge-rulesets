#!/usr/bin/env python3
"""Regenerate node-reject-mirror.list from the node's sing-box rule-set (geosite-cn).

Usage: python3 gen-mirror.py [--push|--verify]
Pulls the decompiled list from the node via ssh (alias from NODE_SSH env), converts to Surge format
(DOMAIN / DOMAIN-SUFFIX lines), excludes red-line families (microsoft/msft/
xboxlive/officewebapps/stripe), writes node-reject-mirror.list next to this
script, and optionally commits + pushes and purges the jsdelivr cache.
"""
import json, re, subprocess, sys, os

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "node-reject-mirror.list")
RED = re.compile(r"microsoft|msft|xboxlive|officewebapps|stripe", re.I)
DROP = {"com", "net", "org", "info", "biz"}
SSH = os.environ.get("NODE_SSH", "")  # ssh alias for the node (set NODE_SSH; never hard-coded)


def main():
    if "--verify" in sys.argv:
        import hashlib
        local = hashlib.sha256(open(OUT, "rb").read()).hexdigest()
        served = subprocess.run(["curl", "-s", "-m", "30",
            "https://cdn.jsdelivr.net/gh/prur/surge-rulesets@main/node-reject-mirror.list"],
            capture_output=True).stdout
        ssha = hashlib.sha256(served).hexdigest()
        print("local :", local)
        print("served:", ssha)
        ok = bool(served) and local == ssha
        print("MATCH" if ok else "MISMATCH / fetch failed")
        sys.exit(0 if ok else 2)
    if not SSH:
        sys.exit("NODE_SSH is not set (ssh alias for the node)")
    raw = subprocess.run(
        ["ssh", SSH,
         "sing-box rule-set decompile /etc/sing-box/geosite-cn.srs >/dev/null 2>&1; cat /etc/sing-box/geosite-cn.json"],
        capture_output=True, text=True, check=True).stdout
    g = json.loads(raw)
    dom, suf, red, reg = set(), set(), 0, 0
    for r in g.get("rules", []):
        for key, vals in r.items():
            if not isinstance(vals, list):
                continue
            for x in vals:
                x = x.strip().lower().rstrip(".")
                x = x[1:] if x.startswith(".") else x
                if not x:
                    continue
                if x in DROP or RED.search(x):
                    red += 1
                    continue
                if key == "domain":
                    dom.add(x)
                elif key == "domain_suffix":
                    suf.add(x)
                elif key == "domain_regex":
                    reg += 1
    lines = [f"DOMAIN-SUFFIX,{x}" for x in sorted(suf)] + [f"DOMAIN,{x}" for x in sorted(dom - suf)]
    with open(OUT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} lines -> {OUT} (excluded red-line {red}, skipped regex {reg})")
    if "--push" in sys.argv:
        subprocess.run(["git", "-C", ROOT, "add", os.path.basename(OUT)], check=True)
        subprocess.run(["git", "-C", ROOT, "-c", "user.email=prur@users.noreply.github.com",
                        "-c", "user.name=prur", "commit", "-m", f"regen: {len(lines)} rules"])
        subprocess.run(["git", "-C", ROOT, "push"], check=True)
        subprocess.run(["curl", "-s", "-m", "20",
                        "https://purge.jsdelivr.net/gh/prur/surge-rulesets@main/node-reject-mirror.list"])
        print("pushed + jsdelivr purge requested")


if __name__ == "__main__":
    main()
