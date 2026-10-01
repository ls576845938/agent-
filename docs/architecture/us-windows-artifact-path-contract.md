# US Windows artifact path contract

`US-V3-WINDOWS-ARTIFACT-PATH-CONTRACT-01` defines durable US artifact paths as
identity-root-relative POSIX strings. A durable field must not contain a drive,
machine-private prefix, backslash, or parent traversal segment.

The contract covers paper-review evidence-pack bindings, startup-sync audit events,
paper-session manifest history, and startup-sync failure events. Physical I/O still
uses `Path` objects resolved from the configured data or ledger root. Paper gate,
broker-adapter, reconciliation, and submission semantics are unchanged.

External or temporary absolute paths use
`us_artifact_path_reference_v1` with `path_kind=external_absolute` and
`stable_identity=false`. Such references cannot be hashed as stable artifact
identity. Durable references use `path_kind=durable_relative` and the G01 shared
canonical serializer/hash.

## Shared change request

G01 provides canonical `Path` serialization, `EvidenceReference` slash
normalization, and immutable repository-relative publication. It does not yet
define an asset-neutral schema that distinguishes durable relative identity from
external absolute location. A future integrator-owned shared ticket should promote
`us_artifact_path_reference_v1` into `quant_shared`; this Goal intentionally does
not modify shared contracts.
