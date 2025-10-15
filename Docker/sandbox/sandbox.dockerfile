# Dockerfile for node container using only pacman for dependencies (no pip)
# Run with docker build -f sandbox.dockerfile -t sandbox:latest .

# Use the latest Arch Linux base image
FROM archlinux:latest

# Update system and install base-devel and git
RUN pacman -Sy \
    && pacman-key --init \
    && pacman-key --populate archlinux \
    && pacman -S --noconfirm archlinux-keyring \
    && pacman -Syu --needed --noconfirm base-devel git micro nano

# Install all Python dependencies via pacman only
# Based on dependencies from pyproject.toml files in src/node and src/ethoscope
RUN pacman -Sy --needed --noconfirm \
    python \
    python-bottle \
    python-cherrypy \
    python-mysql-connector \
    python-netifaces \
    python-gitpython \
    python-zeroconf \
    python-numpy \
    python-opencv \
    python-pyserial \
    python-psutil \
    python-requests \
    python-scipy \
    python-dateutil

# Add ethoscope repository to pacman.conf
RUN echo "" >> /etc/pacman.conf \
    && echo "[ethoscope]" >> /etc/pacman.conf \
    && echo "SigLevel = Optional TrustAll" >> /etc/pacman.conf \
    && echo "Server = https://repo.ethoscope.lab.gilest.ro/" >> /etc/pacman.conf \
    && pacman -Sy

# Install AUR packages
# Create a non-root user for building AUR packages (makepkg cannot run as root)
RUN useradd -m -G wheel -s /bin/bash sandbox && \
    echo "sandbox ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# Install python-mattermostdriver from AUR
USER sandbox
WORKDIR /home/sandbox
RUN git clone https://aur.archlinux.org/python-mattermostdriver.git && \
    cd python-mattermostdriver && \
    makepkg -si --noconfirm

# Switch back to root
USER root

WORKDIR /root

# Run the node server
CMD ["/bin/bash"]
