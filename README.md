# CalmLab

CalmLab shows you how you work with coding agents: how many you run at once, how long
they wait on you, how long you stay focused, and how drained you feel. It runs on your
machine, keeps everything there, and stores no text.

It works with [Claude Code](https://code.claude.com). It needs macOS or Linux and
[uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone https://github.com/Brightwing-Systems-LLC/calmlab && cd calmlab
./setup    # shows what is recorded, asks you to agree, adds the hooks
./start    # opens http://127.0.0.1:7474
```

Recording doesn't need `./start`. A hook writes to a local database whenever Claude Code
fires it; `./start` only opens the view. Sessions already open when you run setup usually
start recording right away, because Claude Code picks up the new hooks; restart one if
`uv run calmlab status` doesn't move.

Want to look first? `uv run calmlab demo` opens the view on eight weeks of made-up data and
leaves yours alone.

## The check-in

Up to twice a day, when an agent finishes, a line appears under its reply:

```
⏺ Done. All 214 tests pass.
  ⎿  Stop says: CalmLab · How drained are you right now? Type calm 1 (not at all) to calm 5 (completely).
❯ calm 2
⏺ UserPromptSubmit operation blocked by hook:
  CalmLab · Drain 2 recorded. Ctrl+U clears the line.
```

The hook keeps the digit and stops the prompt there, so it never reaches Claude.
Claude Code puts the blocked prompt back in the input box, which is what the Ctrl+U is
for. Ignore the question and it counts as skipped. `calm 3` is accepted any time, and the
web view shows a waiting check-in as five buttons.

The rules are the same for everyone and aren't settings, so a check-in always means the
same thing:

- the first time an agent finishes after 16:00 on a day you worked,
- the first time after one session has run 90 minutes without a 30-minute break,
- at most two a day, at least three hours apart.

## What it records

For each Claude Code event (session start and end, a prompt sent, an agent finishing, a
failed tool call, Claude waiting for you): the kind of event and when, a salted hash of the
session id, word and estimated token counts for your prompt and Claude's final reply, and
whether the Vibe Nature scene was running. For each check-in: the time, the number, and
which rule asked.

It never records the text of a prompt or reply, file names, paths, project names, tool
names or tool output. A reply is read only to count its words. The `events` table has no
column a string could go into besides the event kind and the 16-character hash, and
`tests/test_privacy.py` feeds identifying text through every hook input and then searches
every byte written to disk for it.

The web view listens on 127.0.0.1 only, loads nothing from the internet, and refuses
requests that don't name it as the host.

## What the numbers mean

`calmlab/metrics.py` has the exact definitions.

| | |
|---|---|
| **agents at once** | sessions with a turn running at the same moment, averaged over the time at least one is |
| **wait on you** | an agent finishing to your next prompt in that session (gaps over 2 hours are breaks) |
| **parallel starts** | starting a session, or sending a prompt, while an agent in another session is still working |
| **longest focus stretch** | the longest run of activity with no gap of 10 minutes or more |
| **drain** | your check-ins, 1 (not at all) to 5 (completely) |

After seven days with a check-in, CalmLab tests ten day measures (parallel starts,
agents at once, time juggling agents, day length, start and finish time, focus stretch,
wait on you, long waits, prompt pace) against how drained you said you were. Each gets a
Spearman rank correlation with a permutation p-value, and a link is shown only if it
survives a Benjamini-Hochberg correction at 5% across all ten, so looking at many things
doesn't turn up one by luck. Measures that move together are folded into one habit.

The strongest link that holds up is the sentence on the home page ("On days with 19 or
more parallel starts, you rate yourself 1.5 points more drained"). Links also mark the
stat cards and table columns they touch, sit under the matching Patterns charts, and show
on each day's page as where that day fell. It is a pattern in your own days, not a cause:
neighbouring days are alike, and a busy week can drive both sides. The About page says
this in full.

The **Patterns** tab is the longer look, over two weeks, eight weeks or everything: when
in the day you work, how long your agents wait for you, how many you run at once, drain
plotted against any of the day measures above with the test's verdict, and each measure
over time with a seven-day average. It is drawn from the same data; nothing extra is recorded for it.

## Vibe Nature

Vibe Nature is a calming desktop scene from Brightwing Systems. CalmLab is built
to answer whether it changes any of the numbers above for you, with a fair test: random
scene days against normal ones. Recording works without it; linking it is the next version.

The scene reports itself through a heartbeat file:

```
~/.calmlab/scene.json
{"running": true, "updated_at": 1760700000.0, "source": "vibe-nature"}
```

Written at least every 30 seconds while the scene is visible, atomically (temp file and
rename), with `"running": false` when it's hidden or quits. A heartbeat older than 90
seconds counts as not running. `uv run calmlab scene on|off|status` fakes it for testing.

## Stopping

```bash
uv run calmlab status      # is it recording, and what has it got
uv run calmlab uninstall   # remove CalmLab's hooks, keep the data
uv run calmlab delete      # erase ~/.calmlab
```

`./setup` and `uninstall` back up `~/.claude/settings.json` before writing, and leave every
other hook and setting exactly as it was. If you move this folder, run `./setup` again:
the hooks point at the copy of CalmLab inside it.

## Developing

```bash
uv sync
uv run pytest
uv run ruff check
uv run calmlab demo --no-open
```

Tests never touch `~/.calmlab` or `~/.claude`: `CALMLAB_HOME` points at a temporary folder
and every settings write takes `--settings`.

---

CalmLab · by Brightwing Systems · MIT licence
