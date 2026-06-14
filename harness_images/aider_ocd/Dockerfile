# OCD pilot aider image: inherit the ICSE aider image and only override the
# entrypoint so the model-settings file uses edit_format: diff (SEARCH/REPLACE)
# instead of whole. With "whole", devstral mixes narration into filenames and
# leaves the target file unchanged; "diff" produces clean SEARCH/REPLACE blocks
# that aider applies correctly (verified: auth.py expiry logic applied cleanly).
ARG BASE_IMAGE=emnlp/aider:latest
FROM ${BASE_IMAGE}
USER root
COPY entrypoint.sh /opt/oe/entrypoint.sh
RUN chmod 0755 /opt/oe/entrypoint.sh
WORKDIR /workdir
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/oe/entrypoint.sh"]
