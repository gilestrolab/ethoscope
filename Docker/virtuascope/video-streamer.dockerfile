# Dockerfile for streaming remote video to virtual device
FROM ubuntu:22.04

# Install required packages
RUN apt-get update && apt-get install -y \
    v4l2loopback-dkms \
    v4l-utils \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create entrypoint script
COPY video-entrypoint.sh /video-entrypoint.sh
RUN chmod +x /video-entrypoint.sh

ENTRYPOINT ["/video-entrypoint.sh"]