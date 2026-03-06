# These build instructions will create a docker container running the node and most of its services
ARG ETHOSCOPE_BRANCH=dev
# Use the latest Arch Linux base image
FROM archlinux:latest
ARG ETHOSCOPE_BRANCH=dev

# Update system and install base-devel and git for building AUR packages
RUN pacman -Sy \
    && pacman-key --init \
    && pacman-key --populate archlinux \
    && pacman -S --noconfirm archlinux-keyring \
    && pacman -Syu --needed --noconfirm base-devel git micro python-pip


RUN pacman -Sy --needed --noconfirm python-setuptools python-pip python-ifaddr python-numpy \
                                    python-bottle python-pyserial python-mysql-connector python-netifaces python-cherrypy \
                                    python-eventlet python-dnspython python-greenlet python-monotonic \
                                    python-zeroconf python-cheroot python-gitpython \
                                    python-requests python-psutil python-scipy python-dateutil \
                                    openssh sshpass rsync curl

RUN pip install --break-system-packages mattermostdriver


RUN cd /opt && git clone https://github.com/gilestrolab/ethoscope.git
RUN cd /opt/ethoscope/ && git checkout ${ETHOSCOPE_BRANCH:-dev}
RUN cd /opt/ethoscope/src/node && pip install --no-deps -e . --break-system-packages

WORKDIR /opt/ethoscope/src/node/scripts
