FROM ghcr.io/imputnet/yt-session-generator:webserver

USER root

# Verify Chromium path and version
RUN which chromium && chromium --version

# Replace extractor with our diagnostic version
COPY potoken_generator/extractor.py /app/potoken_generator/extractor.py

# Verify that our modified extractor is really inside the image
RUN grep -n "DIAGNOSTIC: launching Chromium" /app/potoken_generator/extractor.py

# Cobalt 11.7.1 expects POST /get_pot
RUN sed -i \
  "s#'/token': self.get_potoken,#'/token': self.get_potoken,\n            '/get_pot': self.get_potoken,#" \
  /app/potoken_generator/server.py
