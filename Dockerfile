FROM ghcr.io/imputnet/yt-session-generator:webserver

USER root

RUN sed -i \
  's/nodriver.start(headless=False,/nodriver.start(headless=False, no_sandbox=True,/' \
  /app/potoken_generator/extractor.py
