FROM ghcr.io/imputnet/yt-session-generator:webserver

USER root

# Use our modified extractor.py
COPY potoken_generator/extractor.py /app/potoken_generator/extractor.py

# Cobalt 11.7.1 expects POST /get_pot
RUN sed -i \
  "s#'/token': self.get_potoken,#'/token': self.get_potoken,\n            '/get_pot': self.get_potoken,#" \
  /app/potoken_generator/server.py
