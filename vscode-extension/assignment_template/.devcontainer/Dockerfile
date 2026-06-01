FROM ubuntu:22.04

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install core C++ development tools and python for background scripts
RUN apt-get update && apt-get install -y \
    build-essential \
    g++ \
    gdb \
    make \
    python3 \
    python3-pip \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a place to store our local telemetry/helper hooks
RUN mkdir -p /usr/local/bin/ta_hooks

# Example Hook: A placeholder shell utility that you can call to simulate logging 
# compiler outputs or terminal context to your AWS backend later.
RUN echo '#!/bin/bash\n\
echo "[TA Hook] Simulating data transmission to AWS..."\n\
# future_curl_cmd="curl -X POST https://your-api.amazonaws.com/telemetry -d @-"\n\
echo "[TA Hook] Sent context: \$@"\n\
' > /usr/local/bin/ta_hooks/telemetry_stub.sh && chmod +x /usr/local/bin/ta_hooks/telemetry_stub.sh

# Set the default shell to bash
ENV SHELL=/bin/bash
