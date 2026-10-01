# shared_contract_change_request

- request_id: `CN-V3-CURRENT-MAIN-FOUNDATION-01-PACKAGE-REGISTRATION`
- blocker: `quant_cn_package_registration_missing`
- owner: `integrator`
- requested_change: 在架构批准的独立集成票据中，将 `quant_cn*` 加入 `pyproject.toml` 的 setuptools package discovery。
- reason: 本 Goal 的 `quant_cn` namespace 在仓库根目录可导入，但 current main 的 wheel/package discovery 只包含 `backend*`、`quant_us*`、`quant_shared*` 与 `integrations*`。
- prohibited_here: A 股程序员不得修改 `pyproject.toml` 或其他共享构建合同。
- acceptance: 独立 integrator worktree 基于届时 current main 修改共享构建配置，并证明 wheel/sdist 包含 `quant_cn`，同时不改变交易安全旗标。

本请求不授权 merge、promotion、paper、live、private、order、broker 或网络能力。
