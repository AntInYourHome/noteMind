#!/bin/bash
# Upgrade server to modern Docker CE (static binaries, aarch64)
set -e

echo "== removing old distro docker-engine =="
dnf -q remove -y docker-engine 2>/dev/null || true

# prefer official source if reachable, else aliyun mirror
M=https://mirrors.aliyun.com/docker-ce/linux/static/stable/aarch64
if curl -sm 5 -o /dev/null https://download.docker.com; then
  M=https://download.docker.com/linux/static/stable/aarch64
fi
echo "== mirror: $M =="

V=27.5.1
curl -sL -o /tmp/d.tgz "$M/docker-$V.tgz"
tar -xzf /tmp/d.tgz -C /usr/local/bin --strip-components=1
rm -f /tmp/d.tgz

mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF

groupadd -f docker
usermod -aG docker zhaosong

cat > /etc/systemd/system/docker.service <<'EOF'
[Unit]
Description=Docker Application Container Engine
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart=/usr/local/bin/dockerd
ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=5
LimitNOFILE=infinity
LimitNPROC=infinity

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now docker >/dev/null 2>&1
sleep 2
systemctl is-active --quiet docker || { journalctl -u docker --no-pager | tail -15; exit 1; }
docker version --format "== docker server {{.Server.Version}} OK =="
getenforce 2>/dev/null || true

# verify an actual container run; on pull failure add registry mirrors and retry
if ! docker run --rm hello-world >/dev/null 2>&1; then
  echo "== direct pull failed, adding registry mirrors =="
  cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "registry-mirrors": ["https://docker.1ms.run", "https://docker.m.daocloud.io"]
}
EOF
  systemctl restart docker
  sleep 3
  docker run --rm hello-world >/dev/null 2>&1 && echo ALL_OK || echo PULL_FAILED
else
  echo ALL_OK
fi
