user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log;
pid /run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    access_log /var/log/nginx/access.log;
    sendfile on;
    client_max_body_size 50m;

    server {
        listen 80 default_server;
        server_name _;
        root __WEB_ROOT__;
        index index.html;

        location /api/ {
            proxy_pass http://127.0.0.1:__SERVER_PORT__;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 120s;
        }

        location = /index.html {
            add_header Cache-Control "no-cache";
        }

        location /assets/ {
            add_header Cache-Control "public, max-age=31536000, immutable";
        }

        location / {
            try_files $uri $uri/ /index.html;
        }
    }
}
