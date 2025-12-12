#!/bin/bash
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Stopping VPN Bot and Web Application...${NC}"
sudo systemctl stop vpn-bot
sudo systemctl stop vpn-webapp
echo -e "${RED}Services stopped.${NC}"
