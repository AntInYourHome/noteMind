#!/bin/bash
set -e
V=$(curl -s https://api.github.com/repos/docker/compose/releases/latest | grep -oP '"tag_name": "\K[^"]+')
[ -n "$V" ] || V=v2.27.0
echo "compose VERSION=$V"
mkdir -p /usr/local/lib/docker/cli-plugins
curl -sL -o /usr/local/lib/docker/cli-plugins/docker-compose \
  "https://github.com/docker/compose/releases/download/$V/docker-compose-linux-aarch64"
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
