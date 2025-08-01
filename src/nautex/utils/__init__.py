"""Utility functions for Nautex."""

from pathlib import Path


def path2display(path: Path) -> str:
    """Convert a Path object to a string for display.
    
    Replaces the home directory with "~/" for better display.
    
    Args:
        path: Path object to convert
        
    Returns:
        String representation of the path
    """
    home = Path.home()
    if path.is_relative_to(home):
        relative = path.relative_to(home)
        return "~/" + str(relative)
    else:
        return str(path)