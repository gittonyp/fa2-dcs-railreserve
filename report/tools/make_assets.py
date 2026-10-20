from pathlib import Path
import html
import re

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)

ARCHITECTURE = """<svg xmlns="http://www.w3.org/2000/svg" width="1360" height="700" viewBox="0 0 1360 700" font-family="Segoe UI, Arial, sans-serif">
  <defs>
    <marker id="arrow" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M2,2 L10,6 L2,10 z" fill="#334155"/>
    </marker>
    <marker id="arrow-dash" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M2,2 L10,6 L2,10 z" fill="#0f766e"/>
    </marker>
  </defs>
  <rect width="1360" height="700" fill="#ffffff"/>
  <text x="680" y="58" font-size="30" font-weight="700" text-anchor="middle" fill="#0f172a">RailReserve logical architecture</text>
  <text x="680" y="92" font-size="19" text-anchor="middle" fill="#475569">The API tier is stateless; Postgres is the authority for inventory.</text>

  <rect x="545" y="130" width="270" height="70" rx="12" fill="#e0f2fe" stroke="#0369a1" stroke-width="2.5"/>
  <text x="680" y="162" font-size="22" font-weight="700" text-anchor="middle" fill="#0c4a6e">Browser dashboard</text>
  <text x="680" y="186" font-size="17" text-anchor="middle" fill="#0c4a6e">safe race · naive race · payment</text>

  <line x1="680" y1="200" x2="680" y2="258" stroke="#334155" stroke-width="2.5" marker-end="url(#arrow)"/>
  <text x="698" y="234" font-size="17" fill="#475569">HTTP/JSON</text>

  <rect x="545" y="260" width="270" height="70" rx="12" fill="#f1f5f9" stroke="#334155" stroke-width="2.5"/>
  <text x="680" y="292" font-size="22" font-weight="700" text-anchor="middle" fill="#0f172a">Nginx :8080</text>
  <text x="680" y="316" font-size="17" text-anchor="middle" fill="#475569">upstream, static dashboard, X-Upstream</text>

  <line x1="620" y1="330" x2="410" y2="400" stroke="#334155" stroke-width="2.5" marker-end="url(#arrow)"/>
  <line x1="740" y1="330" x2="950" y2="400" stroke="#334155" stroke-width="2.5" marker-end="url(#arrow)"/>

  <rect x="250" y="402" width="300" height="92" rx="12" fill="#dcfce7" stroke="#15803d" stroke-width="2.5"/>
  <text x="400" y="437" font-size="22" font-weight="700" text-anchor="middle" fill="#14532d">api1 · FastAPI</text>
  <text x="400" y="462" font-size="17" text-anchor="middle" fill="#14532d">stateless replica + sweeper</text>
  <text x="400" y="484" font-size="15" text-anchor="middle" fill="#166534">max_fails=1 · fail_timeout=5s</text>

  <rect x="810" y="402" width="300" height="92" rx="12" fill="#dcfce7" stroke="#15803d" stroke-width="2.5"/>
  <text x="960" y="437" font-size="22" font-weight="700" text-anchor="middle" fill="#14532d">api2 · FastAPI</text>
  <text x="960" y="462" font-size="17" text-anchor="middle" fill="#14532d">stateless replica + sweeper</text>
  <text x="960" y="484" font-size="15" text-anchor="middle" fill="#166534">any replica can serve any request</text>

  <line x1="400" y1="494" x2="585" y2="570" stroke="#334155" stroke-width="2.5" marker-end="url(#arrow)"/>
  <line x1="960" y1="494" x2="775" y2="570" stroke="#334155" stroke-width="2.5" marker-end="url(#arrow)"/>
  <text x="680" y="530" font-size="17" text-anchor="middle" fill="#475569">SQL transactions</text>

  <rect x="500" y="572" width="360" height="96" rx="12" fill="#fef3c7" stroke="#b45309" stroke-width="2.5"/>
  <text x="680" y="607" font-size="23" font-weight="700" text-anchor="middle" fill="#78350f">Postgres 16 primary</text>
  <text x="680" y="632" font-size="17" text-anchor="middle" fill="#78350f">seats · holds · bookings · payments</text>
  <text x="680" y="655" font-size="15" text-anchor="middle" fill="#92400e">row locks + unique indexes = arbiter of the invariant</text>

  <line x1="1110" y1="448" x2="1185" y2="448" stroke="#0f766e" stroke-width="2.5" stroke-dasharray="8 7" marker-end="url(#arrow-dash)"/>
  <rect x="1190" y="402" width="150" height="92" rx="12" fill="#ccfbf1" stroke="#0f766e" stroke-width="2.5"/>
  <text x="1265" y="437" font-size="20" font-weight="700" text-anchor="middle" fill="#134e4a">Redis 7</text>
  <text x="1265" y="461" font-size="15" text-anchor="middle" fill="#134e4a">fixed-window</text>
  <text x="1265" y="481" font-size="15" text-anchor="middle" fill="#134e4a">rate limit, fail-open</text>
  <text x="1150" y="530" font-size="16" text-anchor="middle" fill="#0f766e">not on the booking critical path</text>
</svg>
"""

RACE_TIMELINE = """<svg xmlns="http://www.w3.org/2000/svg" width="1360" height="720" viewBox="0 0 1360 720" font-family="Segoe UI, Arial, sans-serif">
  <defs>
    <marker id="a2" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M2,2 L10,6 L2,10 z" fill="#334155"/>
    </marker>
  </defs>
  <rect width="1360" height="720" fill="#ffffff"/>
  <text x="680" y="52" font-size="30" font-weight="700" text-anchor="middle" fill="#0f172a">Check-then-act race versus atomic conditional update</text>

  <rect x="50" y="92" width="610" height="580" rx="16" fill="#fff1f2" stroke="#be123c" stroke-width="2.5"/>
  <text x="355" y="134" font-size="24" font-weight="700" text-anchor="middle" fill="#9f1239">Naive path: check, delay, write</text>
  <text x="355" y="162" font-size="17" text-anchor="middle" fill="#9f1239">the availability check and the write are separate operations</text>

  <rect x="105" y="190" width="500" height="58" rx="10" fill="#ffffff" stroke="#fb7185" stroke-width="2"/>
  <text x="355" y="215" font-size="19" font-weight="600" text-anchor="middle" fill="#881337">Request A reads status = available</text>
  <text x="355" y="237" font-size="15" text-anchor="middle" fill="#9f1239">t = 0 ms</text>

  <rect x="105" y="268" width="500" height="58" rx="10" fill="#ffffff" stroke="#fb7185" stroke-width="2"/>
  <text x="355" y="293" font-size="19" font-weight="600" text-anchor="middle" fill="#881337">Request B reads status = available</text>
  <text x="355" y="315" font-size="15" text-anchor="middle" fill="#9f1239">t = 1 ms</text>

  <line x1="355" y1="326" x2="355" y2="380" stroke="#334155" stroke-width="2.5" marker-end="url(#a2)"/>
  <rect x="105" y="382" width="500" height="58" rx="10" fill="#ffe4e6" stroke="#fb7185" stroke-width="2"/>
  <text x="355" y="407" font-size="19" font-weight="600" text-anchor="middle" fill="#881337">Both sleep for the checkout window</text>
  <text x="355" y="429" font-size="15" text-anchor="middle" fill="#9f1239">NAIVE_DELAY_MS = 300 ms widens the race window</text>

  <line x1="355" y1="440" x2="355" y2="494" stroke="#334155" stroke-width="2.5" marker-end="url(#a2)"/>
  <rect x="105" y="496" width="500" height="58" rx="10" fill="#ffffff" stroke="#fb7185" stroke-width="2"/>
  <text x="355" y="521" font-size="19" font-weight="600" text-anchor="middle" fill="#881337">A and B both insert a record and mark the seat booked</text>
  <text x="355" y="543" font-size="15" text-anchor="middle" fill="#9f1239">no database guard; the last writer does not lose</text>

  <line x1="355" y1="554" x2="355" y2="600" stroke="#334155" stroke-width="2.5" marker-end="url(#a2)"/>
  <rect x="105" y="602" width="500" height="52" rx="10" fill="#dcfce7" stroke="#16a34a" stroke-width="2"/>
  <text x="355" y="626" font-size="19" font-weight="700" text-anchor="middle" fill="#166534">201 · winner</text>
  <text x="355" y="646" font-size="19" font-weight="700" text-anchor="middle" fill="#166534">201 · winner</text>

  <rect x="700" y="92" width="610" height="580" rx="16" fill="#f0fdf4" stroke="#15803d" stroke-width="2.5"/>
  <text x="1005" y="134" font-size="24" font-weight="700" text-anchor="middle" fill="#14532d">Safe path: one atomic statement</text>
  <text x="1005" y="162" font-size="17" text-anchor="middle" fill="#166534">Postgres decides the winner under a row lock</text>

  <rect x="755" y="190" width="500" height="58" rx="10" fill="#ffffff" stroke="#4ade80" stroke-width="2"/>
  <text x="1005" y="215" font-size="19" font-weight="600" text-anchor="middle" fill="#14532d">Request A issues UPDATE ... WHERE available</text>
  <text x="1005" y="237" font-size="15" text-anchor="middle" fill="#166534">t = 0 ms</text>

  <rect x="755" y="268" width="500" height="58" rx="10" fill="#ffffff" stroke="#4ade80" stroke-width="2"/>
  <text x="1005" y="293" font-size="19" font-weight="600" text-anchor="middle" fill="#14532d">Request B issues UPDATE ... WHERE available</text>
  <text x="1005" y="315" font-size="15" text-anchor="middle" fill="#166534">t = 1 ms</text>

  <line x1="1005" y1="326" x2="1005" y2="380" stroke="#334155" stroke-width="2.5" marker-end="url(#a2)"/>
  <rect x="755" y="382" width="500" height="58" rx="10" fill="#dcfce7" stroke="#16a34a" stroke-width="2"/>
  <text x="1005" y="407" font-size="19" font-weight="600" text-anchor="middle" fill="#14532d">Postgres locks the row for the first writer</text>
  <text x="1005" y="429" font-size="15" text-anchor="middle" fill="#166534">the second writer waits, then re-evaluates the predicate</text>

  <line x1="1005" y1="440" x2="1005" y2="494" stroke="#334155" stroke-width="2.5" marker-end="url(#a2)"/>
  <rect x="755" y="496" width="500" height="58" rx="10" fill="#ffffff" stroke="#16a34a" stroke-width="2"/>
  <text x="1005" y="521" font-size="19" font-weight="600" text-anchor="middle" fill="#14532d">A commits; B sees status = held and matches no row</text>
  <text x="1005" y="543" font-size="15" text-anchor="middle" fill="#166534">RETURNING gives the winner its hold; the loser gets None</text>

  <line x1="1005" y1="554" x2="1005" y2="600" stroke="#334155" stroke-width="2.5" marker-end="url(#a2)"/>
  <rect x="755" y="602" width="240" height="52" rx="10" fill="#dcfce7" stroke="#16a34a" stroke-width="2"/>
  <text x="875" y="634" font-size="20" font-weight="700" text-anchor="middle" fill="#166534">201 · winner</text>
  <rect x="1015" y="602" width="240" height="52" rx="10" fill="#fee2e2" stroke="#dc2626" stroke-width="2"/>
  <text x="1135" y="634" font-size="20" font-weight="700" text-anchor="middle" fill="#991b1b">409 · rejected</text>

  <rect x="755" y="672" width="500" height="0" fill="none"/>
</svg>
"""

SCHEMA = """<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="900" viewBox="0 0 1400 900" font-family="Segoe UI, Arial, sans-serif">
  <defs>
    <marker id="arrow3" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto">
      <path d="M2,2 L10,6 L2,10 z" fill="#64748b"/>
    </marker>
  </defs>
  <rect width="1400" height="900" fill="#ffffff"/>
  <text x="700" y="48" font-size="30" font-weight="700" text-anchor="middle" fill="#0f172a">RailReserve database schema and guards</text>
  <text x="700" y="80" font-size="19" text-anchor="middle" fill="#475569">The database, not the application, enforces the one-winner invariant.</text>

  <g>
    <rect x="60" y="120" width="390" height="238" rx="10" fill="#ffffff" stroke="#0369a1" stroke-width="2.5"/>
    <rect x="60" y="120" width="390" height="42" rx="10" fill="#e0f2fe" stroke="#0369a1" stroke-width="2.5"/>
    <text x="255" y="149" font-size="21" font-weight="700" text-anchor="middle" fill="#0c4a6e">seats</text>
    <text x="82" y="192" font-size="17" fill="#0f172a">id  PK · serial</text>
    <text x="82" y="220" font-size="17" fill="#0f172a">train_id · journey_date · seat_no</text>
    <text x="82" y="248" font-size="17" fill="#0f172a">status  available | held | booked</text>
    <text x="82" y="276" font-size="17" fill="#0f172a">hold_id · hold_expires_at · version</text>
    <text x="82" y="312" font-size="16" font-weight="600" fill="#0369a1">UNIQUE (train_id, journey_date, seat_no)</text>
    <text x="82" y="338" font-size="16" font-weight="600" fill="#0369a1">CHECK (status IN (available, held, booked))</text>
  </g>

  <g>
    <rect x="60" y="440" width="390" height="270" rx="10" fill="#ffffff" stroke="#0f766e" stroke-width="2.5"/>
    <rect x="60" y="440" width="390" height="42" rx="10" fill="#ccfbf1" stroke="#0f766e" stroke-width="2.5"/>
    <text x="255" y="469" font-size="21" font-weight="700" text-anchor="middle" fill="#134e4a">holds</text>
    <text x="82" y="512" font-size="17" fill="#0f172a">id  PK · uuid</text>
    <text x="82" y="540" font-size="17" fill="#0f172a">seat_id  FK → seats.id</text>
    <text x="82" y="568" font-size="17" fill="#0f172a">user_id · expires_at · created_at</text>
    <text x="82" y="596" font-size="17" fill="#0f172a">status  active | paid | expired | cancelled</text>
    <text x="82" y="632" font-size="16" font-weight="700" fill="#0f766e">partial UNIQUE INDEX (active holds only)</text>
    <text x="82" y="656" font-size="15" fill="#134e4a">one_active_hold_per_seat ON holds (seat_id)</text>
    <text x="82" y="680" font-size="15" fill="#134e4a">WHERE status = active</text>
    <text x="82" y="702" font-size="15" font-weight="600" fill="#0f766e">second line of defence</text>
  </g>

  <g>
    <rect x="560" y="120" width="430" height="280" rx="10" fill="#ffffff" stroke="#b45309" stroke-width="2.5"/>
    <rect x="560" y="120" width="430" height="42" rx="10" fill="#fef3c7" stroke="#b45309" stroke-width="2.5"/>
    <text x="775" y="149" font-size="21" font-weight="700" text-anchor="middle" fill="#78350f">bookings</text>
    <text x="582" y="192" font-size="17" fill="#0f172a">id  PK · uuid</text>
    <text x="582" y="220" font-size="17" fill="#0f172a">hold_id  UNIQUE FK → holds.id</text>
    <text x="582" y="248" font-size="17" fill="#0f172a">seat_id  UNIQUE FK → seats.id</text>
    <text x="582" y="276" font-size="17" fill="#0f172a">user_id · pnr UNIQUE · status</text>
    <text x="582" y="304" font-size="17" fill="#0f172a">idempotency_key  UNIQUE</text>
    <text x="582" y="340" font-size="16" font-weight="600" fill="#b45309">one booking per hold, per seat, per idempotency key</text>
  </g>

  <g>
    <rect x="560" y="440" width="430" height="240" rx="10" fill="#ffffff" stroke="#be123c" stroke-width="2.5"/>
    <rect x="560" y="440" width="430" height="42" rx="10" fill="#ffe4e6" stroke="#be123c" stroke-width="2.5"/>
    <text x="775" y="469" font-size="21" font-weight="700" text-anchor="middle" fill="#881337">payments</text>
    <text x="582" y="512" font-size="17" fill="#0f172a">id  PK · uuid</text>
    <text x="582" y="540" font-size="17" fill="#0f172a">booking_id  FK → bookings.id</text>
    <text x="582" y="568" font-size="17" fill="#0f172a">idempotency_key  UNIQUE</text>
    <text x="582" y="596" font-size="17" fill="#0f172a">amount NUMERIC(10,2) · status</text>
    <text x="582" y="636" font-size="16" font-weight="700" fill="#be123c">replay of the same key returns the original booking</text>
  </g>

  <g>
    <rect x="1080" y="120" width="260" height="180" rx="10" fill="#ffffff" stroke="#64748b" stroke-width="2.5"/>
    <rect x="1080" y="120" width="260" height="42" rx="10" fill="#f1f5f9" stroke="#64748b" stroke-width="2.5"/>
    <text x="1210" y="149" font-size="21" font-weight="700" text-anchor="middle" fill="#334155">naive_bookings</text>
    <text x="1102" y="192" font-size="17" fill="#0f172a">id PK · seat_id FK</text>
    <text x="1102" y="220" font-size="17" fill="#0f172a">user_id · created_at</text>
    <text x="1102" y="258" font-size="16" font-weight="600" fill="#64748b">no uniqueness constraint</text>
    <text x="1102" y="282" font-size="15" fill="#475569">teaching control only</text>
  </g>

  <line x1="255" y1="440" x2="255" y2="358" stroke="#64748b" stroke-width="2.5" marker-end="url(#arrow3)"/>
  <text x="268" y="404" font-size="16" fill="#475569">seat_id</text>

  <line x1="490" y1="330" x2="560" y2="260" stroke="#64748b" stroke-width="2.5" marker-end="url(#arrow3)"/>
  <text x="500" y="286" font-size="16" fill="#475569">seat_id</text>

  <line x1="490" y1="470" x2="560" y2="300" stroke="#64748b" stroke-width="2.5" marker-end="url(#arrow3)"/>
  <text x="502" y="376" font-size="16" fill="#475569">hold_id</text>

  <line x1="775" y1="440" x2="775" y2="400" stroke="#64748b" stroke-width="2.5" marker-end="url(#arrow3)"/>
  <text x="788" y="428" font-size="16" fill="#475569">booking_id</text>

  <line x1="1080" y1="210" x2="990" y2="210" stroke="#64748b" stroke-width="2.5" marker-end="url(#arrow3)"/>
  <text x="1000" y="204" font-size="16" fill="#475569">seat_id</text>

  <rect x="60" y="760" width="1280" height="100" rx="12" fill="#f8fafc" stroke="#cbd5e1" stroke-width="2"/>
  <text x="700" y="798" font-size="20" font-weight="700" text-anchor="middle" fill="#0f172a">Invariant chain</text>
  <text x="700" y="828" font-size="18" text-anchor="middle" fill="#334155">available seat → one active hold (partial unique index) → one booking (unique seat_id and hold_id) → one captured payment (unique idempotency_key)</text>
  <text x="700" y="852" font-size="16" text-anchor="middle" fill="#64748b">Every arrow is enforced by a constraint in Postgres, so a concurrent writer cannot bypass the rule by racing the application code.</text>
</svg>
"""

TERMINAL_CSS = """
body { margin:0; background:#ffffff; }
.terminal { width:1400px; margin:0; background:#0b1220; border-radius:14px; overflow:hidden; border:1px solid #1e293b; font-family:'JetBrains Mono','Fira Code',Consolas,'DejaVu Sans Mono',monospace; }
.bar { height:46px; background:#111c2f; display:flex; align-items:center; gap:10px; padding:0 18px; border-bottom:1px solid #1e293b; }
.dot { width:13px; height:13px; border-radius:50%; display:inline-block; }
.red { background:#ef4444; } .yellow { background:#f59e0b; } .green { background:#22c55e; }
.title { color:#94a3b8; font-size:16px; margin-left:12px; letter-spacing:.4px; }
pre { margin:0; padding:24px 28px; color:#cbd5e1; font-size:17px; line-height:1.5; white-space:pre-wrap; }
.pass { color:#4ade80; font-weight:700; }
.fail { color:#f87171; font-weight:700; }
.test { color:#7dd3fc; }
.meta { color:#fbbf24; font-weight:700; }
.dim { color:#64748b; }
"""


def terminal_page(title: str, text: str, out: Path) -> None:
    lines = []
    for raw in text.rstrip("\n").split("\n"):
        cls = ""
        line = html.escape(raw)
        if "PASSED" in raw or raw.startswith("PASS"):
            cls = "pass"
        elif "FAILED" in raw or raw.startswith("FAIL"):
            cls = "fail"
        elif raw.startswith("tests/"):
            cls = "test"
        elif "passed" in raw or "collected" in raw or raw.startswith("="):
            cls = "meta"
        if cls:
            line = f'<span class="{cls}">{line}</span>'
        lines.append(line)
    body = "\n".join(lines)
    out.write_text(
        f"<!doctype html><html><head><meta charset='utf-8'><style>{TERMINAL_CSS}</style></head>"
        f"<body><div class='terminal'><div class='bar'>"
        f"<span class='dot red'></span><span class='dot yellow'></span><span class='dot green'></span>"
        f"<span class='title'>{html.escape(title)}</span></div><pre>{body}</pre></div></body></html>"
    )


def svg_page(svg: str, out: Path, width: int, height: int) -> None:
    out.write_text(
        f"<!doctype html><html><head><meta charset='utf-8'><style>html,body{{margin:0;background:#fff}}</style></head>"
        f"<body>{svg}</body></html>"
    )


def main() -> None:
    svg_page(ARCHITECTURE, ASSETS / "architecture.html", 1360, 700)
    svg_page(RACE_TIMELINE, ASSETS / "race-timeline.html", 1360, 720)
    svg_page(SCHEMA, ASSETS / "schema.html", 1400, 900)
    (ASSETS / "race-timeline.svg").write_text(RACE_TIMELINE)
    (ASSETS / "architecture.svg").write_text(ARCHITECTURE)
    (ASSETS / "schema.svg").write_text(SCHEMA)

    demo = Path("/home/tony/OpenCode/fa2 dcs/railreserve/demo-output.txt").read_text()
    pytest_out = Path("/tmp/opencode/pytest-output.txt").read_text()
    marker = "============================= test session starts ============================="
    if marker in pytest_out:
        pytest_out = pytest_out[pytest_out.index(marker):]
    pytest_out = re.sub(r"\n=+ warnings summary =+.*?======================== .*? =\n", "\n", pytest_out, flags=re.S)
    pytest_out = re.sub(r"\n=+ short test summary info =+.*?(?=\n=|\Z)", "\n", pytest_out, flags=re.S)
    terminal_page("demo.sh — six-scenario evidence", demo, ASSETS / "terminal-demo.html")
    terminal_page("pytest -v — 15 concurrency and API tests", pytest_out, ASSETS / "terminal-pytest.html")


if __name__ == "__main__":
    main()
