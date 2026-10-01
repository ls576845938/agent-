# Coding Style

## 目标

代码应服务于可审计、可回放、可测试的量化系统，而不是追求炫技或短期脚本速度。

## 规则

1. 核心对象优先使用 typed dataclass、Pydantic model 或明确 schema。
2. 交易路径中的函数不得静默吞异常。
3. 文件、数据库、网络、交易所 SDK 访问必须集中在 adapter/repository 层。
4. Domain 层不得读取环境变量、当前时间、文件系统或外部 API。
5. 函数名应表达业务含义，例如 `build_target_position` 优于 `process_data`。
6. 回测、paper、live 共享核心策略逻辑，差异只能在 data adapter 和 execution adapter。
7. 时间戳必须显式时区；系统内部默认 UTC。
8. 不允许隐式全局状态影响策略结果。
9. 不允许在核心路径中使用随机数，除非显式传入 seed 并记录到 manifest。
10. 不允许把 notebooks 或一次性研究脚本作为生产依赖。

## Codex 检查

修改代码前确认：

- 是否破坏模块边界。
- 是否绕过已有 service layer。
- 是否新增无法测试的隐式副作用。
- 是否新增缺少 schema 的松散 dict。
- 是否需要更新 contract test。

