FROM ghcr.io/imputnet/yt-session-generator:webserver

USER root

# Fix Chromium when running as root
RUN sed -i \
  's/nodriver.start(headless=False, sandbox=False,/nodriver.start(headless=False, no_sandbox=True,/' \
  /app/potoken_generator/extractor.py

# Diagnostic: log every YouTube youtubei request
RUN sed -i \
  "/if not event.request.method == 'POST':/i\\        if 'youtubei' in event.request.url:\\n            logger.info(f'YOUTUBE REQUEST: {event.request.method} {event.request.url}')" \
  /app/potoken_generator/extractor.py

# Cobalt 11.7.1 expects POST /get_pot
RUN sed -i \
  "s#'/token': self.get_potoken,#'/token': self.get_potoken,\\n            '/get_pot': self.get_potoken,#" \
  /app/potoken_generator/server.py
