#!/bin/bash
# (Re)start the 8 context-compression proxies (OpenAI :4210-4213, Anthropic :4220-4223),
# keep = 0/12/6/3 per surface. Kills any existing instance on those ports first.
set -u
PY=/home/qyb/miniconda3/envs/EMNLP_2026_Overeage/bin/python
DIR=/home/qyb/jss_poison/litellm_proxies
LOG=$DIR/logs; mkdir -p $LOG
export NO_PROXY="*" no_proxy="*"; unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy

for p in 4210 4211 4212 4213 4220 4221 4222 4223; do
  fuser -k ${p}/tcp 2>/dev/null
done
sleep 2

launch(){ # script port keep
  setsid nohup $PY $DIR/$1 --port $2 --keep $3 > $LOG/ctx_$2.log 2>&1 < /dev/null &
}
launch ctx_compress_proxy.py 4210 0
launch ctx_compress_proxy.py 4211 12
launch ctx_compress_proxy.py 4212 6
launch ctx_compress_proxy.py 4213 3
launch ctx_compress_anthropic_proxy.py 4220 0
launch ctx_compress_anthropic_proxy.py 4221 12
launch ctx_compress_anthropic_proxy.py 4222 6
launch ctx_compress_anthropic_proxy.py 4223 3
sleep 5
echo "=== health ==="
for p in 4210 4211 4212 4213 4220 4221 4222 4223; do
  printf "%s: " $p; curl -s --noproxy '*' http://127.0.0.1:$p/health || echo DOWN
  echo
done
