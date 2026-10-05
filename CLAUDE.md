# Working on this package

Claude-first public plugin/utility package. Read README.md and relevant OPS.md.

- Keep credentials/OAuth/private deployment files/certificates/logs out of Git.
- Preserve existing launchers, native binaries, accounts and live services.
  Tests use temporary state and their own project/ports, never production auth.
- Skills are operational guidance, not permission grants. Preserve human login
  handoffs and explicit consent for paid/quota-consuming tests.
- Align finite roster, routes, metadata, picker/schema and effort policy.
  Unknown binary/target layouts fail closed; never edit the installed client.
- Run unit/image bridge tests and plugin validation. Docker integration requires
  --allow-docker and tears down only its own test project/volumes.
- Separate verified behavior from untested vendor/account behavior. Update the
  runbook/tests when changing launcher, auth, upgrade or backup mechanics.
