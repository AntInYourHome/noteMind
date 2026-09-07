[Unit]
Description=Super Tools backend (FastAPI/uvicorn)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
User=__RUN_USER__
WorkingDirectory=__APP_HOME__/server
ExecStart=__APP_HOME__/server/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port __SERVER_PORT__
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
