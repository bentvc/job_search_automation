"""
Export utility for creating a single-file codebase summary.
Excludes large data files, logs, and cache directories.
Supports full and incremental (changes since last export) summaries.
Results in a single Markdown file optimized for LLM consumption.
"""
import os
import fnmatch
from datetime import datetime
from pathlib import Path

# Marker file storing timestamp of last full export (epoch seconds)
PROJECT_ROOT = Path(__file__).parent.absolute()
LAST_EXPORT_MARKER = PROJECT_ROOT / ".last_summary_export"

def get_last_export_timestamp() -> float | None:
    """Return epoch seconds of last summary export, or None if never."""
    if not LAST_EXPORT_MARKER.exists():
        return None
    try:
        t = float(LAST_EXPORT_MARKER.read_text().strip())
        return t if t > 0 else None
    except Exception:
        return None

# Patterns to exclude from summary
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
    
    # Large data directories or specific project exclusions
    'data/',
    'debug/',
    'venv/',
    'node_modules/',
    '.git/',
    
    # Build and backup
    '*.bak',
    '*.zip',
    'codebase_summary_*.md',
    '.last_summary_export'
]

def should_exclude(file_path: str, root_dir: str) -> bool:
    """Check if a file or directory should be excluded from summary."""
    rel_path = os.path.relpath(file_path, root_dir)
    
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

def is_binary(file_path: str) -> bool:
    """Check if a file is binary."""
    try:
        with open(file_path, 'tr', encoding='utf-8') as f:
            f.read(1024)
            return False
    except (UnicodeDecodeError, PermissionError):
        return True

def generate_directory_tree(root_dir: str, since_mtime: float | None = None) -> str:
    """Generate a text-based directory tree of the project."""
    tree = ["Project Structure:", "=" * 20]
    for root, dirs, files in os.walk(root_dir):
        # Filter directories in-place for os.walk
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d), root_dir)]
        
        level = os.path.relpath(root, root_dir).count(os.sep)
        if os.path.relpath(root, root_dir) == '.':
            level = 0
            name = os.path.basename(root_dir)
        else:
            name = os.path.basename(root)
            level += 1
            
        indent = '  ' * level
        
        # Check if any files in this dir or subdirs match the criteria
        valid_files = []
        for f in sorted(files):
            f_path = os.path.join(root, f)
            if not should_exclude(f_path, root_dir):
                if since_mtime:
                    try:
                        if os.path.getmtime(f_path) > since_mtime:
                            valid_files.append(f)
                    except OSError:
                        pass
                else:
                    valid_files.append(f)
        
        if valid_files or any(not should_exclude(os.path.join(root, d), root_dir) for d in dirs):
            tree.append(f"{indent}{name}/")
            sub_indent = '  ' * (level + 1)
            for f in valid_files:
                tree.append(f"{sub_indent}{f}")
                
    return "\n".join(tree)

def create_codebase_summary(output_path: str | None = None, incremental: bool = False) -> str:
    """
    Create a single Markdown file containing the codebase summary.
    
    Args:
        output_path: Path for the output file. If None, created in PROJECT_ROOT.
        incremental: If True, only include files changed since last export.
    """
    since_mtime = None
    if incremental:
        if LAST_EXPORT_MARKER.exists():
            try:
                since_mtime = float(LAST_EXPORT_MARKER.read_text().strip())
            except ValueError:
                pass
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if output_path is None:
        prefix = "incremental_summary" if incremental else "codebase_summary"
        output_path = str(PROJECT_ROOT / f"{prefix}_{timestamp}.md")
    
    summary = []
    summary.append(f"# Codebase Summary {'(Incremental)' if incremental else ''}")
    summary.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if since_mtime:
        summary.append(f"Changes since: {datetime.fromtimestamp(since_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
    summary.append("\n" + generate_directory_tree(str(PROJECT_ROOT), since_mtime))
    summary.append("\n" + "=" * 40 + "\n")
    
    file_count = 0
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d), str(PROJECT_ROOT))]
        for file in sorted(files):
            file_path = os.path.join(root, file)
            if should_exclude(file_path, str(PROJECT_ROOT)) or file_path == output_path:
                continue
            
            if since_mtime:
                try:
                    if os.path.getmtime(file_path) <= since_mtime:
                        continue
                except OSError:
                    continue
            
            if is_binary(file_path):
                continue
                
            rel_path = os.path.relpath(file_path, PROJECT_ROOT)
            summary.append(f"## File: {rel_path}")
            
            ext = os.path.splitext(file)[1].lstrip('.') or 'text'
            summary.append(f"```{ext}")
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    summary.append(f.read())
            except Exception as e:
                summary.append(f"Error reading file: {e}")
            
            summary.append("```\n")
            file_count += 1
    
    if file_count == 0 and incremental:
        return "No changes detected since last summary."
        
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(summary))
    
    # Update marker
    LAST_EXPORT_MARKER.write_text(str(datetime.now().timestamp()))
    
    return output_path

if __name__ == "__main__":
    import sys
    inc = "--incremental" in sys.argv
    path = create_codebase_summary(incremental=inc)
    print(f"Summary created: {path}")
