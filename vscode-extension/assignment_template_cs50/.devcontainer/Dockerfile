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
    ca-certificates \
    unzip \
    sudo \
    valgrind \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Install libcs50 (github.com/cs50/libcs50) so problem sets that
# #include <cs50.h> (get_int, get_string, etc.) compile out of the box.
# Version pinned rather than tracking "latest" so a devcontainer rebuild
# mid-course can't silently change library behavior under students.
ARG LIBCS50_VERSION=v11.0.3
RUN curl -sL "https://api.github.com/repos/cs50/libcs50/tarball/${LIBCS50_VERSION}" -o /tmp/libcs50.tar.gz \
    && mkdir -p /tmp/libcs50 \
    && tar -xzf /tmp/libcs50.tar.gz -C /tmp/libcs50 --strip-components=1 \
    && make -C /tmp/libcs50 install \
    && ldconfig \
    && rm -rf /tmp/libcs50 /tmp/libcs50.tar.gz

# CS50's own problem set instructions just say "make progname" - no Makefile,
# no explicit -lcs50. GNU Make's built-in implicit rule for compiling a single
# .c file automatically appends $(LDLIBS) at link time, so this one variable
# is what makes that work with zero custom Makefile or make wrapper needed.
ENV LDLIBS=-lcs50

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

# Create a non-root student user with passwordless sudo so they can install
# any packages the instructor forgot to include without rebuilding the container.
RUN useradd -ms /bin/bash student \
    && echo 'student ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers.d/student \
    && chmod 0440 /etc/sudoers.d/student

# 1. Establish the base extensions directory for the student user
RUN mkdir -p /home/student/.vscode-server/extensions \
    && mkdir -p /home/student/.vscode-remote/extensions \
    && chown -R student:student /home/student/.vscode-server \
    && chown -R student:student /home/student/.vscode-remote

# 2. Create the dummy Version 999 directories
RUN mkdir -p /home/student/.vscode-server/extensions/github.copilot-999.0.0 \
    && mkdir -p /home/student/.vscode-server/extensions/github.copilot-chat-999.0.0 \
    && mkdir -p /home/student/.vscode-remote/extensions/github.copilot-999.0.0 \
    && mkdir -p /home/student/.vscode-remote/extensions/github.copilot-chat-999.0.0

# 3. Plant the dummy package.json files so the server registers them as valid, but fails to activate them
RUN echo '{"name": "copilot", "publisher": "github", "version": "999.0.0", "engines": {"vscode": "^1.0.0"}, "main": "index.js"}' > /home/student/.vscode-server/extensions/github.copilot-999.0.0/package.json \
    && echo '{"name": "copilot-chat", "publisher": "github", "version": "999.0.0", "engines": {"vscode": "^1.0.0"}, "main": "index.js"}' > /home/student/.vscode-server/extensions/github.copilot-chat-999.0.0/package.json \
    && echo '{"name": "copilot", "publisher": "github", "version": "999.0.0", "engines": {"vscode": "^1.0.0"}, "main": "index.js"}' > /home/student/.vscode-remote/extensions/github.copilot-999.0.0/package.json \
    && echo '{"name": "copilot-chat", "publisher": "github", "version": "999.0.0", "engines": {"vscode": "^1.0.0"}, "main": "index.js"}' > /home/student/.vscode-remote/extensions/github.copilot-chat-999.0.0/package.json

# 4. Lock them with root ownership and read/execute only so the student (and server) cannot delete them
RUN chown -R root:root /home/student/.vscode-server/extensions/github.copilot-999.0.0 \
    && chown -R root:root /home/student/.vscode-server/extensions/github.copilot-chat-999.0.0 \
    && chmod -R 0555 /home/student/.vscode-server/extensions/github.copilot-999.0.0 \
    && chmod -R 0555 /home/student/.vscode-server/extensions/github.copilot-chat-999.0.0 \
    && chown -R root:root /home/student/.vscode-remote/extensions/github.copilot-999.0.0 \
    && chown -R root:root /home/student/.vscode-remote/extensions/github.copilot-chat-999.0.0 \
    && chmod -R 0555 /home/student/.vscode-remote/extensions/github.copilot-999.0.0 \
    && chmod -R 0555 /home/student/.vscode-remote/extensions/github.copilot-chat-999.0.0
