#!/bin/bash

# Professional VPN Bot Updater
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
echo -e "${BLUE}       Professional VPN Bot Updater                              ${NC}"
echo -e "${BLUE}=================================================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
  echo -e "${RED}Error: Please run as root (sudo ./update.sh)${NC}"
  exit 1
fi

# Get absolute path of current directory
PROJECT_DIR=$(pwd)

echo -e "${YELLOW}[1/4] Pulling latest changes from Git...${NC}"
git fetch --all
git reset --hard origin/main
git pull origin main

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Successfully pulled latest changes.${NC}"
else
    echo -e "${RED}Failed to pull changes. Please check your internet connection or git configuration.${NC}"
    exit 1
fi
echo ""

echo -e "${YELLOW}[2/4] Updating Dependencies...${NC}"
if [ -d "venv" ]; then
    "$PROJECT_DIR/venv/bin/pip" install --upgrade pip
    "$PROJECT_DIR/venv/bin/pip" install -r requirements.txt
    echo -e "${GREEN}Dependencies updated.${NC}"
else
    echo -e "${RED}Virtual environment not found. Please run installer.sh first.${NC}"
    exit 1
fi
echo ""

echo -e "${YELLOW}[3/4] Fixing Permissions and Line Endings...${NC}"
find "$PROJECT_DIR" -type f -name "*.py" -exec dos2unix {} + 2>/dev/null
find "$PROJECT_DIR" -type f -name "*.sh" -exec dos2unix {} + 2>/dev/null
chmod +x "$PROJECT_DIR/installer.sh" "$PROJECT_DIR/start.sh" "$PROJECT_DIR/stop.sh" "$PROJECT_DIR/update.sh"
echo -e "${GREEN}Permissions fixed.${NC}"
echo ""

echo -e "${YELLOW}[4/4] Restarting Services...${NC}"
systemctl restart vpn-bot
systemctl restart vpn-webapp

# Check status
if systemctl is-active --quiet vpn-bot && systemctl is-active --quiet vpn-webapp; then
    echo -e "${GREEN}Services restarted successfully.${NC}"
else
    echo -e "${RED}Warning: Services might not have started correctly. Check 'systemctl status vpn-bot'${NC}"
fi

echo ""
echo -e "${BLUE}=================================================================${NC}"
echo -e "${GREEN}       Update Completed Successfully!                            ${NC}"
echo -e "${BLUE}=================================================================${NC}"
echo ""
