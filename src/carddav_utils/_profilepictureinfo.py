from pydantic import BaseModel

from ._utils import ParsedPhoneNumber


class ProfilePictureInfo(BaseModel):
    """Information about a profile picture associated with a phone number."""

    phone_number: ParsedPhoneNumber
    photo: bytes
    mime_type: str
