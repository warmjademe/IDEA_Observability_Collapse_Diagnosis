# OpenHands-OCD image: inherit the ICSE OpenHands image and overlay ONLY the
# entrypoint, which adds the controlled [condenser] knob (the OCD context
# operator, P0-6) driven by OE_CONDENSER / OE_CONDENSER_KEEP_FIRST /
# OE_CONDENSER_MAX, plus u_t logging (ctx_operator.json, ctx_fired.json).
# Everything else (OpenHands 0.x, shims, trace_to_atom) is unchanged so the
# noop arm is byte-for-byte the stock harness with compression disabled.
ARG BASE_IMAGE=emnlp/openhands:latest
FROM ${BASE_IMAGE}
USER root
COPY entrypoint.sh /opt/oe/entrypoint.sh
RUN chmod 0755 /opt/oe/entrypoint.sh
WORKDIR /workdir
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/oe/entrypoint.sh"]
