#!/bin/bash
# Stop stalled pull, add CN registry mirrors, restart docker
pkill -f 'docker compose up' 2>/dev/null || true
sleep 1

cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io",
    "https://dockerproxy.net"
  ]
}
EOF

systemctl restart docker
sleep 3
systemctl is-active docker
docker info 2>/dev/null | grep -iA5 'registry mirrors'
