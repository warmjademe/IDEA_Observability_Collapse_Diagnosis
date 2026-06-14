#!/usr/bin/env bash
# OpenHands-OCD entrypoint: original OpenHands LocalRuntime + LiteLLM-Anthropic
# routing, PLUS a controlled [condenser] knob (the OCD context operator, P0-6).
#
# The reviewed design needs the harness context strategy set DIRECTLY and logged
# (u_t) so a run where compression did not fire can be marked invalid. OpenHands
# ships a real condenser family; we expose it via env:
#   OE_CONDENSER            noop | recent | llm   (default noop = preserve/control)
#   OE_CONDENSER_KEEP_FIRST keep_first (default 0  -> even the task prompt is
#                           droppable, so the operator can bite prompt anchors)
#   OE_CONDENSER_MAX        recent->max_events ; llm->max_size (default 4)
# NOTE: OpenHands enable_default_condenser defaults True, so the CONTROL arm MUST
# explicitly request type=noop; omitting [condenser] silently enables an LLM one.
set -uo pipefail
TIMEOUT="${OE_RUN_TIMEOUT:-600}"
MAX_ITER="${OE_OH_MAX_ITER:-25}"
LITELLM_URL="${OE_LITELLM_URL:-http://127.0.0.1:4000}"
LITELLM_KEY="${OE_LITELLM_KEY:-sk-litellm-virtual}"
MODEL="${OE_MODEL:-anthropic/claude-sonnet-4-5}"
DISABLE_STREAM="${OE_OH_DISABLE_STREAMING:-true}"
COND="${OE_CONDENSER:-noop}"
KEEPF="${OE_CONDENSER_KEEP_FIRST:-0}"
CMAX="${OE_CONDENSER_MAX:-4}"
SANDBOX=/workdir/sandbox
OE_DIR=/workdir/.oe
/bin/mkdir -p "$OE_DIR"
FILE_STORE="$OE_DIR/openhands_state"
/bin/mkdir -p "$FILE_STORE"

python3 /opt/oe-shims/fs_snapshot.py "$SANDBOX" --out "$OE_DIR/fs_before.json"
TASK_FILE="$SANDBOX/.oe/task.txt"
if [[ ! -f "$TASK_FILE" ]]; then echo "FATAL: $TASK_FILE missing" >&2; exit 2; fi

CFG="$OE_DIR/config.toml"
cat > "$CFG" <<TOML
[core]
runtime = "local"
workspace_base = "${SANDBOX}"
file_store = "local"
file_store_path = "${FILE_STORE}"
enable_browser = false
save_trajectory_path = "${OE_DIR}/trajectory.json"

[llm]
model = "${MODEL}"
api_key = "${LITELLM_KEY}"
base_url = "${LITELLM_URL}"
temperature = 0.0
num_retries = 3
disable_streaming = ${DISABLE_STREAM}
TOML

# ---- controlled condenser operator (u_t) ----
case "$COND" in
  noop)
    printf '\n[condenser]\ntype = "noop"\n' >> "$CFG" ;;
  recent)
    printf '\n[condenser]\ntype = "recent"\nkeep_first = %s\nmax_events = %s\n' "$KEEPF" "$CMAX" >> "$CFG" ;;
  llm)
    cat >> "$CFG" <<TOML2

[llm.condenser_llm]
model = "${MODEL}"
api_key = "${LITELLM_KEY}"
base_url = "${LITELLM_URL}"
temperature = 0.0
disable_streaming = ${DISABLE_STREAM}

[condenser]
type = "llm"
llm_config = "condenser_llm"
keep_first = ${KEEPF}
max_size = ${CMAX}
TOML2
    ;;
  *) echo "FATAL: unknown OE_CONDENSER=$COND" >&2; exit 3 ;;
esac
# record the operator setting (u_t intent) for the analysis pipeline
printf '{"condenser":"%s","keep_first":%s,"max":%s,"max_iter":%s}\n' "$COND" "$KEEPF" "$CMAX" "$MAX_ITER" > "$OE_DIR/ctx_operator.json"

export ANTHROPIC_API_KEY="${LITELLM_KEY}"
export ANTHROPIC_API_BASE="${LITELLM_URL}"
cd "$SANDBOX"
START_TS=$(/usr/bin/date -u +%s)
set +e
# log-level INFO so condensation events are visible in the log (u_t firing check)
timeout --preserve-status -k 10 "${TIMEOUT}" \
    python3 -m openhands.core.main \
        --config-file "$CFG" -c CodeActAgent -f "$TASK_FILE" -d "$SANDBOX" \
        -i "${MAX_ITER}" --log-level INFO \
    > "$OE_DIR/openhands_stdout.log" 2> "$OE_DIR/openhands_stderr.log"
RC=$?
set -e
END_TS=$(/usr/bin/date -u +%s)
echo "{\"exit_code\":$RC,\"elapsed_sec\":$((END_TS-START_TS))}" > "$OE_DIR/openhands_meta.json"

# u_t: did condensation actually fire? count Condensation markers in the log
CONDN=$(grep -c -iE "condensation|condensing|forget|summariz" "$OE_DIR/openhands_stderr.log" 2>/dev/null || true)
[[ -z "$CONDN" ]] && CONDN=0
echo "{\"condensation_log_hits\":$CONDN}" > "$OE_DIR/ctx_fired.json"

python3 /opt/oe-shims/fs_snapshot.py "$SANDBOX" --out "$OE_DIR/fs_after.json"
python3 /opt/oe/trace_to_atom.py --file-store "$FILE_STORE" --out "$OE_DIR/events.jsonl" 2>/dev/null || true
python3 - <<'PY'
import json, pathlib
root = pathlib.Path("/workdir/sandbox"); out = {}
if root.exists():
    for p in root.rglob("*"):
        if p.is_file() and ".oe" not in p.parts and ".git" not in p.parts:
            try:
                out[str(p.relative_to(root))] = p.read_text(errors="replace")[:200_000]
            except Exception:
                pass
pathlib.Path("/workdir/.oe/file_after.json").write_text(json.dumps(out))
PY
echo "[entrypoint] openhands-ocd done rc=$RC condenser=$COND fired=$CONDN"
exit 0
