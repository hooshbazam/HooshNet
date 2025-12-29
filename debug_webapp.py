#!/usr/bin/env python3
"""
Debug script to test webapp import and identify issues
Run this inside the Docker container to debug startup problems
"""

import sys
import os
import traceback

def test_imports():
    """Test all required imports"""
    print("=" * 60)
    print("Testing imports...")
    print("=" * 60)
    
    imports_to_test = [
        ("os", "os"),
        ("json", "json"),
        ("hashlib", "hashlib"),
        ("hmac", "hmac"),
        ("logging", "logging"),
        ("threading", "threading"),
        ("flask", "flask"),
        ("flask_cors", "flask_cors"),
        ("mysql.connector", "mysql.connector"),
        ("dotenv", "dotenv"),
        ("httpx", "httpx"),
        ("jdatetime", "jdatetime"),
        ("qrcode", "qrcode"),
        ("PIL", "PIL"),
        ("psutil", "psutil"),
    ]
    
    failed = []
    for name, module in imports_to_test:
        try:
            __import__(module)
            print(f"  ✓ {name}")
        except ImportError as e:
            print(f"  ✗ {name}: {e}")
            failed.append(name)
    
    if failed:
        print(f"\n❌ Failed imports: {', '.join(failed)}")
        return False
    else:
        print("\n✓ All imports successful!")
        return True

def test_env_vars():
    """Test required environment variables"""
    print("\n" + "=" * 60)
    print("Testing environment variables...")
    print("=" * 60)
    
    required_vars = [
        "BOT_TOKEN",
        "ADMIN_ID",
        "MYSQL_HOST",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DATABASE",
    ]
    
    missing = []
    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if "PASSWORD" in var or "TOKEN" in var:
                masked = value[:4] + "****" if len(value) > 4 else "****"
            else:
                masked = value
            print(f"  ✓ {var}: {masked}")
        else:
            print(f"  ✗ {var}: NOT SET")
            missing.append(var)
    
    if missing:
        print(f"\n❌ Missing environment variables: {', '.join(missing)}")
        return False
    else:
        print("\n✓ All environment variables set!")
        return True

def test_database_connection():
    """Test database connection"""
    print("\n" + "=" * 60)
    print("Testing database connection...")
    print("=" * 60)
    
    try:
        import mysql.connector
        from mysql.connector import Error
        
        conn = mysql.connector.connect(
            host=os.getenv('MYSQL_HOST', 'localhost'),
            user=os.getenv('MYSQL_USER', 'root'),
            password=os.getenv('MYSQL_PASSWORD', ''),
            database=os.getenv('MYSQL_DATABASE', 'vpn_bot'),
            port=int(os.getenv('MYSQL_PORT', 3306))
        )
        
        if conn.is_connected():
            print(f"  ✓ Connected to MySQL server")
            db_info = conn.get_server_info()
            print(f"  ✓ Server version: {db_info}")
            conn.close()
            return True
    except Error as e:
        print(f"  ✗ Database connection failed: {e}")
        return False

def test_webapp_import():
    """Test webapp import"""
    print("\n" + "=" * 60)
    print("Testing webapp import...")
    print("=" * 60)
    
    try:
        # First test config.py
        print("  Testing config.py...")
        import config
        print("  ✓ config.py imported")
        
        # Then test webapp
        print("  Testing webapp.py...")
        import webapp
        print("  ✓ webapp.py imported")
        print(f"  ✓ Flask app: {webapp.app}")
        return True
    except Exception as e:
        print(f"\n❌ Webapp import failed!")
        print(f"Error: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        return False

def test_processes():
    """Test if required processes are running"""
    print("\n" + "=" * 60)
    print("Testing running processes...")
    print("=" * 60)
    
    required_procs = ['nginx', 'gunicorn', 'supervisord']
    found_procs = {p: False for p in required_procs}
    
    try:
        import psutil
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                name = proc.info['name']
                cmdline = proc.info['cmdline'] or []
                cmdline_str = ' '.join(cmdline)
                
                if 'nginx' in name:
                    found_procs['nginx'] = True
                if 'gunicorn' in name or 'gunicorn' in cmdline_str:
                    found_procs['gunicorn'] = True
                if 'supervisord' in name or 'supervisord' in cmdline_str:
                    found_procs['supervisord'] = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        for proc, found in found_procs.items():
            if found:
                print(f"  ✓ {proc} is running")
            else:
                print(f"  ✗ {proc} is NOT running")
                
        if all(found_procs.values()):
            return True
        else:
            return False
            
    except ImportError:
        print("  ⚠ psutil not installed, skipping process check")
        return True
    except Exception as e:
        print(f"  ✗ Error checking processes: {e}")
        return False

def main():
    print("\n")
    print("=" * 60)
    print("    VPN Bot Webapp Debug Tool")
    print("=" * 60)
    
    results = {
        "imports": test_imports(),
        "env_vars": test_env_vars(),
        "database": test_database_connection(),
        "webapp": test_webapp_import(),
        "processes": test_processes(),
    }
    
    print("\n" + "=" * 60)
    print("    Summary")
    print("=" * 60)
    
    all_passed = True
    for test, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {test}: {status}")
        if not passed:
            all_passed = False
    
    print("\n")
    if all_passed:
        print("✓ All tests passed! Webapp should work correctly.")
        return 0
    else:
        print("❌ Some tests failed. Please fix the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
