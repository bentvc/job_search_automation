"""
Windows helper script to open the Downloads folder after export.
This can be run manually or integrated with the export process.
"""
import os
import subprocess
import platform
from pathlib import Path


def open_folder_windows(folder_path: str):
    """Open a folder in Windows Explorer."""
    if platform.system() != 'Windows':
        print("This script is designed for Windows only.")
        return False
    
    try:
        # Normalize the path
        folder_path = os.path.normpath(folder_path)
        
        # Use explorer.exe to open the folder
        # Use /select to highlight a file if it's a file path, or just open folder
        subprocess.Popen(f'explorer "{folder_path}"', shell=True)
        return True
    except Exception as e:
        print(f"Error opening folder: {e}")
        return False


def get_downloads_folder():
    """Get the Windows Downloads folder path."""
    if platform.system() != 'Windows':
        return None
    
    try:
        # Try to get Downloads folder from user profile
        user_profile = os.environ.get('USERPROFILE')
        if user_profile:
            downloads = os.path.join(user_profile, 'Downloads')
            if os.path.exists(downloads):
                return downloads
        
        # Fallback to temp directory
        return os.path.join(os.environ.get('TEMP', ''), '..', 'Downloads')
    except Exception as e:
        print(f"Error getting Downloads folder: {e}")
        return None


if __name__ == "__main__":
    # Example usage
    downloads = get_downloads_folder()
    if downloads:
        print(f"Opening Downloads folder: {downloads}")
        open_folder_windows(downloads)
    else:
        print("Could not determine Downloads folder path.")
