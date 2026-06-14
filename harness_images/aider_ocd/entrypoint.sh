#!/usr/bin/env bash
# Aider entrypoint (local-model, OpenAI surface).
#
# Drives aider headless against the local vLLM OpenAI-compatible endpoint.
# Aider uses litellm under the hood, so we point OPENAI_API_BASE at the
# vLLM /v1 and use model "openai/qwen-coder".
#
# Required / honoured env (from runner):
#   OE_RUN_TIMEOUT     seconds (default 240)
#   OE_MODEL           litellm model id (default openai/qwen-coder)
#   OE_OPENAI_BASE     OpenAI base URL (default http://127.0.0.1:8000/v1)
#   OE_OPENAI_KEY      API key (default sk-local)
#   OE_MAX_TOKENS      cap on model output tokens (default 4096)

set -uo pipefail
TIMEOUT="${OE_RUN_TIMEOUT:-240}"
MODEL="${OE_MODEL:-openai/qwen-coder}"
OPENAI_BASE="${OE_OPENAI_BASE:-http://127.0.0.1:8000/v1}"
OPENAI_KEY="${OE_OPENAI_KEY:-sk-local}"
MAX_TOKENS="${OE_MAX_TOKENS:-4096}"
SANDBOX=/workdir/sandbox
OE_DIR=/workdir/.oe
# aider installed system-wide; resolve its console script (not PATH-shimmed).
AIDER_BIN="$(command -v aider 2>/dev/null || true)"
[[ -z "$AIDER_BIN" ]] && AIDER_BIN="/usr/local/bin/aider"
[[ -x "$AIDER_BIN" ]] || AIDER_BIN="/usr/bin/python3 -m aider"
/bin/mkdir -p "$OE_DIR"

# 1. fs snapshot BEFORE
python3 /opt/oe-shims/fs_snapshot.py "$SANDBOX" --out "$OE_DIR/fs_before.json"

# 2. read prompt
TASK_FILE="$SANDBOX/.oe/task.txt"
if [[ ! -f "$TASK_FILE" ]]; then
    echo "FATAL: $TASK_FILE missing" >&2
    exit 2
fi

# 3. model routing for aider/litellm: openai-compatible surface.
export OPENAI_API_BASE="$OPENAI_BASE"
export OPENAI_API_KEY="$OPENAI_KEY"
export OPENAI_BASE_URL="$OPENAI_BASE"      # litellm also reads this name
export AIDER_ANALYTICS=false
export AIDER_ANALYTICS_DISABLE=true
# Keep aider config/state inside .oe so it never pollutes the sandbox diff.
export HOME=/workdir/.oe
/bin/mkdir -p "$HOME"

# Model-settings file caps OUTPUT tokens (vLLM qwen-coder max_model_len=40960;
# aider/litellm otherwise may request a huge max_tokens and trip HTTP 400).
SETTINGS="$OE_DIR/aider.model.settings.yml"
cat > "$SETTINGS" <<YML
- name: ${MODEL}
  edit_format: diff
  use_repo_map: false
  send_undo_reply: false
  extra_params:
    max_tokens: ${MAX_TOKENS}
    temperature: 0.0
YML

# 4. invoke aider HEADLESS, non-interactive, CWD = sandbox.
#   --yes-always: never prompt; --no-git: don't init a repo / commit;
#   --no-auto-commits / --no-dirty-commits: belt and braces;
#   --no-check-update / --no-show-model-warnings / --no-stream: quieter & robust;
#   --map-tokens 0: disable repo-map LLM calls; --message-file: the task.
cd "$SANDBOX"
# Collect the sandbox's regular files as positional args so aider has them in
# its chat context (aider only edits files it has been given). Exclude .oe/.git
# and skip oversized/binary files. Without this aider replies "I have no files".
mapfile -t FILES < <(find . -type f \
        -not -path './.oe/*' -not -path './.git/*' \
        -not -name '*.png' -not -name '*.jpg' -not -name '*.jpeg' \
        -not -name '*.gif' -not -name '*.pdf' -not -name '*.zip' \
        -not -name '*.tar' -not -name '*.gz' \
        -printf '%P\n' 2>/dev/null)
START_TS=$(/usr/bin/date -u +%s)
set +e
timeout --preserve-status -k 5 "${TIMEOUT}" \
    $AIDER_BIN \
        --model "$MODEL" \
        --model-settings-file "$SETTINGS" \
        --yes-always \
        --no-git \
        --no-auto-commits \
        --no-dirty-commits \
        --no-check-update \
        --no-show-model-warnings \
        --no-stream \
        --no-pretty \
        --map-tokens 0 \
        --no-gitignore \
        --chat-history-file "$OE_DIR/aider.chat.history.md" \
        --input-history-file "$OE_DIR/aider.input.history" \
        --llm-history-file "$OE_DIR/aider.llm.history" \
        --message-file "$TASK_FILE" \
        "${FILES[@]}" \
    > "$OE_DIR/aider_stream.txt" 2> "$OE_DIR/aider_stderr.log"
RC=$?
set -e
END_TS=$(/usr/bin/date -u +%s)
echo "{\"exit_code\":$RC,\"elapsed_sec\":$((END_TS-START_TS))}" > "$OE_DIR/aider_meta.json"

# 5. fs snapshot AFTER
python3 /opt/oe-shims/fs_snapshot.py "$SANDBOX" --out "$OE_DIR/fs_after.json"

# 6. events.jsonl — aider has no structured tool-event stream comparable to
#    codex apply_patch; derive judge-compatible events from (a) the atom log
#    (real shell calls) and (b) the fs diff (file writes/edits/deletes). The
#    fs-diff events let event_pattern/file checkers see aider's edits even
#    though aider edits files via python io (no PATH-shim traversal).
python3 - "$OE_DIR" <<'PY'
import json, pathlib, sys, datetime
oe = pathlib.Path(sys.argv[1])
def _ts(): return datetime.datetime.utcnow().isoformat() + "Z"
events = []
# (a) shell atoms -> Bash events
flat = oe / "atoms.flat"
if flat.exists():
    for ln in flat.read_text(errors="replace").splitlines():
        ln = ln.strip()
        if ln:
            events.append({"ts": _ts(), "kind": "tool_use", "name": "Bash",
                           "args": {"command": ln}, "flat": "Bash " + ln[:240]})
# (b) fs diff -> Write/Edit/Delete events
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

echo "[entrypoint] aider done rc=$RC; artifacts in $OE_DIR"
exit 0
