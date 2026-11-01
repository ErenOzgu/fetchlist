FROM golang:1.23 AS build
RUN go install golang.org/x/tools/cmd/goimports@latest
RUN curl -fsSL https://example.com/tools/lint-1.4.0.tar.gz -o /tmp/lint.tgz

FROM python:3.12-slim@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
COPY --from=build /go/bin/goimports /usr/local/bin/goimports
COPY --from=ghcr.io/example/helper:2.1 /helper /usr/local/bin/helper
ADD https://example.com/data/dataset.csv /data/dataset.csv
RUN pip install --no-cache-dir flask==3.0.3 gunicorn
