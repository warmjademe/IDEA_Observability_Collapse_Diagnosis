#!/bin/bash
# Recon the model-routing env contract for every not-yet-wired harness, so we know
# exactly which base-URL env var to point at the compression proxy + which API surface.
A=/home/qyb/TongBu/ICSE_2027_Overeager/Source_Codes
RE='OE_[A-Z_]+|OPENAI[A-Z_]*|ANTHROPIC[A-Z_]*|GOOGLE[A-Z_]*|BASE_URL|baseUrl|base_url|/v1/responses|/chat/completions|/v1/messages|--model|MODEL'

echo "########## config-backed (agent dirs) ##########"
for h in goose codex_cli; do
  echo "=== $h/entrypoint.sh ==="
  grep -hoE "$RE" $A/agents/$h/entrypoint.sh 2>/dev/null | sort -u | tr '\n' ' '; echo
done

echo; echo "########## qwen (Qwen Code, inside emnlp/qwen:v2) ##########"
docker run --rm --entrypoint /bin/sh emnlp/qwen:v2 -c '
  for f in /opt/oe/qwen_entrypoint.sh /opt/oe/oe_qwen_preload.cjs; do
    echo "== $f =="; grep -hoE "OE_[A-Z_]+|OPENAI[A-Z_]*|ANTHROPIC[A-Z_]*|BASE_URL|baseUrl|base_url|/chat/completions|/responses|/v1|model|MODEL" "$f" 2>/dev/null | sort -u | tr "\n" " "; echo
  done' 2>/dev/null

echo; echo "########## image-only harnesses ##########"
for img in emnlp/cline:v2 emnlp/crush:v2 emnlp/opencode:latest emnlp/pi:v2; do
  docker image inspect $img >/dev/null 2>&1 || { echo "=== $img : MISSING ==="; continue; }
  ep=$(docker image inspect $img --format '{{.Config.Entrypoint}} {{.Config.Cmd}}')
  echo "=== $img  EP=$ep ==="
  docker run --rm --entrypoint /bin/sh $img -c '
    for f in /opt/oe/*entrypoint*.sh /opt/oe/*.sh /entrypoint.sh; do
      [ -f "$f" ] || continue
      echo "  -- $f --"; grep -hoE "OE_[A-Z_]+|OPENAI[A-Z_]*|ANTHROPIC[A-Z_]*|BASE_URL|baseUrl|base_url|/chat/completions|/responses|/v1|--model|MODEL" "$f" 2>/dev/null | sort -u | tr "\n" " "; echo
    done' 2>/dev/null
done
