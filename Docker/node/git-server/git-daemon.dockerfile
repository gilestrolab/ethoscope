#!/usr/bin/env -S docker build . --tag=git-daemon
FROM alpine:3.10.2

RUN apk add --no-cache git-daemon git

WORKDIR /srv/git

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT [ "/entrypoint.sh" ]
