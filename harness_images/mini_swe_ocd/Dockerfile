# OCD pilot mini-swe-agent image: inherit the ICSE image and only override the
# entrypoint with the config-path fix (so mini runs headless instead of aborting
# in the interactive setup wizard). Nothing else changes — same mini-swe-agent,
# same shims, same artifact layout.
ARG BASE_IMAGE=emnlp/mini-swe-agent:latest
FROM ${BASE_IMAGE}
USER root
COPY entrypoint.sh /opt/oe/entrypoint.sh
RUN chmod 0755 /opt/oe/entrypoint.sh
WORKDIR /workdir
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/oe/entrypoint.sh"]
