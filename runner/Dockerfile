FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    g++ \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 runner

WORKDIR /runner
COPY run_cpp.py /runner/run_cpp.py
RUN chmod 0555 /runner/run_cpp.py

USER runner
WORKDIR /workspace

ENTRYPOINT ["python3", "/runner/run_cpp.py"]
