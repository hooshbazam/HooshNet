import os
import subprocess
import sys
import time
import platform

# ANSI Colors for professional output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_step(message):
    print(f"{Colors.CYAN}[INFO] {message}{Colors.ENDC}")

def print_success(message):
    print(f"{Colors.GREEN}[SUCCESS] {message}{Colors.ENDC}")

def print_error(message):
    print(f"{Colors.FAIL}[ERROR] {message}{Colors.ENDC}")

def print_warning(message):
    print(f"{Colors.WARNING}[WARNING] {message}{Colors.ENDC}")

def run_command(command, cwd=None, shell=True):
    """Runs a shell command and returns the output."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=shell,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {command}\nError: {e.stderr.strip()}")
        return None

def main():
    print(f"\n{Colors.HEADER}{Colors.BOLD}=== Post-Update System Configuration ==={Colors.ENDC}")
    
    project_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Update Dependencies
    print_step("Updating Python dependencies...")
    venv_python = os.path.join(project_dir, "venv", "bin", "python")
    if not os.path.exists(venv_python):
        print_warning("Virtual environment not found at venv/bin/python. Trying global python3...")
        venv_python = "python3"
    
    # Install requirements
    req_file = os.path.join(project_dir, "requirements.txt")
    if os.path.exists(req_file):
        if run_command(f'"{venv_python}" -m pip install -r "{req_file}"'):
             print_success("Dependencies updated successfully.")
        else:
             print_error("Failed to update dependencies.")
    else:
        print_warning("requirements.txt not found. Skipping dependency update.")

    # 2. Fix Permissions
    print_step("Fixing file permissions and line endings...")
    # dos2unix for all .sh and .py files
    run_command(f'find "{project_dir}" -type f -name "*.py" -exec dos2unix {{}} + 2>/dev/null')
    run_command(f'find "{project_dir}" -type f -name "*.sh" -exec dos2unix {{}} + 2>/dev/null')
    
    # chmod +x for scripts
    scripts = ["installer.sh", "start.sh", "stop.sh", "update.sh"]
    for script in scripts:
        script_path = os.path.join(project_dir, script)
        if os.path.exists(script_path):
            run_command(f'chmod +x "{script_path}"')
    print_success("Permissions fixed.")

    # 3. Restart Services
    print_step("Restarting services...")
    services = ["vpn-bot", "vpn-webapp"]
    
    for service in services:
        print(f"Restarting {service}...", end=" ", flush=True)
        if run_command(f"systemctl restart {service}") is not None:
            print(f"{Colors.GREEN}OK{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}FAILED{Colors.ENDC}")

    # 4. Verification
    print_step("Verifying service status...")
    all_active = True
    for service in services:
        status = run_command(f"systemctl is-active {service}")
        if status == "active":
             print_success(f"Service {service} is active and running.")
        else:
             print_error(f"Service {service} is NOT active (Status: {status}).")
             all_active = False
    
    if all_active:
        print(f"\n{Colors.GREEN}{Colors.BOLD}=== Update Completed Successfully ==={Colors.ENDC}")
        print(f"{Colors.GREEN}The system is now running the latest version.{Colors.ENDC}\n")
    else:
        print(f"\n{Colors.FAIL}{Colors.BOLD}=== Update Completed with Errors ==={Colors.ENDC}")
        print(f"{Colors.FAIL}Some services failed to start. Please check logs: journalctl -u vpn-bot -n 50{Colors.ENDC}\n")

if __name__ == "__main__":
    # Ensure we are root
    if os.geteuid() != 0:
        print_error("This script must be run as root.")
        sys.exit(1)
    
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Operation cancelled by user.{Colors.ENDC}")
    except Exception as e:
        print(f"\n{Colors.FAIL}An unexpected error occurred: {e}{Colors.ENDC}")
