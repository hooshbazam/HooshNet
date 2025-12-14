import os
import subprocess
import sys
import datetime
import time

# Configuration
# You can hardcode your repository URL here to avoid typing it every time
# Example: GITHUB_REPO_URL = "https://github.com/username/repo.git"
GITHUB_REPO_URL = ""

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

def run_command(command, cwd=None):
    """Runs a shell command and returns the output."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        # Return None to indicate failure, but print stderr for debugging if needed
        # print_error(f"Command failed: {command}\n{e.stderr}")
        return None

def is_git_installed():
    return run_command("git --version") is not None

def is_git_repo():
    return os.path.isdir(".git")

def get_remote_url():
    return run_command("git remote get-url origin")

def main():
    print(f"{Colors.HEADER}{Colors.BOLD}=== Professional GitHub Project Updater ==={Colors.ENDC}")
    print(f"{Colors.HEADER}Starting update process at {datetime.datetime.now()}{Colors.ENDC}\n")

    # 1. Check Git Installation
    print_step("Checking Git installation...")
    if not is_git_installed():
        print_error("Git is not installed or not found in PATH. Please install Git first.")
        sys.exit(1)
    print_success("Git is installed.")

    # 2. Check/Initialize Repository
    if not is_git_repo():
        print_warning("No git repository found. Initializing new repository...")
        run_command("git init")
        # FORCE BRANCH TO MAIN
        run_command("git branch -M main")
        print_success("Initialized empty Git repository and set branch to 'main'.")
    else:
        print_step("Git repository already exists.")
        # Ensure we are on main or rename current to main if it is master
        current_branch = run_command("git branch --show-current")
        if current_branch == "master":
             print_step("Renaming 'master' branch to 'main'...")
             run_command("git branch -M main")

    # 3. Configure Remote
    current_remote = get_remote_url()
    target_repo = GITHUB_REPO_URL

    if not current_remote:
        print_warning("No remote 'origin' configured.")
        if not target_repo:
            try:
                target_repo = input(f"{Colors.BLUE}Please enter your GitHub Repository URL: {Colors.ENDC}").strip()
            except EOFError:
                 print_error("Could not read input. Please set GITHUB_REPO_URL in the script.")
                 sys.exit(1)
        
        if target_repo:
            run_command(f"git remote add origin {target_repo}")
            print_success(f"Remote 'origin' added: {target_repo}")
        else:
            print_error("No repository URL provided. Aborting.")
            sys.exit(1)
    else:
        print_step(f"Remote 'origin' is set to: {current_remote}")
        # Optional: Update remote if GITHUB_REPO_URL is set and different? 
        # For now, we assume existing remote is correct.

    # 4. Check status and Add Files
    print_step("Checking for file changes...")
    status = run_command("git status --porcelain")
    
    if not status:
        print_success("No changes detected. Project is already up to date locally.")
        # We might still want to push if local is ahead of remote, but 'git status' doesn't show that easily without fetch.
        # Let's try to push anyway to be safe, or just exit.
        # For an "updater", forcing a push check is good.
    else:
        print_step("Changes detected. Staging files...")
        run_command("git add .")
        print_success("All files staged.")

        # 5. Commit
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        commit_message = f"Auto-update: {timestamp}"
        print_step(f"Committing changes with message: '{commit_message}'...")
        run_command(f'git commit -m "{commit_message}"')
        print_success("Changes committed.")

    # 6. Push
    print_step("Pushing to GitHub...")
    
    # Check current branch name (usually main or master)
    branch = run_command("git branch --show-current")
    if not branch:
        branch = "main" # Default fallback
    
    push_result = run_command(f"git push -u origin {branch}")
    
    if push_result is not None:
        print_success("Successfully pushed to GitHub!")
        print(f"\n{Colors.GREEN}{Colors.BOLD}Project is now fully synchronized with GitHub.{Colors.ENDC}")
    else:
        print_error("Failed to push to GitHub.")
        print_warning("Common reasons:")
        print_warning("1. You haven't authenticated. Try running 'git push' manually once to sign in.")
        print_warning("2. The remote repository has changes you don't have (need 'git pull').")
        print_warning("3. The repository URL is incorrect.")
        
        # Try to give a hint about pulling
        print_step("Attempting to pull remote changes (rebase)...")
        pull_result = run_command(f"git pull origin {branch} --rebase")
        if pull_result is not None:
             print_success("Pulled remote changes. Retrying push...")
             push_result_retry = run_command(f"git push -u origin {branch}")
             if push_result_retry is not None:
                 print_success("Successfully pushed to GitHub after pulling!")
             else:
                 print_error("Still unable to push. Please check your git status manually.")
        else:
             print_error("Could not pull changes. You may have merge conflicts.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}Operation cancelled by user.{Colors.ENDC}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.FAIL}An unexpected error occurred: {e}{Colors.ENDC}")
        sys.exit(1)
