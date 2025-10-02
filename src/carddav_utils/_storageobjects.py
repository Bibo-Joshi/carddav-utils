import hashlib
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any, Self

import tomlkit
from pydantic import BaseModel, model_validator

from ._profilepictureinfo import ProfilePictureInfo
from ._utils import ParsedPhoneNumber


class StoredProfilePictureInfo(BaseModel):
    phone_number: ParsedPhoneNumber
    mime_type: str
    file_path: Path
    hash: str

    @classmethod
    def from_profile_picture_info(cls, ppi: ProfilePictureInfo, storage_path: Path) -> Self:
        return cls(
            phone_number=ppi.phone_number,
            mime_type=ppi.mime_type,
            file_path=(storage_path / ppi.phone_number).with_suffix(
                f".{ppi.mime_type.split('/')[-1]}"
            ),
            hash=hashlib.sha256(ppi.photo).hexdigest(),
        )


class StoredProfilePictureInfoCollection(BaseModel):
    profile_pictures: list[StoredProfilePictureInfo]

    def update(self, profile_picture_info: ProfilePictureInfo) -> StoredProfilePictureInfo | None:
        """Update or add a profile picture.
        Updates are based on phone number. If a profile picture for the given phone number
        already exists, it will be replaced only if the hash of the new picture differs from
        the existing one.

        Args:
            profile_picture_info (ProfilePictureInfo): The profile picture information to add
                or update.

        Returns:
            StoredProfilePictureInfo | None: The updated or added StoredProfilePictureInfo,
                or None if no update was necessary.
        """
        new_entry = StoredProfilePictureInfo.from_profile_picture_info(
            profile_picture_info, Path("./photos")
        )

        for existing in self.profile_pictures:
            if existing.phone_number == profile_picture_info.phone_number:
                if existing.hash == new_entry.hash:
                    return None
                self.profile_pictures.remove(existing)

        self.profile_pictures.append(new_entry)
        return new_entry

    def get_by_phone_number(
        self, phone_number: ParsedPhoneNumber
    ) -> StoredProfilePictureInfo | None:
        """Get the StoredProfilePictureInfo for the given phone number.

        Args:
            phone_number (ParsedPhoneNumber): The phone number to look for.
        """
        try:
            return next(pic for pic in self.profile_pictures if pic.phone_number == phone_number)
        except StopIteration:
            return None

    def to_toml(self) -> str:
        data = self.model_dump()
        for pic in data["profile_pictures"]:
            pic["file_path"] = pic["file_path"].as_posix()
        return tomlkit.dumps(data)

    @classmethod
    def from_toml(cls, toml_str: str) -> Self:
        data = tomllib.loads(toml_str)
        return cls.model_validate(data)


class VCardIdentifier(BaseModel):
    uid: str | None = None
    phone: ParsedPhoneNumber | None = None
    email: str | None = None
    nick_name: str | None = None

    @model_validator(mode="after")
    def at_least_one_field_provided(cls, obj: Any) -> Any:
        if not any(getattr(obj, field_name) is not None for field_name in cls.model_fields):
            raise ValueError("At least one field must be non-None")
        return obj


class VCardPhoneType(StrEnum):
    CELL = "CELL"
    HOME = "HOME"
    WORK = "WORK"
    OTHER = "OTHER"


class VCardEmailType(StrEnum):
    HOME = "HOME"
    WORK = "WORK"


class VCardPhoneNumber(BaseModel):
    number: ParsedPhoneNumber
    number_type: VCardPhoneType


class VCardEmail(BaseModel):
    email: str
    email_type: VCardEmailType


class AdditionalVCardInfo(BaseModel):
    identifiers: VCardIdentifier
    phone_numbers: list[VCardPhoneNumber] = []
    emails: list[VCardEmail] = []


class AdditionalVCardInfoCollection(BaseModel):
    entries: list[AdditionalVCardInfo] = []

    def get_by_identifier(self, identifier: VCardIdentifier) -> AdditionalVCardInfo | None:
        for entry in self.entries:
            if identifier.uid is not None and entry.identifiers.uid == identifier.uid:
                return entry
            if identifier.phone is not None and entry.identifiers.phone == identifier.phone:
                return entry
            if identifier.email is not None and entry.identifiers.email == identifier.email:
                return entry
            if (
                identifier.nick_name is not None
                and entry.identifiers.nick_name == identifier.nick_name
            ):
                return entry
        return None

    @classmethod
    def from_toml(cls, toml_str: str) -> Self:
        data = tomllib.loads(toml_str)
        return cls.model_validate(data)
