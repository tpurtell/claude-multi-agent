# Verification record

## DeepSeek inline-tool recovery — 2026-10-22

Native Claude Code 2.1.306's refusal classifier now also recognizes the exact
LiteLLM DeepSeek `unknown variant tool_definition, expected tool_reference`
error at the configured gateway. It uses native kind-scoped recovery rather
than disabling inline tools across the host. Model permissions and original
native errors keep their behavior. No installed binary is edited.

74 host tests passed (including two opt-in native tests skipped during discovery),
as did 15 offline bridge tests in the private deployment's LiteLLM image and
plugin validation (root context/icon warnings). The separate native model/effort
test passed all 36 public-roster Agent launches on 2.1.306.
The opt-in native inline test separately passed: ToolSearch discovery, injected
connector-style inline request, HTTP 422, native retry with complete schema,
MCP echo execution and coordinator inline-beta retention. It uses a temporary
config/cache, dummy key and fake API. The injection reproduces the wire shape,
not actual interactive connector discovery or the native history snapshot path.
The same synthetic child also passed against the private real DeepSeek gateway;
the coordinator/search remained fake. Public credential/login behavior,
interactive connector resume and cache-hit performance were not tested here.

## Client compatibility update — 2026-10-15

Claude Code 2.1.299 adds a `timing` argument to the Agent launch handler. Both
reviewed native handler signatures remain supported; unknown layouts still
fail closed. Verified 35 offline host checks (one additional opt-in test skipped
in discovery), 15 pinned LiteLLM bridge checks and plugin validation (existing
root CLAUDE.md warning). The opt-in real native-client test separately passed:
36 Agent launches against a fake loopback API checked all custom model routes,
absolute/relative effort and the actual tool schema. No real credentials or
quota were used; the installed binary was unchanged. Background/persisted effort
is covered by fixtures, not a new live resume test. Live Remote Control and
provider inference were not retested. Gateway deployment/config was unchanged.

## Original deployment baseline

Recorded 2026-10-05. Reviewed baseline: Claude Code 2.1.289, LiteLLM 1.104.0,
Python 3.10+ interface, Docker Compose. Tests use temporary state, synthetic
credentials and fake upstream APIs. No personal NAS deployment was modified.

## Completed

- 29 host tests: finite model/schema/effort policy; native policy preservation;
  per-agent definition isolation; native binary layout/cache upgrade/corruption;
  manager state/permissions/secret guards; loopback-only ports; account dispatch;
  private worker volumes; launcher argument forwarding; hook JSON/context;
  duplicate task refusal; actual exit codes; whole-process-group stopping and
  PID-reuse rejection.
- 15 tests inside the pinned gateway image: dictionary completion events,
  streaming tool-stop/usage, system/developer scoping, incomplete completion,
  DeepSeek regex equivalence/recursive schema preservation/provider scoping;
  all five advertised subscription efforts survive the real LiteLLM bridges;
  worker configuration does not force a reasoning effort.
- Official Claude plugin/marketplace manifest validation passed.
- All four skill frontmatter files passed the skill validator.
- Real Claude 2.1.289 binary prepared and executed with `--version` in an
  isolated cache; original binary hash unchanged. Public GitHub marketplace
  installed successfully in a disposable home, not the user's plugin config.
- Real isolated Docker stack with PostgreSQL, proxy and two workers: restricted
  key generated/read back; exact extra-model catalog; streaming tool/follow-up
  loops on four Codex routes and native Claude alias against fake upstreams;
  xhigh arrived unchanged; native OAuth header preserved only on native routing;
  gateway authentication not leaked upstream. Private database/config/OAuth
  backup bundle verified. Fresh unauthenticated workers and proxy became healthy
  without triggering a login; configuration reload preserved database startup.
  Only that test project's containers/volumes were removed after the test.

## Not established by those tests

- New users' browser/device authorization, model entitlement, quota and vendor
  subscription acceptance. Run login and explicitly approved live smoke tests.
- Full Claude Agent execution/Remote Control against this localhost deployment:
  fake upstream tool loops and patch unit tests are not that end-to-end proof.
  The extracted implementation had live tests in the original deployment, but
  those credentials/deployment are not part of this package's tests.
- Future Claude/Bun or LiteLLM releases, macOS/Windows binaries, forced full-
  context compaction, actual paid EXA searches or arbitrary model additions.
- Production disaster recovery/schema rollback or a fully atomic backup across
  independently refreshing OAuth stores. Quiesce usage and rehearse restoration.

Follow the README verification commands; do not interpret a healthy service or
present OAuth file as proof of account access. Live authorization and actual
model entitlement still require the owner's participation.
