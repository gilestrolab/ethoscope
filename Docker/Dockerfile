# These build instructions will create a docker container running the node and most of its services

# Use the latest Arch Linux base image
FROM archlinux:latest

# Update system and install base-devel and git for building AUR packages
RUN pacman -Syu --noconfirm \
    && pacman -S --needed --noconfirm base-devel git nano

# Create a non-root user for building the AUR package
RUN useradd -m node \
    && passwd -d node \
    && printf 'node ALL=(ALL) ALL\n' | tee -a /etc/sudoers

# Switch to the non-root user
USER node
WORKDIR /home/node

# Clone yay and install it
RUN git clone https://aur.archlinux.org/yay.git \
    && cd yay \
    && makepkg -si --noconfirm \
    && cd .. \
    && rm -rf yay

# This replaces systemctl which cannot work in containers
# https://github.com/gdraheim/docker-systemctl-replacement
RUN yay -S --noconfirm docker-systemctl-replacement-git

# Install ethoscope-node from AUR
RUN yay -S --noconfirm ethoscope-node
RUN git config --global --add safe.directory /srv/git/ethoscope.git

# Clean up packages
RUN sudo pacman -Scc --noconfirm

# Set the working directory
WORKDIR /opt/ethoscope-node/node_src/scripts
USER root

# Command to run when the container starts
CMD ["/usr/bin/systemctl.py", "-1"]

