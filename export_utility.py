"""
Export utility for creating codebase archives.
Excludes large data files, logs, and cache directories.
Supports full and incremental (changes since last export) exports.
"""
import os
import zipfile
import tempfile
import fnmatch
from datetime import datetime
from pathlib import Path

# Marker file storing timestamp of last full export (epoch seconds)
PROJECT_ROOT = Path(__file__).parent.absolute()
LAST_EXPORT_MARKER = PROJECT_ROOT / ".last_full_export"


# Patterns to exclude from export
EXCLUDE_PATTERNS = [
    # Cache and compiled files
    '__pycache__',
    '*.pyc',
    '*.pyo',
    '*.pyd',
    '.pytest_cache',
    
    # Database files
    '*.db',
    '*.sqlite',
    '*.sqlite3',
    
    # Log files
    '*.log',
    
    # Environment and secrets
    '.env',
    '.env.*',
    
    # IDE files
    '.vscode',
    '.idea',
    '*.swp',
    '*.swo',
    '*~',
    
    # OS files
    '.DS_Store',
    'Thumbs.db',
    
    # Large data directories
    'data/',
    'debug/',
    
    # Docker and build artifacts
    '*.bak',
    
    # Git (optional - you might want to include .gitignore)
    # '.git',
]


def should_exclude(file_path: str, root_dir: str) -> bool:
    """Check if a file or directory should be excluded from export."""
    rel_path = os.path.relpath(file_path, root_dir)
    
    # Also exclude the marker and any export zip in project
    if LAST_EXPORT_MARKER.as_posix() in file_path or ".last_full_export" in rel_path:
        return True
    if rel_path.endswith(".zip") and "export" in rel_path.lower():
        return True
    
    # Check against exclude patterns
    for pattern in EXCLUDE_PATTERNS:
        # Directory patterns
        if pattern.endswith('/'):
            if rel_path.startswith(pattern) or f'/{pattern}' in f'/{rel_path}':
                return True
        # File patterns
        elif '*' in pattern:
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(os.path.basename(rel_path), pattern):
                return True
        # Exact matches
        elif pattern in rel_path or os.path.basename(rel_path) == pattern:
            return True
    
    return False


def get_last_export_timestamp() -> float | None:
    """Return epoch seconds of last full export, or None if never."""
    if not LAST_EXPORT_MARKER.exists():
        return None
    try:
        t = float(LAST_EXPORT_MARKER.read_text().strip())
        return t if t > 0 else None
    except Exception:
        return None


def set_last_export_timestamp(ts: float | None = None) -> None:
    """Store timestamp of last full export (default: now)."""
    ts = ts if ts is not None else datetime.now().timestamp()
    LAST_EXPORT_MARKER.write_text(str(ts))


def _add_files_to_zip(zipf, project_root: Path, output_path: str, since_mtime: float | None = None) -> int:
    """Add matching project files to zip. Optionally only files modified after since_mtime (epoch). Returns count."""
    project_root_str = str(project_root)
    n = 0
    for root, dirs, files in os.walk(project_root):
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d), project_root_str)]
        for file in files:
            file_path = os.path.join(root, file)
            if should_exclude(file_path, project_root_str) or file_path == output_path:
                continue
            if since_mtime is not None:
                try:
                    m = os.path.getmtime(file_path)
                    if m <= since_mtime:
                        continue
                except OSError:
                    continue
            arcname = os.path.relpath(file_path, project_root_str)
            try:
                zipf.write(file_path, arcname)
                n += 1
            except (OSError, PermissionError):
                continue
    return n


def create_codebase_export(output_path: str | None = None) -> str:
    """
    Create a zip archive of the codebase excluding large files.
    Updates .last_full_export marker after a successful full export.
    
    Args:
        output_path: Optional path for the output zip file. If None, creates in temp directory.
    
    Returns:
        Path to the created zip file.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_path is None:
        output_dir = tempfile.gettempdir()
        output_path = os.path.join(output_dir, f"job_search_automation_export_{timestamp}.zip")
    else:
        d = os.path.dirname(output_path)
        if d:
            os.makedirs(d, exist_ok=True)
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        _add_files_to_zip(zipf, PROJECT_ROOT, output_path, since_mtime=None)
    
    set_last_export_timestamp()
    return output_path


def create_incremental_export(output_path: str | None = None) -> tuple[str | None, int]:
    """
    Create a zip of only files changed since the last full export.
    
    Args:
        output_path: Optional path for the output zip. If None, uses temp directory.
    
    Returns:
        (path to zip, number of files included). (None, 0) if no last export or no changes.
    """
    since = get_last_export_timestamp()
    if since is None:
        return None, 0
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_path is None:
        output_dir = tempfile.gettempdir()
        output_path = os.path.join(output_dir, f"job_search_automation_incremental_{timestamp}.zip")
    else:
        d = os.path.dirname(output_path)
        if d:
            os.makedirs(d, exist_ok=True)
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        n = _add_files_to_zip(zipf, PROJECT_ROOT, output_path, since_mtime=since)
    
    if n == 0:
        try:
            os.remove(output_path)
        except OSError:
            pass
        return None, 0
    return output_path, n


def get_export_size_mb(zip_path: str) -> float:
    """Get the size of the export file in MB."""
    if os.path.exists(zip_path):
        return os.path.getsize(zip_path) / (1024 * 1024)
    return 0.0
