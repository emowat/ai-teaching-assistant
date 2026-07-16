FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    g++ \
    gdb \
    make \
    python3 \
    python3-pip \
    git \
    curl \
    unzip \
    sudo \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /usr/local/bin/ta_hooks

RUN echo '#!/bin/bash\n\
echo "[TA Hook] Simulating data transmission to AWS..."\n\
echo "[TA Hook] Sent context: \$@"\n\
' > /usr/local/bin/ta_hooks/telemetry_stub.sh && chmod +x /usr/local/bin/ta_hooks/telemetry_stub.sh

ENV SHELL=/bin/bash
