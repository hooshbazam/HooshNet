#!/bin/bash

# HooshNet Professional Manager
# Created by Antigravity

# ==========================================
#              CONFIGURATION
# ==========================================

# Colors & Formatting
BOLD='\033[1m'
DIM='\033[2m'
UNDERLINE='\033[4m'
BLINK='\033[5m'
REVERSE='\033[7m'

# Foreground Colors
BLACK='\033[30m'
RED='\033[31m'
GREEN='\033[32m'
YELLOW='\033[33m'
BLUE='\033[34m'
MAGENTA='\033[35m'
CYAN='\033[36m'
WHITE='\033[37m'
RESET='\033[0m'

# Background Colors
BG_BLUE='\033[44m'
BG_RED='\033[41m'
BG_GREEN='\033[42m'

# Icons
ICON_CHECK="✅"
ICON_ERROR="❌"
ICON_WARN="⚠️"
ICON_INFO="ℹ️"
ICON_ROCKET="🚀"
ICON_GEAR="⚙️"
ICON_DB="🗄️"
ICON_LOCK="🔒"
ICON_LOG="📝"
ICON_CHART="📊"
ICON_INSTALL="💾"
ICON_UPDATE="🔄"
ICON_TRASH="🗑️"
ICON_POWER="🔌"
ICON_STOP="🛑"
ICON_RESTART="♻️"
ICON_EXIT="🚪"

# Directory
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do # resolve $SOURCE until the file is no longer a symlink
  DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE" # if $SOURCE was a relative symlink, we need to resolve it relative to the path where the symlink file was located
done
PROJECT_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"

# Change to project directory to ensure docker compose finds the config
cd "$PROJECT_DIR"

# ==========================================
#              UI FUNCTIONS
# ==========================================

print_banner() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo "    __  __                 __    _   __     __ "
    echo "   / / / /___  ____  _____/ /_  / | / /__  / /_"
    echo "  / /_/ / __ \/ __ \/ ___/ __ \/  |/ / _ \/ __/"
    echo " / __  / /_/ / /_/ (__  ) / / / /|  /  __/ /_  "
    echo "/_/ /_/\____/\____/____/_/ /_/_/ |_/\___/\__/  "
    echo -e "${RESET}"
    echo -e "${BLUE}${BOLD}      » Professional VPN Management System «      ${RESET}"
    echo -e "${DIM}      --------------------------------------      ${RESET}"
    echo ""
}

print_header() {
    echo -e "${BG_BLUE}${WHITE}${BOLD} $1 ${RESET}"
    echo ""
}

print_success() {
    echo -e "${GREEN}${ICON_CHECK} $1${RESET}"
}

print_error() {
    echo -e "${RED}${ICON_ERROR} $1${RESET}"
}

print_warning() {
    echo -e "${YELLOW}${ICON_WARN} $1${RESET}"
}

print_info() {
    echo -e "${CYAN}${ICON_INFO} $1${RESET}"
}

print_step() {
    echo -e "${MAGENTA}${BOLD}» $1${RESET}"
}

wait_enter() {
    echo ""
    echo -e "${DIM}Press Enter to continue...${RESET}"
    read -r
}

# ==========================================
#              CORE FUNCTIONS
# ==========================================

check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed."
        print_info "Please run the installation option first."
        return 1
    fi
    return 0
}

install_docker() {
    print_step "Installing Docker Engine..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    print_success "Docker installed successfully."
}

install_shortcut() {
    print_step "Creating 'hooshnet' global command..."
    chmod +x "$PROJECT_DIR/manager.sh"
    ln -sf "$PROJECT_DIR/manager.sh" /usr/local/bin/hooshnet
    print_success "Shortcut created! Type '${BOLD}hooshnet${RESET}${GREEN}' anywhere to open this manager."
}

check_ports() {
    print_step "Checking ports..."
    # Check port 80
    if lsof -Pi :80 -sTCP:LISTEN -t >/dev/null ; then
        print_warning "Port 80 is already in use!"
        PID=$(lsof -Pi :80 -sTCP:LISTEN -t)
        PROCESS_NAME=$(ps -p $PID -o comm=)
        echo -e "${RED}Process '$PROCESS_NAME' (PID: $PID) is using port 80.${RESET}"
        read -p "Do you want to stop this process to free up the port? (y/n): " confirm
        if [[ "$confirm" == "y" ]]; then
            kill -9 $PID
            print_success "Process killed. Port 80 is now free."
        else
            print_error "Cannot start services while port 80 is in use."
            return 1
        fi
    fi
    
    # Check port 443
    if lsof -Pi :443 -sTCP:LISTEN -t >/dev/null ; then
        print_warning "Port 443 is already in use!"
        PID=$(lsof -Pi :443 -sTCP:LISTEN -t)
        PROCESS_NAME=$(ps -p $PID -o comm=)
        echo -e "${RED}Process '$PROCESS_NAME' (PID: $PID) is using port 443.${RESET}"
        read -p "Do you want to stop this process to free up the port? (y/n): " confirm
        if [[ "$confirm" == "y" ]]; then
            kill -9 $PID
            print_success "Process killed. Port 443 is now free."
        else
            print_error "Cannot start services while port 443 is in use."
            return 1
        fi
    fi
    return 0
}

create_config() {
    print_header "CONFIGURATION SETUP"
    echo -e "${CYAN}Please enter the following configuration details:${RESET}"
    echo ""

    # Required Fields
    while [[ -z "$BOT_TOKEN" ]]; do
        read -p "Enter Bot Token (Required): " BOT_TOKEN
    done

    while [[ -z "$ADMIN_ID" ]]; do
        read -p "Enter Admin ID (Numeric, Required): " ADMIN_ID
        if ! [[ "$ADMIN_ID" =~ ^[0-9]+$ ]]; then
            print_error "Admin ID must be a number."
            ADMIN_ID=""
        fi
    done

    read -p "Enter WebApp URL (Default: https://your-domain.com): " WEBAPP_URL
    WEBAPP_URL=${WEBAPP_URL:-https://your-domain.com}

    # Optional Fields
    read -p "Enter Reports Group ID (Optional): " REPORTS_CHANNEL_ID
    REPORTS_CHANNEL_ID=${REPORTS_CHANNEL_ID:-0}

    read -p "Enter Receipts Channel ID (Optional): " RECEIPTS_CHANNEL_ID
    RECEIPTS_CHANNEL_ID=${RECEIPTS_CHANNEL_ID:-0}

    # Database Passwords
    read -p "Enter Database Password (Leave empty to auto-generate): " DB_PASSWORD
    if [[ -z "$DB_PASSWORD" ]]; then
        DB_PASSWORD=$(openssl rand -base64 16 2>/dev/null || date +%s%N | sha256sum | base64 | head -c 16)
        print_info "Generated Database Password: $DB_PASSWORD"
    fi

    read -p "Enter Database Root Password (Leave empty to auto-generate): " DB_ROOT_PASSWORD
    if [[ -z "$DB_ROOT_PASSWORD" ]]; then
        DB_ROOT_PASSWORD=$(openssl rand -base64 16 2>/dev/null || date +%s%N | sha256sum | base64 | head -c 16)
        print_info "Generated Database Root Password: $DB_ROOT_PASSWORD"
    fi

    # Write to .env
    cat > .env <<EOL
# Bot Configuration
BOT_TOKEN=$BOT_TOKEN
ADMIN_ID=$ADMIN_ID
BOT_USERNAME=
REPORTS_CHANNEL_ID=$REPORTS_CHANNEL_ID
RECEIPTS_CHANNEL_ID=$RECEIPTS_CHANNEL_ID

# WebApp Configuration
WEBAPP_URL=$WEBAPP_URL
BOT_WEBAPP_URL=$WEBAPP_URL

# Database Configuration
MYSQL_HOST=vpn-db
MYSQL_PORT=3306
MYSQL_USER=vpn_bot
MYSQL_PASSWORD=$DB_PASSWORD
MYSQL_DATABASE=vpn_bot
DB_PASSWORD=$DB_PASSWORD
DB_ROOT_PASSWORD=$DB_ROOT_PASSWORD
EOL

    print_success "Configuration saved to .env"
    wait_enter
}

install_bot() {
    print_header "SYSTEM INSTALLATION"
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        install_docker
    fi
    
    # Check .env
    if [ ! -f .env ]; then
        print_warning "Configuration file (.env) not found."
        create_config
    else
        print_info "Configuration file (.env) found."
        read -p "Do you want to reconfigure? (y/n): " reconfigure
        if [[ "$reconfigure" == "y" ]]; then
            create_config
        fi
    fi
    
    print_step "Building and Starting Containers..."
    chmod +x entrypoint.sh
    docker compose up -d --build
    
    install_shortcut
    
    echo ""
    print_success "Installation Completed Successfully!"
    
    if [ -f .env ]; then
        WEBAPP_URL=$(grep WEBAPP_URL .env | cut -d'=' -f2 | sed 's/https:\/\///')
        echo -e "${CYAN}${BOLD}🌐 Web Panel:${RESET} https://$WEBAPP_URL"
    fi
    wait_enter
}

update_bot() {
    print_header "SYSTEM UPDATE"
    print_step "Pulling latest changes..."
    git pull
    print_step "Rebuilding containers..."
    chmod +x entrypoint.sh
    
    # Force recreation of containers to ensure new config is picked up
    docker compose down
    docker compose up -d --build --force-recreate
    
    print_success "System updated successfully."
    wait_enter
}

uninstall_bot() {
    print_header "UNINSTALLATION"
    echo -e "${RED}${BOLD}WARNING: This will remove all containers and data volumes!${RESET}"
    read -p "Are you sure you want to proceed? (y/n): " confirm
    if [[ "$confirm" == "y" ]]; then
        print_step "Stopping and removing containers..."
        docker compose down -v
        print_success "Uninstalled successfully."
    else
        print_warning "Operation cancelled."
    fi
    wait_enter
}

# ==========================================
#           SERVICE MANAGEMENT
# ==========================================

start_services() {
    check_ports || return
    print_step "Starting Services..."
    chmod +x entrypoint.sh
    docker compose up -d
    print_success "All services started."
    wait_enter
}

stop_services() {
    print_step "Stopping Services..."
    docker compose stop
    print_success "All services stopped."
    wait_enter
}

restart_services() {
    print_step "Restarting Services..."
    docker compose down
    check_ports || return
    chmod +x entrypoint.sh
    docker compose up -d
    print_success "All services restarted."
    wait_enter
}

service_status() {
    print_header "SYSTEM STATUS"
    echo -e "${YELLOW}${BOLD}Docker Containers:${RESET}"
    docker compose ps
    echo ""
    echo -e "${YELLOW}${BOLD}Resource Usage:${RESET}"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
    wait_enter
}

# ==========================================
#        CONFIGURATION & DATABASE
# ==========================================

edit_config() {
    if [ -f .env ]; then
        nano .env
    else
        print_error ".env file not found!"
    fi
}

backup_database() {
    print_step "Creating Database Backup..."
    mkdir -p database_backups
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    
    if docker compose exec vpn-db mysqldump -u vpn_bot -p$(grep MYSQL_PASSWORD .env | cut -d'=' -f2) vpn_bot > "database_backups/backup_$TIMESTAMP.sql"; then
        print_success "Backup saved: database_backups/backup_$TIMESTAMP.sql"
    else
        print_error "Backup failed! Check database connection."
    fi
    wait_enter
}

restore_database() {
    print_header "RESTORE DATABASE"
    echo -e "${YELLOW}Available Backups:${RESET}"
    ls -1 database_backups/*.sql 2>/dev/null | xargs -n 1 basename
    echo ""
    read -p "Enter backup filename (e.g., backup_2024...sql): " BACKUP_NAME
    BACKUP_FILE="database_backups/$BACKUP_NAME"
    
    if [ -f "$BACKUP_FILE" ]; then
        echo -e "${RED}${BOLD}WARNING: This will overwrite the current database!${RESET}"
        read -p "Are you sure? (y/n): " confirm
        if [[ "$confirm" == "y" ]]; then
            print_step "Restoring database..."
            cat "$BACKUP_FILE" | docker compose exec -T vpn-db mysql -u vpn_bot -p$(grep MYSQL_PASSWORD .env | cut -d'=' -f2) vpn_bot
            print_success "Database restored successfully."
        else
            print_warning "Operation cancelled."
        fi
    else
        print_error "File not found!"
    fi
    wait_enter
}

install_ssl() {
    print_step "Installing SSL Certificate..."
    read -p "Enter Domain Name (e.g., example.com): " DOMAIN
    read -p "Enter Email Address (Optional): " EMAIL
    
    if [ -z "$DOMAIN" ]; then
        print_error "Domain name is required!"
        return
    fi
    
    print_info "Generating certificate for $DOMAIN..."
    
    # Copy script to container if not already there (it's mounted via volume usually, but let's be safe)
    # Actually, .:/app volume mount handles it.
    
    docker compose exec vpn-bot chmod +x /app/generate_ssl.sh
    docker compose exec vpn-bot /app/generate_ssl.sh "$DOMAIN" "$EMAIL"
    
    if [ $? -eq 0 ]; then
        print_success "SSL Certificate installed successfully!"
    else
        print_error "Failed to install SSL Certificate."
    fi
    wait_enter
}

renew_ssl() {
    print_step "Renewing SSL Certificate..."
    docker compose exec vpn-bot certbot renew
    docker compose exec vpn-bot supervisorctl restart nginx
    print_success "SSL Renewed."
    wait_enter
}

# ==========================================
#           TOOLS & UTILITIES
# ==========================================

view_logs() {
    print_header "LIVE LOGS"
    echo -e "${YELLOW}1.${RESET} All Logs"
    echo -e "${YELLOW}2.${RESET} Bot Logs"
    echo -e "${YELLOW}3.${RESET} WebApp Logs"
    echo -e "${YELLOW}4.${RESET} Database Logs"
    echo ""
    read -p "Select log type [1-4]: " log_choice

    print_info "Press Ctrl+C to exit log view"
    sleep 1

    case $log_choice in
        2) docker compose logs -f --tail=100 vpn-bot | grep "vpn-bot" ;;
        3) docker compose logs -f --tail=100 vpn-bot | grep "vpn-webapp" ;;
        4) docker compose logs -f --tail=100 vpn-db ;;
        *) docker compose logs -f --tail=100 ;;
    esac
}

clear_logs() {
    print_step "Clearing Application Logs..."
    rm -f logs/*.log
    print_success "Logs cleared."
    wait_enter
}

system_monitoring() {
    if command -v htop &> /dev/null; then
        htop
    else
        top
    fi
}

enable_bbr() {
    print_step "Enabling BBR Congestion Control..."
    if grep -q "net.core.default_qdisc=fq" /etc/sysctl.conf; then
        print_info "BBR is already enabled."
    else
        echo "net.core.default_qdisc=fq" >> /etc/sysctl.conf
        echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.conf
        sysctl -p
        print_success "BBR Enabled successfully."
    fi
    wait_enter
}

run_speedtest() {
    print_header "NETWORK SPEEDTEST"
    if ! command -v speedtest-cli &> /dev/null; then
        print_step "Installing speedtest-cli..."
        apt-get update && apt-get install -y speedtest-cli
    fi
    speedtest-cli
    wait_enter
}

# ==========================================
#               MAIN LOGIC
# ==========================================

# Handle command line arguments
if [[ "$1" == "install" ]]; then
    install_bot
    exit 0
elif [[ "$1" == "update" ]]; then
    update_bot
    exit 0
elif [[ "$1" == "restart" ]]; then
    restart_services
    exit 0
fi

# Main Menu Loop
while true; do
    print_banner
    
    echo -e " ${CYAN}${BOLD}INSTALLATION${RESET}"
    echo -e " ${GREEN}1.${RESET} ${ICON_INSTALL} Install / Reinstall"
    echo -e " ${GREEN}2.${RESET} ${ICON_UPDATE} Update System"
    echo -e " ${GREEN}3.${RESET} ${ICON_TRASH} Uninstall"
    echo ""
    echo -e " ${CYAN}${BOLD}SERVICE CONTROL${RESET}"
    echo -e " ${GREEN}4.${RESET} ${ICON_ROCKET} Start Services"
    echo -e " ${GREEN}5.${RESET} ${ICON_STOP} Stop Services"
    echo -e " ${GREEN}6.${RESET} ${ICON_RESTART} Restart Services"
    echo -e " ${GREEN}7.${RESET} ${ICON_CHART} Service Status"
    echo ""
    echo -e " ${CYAN}${BOLD}CONFIGURATION${RESET}"
    echo -e " ${GREEN}8.${RESET} ${ICON_GEAR} Edit Config (.env)"
    echo -e " ${GREEN}9.${RESET} ${ICON_DB} Backup Database"
    echo -e " ${GREEN}10.${RESET} ${ICON_DB} Restore Database"
    echo -e " ${GREEN}11.${RESET} ${ICON_LOCK} Install SSL Certificate"
    echo -e " ${GREEN}12.${RESET} ${ICON_LOCK} Renew SSL"
    echo ""
    echo -e " ${CYAN}${BOLD}UTILITIES${RESET}"
    echo -e " ${GREEN}13.${RESET} ${ICON_LOG} View Logs"
    echo -e " ${GREEN}14.${RESET} ${ICON_TRASH} Clear Logs"
    echo -e " ${GREEN}15.${RESET} ${ICON_CHART} System Monitor"
    echo -e " ${GREEN}16.${RESET} ${ICON_ROCKET} Enable BBR"
    echo -e " ${GREEN}17.${RESET} ${ICON_ROCKET} Speedtest"
    echo -e " ${GREEN}18.${RESET} ${ICON_INSTALL} Install 'hooshnet' Command"
    echo ""
    echo -e " ${RED}0.${RESET} ${ICON_EXIT} Exit"
    echo ""
    echo -e "${DIM}──────────────────────────────────────${RESET}"
    read -p " Enter your choice [0-17]: " choice
    
    case $choice in
        1) install_bot ;;
        2) update_bot ;;
        3) uninstall_bot ;;
        4) start_services ;;
        5) stop_services ;;
        6) restart_services ;;
        7) service_status ;;
        8) edit_config ;;
        9) backup_database ;;
        10) restore_database ;;
        11) install_ssl ;;
        12) renew_ssl ;;
        13) view_logs ;;
        14) clear_logs ;;
        15) system_monitoring ;;
        16) enable_bbr ;;
        17) run_speedtest ;;
        18) install_shortcut ;;
        0) clear; exit 0 ;;
        *) print_error "Invalid choice!"; sleep 1 ;;
    esac
done
