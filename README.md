# Professional VPN Bot & Web App

A powerful, secure, and professional VPN management system with a Telegram Bot and Web Application.

## Features
- **Telegram Bot**: Full management via Telegram.
- **Web Application**: Beautiful user dashboard.
- **Secure**: Built with security best practices.
- **Automated**: Auto-setup script for Ubuntu.
- **SSL**: Automatic SSL configuration with Let's Encrypt.

## Installation

1. **Upload** the files to your Ubuntu server (e.g., via SFTP).
2. **Make the installer executable**:
   ```bash
   chmod +x installer.sh
   ```
3. **Run the installer** (as root):
   ```bash
   sudo ./installer.sh
   ```
4. **Follow the on-screen prompts**. You will need:
   - Bot Token (from @BotFather)
   - Admin Telegram ID
   - Domain Name (pointed to your server IP)
   - Starsefar License Key

## Management

### Start Services
To start both the Bot and Web App:
```bash
./start.sh
```

### Stop Services
To stop both the Bot and Web App:
```bash
./stop.sh
```

### Check Status
To check the status of the services:
```bash
sudo systemctl status vpn-bot vpn-webapp
```

## Requirements
- Ubuntu 20.04 or higher
- Root access
- A domain name pointed to your server IP
