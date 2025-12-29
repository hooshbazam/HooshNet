#!/bin/bash
set -e

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Wait for database
log_info "Waiting for Database..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if python3 -c "
import mysql.connector
from mysql.connector import Error
try:
    conn = mysql.connector.connect(
        host='${MYSQL_HOST:-vpn-db}',
        user='${MYSQL_USER:-vpn_bot}',
        password='${MYSQL_PASSWORD:-vpn_bot_password}',
        port=${MYSQL_PORT:-3306}
    )
    if conn.is_connected():
        conn.close()
        exit(0)
except Error as e:
    exit(1)
" 2>/dev/null; then
        log_success "Database connected!"
        break
    fi
    attempt=$((attempt + 1))
    log_warn "Waiting for database... attempt $attempt/$max_attempts"
    sleep 2
done

if [ $attempt -eq $max_attempts ]; then
    log_error "Failed to connect to database after $max_attempts attempts"
    exit 1
fi

# Run Migrations
log_info "Running Database Migrations..."
python3 -c "
from professional_database import ProfessionalDatabaseManager
db = ProfessionalDatabaseManager()
db.init_database()
print('Database initialized successfully!')
" || {
    log_error "Database migration failed!"
    # Continue anyway - might work if tables exist
    log_warn "Continuing despite migration error..."
}

# Ensure SSL Directory Exists
mkdir -p /etc/nginx/ssl

# Check for Let's Encrypt certificates on host (mounted from /etc/letsencrypt)
LETSENCRYPT_CERT=""
if [ -d /etc/letsencrypt/live ]; then
    for domain_dir in /etc/letsencrypt/live/*/; do
        if [ -f "${domain_dir}fullchain.pem" ] && [ -f "${domain_dir}privkey.pem" ]; then
            log_success "Found Let's Encrypt certificate in ${domain_dir}"
            ln -sf "${domain_dir}fullchain.pem" /etc/nginx/ssl/fullchain.pem
            ln -sf "${domain_dir}privkey.pem" /etc/nginx/ssl/privkey.pem
            LETSENCRYPT_CERT="yes"
            break
        fi
    done
fi

# Generate Self-Signed Certificate if no Let's Encrypt cert found
if [ ! -f /etc/nginx/ssl/fullchain.pem ] || [ ! -f /etc/nginx/ssl/privkey.pem ]; then
    log_warn "No Let's Encrypt certificate found, generating self-signed certificate..."
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout /etc/nginx/ssl/privkey.pem \
        -out /etc/nginx/ssl/fullchain.pem \
        -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost" 2>/dev/null
    log_success "Self-signed certificate generated"
fi

# Create certbot directory
mkdir -p /var/www/certbot

# Write Nginx config
log_info "Writing Nginx configuration..."
cat > /etc/nginx/sites-available/vpn_bot << 'NGINX_CONFIG'
server {
    listen 80;
    server_name _;
    
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name _;

    ssl_certificate /etc/nginx/ssl/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/privkey.pem;

    client_max_body_size 10M;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
NGINX_CONFIG

# Ensure symlink exists and default is removed
ln -sf /etc/nginx/sites-available/vpn_bot /etc/nginx/sites-enabled/vpn_bot
rm -f /etc/nginx/sites-enabled/default

# Create nginx log directory
mkdir -p /var/log/nginx

# Test Nginx configuration
log_info "Testing Nginx configuration..."
if nginx -t 2>&1; then
    log_success "Nginx configuration is valid!"
else
    log_error "Nginx configuration test failed!"
    cat /etc/nginx/sites-available/vpn_bot
fi

# Test webapp import before starting supervisor
log_info "Testing webapp import..."
if python3 -c "import webapp; print('Webapp import successful!')" 2>&1; then
    log_success "Webapp imported successfully!"
else
    log_error "Webapp import failed! Check logs for details:"
    python3 -c "import webapp" 2>&1 || true
    log_warn "Starting supervisor anyway..."
fi

# Start Supervisor
log_success "Starting Supervisor..."
exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf
