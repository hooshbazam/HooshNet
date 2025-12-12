#!/bin/bash
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}Starting VPN Bot and Web Application...${NC}"
sudo systemctl start vpn-bot
sudo systemctl start vpn-webapp
echo -e "${GREEN}Services started successfully!${NC}"
echo -e "Check status with: sudo systemctl status vpn-bot vpn-webapp"
