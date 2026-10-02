FROM ghcr.io/imputnet/yt-session-generator:webserver

USER root

RUN sed -i 's/nodriver.start(headless=False,/nodriver.start(headless=False, sandbox=False,/' /app/potoken_generator/extractor.py
