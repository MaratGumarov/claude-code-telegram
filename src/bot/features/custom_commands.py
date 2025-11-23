"""Custom slash commands management for Claude Code integration.

Scans and manages custom commands from both global and project-specific locations.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class CustomCommand:
    """Represents a custom Claude Code slash command."""

    name: str
    description: str
    prompt: str
    source: str  # "global" or "project"
    file_path: Path


def scan_commands(working_directory: Path) -> List[CustomCommand]:
    """Scan for custom commands from both global and project directories.
    
    Args:
        working_directory: Current working directory for project-specific commands
        
    Returns:
        List of available custom commands, with project commands overriding global ones
    """
    commands = {}
    
    # Scan global commands
    global_dir = Path.home() / ".claude" / "commands"
    if global_dir.exists() and global_dir.is_dir():
        for cmd in _scan_directory(global_dir, "global"):
            commands[cmd.name] = cmd
    
    # Scan project commands (override global if same name)
    project_dir = working_directory / ".claude" / "commands"
    if project_dir.exists() and project_dir.is_dir():
        for cmd in _scan_directory(project_dir, "project"):
            commands[cmd.name] = cmd
    
    return sorted(commands.values(), key=lambda c: c.name)


def _scan_directory(directory: Path, source: str) -> List[CustomCommand]:
    """Scan a single directory for command files.
    
    Args:
        directory: Directory to scan
        source: Source identifier ("global" or "project")
        
    Returns:
        List of commands found in the directory
    """
    commands = []
    
    try:
        for file_path in directory.glob("*.json"):
            cmd = _load_command(file_path, source)
            if cmd:
                commands.append(cmd)
    except Exception as e:
        logger.warning(
            "Failed to scan command directory",
            directory=str(directory),
            error=str(e),
        )
    
    return commands


def _load_command(file_path: Path, source: str) -> Optional[CustomCommand]:
    """Load a command from a JSON file.
    
    Args:
        file_path: Path to command JSON file
        source: Source identifier ("global" or "project")
        
    Returns:
        CustomCommand if valid, None if invalid
    """
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
        
        # Validate required fields
        if "description" not in data or "prompt" not in data:
            logger.warning(
                "Invalid command file missing required fields",
                file=str(file_path),
            )
            return None
        
        # Command name is the filename without .json extension
        name = file_path.stem
        
        return CustomCommand(
            name=name,
            description=data["description"],
            prompt=data["prompt"],
            source=source,
            file_path=file_path,
        )
    
    except json.JSONDecodeError as e:
        logger.warning(
            "Failed to parse command JSON",
            file=str(file_path),
            error=str(e),
        )
        return None
    except Exception as e:
        logger.warning(
            "Failed to load command",
            file=str(file_path),
            error=str(e),
        )
        return None


def get_command_by_name(
    name: str, working_directory: Path
) -> Optional[CustomCommand]:
    """Get a specific command by name.
    
    Project-specific commands take precedence over global commands.
    
    Args:
        name: Command name (without slash prefix)
        working_directory: Current working directory
        
    Returns:
        CustomCommand if found, None otherwise
    """
    # Check project directory first
    project_file = working_directory / ".claude" / "commands" / f"{name}.json"
    if project_file.exists():
        cmd = _load_command(project_file, "project")
        if cmd:
            return cmd
    
    # Check global directory
    global_file = Path.home() / ".claude" / "commands" / f"{name}.json"
    if global_file.exists():
        cmd = _load_command(global_file, "global")
        if cmd:
            return cmd
    
    return None
