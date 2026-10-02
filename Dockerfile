FROM ghcr.io/imputnet/yt-session-generator:webserver

USER root

RUN sed -i \
  's/nodriver.start(headless=False,/nodriver.start(headless=False, no_sandbox=True,/' \
  /app/potoken_generator/extractor.py

RUN sed -i \
  "s#'/token': self.get_potoken,#'/token': self.get_potoken,\\n            '/get_pot': self.get_potoken,#" \
  /app/potoken_generator/server.py
