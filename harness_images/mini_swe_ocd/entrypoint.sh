#!/usr/bin/env bash
# mini-swe-agent entrypoint (local-model, OpenAI surface).
#
# Drives `mini` headless against the local vLLM OpenAI-compatible endpoint.
# mini-swe-agent uses litellm; model "openai/qwen-coder".
#
# Honoured env (from runner):
#   OE_RUN_TIMEOUT   seconds (default 240)
#   OE_MODEL         litellm model id (default openai/qwen-coder)
#   OE_OPENAI_BASE   OpenAI base URL (default http://127.0.0.1:8000/v1)
#   OE_OPENAI_KEY    API key (default sk-local)
#   OE_MAX_TOKENS    cap on model output tokens (default 4096)
#   OE_MSWEA_STEPS   max agent steps (default 25)

set -uo pipefail
TIMEOUT="${OE_RUN_TIMEOUT:-240}"
MODEL="${OE_MODEL:-openai/qwen-coder}"
OPENAI_BASE="${OE_OPENAI_BASE:-http://127.0.0.1:8000/v1}"
OPENAI_KEY="${OE_OPENAI_KEY:-sk-local}"
MAX_TOKENS="${OE_MAX_TOKENS:-4096}"
STEPS="${OE_MSWEA_STEPS:-25}"
SANDBOX=/workdir/sandbox
OE_DIR=/workdir/.oe
MINI_BIN="$(command -v mini 2>/dev/null || true)"
[[ -z "$MINI_BIN" ]] && MINI_BIN="/usr/local/bin/mini"
/bin/mkdir -p "$OE_DIR"

# 1. fs snapshot BEFORE
python3 /opt/oe-shims/fs_snapshot.py "$SANDBOX" --out "$OE_DIR/fs_before.json"

# 2. read prompt
TASK_FILE="$SANDBOX/.oe/task.txt"
if [[ ! -f "$TASK_FILE" ]]; then
    echo "FATAL: $TASK_FILE missing" >&2
    exit 2
fi
TASK="$(cat "$TASK_FILE")"

# 3. routing for mini-swe-agent / litellm + caps. mini-swe-agent reads the
#    model name from MSWEA_MODEL_NAME and forwards api_base/api_key/max_tokens
#    to litellm via the model kwargs; we also export OPENAI_* for litellm's
#    openai provider. Keep config/state inside .oe.
export OPENAI_API_BASE="$OPENAI_BASE"
export OPENAI_API_KEY="$OPENAI_KEY"
export OPENAI_BASE_URL="$OPENAI_BASE"
export MSWEA_MODEL_NAME="$MODEL"
export MSWEA_MODEL_API_KEY="$OPENAI_KEY"
export MSWEA_SILENT_STARTUP=true
# OCD FIX (the real one): mini-swe-agent v2.3.0 triggers the interactive setup
# wizard whenever the env var MSWEA_CONFIGURED is unset — see
# minisweagent/run/utilities/config.py: configure_if_first_time() checks ONLY
# `os.getenv("MSWEA_CONFIGURED")`, not whether the .env exists. Set it to skip.
export MSWEA_CONFIGURED=true
# Local ollama models are not in litellm's price map, so mini's cost tracking
# raises and aborts the run; tell it to ignore that (mini prints this exact hint).
export MSWEA_COST_TRACKING=ignore_errors
export MSWEA_GLOBAL_CONFIG_DIR="$OE_DIR/mswea"
export HOME=/workdir/.oe
/bin/mkdir -p "$HOME" "$OE_DIR/mswea"

# mini-swe-agent v2 loads its global config from $HOME/.config/mini-swe-agent/.env
# and, if absent, launches an interactive setup wizard that aborts on a non-tty.
# Pre-seed that dotenv with the model + routing so the run is fully headless.
# OCD FIX: the ICSE image wrote the headless config ONLY to $HOME/.config while
# exporting MSWEA_GLOBAL_CONFIG_DIR to a different (empty) dir, so mini found no
# config and launched the interactive setup wizard, which aborts on a non-tty
# ("Input is not a terminal ... Aborted."). Write config to EVERY dir/name mini reads.
_write_cfg() {
  local dir="$1"
  /bin/mkdir -p "$dir"
  cat > "$dir/.env" <<ENV
MSWEA_MODEL_NAME=${MODEL}
MSWEA_CONFIGURED=true
MSWEA_COST_TRACKING=ignore_errors
MSWEA_CONFIRM_EXIT=false
MSWEA_SILENT_STARTUP=true
OPENAI_API_BASE=${OPENAI_BASE}
OPENAI_BASE_URL=${OPENAI_BASE}
OPENAI_API_KEY=${OPENAI_KEY}
LITELLM_MODEL_KWARGS={"api_base":"${OPENAI_BASE}","api_key":"${OPENAI_KEY}","max_tokens":${MAX_TOKENS},"temperature":0}
ENV
  /bin/cp "$dir/.env" "$dir/mini.env" 2>/dev/null || true
}
_write_cfg "$MSWEA_GLOBAL_CONFIG_DIR"
_write_cfg "$HOME/.config/mini-swe-agent"

# litellm model kwargs file (caps output tokens; sets api_base explicitly).
export LITELLM_MODEL_KWARGS="{\"api_base\":\"${OPENAI_BASE}\",\"api_key\":\"${OPENAI_KEY}\",\"max_tokens\":${MAX_TOKENS},\"temperature\":0}"

# 4. invoke mini headless. `-y` = yolo/auto-confirm (no interactive prompts);
#    `-t` = task; `--exit-immediately` ends after the agent declares done;
#    `-o` writes the trajectory next to our other artifacts.
cd "$SANDBOX"
START_TS=$(/usr/bin/date -u +%s)
set +e
timeout --preserve-status -k 5 "${TIMEOUT}" \
    "$MINI_BIN" \
        -m "$MODEL" \
        -t "$TASK" \
        -y \
        -l 0 \
        --exit-immediately \
        -o "$OE_DIR/mswea_traj.json" \
    > "$OE_DIR/mswea_stream.txt" 2> "$OE_DIR/mswea_stderr.log"
RC=$?
set -e
END_TS=$(/usr/bin/date -u +%s)
echo "{\"exit_code\":$RC,\"elapsed_sec\":$((END_TS-START_TS))}" > "$OE_DIR/mswea_meta.json"

# 5. fs snapshot AFTER
python3 /opt/oe-shims/fs_snapshot.py "$SANDBOX" --out "$OE_DIR/fs_after.json"

# 6. events.jsonl from atoms + fs diff (mini-swe-agent acts purely by issuing
#    bash commands, so the PATH shim captures most of its actions directly).
python3 - "$OE_DIR" <<'PY'
import json, pathlib, sys, datetime
oe = pathlib.Path(sys.argv[1])
def _ts(): return datetime.datetime.utcnow().isoformat() + "Z"
events = []
flat = oe / "atoms.flat"
if flat.exists():
    for ln in flat.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if ln:
            events.append({"ts": _ts(), "kind": "tool_use", "name": "Bash",
                           "args": {"command": ln}, "flat": "Bash " + ln[:240]})
def _load(p):
    try: return json.loads((oe / p).read_text())
    except Exception: return {}
before, after = _load("fs_before.json"), _load("fs_after.json")
for path, h in after.items():
    if path not in before:
        events.append({"ts": _ts(), "kind": "tool_use", "name": "Write",
                       "args": {"file_path": path}, "flat": f"Write {path}"})
    elif before[path] != h:
        events.append({"ts": _ts(), "kind": "tool_use", "name": "Edit",
                       "args": {"file_path": path}, "flat": f"Edit {path}"})
for path in before:
    if path not in after:
        events.append({"ts": _ts(), "kind": "tool_use", "name": "Delete",
                       "args": {"file_path": path}, "flat": f"Delete {path}"})
(oe / "events.jsonl").write_text(
    "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events))
PY

# 7. snapshot textual contents (for file_contains checkers)
python3 -c '
import json, pathlib
root = pathlib.Path("/workdir/sandbox")
out = {}
for p in root.rglob("*"):
    if p.is_file() and ".oe" not in p.parts and ".git" not in p.parts:
        try:
            txt = p.read_text(errors="replace")[:200_000]
            out[str(p.relative_to(root))] = txt
        except Exception:
            pass
pathlib.Path("/workdir/.oe/file_after.json").write_text(json.dumps(out))
'

echo "[entrypoint] mini-swe-agent done rc=$RC; artifacts in $OE_DIR"
exit 0
