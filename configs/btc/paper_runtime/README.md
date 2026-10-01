# BTC Paper Runtime 人工证明

这个目录只放非密钥证明文件，用来证明 OKX paper 账户运行环境已经人工核对。

使用方式：

1. 复制 `account_runtime_attestation.template.json` 为 `account_runtime_attestation.json`。
2. 只填写人工确认结果、审批编号、过期时间和证据代号。
3. 不要写入 API key、secret、passphrase、token、签名、账号密码或截图中的敏感内容。
4. 没有完成真实人工确认时，所有 `*_verified` 保持 `false`。
5. 运行 `python scripts/build_btc_paper_account_runtime_attestation.py` 生成证明报告。

即使该证明通过，也只代表账户运行环境证明完整；它不会写 paper 队列，也不会解锁 live。paper/live 还必须继续通过 server time、交易所规则、paper fill、风控熔断、observe-only 和 micro-live preflight 等 gate。
