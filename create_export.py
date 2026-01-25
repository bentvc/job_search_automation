#!/usr/bin/env python3
"""
Standalone script to create a codebase summary and generate SCP command to transfer to Windows laptop.
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
    create_codebase_summary,
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
    if ssh_connection:
        parts = ssh_connection.split()
        if len(parts) >= 1:
            windows_ip = parts[0]
    
    if not windows_ip and ssh_client:
        parts = ssh_client.split()
        if len(parts) >= 1:
            windows_ip = parts[0]
    
    remote_host = None
    try:
        remote_host = os.uname().nodename if hasattr(os, 'uname') else None
        if remote_host:
            try:
                remote_ip = socket.gethostbyname(remote_host)
                if remote_ip and remote_ip != '127.0.0.1':
                    remote_host = remote_ip
            except:
                pass
    except:
        pass
    
    if ssh_connection:
        parts = ssh_connection.split()
        if len(parts) >= 3:
            server_ip = parts[2]
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
    
    if local_path is None:
        local_path = f'C:\\Users\\{windows_username}\\Downloads\\{filename}'
    elif not os.path.isabs(local_path) and not local_path.startswith('C:'):
        local_path = f'C:\\Users\\{windows_username}\\Downloads\\{local_path}'
    
    scp_cmd = f'scp {remote_user}@{remote_host}:{remote_file_path} "{local_path}"'
    return scp_cmd, windows_username


def execute_scp_on_windows(scp_command, windows_ip, windows_username='chris', timeout=30):
    """Execute SCP command on Windows machine via SSH."""
    try:
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
            return True
        else:
            print(f"   Error: {result.stderr.strip() if result.stderr else 'Unknown error'}")
            return False
            
    except Exception as e:
        print(f"   ⚠️  Error executing SSH: {e}")
        return False


def get_file_size_mb(file_path: str) -> float:
    """Get the size of a file in MB."""
    if os.path.exists(file_path):
        return os.path.getsize(file_path) / (1024 * 1024)
    return 0.0


def run_export_and_transfer(
    incremental: bool = False,
    auto_scp: bool = True,
    windows_username: str = "chris",
    local_path: str | None = None,
):
    """
    Create summary and attempt SCP transfer to Windows.
    Returns dict: path, size_mb, scp_command, scp_success, error.
    """
    out = {
        "path": None,
        "size_mb": 0.0,
        "scp_command": None,
        "scp_success": False,
        "error": None,
    }
    try:
        path = create_codebase_summary(incremental=incremental)
        if path.startswith("No changes"):
            out["error"] = path
            return out
            
        out["path"] = path
        out["size_mb"] = get_file_size_mb(path)
        
        ssh_info = get_ssh_connection_info()
        if not ssh_info:
            out["error"] = "Could not detect SSH connection info."
            return out
            
        scp_cmd, _ = generate_scp_command(path, local_path, ssh_info, windows_username=windows_username)
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
        description='Create a codebase summary and generate SCP command to transfer to Windows laptop',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--output', type=str, default=None,
                       help='Output path for the summary file on remote server')
    parser.add_argument('--local-path', type=str, default=None,
                       help='Destination path on Windows laptop')
    parser.add_argument('--no-auto-scp', action='store_true',
                       help='Do NOT attempt automatic download')
    parser.add_argument('--incremental', action='store_true',
                       help='Export only files changed since last summary')
    
    args = parser.parse_args()
    windows_username = 'chris'
    
    print(f"🚀 Creating {'incremental ' if args.incremental else ''}codebase summary...")
    
    res = run_export_and_transfer(
        incremental=args.incremental,
        auto_scp=not args.no_auto_scp,
        windows_username=windows_username,
        local_path=args.local_path
    )
    
    if res["error"]:
        print(f"❌ {res['error']}")
        return 1
    
    print("\n" + "="*70)
    print("✅ SUMMARY CREATED SUCCESSFULLY!")
    print("="*70)
    print(f"\n📁 Remote File: {res['path']}")
    print(f"📊 Size: {res['size_mb']:.2f} MB")
    print("="*70 + "\n")
    
    if res["scp_command"]:
        print("📥 TO DOWNLOAD TO YOUR WINDOWS LAPTOP:")
        print("="*70)
        print("\n🔧 Run this command from your Windows PowerShell or CMD:")
        print(f"\n   {res['scp_command']}\n")
        print("="*70)
        
        if res["scp_success"]:
            print("\n✅ File successfully downloaded to Windows!")
        elif not args.no_auto_scp:
            print("\n⚠️  Automatic download failed. Please run the SCP command manually.")
            
    return 0


if __name__ == "__main__":
    sys.exit(main())
