"""Server-rendered SVG charts.

Inline SVG rather than a charting library: the page needs no JavaScript to draw, and
every colour comes from a CSS class whose value is a token in calmlab.css, so the charts
follow the light and dark themes like everything else. Each mark carries a <title>,
which is its hover tooltip.
"""

from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from html import escape

from markupsafe import Markup

from ..findings import duration
from ..metrics import local_dt


def _f(v) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _svg(w: int, h: int, body: list[str], label: str, cls: str = "viz") -> Markup:
    return Markup(
        f'<svg class="{cls}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}">'
        f'{"".join(body)}</svg>'
    )


def _text(x, y, s, cls="ax", anchor="start") -> str:
    return f'<text x="{_f(float(x))}" y="{_f(float(y))}" class="{cls}" text-anchor="{anchor}">{escape(str(s))}</text>'


def _ticks(vmax: float, most: int = 4) -> tuple[float, list[float]]:
    """A round top value and evenly spaced round ticks from 0 to it."""
    vmax = vmax if vmax > 0 else 1
    exp = 10 ** math.floor(math.log10(vmax / most))
    for mult in (1, 2, 2.5, 5, 10, 20):
        step = mult * exp
        if vmax / step <= most:
            break
    n = max(1, math.ceil(vmax / step - 1e-9))
    return n * step, [round(i * step, 6) for i in range(n + 1)]


def daily_bars(all_days: dict[date, dict], end: date, n: int = 14, key: str = "parallel_starts") -> Markup:
    """Bars for the last `n` calendar days, with that day's drain in a circle underneath."""
    W, l, r, t, plot_h = 640, 40, 20, 14, 140
    base = t + plot_h
    H = base + 62
    span = [end - timedelta(days=n - 1 - i) for i in range(n)]
    values = [all_days.get(d, {}).get(key) if all_days.get(d, {}).get("turns") else None for d in span]
    ymax, ticks = _ticks(max((v for v in values if v is not None), default=0) * 1.08 or 4)
    slot = (W - l - r) / n
    bw = min(24, slot * 0.56)

    def Y(v):
        return base - v / ymax * plot_h

    body = []
    for v in ticks:
        body.append(f'<line class="grid{" grid-base" if v == 0 else ""}" x1="{l}" x2="{W - r}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
        body.append(_text(l - 8, Y(v) + 3.5, _f(float(v)), anchor="end"))
    body.append(_text(l - 8, base + 48, "drain", anchor="end"))
    for i, (d, v) in enumerate(zip(span, values, strict=True)):
        cx = l + slot * i + slot / 2
        label = d.strftime("%a %-d %b")
        body.append(_text(cx, base + 16, d.strftime("%a")[0], "ax", "middle"))
        body.append(_text(cx, base + 27, d.day, "ax ax-faint", "middle"))
        if v is None:
            body.append(f'<rect class="bar-empty" x="{cx - bw / 2:.1f}" y="{base - 3}" width="{bw:.1f}" height="3" rx="1.5"/>')
        else:
            h = max(2.0, v / ymax * plot_h)
            body.append(f'<a href="/day/{d.isoformat()}"><rect class="bar" x="{cx - bw / 2:.1f}" y="{base - h:.1f}" '
                        f'width="{bw:.1f}" height="{h:.1f}" rx="3"><title>{escape(label)}: {v}</title></rect></a>')
        drain = all_days.get(d, {}).get("drain")
        if drain is not None:
            shown = _f(round(drain, 1))
            body.append(f'<circle class="dot" cx="{cx:.1f}" cy="{base + 44}" r="{9 if len(shown) == 1 else 11.5}">'
                        f'<title>{escape(label)}: drain {shown} of 5</title></circle>')
            body.append(_text(cx, base + 47.5, shown, "dot-t" if len(shown) == 1 else "dot-t dot-t-sm", "middle"))
    return _svg(W, H, body, "Parallel starts per day for the last two weeks, with drain check-ins")


def _lanes(turns, events):
    """Pack sessions into as few lanes as possible, so lanes read as agents at once."""
    spans = {}
    for e in events:
        s = spans.setdefault(e["session"], [e["ts"], e["ts"]])
        s[0], s[1] = min(s[0], e["ts"]), max(s[1], e["ts"])
    for tn in turns:
        s = spans.setdefault(tn.session, [tn.start, tn.end])
        s[1] = max(s[1], tn.end)
    lanes_end: list[float] = []
    lane_of = {}
    for sid, (s, e) in sorted(spans.items(), key=lambda kv: kv[1][0]):
        for i, end in enumerate(lanes_end):
            if s > end + 30:
                lanes_end[i] = e
                lane_of[sid] = i
                break
        else:
            lanes_end.append(e)
            lane_of[sid] = len(lanes_end) - 1
    return lane_of, len(lanes_end)


def timeline(tl: dict, offset_min: int) -> Markup:
    """One day: a lane per agent running at once, its turns, the waits on you, and
    where you started one agent while another was still working."""
    events, turns = tl["events"], tl["turns"]
    if not events:
        return Markup("")
    first = local_dt(events[0]["ts"], offset_min)
    last_ts = max([events[-1]["ts"]] + [tn.end for tn in turns])
    last = local_dt(last_ts, offset_min)
    h0 = first.replace(minute=0, second=0, microsecond=0)
    h1 = last.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    lane_of, n_lanes = _lanes(turns, events)
    has_scene = any(on for _, on in tl["scene"])

    W, l, r = 1000, 8, 8
    pw = W - l - r
    lane_h = 26
    t_scene = 8
    t_lanes = t_scene + (16 if has_scene else 0)
    base = t_lanes + n_lanes * lane_h + 6
    H = base + 24
    total = (h1 - h0).total_seconds()

    def X(ts):
        return l + (local_dt(ts, offset_min) - h0).total_seconds() / total * pw

    body = []
    hours = int(total // 3600)
    every = 1 if hours <= 10 else 2
    for i in range(hours + 1):
        x = l + i * 3600 / total * pw
        body.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="{t_lanes - 4}" y2="{base}"/>')
        if i % every == 0:
            anchor = "start" if i == 0 else "end" if i == hours else "middle"
            body.append(_text(x, H - 6, (h0 + timedelta(hours=i)).strftime("%H:%M"), "ax", anchor))

    if has_scene:
        run_start, prev = None, None
        for ts, on in tl["scene"] + [(events[-1]["ts"] + 1, None)]:
            if on and run_start is None:
                run_start = ts
            elif not on and run_start is not None:
                body.append(f'<rect class="scene" x="{X(run_start):.1f}" y="{t_scene}" width="{max(1, X(prev) - X(run_start)):.1f}" '
                            f'height="6" rx="3"><title>Vibe Nature running</title></rect>')
                run_start = None
            prev = ts

    for i in range(n_lanes):
        y = t_lanes + i * lane_h + lane_h / 2
        body.append(f'<line class="lane" x1="{l}" x2="{W - r}" y1="{y}" y2="{y}"/>')
    for tn in turns:
        y = t_lanes + lane_of.get(tn.session, 0) * lane_h
        x1, x2 = X(tn.start), X(tn.end)
        tip = (f"{local_dt(tn.start, offset_min):%H:%M}: agent worked {duration(tn.duration_s)}"
               + (f", reply of {tn.reply_words} words" if tn.reply_words is not None else "")
               + (f", then waited {duration(tn.wait_s)} for you" if tn.wait_s is not None else ""))
        if tn.wait_s is not None:
            body.append(f'<line class="wait" x1="{x2:.1f}" x2="{X(tn.end + tn.wait_s):.1f}" y1="{y + lane_h / 2}" y2="{y + lane_h / 2}"/>')
        body.append(f'<rect class="turn" x="{x1:.1f}" y="{y + 8}" width="{max(1.5, x2 - x1):.1f}" height="{lane_h - 14}" '
                    f'rx="2"><title>{escape(tip)}</title></rect>')
        if tn.parallel_start:
            body.append(_par_dot(x1, y + lane_h / 2, f"{local_dt(tn.start, offset_min):%H:%M}: started while another agent was working"))
    for e in tl["parallel"]:
        if e["kind"] == "session_start":
            y = t_lanes + lane_of.get(e["session"], 0) * lane_h + lane_h / 2
            body.append(_par_dot(X(e["ts"]), y, f"{local_dt(e['ts'], offset_min):%H:%M}: new session while another agent was working"))
    return _svg(W, H, body, "Timeline of the day: agents working, waiting for you, and parallel starts", "viz viz-wide")


def _par_dot(cx: float, cy: float, tip: str) -> str:
    return f'<circle class="par" cx="{cx:.1f}" cy="{cy - 9:.1f}" r="1.8"><title>{escape(tip)}</title></circle>'


def heatmap(grid: dict) -> Markup:
    """Weekday rows by hour columns, each cell shaded by average prompts in that hour."""
    hours, rows = grid["hours"], grid["rows"]
    W, l, r, t, ch, gap = 640, 40, 4, 4, 24, 3
    cw = (W - l - r) / len(hours)
    H = t + len(rows) * (ch + gap) + 18
    vmax = max((c["prompts"] for row in rows for c in row["cells"]), default=0) or 1
    body = []
    for i, row in enumerate(rows):
        y = t + i * (ch + gap)
        body.append(_text(l - 8, y + ch / 2 + 3.5, row["label"], anchor="end"))
        for j, c in enumerate(row["cells"]):
            x = l + j * cw
            tip = (f"{row['name']} {c['hour']:02d}:00: {c['prompts']:.1f} prompts on average"
                   + (f", {c['parallel']:.1f} parallel starts" if c["parallel"] >= 0.05 else "")
                   + f" ({row['days']} day{'' if row['days'] == 1 else 's'})")
            if c["prompts"] < 0.05:
                body.append(f'<rect class="cell-empty" x="{x + 1:.1f}" y="{y}" width="{cw - 2:.1f}" height="{ch}" rx="3">'
                            f'<title>{escape(tip)}</title></rect>')
            else:
                body.append(f'<rect class="cell" x="{x + 1:.1f}" y="{y}" width="{cw - 2:.1f}" height="{ch}" rx="3" '
                            f'fill-opacity="{0.12 + 0.88 * c["prompts"] / vmax:.2f}"><title>{escape(tip)}</title></rect>')
    for j, h in enumerate(hours):
        if h % 2 == 0:
            body.append(_text(l + j * cw + cw / 2, H - 4, f"{h:02d}", anchor="middle"))
    return _svg(W, H, body, "Average prompts by hour of the day, for each weekday")


def share_bars(items: list[dict], label: str) -> Markup:
    """Horizontal bars for shares of a whole, the biggest drawn full width."""
    W, l, r, row_h = 400, 96, 40, 30
    H = len(items) * row_h
    top = max(i["share"] for i in items) or 1
    body = []
    for k, it in enumerate(items):
        y = k * row_h
        w = (W - l - r) * it["share"] / top
        body.append(_text(0, y + row_h / 2 + 4, it["label"], "ax ax-label"))
        body.append(f'<rect class="track" x="{l}" y="{y + 8}" width="{W - l - r}" height="{row_h - 16}" rx="3"/>')
        if it["share"] > 0:
            body.append(f'<rect class="bar" x="{l}" y="{y + 8}" width="{max(2.0, w):.1f}" height="{row_h - 16}" rx="3">'
                        f'<title>{escape(it["label"])}: {it["share"]:.0%}</title></rect>')
        body.append(_text(W, y + row_h / 2 + 4, f"{it['share']:.0%}", "ax ax-v", "end"))
    return _svg(W, H, body, label)


def _jitter(key: str) -> float:
    return (int.from_bytes(key.encode(), "little") * 2654435761 % 1000) / 1000 - 0.5


def scatter(data: dict, xlabel: str, fmt, unit: float = 1, tick=str) -> Markup:
    """Drain against one day measure, one dot a day, with the halves' averages drawn in."""
    pts = data["points"]
    W, l, r, t, b = 640, 34, 16, 12, 44
    H = 280
    ph, pw = H - t - b, W - l - r
    top, steps = _ticks(max((p["x"] for p in pts), default=0) * 1.05 / unit or 1)
    xmax, xticks = top * unit, [v * unit for v in steps]

    def X(v):
        return l + v / xmax * pw

    def Y(v):
        return t + (5 - v) / 4 * ph

    body = []
    for v in range(1, 6):
        body.append(f'<line class="grid{" grid-base" if v == 1 else ""}" x1="{l}" x2="{W - r}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
        body.append(_text(l - 10, Y(v) + 3.5, v, anchor="end"))
    for i, v in enumerate(xticks):
        body.append(_text(X(v), H - b + 18, tick(v) if v else "0", anchor="end" if i == len(xticks) - 1 else "middle"))
    body.append(_text(l + pw / 2, H - 6, xlabel, "ax ax-label", "middle"))
    split = data["split"]
    if split:
        cx = X(split["cut"])
        body.append(f'<rect class="half" x="{cx:.1f}" y="{t}" width="{W - r - cx:.1f}" height="{ph}"/>')
        for x1, x2, v, n, side in ((l, cx, split["low"], split["n_low"], "lower"), (cx, W - r, split["high"], split["n_high"], "higher")):
            tip = f"Your {side} days ({n}): drain {v:.1f} on average"
            body.append(f'<line class="mean" x1="{x1 + 6:.1f}" x2="{x2 - 6:.1f}" y1="{Y(v):.1f}" y2="{Y(v):.1f}">'
                        f'<title>{escape(tip)}</title></line>')
            body.append(_text(x2 - 8, Y(v) - 7, f"avg {v:.1f}", "ax ax-mean", "end"))
    for p in pts:
        y = p["y"]
        if float(y).is_integer():
            y = min(5, max(1, y + _jitter(p["date"].isoformat()) * 0.22))
        tip = f"{p['date']:%a %-d %b}: {fmt(p['x'])}, drain {p['y']:.1f}".replace(".0,", ",")
        body.append(f'<a href="/day/{p["date"].isoformat()}"><circle class="pt" cx="{X(p["x"]):.1f}" cy="{Y(y):.1f}" r="5">'
                    f'<title>{escape(tip)}</title></circle></a>')
    return _svg(W, H, body, f"Drain against {xlabel.lower()}, one dot per day")


def trend(all_days: dict[date, dict], start: date, end: date, key: str, fmt, ymax_fixed=None,
          unit: float = 1, tick=str) -> Markup:
    """A small daily bar chart over the range, with a line for the average of the last seven days worked.

    Ticks are placed in multiples of `unit` (60 turns seconds into whole minutes) and
    labelled by `tick`."""
    W, l, r, t, base = 420, 44, 6, 8, 104
    H = base + 20
    span = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    values = [all_days.get(d, {}).get(key) if all_days.get(d, {}).get("turns") else None for d in span]
    present = [v for v in values if v is not None]
    if ymax_fixed:
        ymax, ticks = ymax_fixed, [0, ymax_fixed]
    else:
        top, steps = _ticks(max(present, default=0) * 1.08 / unit or 1, most=3)
        ymax, ticks = top * unit, [v * unit for v in steps]
    slot = (W - l - r) / len(span)
    bw = max(1.0, min(14, slot * 0.62))

    def Y(v):
        return base - v / ymax * (base - t)

    body = []
    for v in ticks:
        body.append(f'<line class="grid{" grid-base" if v == 0 else ""}" x1="{l}" x2="{W - r}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>')
        body.append(_text(l - 6, Y(v) + 3.5, tick(v) if v else "0", anchor="end"))
    recent: list[float] = []
    line = []
    for i, (d, v) in enumerate(zip(span, values, strict=True)):
        if v is None:
            continue
        cx = l + slot * i + slot / 2
        h = max(1.5, v / ymax * (base - t))
        body.append(f'<a href="/day/{d.isoformat()}"><rect class="bar bar-soft" x="{cx - bw / 2:.1f}" y="{base - h:.1f}" '
                    f'width="{bw:.1f}" height="{h:.1f}" rx="1.5"><title>{d:%a %-d %b}: {escape(fmt(v))}</title></rect></a>')
        recent = (recent + [v])[-7:]
        line.append(f"{cx:.1f},{Y(statistics.fmean(recent)):.1f}")
    if len(line) > 1:
        body.append(f'<polyline class="avg" points="{" ".join(line)}"/>')
    body.append(_text(l, H - 4, f"{start:%-d %b}", "ax"))
    body.append(_text(W - r, H - 4, f"{end:%-d %b}", "ax", "end"))
    return _svg(W, H, body, f"{key} per day, with a seven-day average", "viz viz-sm")
