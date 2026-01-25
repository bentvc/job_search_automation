#!/usr/bin/env python3
"""
Standalone script to create a codebase export and generate SCP command to transfer to Windows laptop.
Usage: python create_export.py [--output PATH] [--local-path PATH] [--auto-scp]
"""
import argparse
import sys
import os
import platform
import subprocess
import getpass
import socket
from export_utility import (
    create_codebase_export,
    create_incremental_export,
    get_export_size_mb,
    get_last_export_timestamp,
)
from pathlib import Path
from datetime import datetime


def copy_to_clipboard(text: str):
    """Copy text to clipboard (cross-platform)."""
    try:
        system = platform.system()
        if system == 'Windows':
            subprocess.run(['clip'], input=text.encode(), check=True)
        elif system == 'Darwin':  # macOS
            subprocess.run(['pbcopy'], input=text.encode(), check=True)
        else:  # Linux
            subprocess.run(['xclip', '-selection', 'clipboard'], input=text.encode(), check=True)
        return True
    except Exception:
        return False


def get_ssh_connection_info():
    """Extract SSH connection information from environment variables."""
    ssh_client = os.environ.get('SSH_CLIENT', '')
    ssh_connection = os.environ.get('SSH_CONNECTION', '')
    
    # Get Windows client IP (where SSH session originates)
    windows_ip = None
    # Parse SSH_CONNECTION format: "client_ip client_port server_ip server_port"
    if ssh_connection:
        parts = ssh_connection.split()
        if len(parts) >= 1:
            windows_ip = parts[0]  # First part is the client (Windows) IP
    
    # Fallback to SSH_CLIENT format: "client_ip client_port server_port"
    if not windows_ip and ssh_client:
        parts = ssh_client.split()
        if len(parts) >= 1:
            windows_ip = parts[0]
    
    # Get remote hostname/IP - this is the server we're SSH'd into
    remote_host = None
    try:
        # Try to get hostname
        remote_host = os.uname().nodename if hasattr(os, 'uname') else None
        # Also try to get IP from hostname
        if remote_host:
            try:
                remote_ip = socket.gethostbyname(remote_host)
                # Prefer IP if it's not localhost
                if remote_ip and remote_ip != '127.0.0.1':
                    remote_host = remote_ip
            except:
                pass
    except:
        pass
    
    # Parse SSH_CONNECTION format: "client_ip client_port server_ip server_port"
    # The server_ip is what we need - that's the remote server's IP
    if ssh_connection:
        parts = ssh_connection.split()
        if len(parts) >= 3:
            server_ip = parts[2]  # This is the remote server's IP
            if server_ip and server_ip != '127.0.0.1':
                remote_host = server_ip
    
    result = {
        'remote_user': getpass.getuser(),
        'remote_host': remote_host
    }
    
    if windows_ip:
        result['windows_ip'] = windows_ip
    
    return result if remote_host else None


def generate_scp_command(remote_file_path, local_path=None, ssh_info=None, windows_username='chris'):
    """Generate SCP command to copy file from remote to local Windows machine."""
    if not ssh_info:
        ssh_info = get_ssh_connection_info()
    
    if not ssh_info:
        return None
    
    remote_user = ssh_info['remote_user']
    remote_host = ssh_info.get('remote_host', 'remote')
    filename = os.path.basename(remote_file_path)
    
    # Default to Windows Downloads folder (use explicit path; %USERPROFILE% fails in scp)
    if local_path is None:
        local_path = f'C:\\Users\\{windows_username}\\Downloads\\{filename}'
    elif not os.path.isabs(local_path) and not local_path.startswith('C:'):
        local_path = f'C:\\Users\\{windows_username}\\Downloads\\{local_path}'
    
    scp_cmd = f'scp {remote_user}@{remote_host}:{remote_file_path} "{local_path}"'
    return scp_cmd, windows_username


def execute_scp_on_windows(scp_command, windows_ip, windows_username='chris', timeout=30):
    """Execute SCP command on Windows machine via SSH."""
    try:
        # Escape the command for Windows CMD
        # The SCP command needs to be executed in a shell on Windows
        # Use cmd.exe /c to execute the command
        ssh_command = [
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'ConnectTimeout=10',
            f'{windows_username}@{windows_ip}',
            f'cmd.exe /c "{scp_command}"'
        ]
        
        print(f"   Executing: ssh {windows_username}@{windows_ip} 'cmd.exe /c \"{scp_command}\"'")
        
        result = subprocess.run(
            ssh_command,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode == 0:
            if result.stdout:
                print(f"   Output: {result.stdout.strip()}")
            return True
        else:
            print(f"   Error: {result.stderr.strip() if result.stderr else 'Unknown error'}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"   ⏱️  Command timed out after {timeout} seconds")
        return False
    except FileNotFoundError:
        print("   ⚠️  SSH command not found. Is OpenSSH installed?")
        return False
    except Exception as e:
        print(f"   ⚠️  Error executing SSH: {e}")
        return False


def create_scp_script(scp_command, script_path=None, windows_username='chris'):
    """Create a batch script (.bat) for Windows."""
    if script_path is None:
        script_path = 'download_export.bat'
    
    dest_path = scp_command.split()[-1].strip('"')
    downloads = f'C:\\Users\\{windows_username}\\Downloads'
    
    script_content = f"""@echo off
REM Auto-generated SCP download script
REM Run this from your Windows laptop to download the export file

echo ========================================
echo Transferring export file to Windows...
echo ========================================
echo.
echo Command: {scp_command}
echo.

{scp_command}

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo ✅ File downloaded successfully!
    echo ========================================
    echo.
    echo 📁 File saved to: {dest_path}
    echo.
    echo Opening Downloads folder...
    start "" "{downloads}"
) else (
    echo.
    echo ========================================
    echo ❌ Download failed
    echo ========================================
    echo.
    echo Please check:
    echo   1. You can SSH into the remote server
    echo   2. The remote file exists
    echo   3. You have write permissions to Downloads folder
    echo.
)

pause
"""
    
    try:
        with open(script_path, 'w') as f:
            f.write(script_content)
        os.chmod(script_path, 0o755)
        return script_path
    except Exception as e:
        print(f"⚠️  Could not create script file: {e}")
        return None


def run_export_and_transfer(
    incremental: bool = False,
    auto_scp: bool = True,
    windows_username: str = "chris",
    local_path: str | None = None,
):
    """
    Create export (full or incremental) and attempt SCP transfer to Windows.
    For use by Streamlit UI or other callers.
    Returns dict: zip_path, size_mb, scp_command, scp_success, error, n_files (incremental only).
    """
    out = {
        "zip_path": None,
        "size_mb": 0.0,
        "scp_command": None,
        "scp_success": False,
        "error": None,
        "n_files": None,
    }
    try:
        if incremental:
            zip_path, n_files = create_incremental_export()
            out["n_files"] = n_files
            if zip_path is None:
                if get_last_export_timestamp() is None:
                    out["error"] = "No previous full export. Run a full export first."
                else:
                    out["error"] = "No changes since last export."
                return out
        else:
            zip_path = create_codebase_export()
            n_files = None
        out["zip_path"] = zip_path
        out["size_mb"] = get_export_size_mb(zip_path)
        ssh_info = get_ssh_connection_info()
        if not ssh_info:
            out["error"] = "Could not detect SSH connection info."
            return out
        scp_cmd, _ = generate_scp_command(zip_path, local_path, ssh_info, windows_username=windows_username)
        if not scp_cmd:
            out["error"] = "Could not generate SCP command."
            return out
        out["scp_command"] = scp_cmd
        if not auto_scp:
            return out
        windows_ip = ssh_info.get("windows_ip")
        if not windows_ip:
            out["error"] = "Could not detect Windows IP."
            return out
        out["scp_success"] = execute_scp_on_windows(scp_cmd, windows_ip, windows_username=windows_username)
        return out
    except Exception as e:
        out["error"] = str(e)
        return out


def main():
    parser = argparse.ArgumentParser(
        description='Create a codebase export and generate SCP command to transfer to Windows laptop',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python create_export.py                    # Full export, auto SCP to Windows
  python create_export.py --incremental      # Only changes since last full export
  python create_export.py --local-path "C:\\Users\\chris\\Documents"
  python create_export.py --no-auto-scp      # Skip automatic download, just show command
        """
    )
    parser.add_argument('--output', type=str, default=None,
                       help='Output path for the zip file on remote server (default: temp directory)')
    parser.add_argument('--local-path', type=str, default=None,
                       help='Destination path on Windows laptop (default: Downloads folder)')
    parser.add_argument('--no-auto-scp', action='store_true',
                       help='Do NOT attempt automatic download (downloads automatically by default)')
    parser.add_argument('--copy-command', action='store_true',
                       help='Copy SCP command to clipboard')
    parser.add_argument('--no-create-script', action='store_false', dest='create_script',
                       help='Do NOT create a .bat script file (script is created by default)')
    parser.add_argument('--incremental', action='store_true',
                       help='Export only files changed since last full export')
    parser.set_defaults(create_script=True)
    
    args = parser.parse_args()
    windows_username = 'chris'
    
    if args.incremental:
        print("🔄 Creating incremental export (changes since last full export)...")
    else:
        print("🚀 Creating full codebase export...")
    try:
        if args.incremental:
            zip_path, n_files = create_incremental_export(args.output)
            if zip_path is None:
                if get_last_export_timestamp() is None:
                    print("❌ No previous full export found. Run a full export first.")
                else:
                    print("✅ No changes since last export — nothing to include.")
                return 0 if get_last_export_timestamp() is not None else 1
            zip_size_mb = get_export_size_mb(zip_path)
            filename = os.path.basename(zip_path)
            print(f"   Included {n_files} changed file(s).")
        else:
            zip_path = create_codebase_export(args.output)
            zip_size_mb = get_export_size_mb(zip_path)
            filename = os.path.basename(zip_path)
        
        # Print results prominently
        print("\n" + "="*70)
        print("✅ EXPORT CREATED SUCCESSFULLY!")
        print("="*70)
        print(f"\n📁 Remote File: {zip_path}")
        print(f"📊 Size: {zip_size_mb:.2f} MB")
        print("="*70 + "\n")
        
        # Get SSH connection info
        ssh_info = get_ssh_connection_info()
        
        if ssh_info:
            scp_command, _ = generate_scp_command(zip_path, args.local_path, ssh_info, windows_username=windows_username)
            
            if scp_command:
                print("📥 TO DOWNLOAD TO YOUR WINDOWS LAPTOP:")
                print("="*70)
                print("\n🔧 Run this command from your Windows PowerShell or CMD:")
                print(f"\n   {scp_command}\n")
                print("="*70)
                
                # Copy command to clipboard if requested
                if args.copy_command:
                    if copy_to_clipboard(scp_command):
                        print("\n✅ SCP command copied to clipboard!")
                    else:
                        print("\n⚠️  Could not copy command to clipboard")
                
                # Create batch script for Windows
                if args.create_script:
                    script_path = create_scp_script(scp_command, windows_username=windows_username)
                    if script_path:
                        print(f"\n📝 Created Windows batch script: {script_path}")
                        print(f"   Transfer this script to your Windows laptop and run it")
                        print(f"   Or copy the SCP command above and run it manually")
                
                # Try auto-SCP - execute SCP command on Windows via SSH
                if not args.no_auto_scp:  # Auto-SCP by default
                    windows_ip = ssh_info.get('windows_ip')
                    if windows_ip:
                        print(f"\n🔄 Attempting automatic download to Windows ({windows_ip})...")
                        success = execute_scp_on_windows(scp_command, windows_ip, windows_username=windows_username)
                        if success:
                            print("✅ File successfully downloaded to Windows Downloads folder!")
                        else:
                            print("⚠️  Automatic download failed. Please run the SCP command manually from Windows.")
                    else:
                        print("⚠️  Could not detect Windows IP. Please run the SCP command manually.")
            else:
                print("⚠️  Could not generate SCP command. SSH connection info not available.")
                print(f"   File location: {zip_path}")
                print(f"   You can manually copy this file using SCP or SFTP")
        else:
            print("⚠️  Could not detect SSH connection information.")
            print(f"   File created at: {zip_path}")
            print(f"   Please use SCP manually to transfer the file:")
            print(f"   scp {zip_path} your-windows-user@your-windows-ip:/path/to/destination/")
        
        return 0
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        return 1
    except Exception as e:
        print(f"\n❌ Error creating export: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
