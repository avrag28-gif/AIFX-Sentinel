FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive WINEDEBUG=-all DISPLAY=:99
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y --no-install-recommends \
    wine64 wine32 xvfb x11vnc wget ca-certificates cabextract winbind procps python3 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 trader && mkdir -p /opt/mt5 /home/trader/.wine \
    && chown -R trader:trader /opt/mt5 /home/trader
COPY entrypoint.sh /entrypoint.sh
COPY mt5-healthcheck /usr/local/bin/mt5-healthcheck
RUN chmod +x /entrypoint.sh /usr/local/bin/mt5-healthcheck
USER trader
WORKDIR /home/trader
ENTRYPOINT ["/entrypoint.sh"]
