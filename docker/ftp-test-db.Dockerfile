FROM delfer/alpine-ftp-server:latest

RUN apk add --no-cache iproute2

COPY ftp/ftp-test-db-entrypoint.sh /usr/local/bin/ftp-test-db-entrypoint.sh

RUN sed -i 's/\r$//' /usr/local/bin/ftp-test-db-entrypoint.sh \
    && chmod +x /usr/local/bin/ftp-test-db-entrypoint.sh

ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/ftp-test-db-entrypoint.sh"]
