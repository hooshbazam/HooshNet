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

# 1. Check Internet Connection
echo -e "${YELLOW}[1/3] Checking Internet Connection...${NC}"
wget -q --spider http://github.com

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Internet connection is active.${NC}"
else
    echo -e "${RED}Error: No internet connection. Cannot update.${NC}"
    exit 1
fi
echo ""

# 2. Pull Latest Changes
echo -e "${YELLOW}[2/3] Pulling latest changes from GitHub...${NC}"
echo -e "${BLUE}Resetting local changes and fetching latest version...${NC}"

# Fetch and Reset
git fetch --all
git reset --hard origin/main

if [ $? -eq 0 ]; then
    echo -e "${GREEN}Successfully pulled latest code.${NC}"
else
    echo -e "${RED}Failed to pull from GitHub. Please check your git configuration.${NC}"
    exit 1
fi
echo ""

# 3. Run Post-Update Script (Python)
echo -e "${YELLOW}[3/3] Running System Configuration...${NC}"

# Check if post_update.py exists
if [ -f "$PROJECT_DIR/post_update.py" ]; then
    # Use venv python if available, else system python3
    if [ -f "$PROJECT_DIR/venv/bin/python" ]; then
        "$PROJECT_DIR/venv/bin/python" "$PROJECT_DIR/post_update.py"
    else
        python3 "$PROJECT_DIR/post_update.py"
    fi
else
    echo -e "${RED}Error: post_update.py not found! Update might be incomplete.${NC}"
    exit 1
fi
