"""Optional single-page web trigger for PatentLoop.

Submit an idea, watch the live log of which agent is running and what it just
found. The web process only triggers the run and reads the run folder; the loop
itself is the same orchestrator the CLI uses, so nothing about a web run is
interactive.

    python -m patentloop.web            # http://127.0.0.1:5001
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template_string, request, url_for

from .config import Config, ConfigError
from .orchestrator import Orchestrator, new_run_id

PAGE = """<!doctype html>
<title>PatentLoop</title>
<style>
 body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}
 textarea{width:100%;height:9rem;font:14px/1.4 ui-monospace,monospace}
 button{padding:.6rem 1.2rem;font-size:15px}
 pre{background:#111;color:#d7ffd7;padding:1rem;border-radius:6px;overflow:auto;max-height:26rem}
 .verdict{padding:.6rem 1rem;border-radius:6px;font-weight:600}
 .DRAFTED{background:#e6ffe6;border:1px solid #2a2}
 .KILLED_SATURATED,.KILLED_INFEASIBLE{background:#ffecec;border:1px solid #c22}
 .running{background:#fff8e0;border:1px solid #db2}
 code{background:#f2f2f2;padding:.1rem .3rem}
</style>
<h1>PatentLoop</h1>
{% if not run_id %}
<p>One trigger, no questions: the loop researches, searches patents, gates feasibility, pivots when
blocked, and ends in <code>DRAFTED</code>, <code>KILLED_SATURATED</code> or
<code>KILLED_INFEASIBLE</code>.</p>
<form method="post" action="{{ url_for('start') }}">
  <textarea name="idea" placeholder="Describe the invention in plain text..." required></textarea>
  <p><label>Max pivots <input name="max_iterations" type="number" value="4" min="1" max="8"></label></p>
  <button type="submit">Run unattended</button>
</form>
{% if error %}<p style="color:#c22">{{ error }}</p>{% endif %}
{% else %}
<p><a href="{{ url_for('index') }}">&larr; new run</a> &middot; run <code>{{ run_id }}</code></p>
<div id="verdict" class="verdict running">running…</div>
<h3>Live agent log</h3>
<pre id="log">waiting for the first agent…</pre>
<div id="artifacts"></div>
<script>
async function poll(){
  const r = await fetch("{{ url_for('state', run_id=run_id) }}");
  const s = await r.json();
  document.getElementById('log').textContent = s.log.join("\\n");
  const v = document.getElementById('verdict');
  v.className = 'verdict ' + (s.outcome || 'running');
  v.textContent = s.outcome ? (s.outcome + ' — ' + s.reason) : ('running: ' + (s.current || 'starting'));
  if (s.outcome){
    document.getElementById('artifacts').innerHTML =
      '<h3>Artifacts</h3><ul>' + s.artifacts.map(a => '<li><code>' + a + '</code></li>').join('') + '</ul>';
    return;
  }
  setTimeout(poll, 2000);
}
poll();
</script>
{% endif %}
"""


def create_app(config: Config | None = None) -> Flask:
    app = Flask(__name__)
    app.config["PATENTLOOP_CONFIG"] = config

    def _config() -> Config:
        return app.config.get("PATENTLOOP_CONFIG") or Config.from_env()

    @app.get("/")
    def index():
        return render_template_string(PAGE, run_id=None, error=request.args.get("error"))

    @app.post("/runs")
    def start():
        idea = (request.form.get("idea") or "").strip()
        if not idea:
            return redirect(url_for("index", error="idea text is required"))
        try:
            config = _config()
        except ConfigError as exc:
            return redirect(url_for("index", error=str(exc)))
        max_iterations = request.form.get("max_iterations")
        if max_iterations and max_iterations.isdigit():
            config.max_iterations = int(max_iterations)
        run_id = new_run_id()
        orchestrator = Orchestrator(config, run_id)
        threading.Thread(target=orchestrator.run, args=(idea,), daemon=True).start()
        return redirect(url_for("show", run_id=run_id))

    @app.get("/runs/<run_id>")
    def show(run_id: str):
        return render_template_string(PAGE, run_id=run_id, error=None)

    @app.get("/runs/<run_id>/state")
    def state(run_id: str):
        run_dir = Path(_runs_dir(app)) / run_id
        if not run_dir.exists():
            abort(404)
        log_path = run_dir / "run.log"
        lines = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
        result_path = run_dir / "result.json"
        outcome = reason = None
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            outcome, reason = payload.get("outcome"), payload.get("reason")
        current = ""
        for line in reversed(lines):
            if "]" in line:
                current = line.split("] ", 1)[-1].split(":")[0]
                break
        return jsonify(
            {
                "run_id": run_id,
                "log": lines[-400:],
                "outcome": outcome,
                "reason": reason,
                "current": current,
                "artifacts": sorted(p.name for p in run_dir.iterdir()) if outcome else [],
            }
        )

    def _runs_dir(app: Flask) -> Path:
        config = app.config.get("PATENTLOOP_CONFIG")
        if config:
            return Path(config.runs_dir)
        from .config import DEFAULT_RUNS_DIR

        return DEFAULT_RUNS_DIR

    return app


def main() -> None:
    create_app().run(host="127.0.0.1", port=5001, debug=False)


if __name__ == "__main__":
    main()
