#!/bin/bash

# Professional VPN Bot Installer for Ubuntu
# Created by Antigravity

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Clear screen
clear

echo -e "${BLUE}=================================================================${NC}"
echo -e "${BLUE}       Professional VPN Bot Installer for Ubuntu Server          ${NC}"
echo -e "${BLUE}=================================================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
  echo -e "${RED}Error: Please run as root (sudo ./installer.sh)${NC}"
  exit 1
fi

# Get absolute path of current directory
PROJECT_DIR=$(pwd)

echo -e "${YELLOW}[1/7] Updating System and Installing Dependencies...${NC}"
# Stop conflicting services first
echo -e "Stopping conflicting services (Apache/Nginx)..."
systemctl stop apache2 2>/dev/null || true
systemctl disable apache2 2>/dev/null || true
systemctl stop nginx 2>/dev/null || true
# Kill any process using port 80 or 443
fuser -k 80/tcp 2>/dev/null || true
fuser -k 443/tcp 2>/dev/null || true

apt-get update
apt-get install -y python3 python3-pip python3-venv mysql-server nginx certbot python3-certbot-nginx libmysqlclient-dev python3-dev build-essential dos2unix psmisc

echo -e "${GREEN}Dependencies installed successfully.${NC}"
echo ""

echo -e "${YELLOW}[2/7] Fixing Line Endings...${NC}"
# Fix line endings for all scripts and python files (crucial for files uploaded from Windows)
echo -e "Converting files to Unix format..."
find "$PROJECT_DIR" -type f -name "*.py" -exec dos2unix {} + 2>/dev/null
find "$PROJECT_DIR" -type f -name "*.sh" -exec dos2unix {} + 2>/dev/null
find "$PROJECT_DIR" -type f -name "*.txt" -exec dos2unix {} + 2>/dev/null
chmod +x "$PROJECT_DIR/installer.sh" "$PROJECT_DIR/start.sh" "$PROJECT_DIR/stop.sh"

echo -e "${GREEN}Line endings fixed.${NC}"
echo ""

echo -e "${YELLOW}[3/7] Collecting Configuration Information...${NC}"
echo -e "${BLUE}Please enter the following information to configure your bot:${NC}"

read -p "Enter Bot Token (from @BotFather): " BOT_TOKEN
while [[ -z "$BOT_TOKEN" ]]; do
    echo -e "${RED}Bot Token cannot be empty.${NC}"
    read -p "Enter Bot Token: " BOT_TOKEN
done

read -p "Enter Admin Telegram ID (numeric): " ADMIN_ID
while [[ ! "$ADMIN_ID" =~ ^[0-9]+$ ]]; do
    echo -e "${RED}Admin ID must be a number.${NC}"
    read -p "Enter Admin Telegram ID: " ADMIN_ID
done

read -p "Enter Bot Username (without @): " BOT_USERNAME
read -p "Enter Channel ID (e.g., @MyChannel): " CHANNEL_ID
read -p "Enter Channel Link (e.g., https://t.me/MyChannel): " CHANNEL_LINK
read -p "Enter Reports Channel ID (numeric, optional, press Enter to skip): " REPORTS_CHANNEL_ID
REPORTS_CHANNEL_ID=${REPORTS_CHANNEL_ID:-0}

# Payment configuration removed as per request

echo -e "${BLUE}--- Web Application Configuration ---${NC}"
read -p "Enter Domain Name (e.g., vpn.example.com): " DOMAIN
while [[ -z "$DOMAIN" ]]; do
    echo -e "${RED}Domain cannot be empty.${NC}"
    read -p "Enter Domain Name: " DOMAIN
done

echo -e "${BLUE}--- Database Configuration ---${NC}"
read -p "Enter a secure password for the MySQL database user: " DB_PASS
while [[ -z "$DB_PASS" ]]; do
    echo -e "${RED}Password cannot be empty.${NC}"
    read -p "Enter MySQL Password: " DB_PASS
done

echo ""
echo -e "${YELLOW}[4/7] Setting up Project Environment...${NC}"

echo -e "Installing in: $PROJECT_DIR"

# FORCE RECREATE VENV
# This fixes the issue where a Windows venv was uploaded to Linux
if [ -d "venv" ]; then
    echo -e "${YELLOW}Removing existing virtual environment to ensure compatibility...${NC}"
    rm -rf venv
fi

echo -e "Creating new virtual environment..."
python3 -m venv venv
echo -e "${GREEN}Virtual environment created.${NC}"

# Install Python requirements
echo -e "Installing Python packages..."
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip
"$PROJECT_DIR/venv/bin/pip" install -r requirements.txt
"$PROJECT_DIR/venv/bin/pip" install gunicorn

# Create .env file
echo -e "Creating configuration file..."
cat > .env << EOL
BOT_TOKEN=$BOT_TOKEN
ADMIN_ID=$ADMIN_ID
BOT_USERNAME=$BOT_USERNAME
REPORTS_CHANNEL_ID=$REPORTS_CHANNEL_ID
CHANNEL_ID=$CHANNEL_ID
CHANNEL_LINK=$CHANNEL_LINK
WEBAPP_URL=https://$DOMAIN
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=vpn_bot
MYSQL_PASSWORD=$DB_PASS
MYSQL_DATABASE=vpn_bot
MULTI_BOT_MODE=false
EOL

echo -e "${GREEN}Environment configured.${NC}"

echo ""
echo -e "${YELLOW}[5/7] Configuring Database...${NC}"

# Configure MySQL
# Check if we can connect without password (socket auth)
if mysql -e "SELECT 1;" &>/dev/null; then
    echo -e "Connected to MySQL using socket auth."
    MYSQL_CMD="mysql"
else
    echo -e "${YELLOW}MySQL root password required.${NC}"
    echo -e "It seems your MySQL root user has a password set."
    read -s -p "Enter current MySQL root password: " MYSQL_ROOT_PASS
    echo ""
    MYSQL_CMD="mysql -u root -p$MYSQL_ROOT_PASS"
fi

# Create database and user
$MYSQL_CMD -e "CREATE DATABASE IF NOT EXISTS vpn_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
$MYSQL_CMD -e "CREATE USER IF NOT EXISTS 'vpn_bot'@'localhost' IDENTIFIED BY '$DB_PASS';"
$MYSQL_CMD -e "GRANT ALL PRIVILEGES ON vpn_bot.* TO 'vpn_bot'@'localhost';"
$MYSQL_CMD -e "FLUSH PRIVILEGES;"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Database configured successfully.${NC}"
else
    echo -e "${RED}Database configuration failed. Please check your MySQL password.${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}[6/7] Configuring Nginx and SSL...${NC}"

# Create Nginx config
cat > /etc/nginx/sites-available/vpn_bot << EOL
server {
    server_name $DOMAIN;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOL

# Enable site
ln -sf /etc/nginx/sites-available/vpn_bot /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test and restart Nginx
# Ensure port 80 is free again just in case
fuser -k 80/tcp 2>/dev/null || true
systemctl restart nginx

# Obtain SSL Certificate
echo -e "Obtaining SSL certificate from Let's Encrypt..."
certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m admin@$DOMAIN --redirect

echo ""
echo -e "${YELLOW}[7/7] Setting up System Services...${NC}"

# Verify paths exist
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
GUNICORN_BIN="$PROJECT_DIR/venv/bin/gunicorn"

if [ ! -f "$PYTHON_BIN" ]; then
    echo -e "${RED}Error: Python binary not found at $PYTHON_BIN${NC}"
    exit 1
fi

if [ ! -f "$GUNICORN_BIN" ]; then
    echo -e "${RED}Error: Gunicorn binary not found at $GUNICORN_BIN${NC}"
    exit 1
fi

# Create Systemd Service for Bot
cat > /etc/systemd/system/vpn-bot.service << EOL
[Unit]
Description=VPN Telegram Bot
After=network.target mysql.service

[Service]
User=root
WorkingDirectory=$PROJECT_DIR
ExecStart=$PYTHON_BIN $PROJECT_DIR/telegram_bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL

# Create Systemd Service for WebApp
cat > /etc/systemd/system/vpn-webapp.service << EOL
[Unit]
Description=VPN Web Application
After=network.target mysql.service

[Service]
User=root
WorkingDirectory=$PROJECT_DIR
ExecStart=$GUNICORN_BIN --workers 3 --bind 127.0.0.1:5000 webapp:app
Restart=always
RestartSec=5
Environment="PATH=$PROJECT_DIR/venv/bin"

[Install]
WantedBy=multi-user.target
EOL

# Reload systemd
systemctl daemon-reload
systemctl enable vpn-bot
systemctl enable vpn-webapp

echo ""
echo -e "${BLUE}=================================================================${NC}"
echo -e "${GREEN}       Installation Completed Successfully!                      ${NC}"
echo -e "${BLUE}=================================================================${NC}"
echo -e "You can now manage the bot using the following commands:"
echo -e "  ${YELLOW}./start.sh${NC} - Start the bot and web application"
echo -e "  ${YELLOW}./stop.sh${NC}  - Stop the bot and web application"
echo ""
echo -e "Your web application is accessible at: ${GREEN}https://$DOMAIN${NC}"
echo ""
