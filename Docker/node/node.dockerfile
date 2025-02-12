# These build instructions will create a docker container running the node and most of its services
ARG ETHOSCOPE_BRANCH=dev
# Use the latest Arch Linux base image
FROM archlinux:latest

# Update system and install base-devel and git for building AUR packages
RUN pacman -Sy \
    && pacman-key --init \
    && pacman-key --populate archlinux \
    && pacman -S --noconfirm archlinux-keyring \
    && pacman -Syu --needed --noconfirm base-devel git micro python-pip


RUN pacman -Sy --needed --noconfirm python-setuptools python-pip python-ifaddr python-numpy \
                                    python-bottle python-pyserial python-mysql-connector python-netifaces python-cherrypy \
                                    python-eventlet python-dnspython python-greenlet python-monotonic \
                                    python-zeroconf python-cheroot python-opencv python-gitpython 


RUN git clone https://github.com/gilestrolab/ethoscope.git /opt/ethoscope-node
RUN cd /opt/ethoscope-node/ && git checkout ${ETHOSCOPE_BRANCH}
RUN cd /opt/ethoscope-node/node_src && python setup.py develop
RUN cd /opt/ethoscope-node/src && python setup.py develop

WORKDIR /opt/ethoscope-node/node_src/scripts
