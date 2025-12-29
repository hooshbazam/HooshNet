#!/bin/bash

# SSL Generation Script
# This script runs inside the container to generate SSL certificates

DOMAIN=$1
EMAIL=$2

if [ -z "$DOMAIN" ]; then
    echo "Usage: ./generate_ssl.sh <domain> [email]"
    exit 1
fi

echo "Requesting SSL certificate for $DOMAIN..."

# Try Webroot mode first (Zero Downtime)
echo "Attempting to generate certificate using webroot mode..."
if [ -z "$EMAIL" ]; then
    certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --register-unsafely-without-email --agree-tos --non-interactive
else
    certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive
fi

# Check if successful
if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "Certificate generated successfully (Webroot mode)!"
else
    echo "Webroot mode failed. Trying Standalone mode (requires stopping Nginx)..."
    
    # Stop Nginx to free port 80
    supervisorctl stop nginx
    
    # Run Certbot Standalone
    if [ -z "$EMAIL" ]; then
        certbot certonly --standalone -d "$DOMAIN" --register-unsafely-without-email --agree-tos --non-interactive
    else
        certbot certonly --standalone -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive
    fi
    
    # Start Nginx back up regardless of success (it will use self-signed if failed)
    supervisorctl start nginx
fi

# Check if successful (either method)
if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    echo "Linking certificates..."
    
    # Link certificates
    ln -sf "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" /etc/nginx/ssl/fullchain.pem
    ln -sf "/etc/letsencrypt/live/$DOMAIN/privkey.pem" /etc/nginx/ssl/privkey.pem
    
    echo "Certificates linked."
    
    # Reload Nginx to apply changes
    supervisorctl restart nginx
    echo "Nginx reloaded with new certificate."
else
    echo "Certificate generation failed!"
    exit 1
fi
