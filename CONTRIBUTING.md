# Contributing to MCBH

Please distinguish between a **verified implementation** and an untested proposal. Any claim of loader/version compatibility should come with a test environment and a report. Add new blocks or commands only if they are valid for supported versions. Never bundle third-party schematics, images or worlds without redistribution rights.

## Checks

```bash
python -m pip install -e '.[dev]'
pytest -q
python -m compileall -q src
```

For a live server test use a disposable world with RCON bound to localhost, a backed-up save, and a user-approved test area. Test connection, terrain probe, stage/preview, partial execution, recovery after a dropped RCON connection, and two version/loader combinations whenever possible. Take screenshots before/after at each major build phase and report any aesthetic differences.

Security: redact secrets/log tokens; do not expose arbitrary shell execution or console commands through MCP. Review any feature that modifies blocks, entities, dimensions or chunks for abuse and unexpected data destruction. A contribution must preserve atomic local job persistence, explicit human approval, coordinate validation and bounded Minecraft commands.
