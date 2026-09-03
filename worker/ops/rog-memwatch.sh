#!/usr/bin/env bash
# What is holding the memory on the shared render machine, sampled.
#
# Temporary, and deliberately so: it exists to answer one question the owner
# asked on 2026-09-02 — how often does the local LLM client load the 9 GB model,
# for how long, and how much of that lands inside this project's render window
# — before anyone spends money on RAM or changes a config that is not ours.
#
# It READS. It never touches ollama, openclaw, ComfyUI or anything belonging to
# the other projects: one HTTP GET to ollama's own status endpoint (which
# reports loaded models and loads nothing), one read of /proc/meminfo. Output is
# one CSV line into this project's own directory.
#
# To remove it entirely:
#   systemctl --user disable --now eko-rog-memwatch.timer
#   rm ~/.config/systemd/user/eko-rog-memwatch.{timer,service}
set -u
OUT="$HOME/eko-render/rog-memory.csv"
[ -f "$OUT" ] || echo "when,mem_available_gb,models_loaded,detail" > "$OUT"

avail=$(awk '/MemAvailable/ {printf "%.2f", $2/1048576}' /proc/meminfo 2>/dev/null || echo "")

# `/api/ps` lists what is resident right now. An empty list is the answer we
# expect most of the time, and it is worth recording: "nothing loaded" is the
# baseline the overlap is measured against.
detail=$(curl -s --max-time 5 http://127.0.0.1:11434/api/ps 2>/dev/null \
  | python3 -c '
import sys, json
try:
    models = json.load(sys.stdin).get("models") or []
except Exception:
    print("0|unreadable"); raise SystemExit
names = ";".join(
    f"{m.get('"'"'name'"'"','"'"'?'"'"')}@{round(m.get('"'"'size'"'"',0)/1e9,1)}GB" for m in models
)
print(f"{len(models)}|{names or '"'"'none'"'"'}")
' 2>/dev/null || echo "0|no-answer")

# `detail` already carries "<count>|<models>", so it fills the last TWO header
# columns once the pipe is turned into a comma. Writing it as one field is what
# made the first reading of this file wrong: an `awk` on column 3 compared
# "0|none" against "0" and reported a loaded model in 11 of 12 samples.
printf '%s,%s,%s\n' "$(date -Iseconds)" "$avail" "${detail/|/,}" >> "$OUT"
