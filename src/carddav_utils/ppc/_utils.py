from typing import NewType

import phonenumbers

ParsedPhoneNumber = NewType("ParsedPhoneNumber", str)


def phone_number_to_string(phone_number: str) -> ParsedPhoneNumber:
    number = phonenumbers.parse(phone_number, "DE")
    if not phonenumbers.is_valid_number(number):
        return ParsedPhoneNumber(phone_number)
    return ParsedPhoneNumber(
        phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    )
