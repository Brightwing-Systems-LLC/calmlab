# CalmLab — working notes for agents

A public, local-first tool: a Claude Code hook records times and counts into SQLite under
`~/.calmlab`, and a Flask view on 127.0.0.1:7474 shows them. README.md is the user-facing
contract (what is recorded, the check-in rules, the Vibe Nature heartbeat).

- **Privacy is enforced by `tests/test_privacy.py`.** Any new hook input, table column or
  printed output needs it extended. A string from a hook payload goes only into a counter,
  or through `checkin.parse_answer`, which keeps one digit.
- **The hook prints exactly two things, both fixed JSON:** the check-in question after a
  Stop (`systemMessage`, shown to the user, not the model) and the block that keeps a
  `calm N` answer from reaching the model. Plain stdout from a UserPromptSubmit hook is
  added to the model's context, so anything else printed there is a leak. It never raises.
- **A blocked prompt is put back in Claude Code's input box.** That is Claude Code's
  behaviour, not ours, and it is why the confirmation says Ctrl+U clears the line. Checked
  by hand in a tmux session on Claude Code 2.1.302; re-check after a Claude Code upgrade
  if the check-in looks wrong.
- **The hook path must stay stdlib only.** `cli.py` and `hook.py` never import Flask at
  module level; a test runs a subprocess to prove it.
- **Never run `calmlab setup` or `uninstall` against the real `~/.claude/settings.json`
  while developing.** Tests pass `--settings` a temp path, and `CALMLAB_HOME` isolates the
  data folder. `uv run calmlab demo` is the way to look at the UI.
- **The check-in rules are constants in `checkin.py`, deliberately not settings**, so a
  check-in means the same thing for everyone. Changing one changes what old data means.
- **Colours are tokens in `calmlab/web/static/calmlab.css`;** charts use classes, never a
  literal colour. Fonts are vendored in `static/fonts` so the page loads nothing remote, and
  `tests/test_web.py` holds that line.
- `./setup` runs `uv sync --no-dev`, which removes pytest and ruff from `.venv`. Run
  `uv sync` again before testing.
- Templates are Jinja. Write no template comments.
