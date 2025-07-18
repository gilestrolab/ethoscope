# These build instructions will create a docker container running the virtuascope

# Use the latest Arch Linux base image
FROM archlinux:latest

# Update system and install base-devel and git for building AUR packages
RUN pacman -Syu --noconfirm \
    && pacman -S --needed --noconfirm base-devel git nano

# Create a non-root user for building the AUR package
RUN useradd -m ethoscope \
    && passwd -d ethoscope \
    && printf 'ethoscope ALL=(ALL) ALL\n' | tee -a /etc/sudoers

# Switch to the non-root user
USER ethoscope
WORKDIR /home/ethoscope

# Clone yay and install it
RUN git clone https://aur.archlinux.org/yay.git \
    && cd yay \
    && makepkg -si --noconfirm \
    && cd .. \
    && rm -rf yay

# Install ethoscope-node from AUR
RUN yay -S --noconfirm ethoscope-device

#we remove this file to activate the VIRTUASCOPE Mode
RUN sudo rm /etc/machine-name

# Clean up packages
RUN sudo pacman -Scc --noconfirm

# Set the working directory
WORKDIR /opt/ethoscope/src/ethoscope/scripts
USER root

# Command to run when the container starts
CMD ["python3", "/opt/ethoscope/src/ethoscope/scripts/device_server.py", "-D"]
