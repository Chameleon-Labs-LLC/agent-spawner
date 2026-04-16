# IDE integration

There is **no JetBrains plugin yet** for Claude Code or the Agent SDK. What we generate:

1. **JetBrains External Tool** (XML) — adds a menu item like *Tools → Run Local Agent* that launches `local/agent.py` in the project's Python interpreter
2. **JetBrains Run Configuration** (XML) — appears in the run-configuration dropdown so the user can hit ▶︎ to start the agent
3. **VSCode tasks.json** — same idea for VSCode (and Cursor, which inherits VSCode's task system)

When a real plugin ships, update this skill to detect and prefer it. For now, External Tool + Run Configuration covers 90% of the experience.

## JetBrains External Tool

Lives in `.idea/tools/External Tools.xml` (project-level) or in the user's global IDE config. The scaffolder generates a project-level file so it travels with the repo.

Import path: *Settings → Tools → External Tools → ⚙ → Import*.

## JetBrains Run Configuration

`.idea/runConfigurations/Run_<agent_name>_Locally.xml`. Full PythonRunConfiguration — the template handles it. The user refreshes the project after the file is created and the configuration appears in the dropdown.

## VSCode tasks.json

`.vscode/tasks.json`. If the file already exists, merge manually. (v2 TODO: merge in place with a JSONC library.)

Both Linux (primary) and Windows command paths are included.

## What we do NOT generate

- A JetBrains plugin manifest (no plugin)
- IntelliJ live templates (out of scope)
- Debugger configurations (convert the Run Configuration to a debug one with one click)
