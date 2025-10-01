import logging
from pathlib import Path
from typing import NewType

import phonenumbers

project_root = Path(__file__).parent.parent


def get_logger(file_path: Path, class_name: str) -> logging.Logger:
    """Get a logger for a specific class in a specific file."""
    relative_path = file_path.relative_to(project_root, walk_up=True)
    module = relative_path.parent
    logger_name = ".".join((*module.parts, class_name))
    return logging.getLogger(logger_name)


ParsedPhoneNumber = NewType("ParsedPhoneNumber", str)


def phone_number_to_string(phone_number: str) -> ParsedPhoneNumber:
    number = phonenumbers.parse(phone_number, "DE")
    if not phonenumbers.is_valid_number(number):
        return ParsedPhoneNumber(phone_number)
    return ParsedPhoneNumber(
        phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    )
