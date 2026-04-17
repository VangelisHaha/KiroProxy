# Changelog

## v1.7.17 - 2026-04-18

### Core fixes
- Fixed Kiro upstream `profileArn is required` failures by enforcing top-level `profileArn` in outbound Kiro requests.
- Added auth guard and recovery flow for missing `profileArn` (refresh, env/log backfill, clear diagnostics).
- Improved credential loading resilience with cache-directory JSON merge and corrupted JSON field recovery.
- Stabilized machine fingerprint generation (`uuid > profileArn > clientId > system id`) to reduce multi-account jitter.

### Protocol compatibility
- Deepened Anthropic/OpenAI/Responses/Gemini conversion compatibility for current CLI behaviors.
- Added stronger history/tool pairing normalization to reduce protocol drift regressions.
- Added thinking-prefix mapping support for Anthropic/OpenAI/Gemini request variants.
- Expanded tool description handling for long tool schemas used by external clients.

### Regression testing
- Added end-to-end fixture regression tests for:
  - Claude Code (`/v1/messages`)
  - Codex Responses API (`/v1/responses`)
  - Gemini CLI (`/v1/models/*:generateContent`)
- Added real flow fixture regression coverage to lock `profileArn` auth-error classification behavior.
- Added credential merge/corruption recovery tests and machine-id stability tests.
