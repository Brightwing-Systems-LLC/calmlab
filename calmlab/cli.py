"""`calmlab`: setup, start, status, demo, uninstall, delete, and `hook` for Claude Code.

Nothing here imports Flask at module level. `calmlab hook` runs on every Claude Code
event, so the path it takes has to start fast.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
import urllib.request
import webbrowser
from pathlib import Path

from . import checkin, hook, install, paths, scene, store

CONSENT_VERSION = "2026-10-2"
DEFAULT_PORT = 7474

WHAT_IS_RECORDED = """\
CalmLab: what it records

A Claude Code hook on this computer records, for each event (session start and end, a
prompt sent, an agent finishing, a failed tool call, Claude waiting for you):
  - what kind of event it was and when it happened,
  - a scrambled code for the session (a salted hash, not the session id),
  - how many words, and roughly how many tokens, your prompt had, and the same for
    Claude's final reply,
  - whether the Vibe Nature scene was running, if you use it.

It never records the text of a prompt or reply, file names, paths, project names, tool
names or tool output. A reply is read only to count its words.

Up to twice a day, when an agent finishes, it asks how drained you are, 1 to 5. Type
`calm 3` to answer, or ignore it. Your answer never reaches Claude.

Everything stays in ~/.calmlab on this computer. Nothing is sent anywhere.
"""


def _ask(question: str, default: bool) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    answer = input(f"{question} {hint} ").strip().lower()
    return default if not answer else answer in ("y", "yes")


def _settings_path(args) -> Path:
    return Path(args.settings).expanduser() if args.settings else install.DEFAULT_SETTINGS


def cmd_setup(args) -> int:
    print(WHAT_IS_RECORDED)
    if not args.yes and not _ask("Start recording on these terms?", default=False):
        print("Nothing set up, and nothing recorded.")
        return 1
    with store.connect() as conn:
        store.set_meta(conn, "consent", {"version": CONSENT_VERSION, "agreed_at": time.time()})
        store.salt(conn)

    settings = _settings_path(args)
    print(f"\nCalmLab adds one hook command to {len(hook.HOOK_EVENTS)} Claude Code events in {settings}:")
    print("  " + ", ".join(hook.HOOK_EVENTS))
    print(f"  command: {install.hook_command()}")
    print("Your other hooks and settings stay exactly as they are, and a backup is written first.")
    if not args.yes and not _ask("Add the hooks?", default=True):
        print("Hooks not added. Run ./setup again when you want to start.")
        return 1
    install.install(settings, out=lambda s: print("  " + s))
    with store.connect() as conn:
        store.set_meta(conn, "settings_path", str(settings))
    print("\nDone. Claude Code sessions are recorded from now on, usually including ones already open.")
    print("If `uv run calmlab status` doesn't count up as you work, restart that session.")
    print("Run ./start to open CalmLab.")
    return 0


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.5) as r:
            return r.read() == b"calmlab"
    except Exception:
        return False


def cmd_start(args) -> int:
    url = f"http://127.0.0.1:{args.port}/"
    if _already_running(args.port):
        print(f"CalmLab is already running at {url}")
        if not args.no_open:
            webbrowser.open(url)
        return 0
    from .web.app import serve

    print(f"CalmLab is at {url}  (Ctrl+C to stop; recording carries on without it)")
    serve(args.port, open_browser=not args.no_open)
    return 0


def cmd_demo(args) -> int:
    from . import synth
    from .web.app import serve

    folder = Path(tempfile.mkdtemp(prefix="calmlab-demo-"))
    with store.connect(folder / "calmlab.sqlite3") as conn:
        store.set_meta(conn, "consent", {"version": "demo", "agreed_at": time.time()})
        store.set_meta(conn, "demo", True)
        synth.load(conn)
    print(f"Demo data in {folder}. Your own data is not touched.")
    print(f"CalmLab demo is at http://127.0.0.1:{args.port}/  (Ctrl+C to stop)")
    serve(args.port, open_browser=not args.no_open, home=folder)
    return 0


def cmd_status(args) -> int:
    with store.connect() as conn:
        consent = store.get_meta(conn, "consent")
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        checkins = conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0]
        pending = checkin.pending(conn, time.time())
        used = store.get_meta(conn, "settings_path")
    hooked = install.installed(Path(used) if used and not args.settings else _settings_path(args))
    s = scene.running()
    print(f"Data folder:  {paths.home()}")
    print(f"Recording:    {'on' if consent and hooked else 'off: run ./setup'}")
    print(f"Events:       {count} (times and counts only)")
    print(f"Check-ins:    {checkins}" + ("  (one is waiting: type calm 1 to calm 5 in Claude Code)" if pending else ""))
    print(f"Vibe Nature:  {'running' if s else 'not running' if s is False else 'not linked'}")
    return 0


def cmd_scene(args) -> int:
    if args.state == "status":
        s = scene.running()
        print("running" if s else "not running" if s is False else "never reported")
        return 0
    scene.write(args.state == "on", source="manual")
    print(f"Scene marked {args.state}. Vibe Nature normally does this itself.")
    return 0


def cmd_uninstall(args) -> int:
    install.uninstall(_settings_path(args))
    print("CalmLab's hooks are removed. Your data is still in "
          f"{paths.home()}; `calmlab delete` erases it.")
    return 0


def cmd_delete(args) -> int:
    if not args.yes:
        answer = input(f"Erase everything in {paths.home()}? This cannot be undone. Type 'erase': ")
        if answer.strip() != "erase":
            print("Nothing erased.")
            return 1
    removed = store.delete_everything()
    print(f"Erased {len(removed)} file(s). Run `calmlab uninstall` too, if you have not.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="calmlab", description="CalmLab: how you work with coding agents.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("setup", help="read what is recorded, agree, and add the hooks")
    s.add_argument("--settings", help=f"Claude Code settings file (default {install.DEFAULT_SETTINGS})")
    s.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_setup)

    for name, func, text in (("start", cmd_start, "open the web view of your data"),
                             ("demo", cmd_demo, "open the web view on made-up data")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--port", type=int, default=DEFAULT_PORT)
        s.add_argument("--no-open", action="store_true", help="do not open a browser")
        s.set_defaults(func=func)

    s = sub.add_parser("status", help="is it recording, and what has it got")
    s.add_argument("--settings", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("hook", help="called by Claude Code; reads the hook payload on stdin")
    s.set_defaults(func=lambda a: hook.main())

    s = sub.add_parser("scene", help="mark the Vibe Nature scene on or off by hand, or show it")
    s.add_argument("state", choices=["on", "off", "status"])
    s.set_defaults(func=cmd_scene)

    s = sub.add_parser("uninstall", help="remove the hooks (keeps your data)")
    s.add_argument("--settings", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_uninstall)

    s = sub.add_parser("delete", help="erase all local CalmLab data")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(func=cmd_delete)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
