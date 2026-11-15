# surge-rulesets

Generated Surge rule sets (data files; do not hand-edit).

- `node-reject-mirror.list` — mirror of the upstream node's CN-domain reject list, converted to Surge format.
  Purpose: client-side routing must never send domains that the node would reject.
- `mirror-exempt.list` — **手写白名单**：永不进入镜像的域（Google 前端静态 CDN、*.googleapis.com 等）。
  这些域客户端必须能自由走代理，靠镜像"强制直连"会让网页应用落到国内单点 CDN 边缘而报错。
- `node-exempt.json` — 节点侧 sing-box route 的放行规则体（`domain_suffix: gstatic.com, googleapis.com`
  → `outbound: direct`），插在 `geosite-cn` reject 之前，避免节点把客户端送来代理的 Google 域秒拒。
- `apply-node-exempt.py` — 把上面那条节点规则**幂等**铺到整支机队（`--verify` / `--apply` / `--rollback`）。

## 顺序（重要）

```
python3 apply-node-exempt.py --apply     # 1. 先让节点不再 reject
NODE_SSH=<ssh-alias> python3 gen-mirror.py --push   # 2. 再从镜像剔除并下发
```

反了会让还没放行的节点在过渡期 reject 这些域（客户端表现为 `SSL_ERROR_SYSCALL` / 秒断）。

## 生成与校验

```
NODE_SSH=<ssh-alias> python3 gen-mirror.py --push   # 从节点 geosite-cn 重建镜像，提交+推送+清 jsdelivr 缓存
python3 gen-mirror.py --verify                      # sha256(local) vs sha256(served by jsdelivr)
bash verify-weekly.sh                               # 每周一 cron 用的 same 校验
```

## 判定"某域该不该进镜像"

只问一句：**节点会 reject 它，而客户端又希望把流量送到节点吗？**

- 是 → 不该进镜像，进 `mirror-exempt.list`，同时进 `node-exempt.json`。
- 否（客户端本来就该直连，例如国内域名、更新包 CDN、连通性探测）→ 留在镜像里。
