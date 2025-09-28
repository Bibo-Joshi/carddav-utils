import logging
from pathlib import Path

project_root = Path(__file__).parent.parent


def get_logger(file_path: Path, class_name: str) -> logging.Logger:
    """Get a logger for a specific class in a specific file."""
    relative_path = file_path.relative_to(project_root, walk_up=True)
    module = relative_path.parent
    logger_name = ".".join((*module.parts, class_name))
    return logging.getLogger(logger_name)
