# Optional session evidence

Status: approved on 2026-11-14 and released in v0.3.0 under project P02.

The accepted specification is
[design 0007](../../design/0007-optional-session-evidence.md). It defines the
record model, persistence, meanings, adapters, compatibility, and verification
requirements. This planning entry links that specification from the project's
standard planning location without maintaining a second copy.

The approved outcome is optional session evidence layered onto existing
discovery. Store separate event and assessment records, derive one combined
summary, and preserve the distinction between lifecycle observations, closure
intent, work completion, and present liveness. A recap-only reopening must not
look like resumed task work. Missing records remain unknown.

Delivery is split into the storage/CLI prerequisite and the companion
plugin/documentation change. The [project record](../../../projects/P02-optional-session-evidence.md)
tracks implementation, validation, and release status.
