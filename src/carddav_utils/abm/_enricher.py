from collections.abc import Sequence

import vobject
from aiorem import AbstractResourceManager

from .._nextcloudstorage import NextCloudStorage
from .._storageobjects import (
    AdditionalVCardInfo,
    AdditionalVCardInfoCollection,
    StoredProfilePictureInfo,
    StoredProfilePictureInfoCollection,
    VCardIdentifier,
)
from .._utils import phone_number_to_string


class VCardEnricher(AbstractResourceManager):
    """Enriches vCards with additional information from NextCloudStorage"""

    def __init__(self, nextcloud_storage: NextCloudStorage) -> None:
        self._nextcloud_storage: NextCloudStorage = nextcloud_storage
        self.__sppic: StoredProfilePictureInfoCollection | None = None
        self.__avci: AdditionalVCardInfoCollection | None = None

    async def acquire_resources(self) -> None:
        await self._nextcloud_storage.acquire_resources()
        self.__sppic = await self._nextcloud_storage.get_current_profile_pictures()
        self.__avci = await self._nextcloud_storage.get_current_additional_vcard_info()

    async def release_resources(self) -> None:
        await self._nextcloud_storage.release_resources()
        self.__sppic = None
        self.__avci = None

    @property
    def _sppic(self) -> StoredProfilePictureInfoCollection:
        if self.__sppic is None:
            raise RuntimeError(
                "Stored profile picture info not loaded. Call acquire_resources() first."
            )
        return self.__sppic

    @property
    def _avci(self) -> AdditionalVCardInfoCollection:
        if self.__avci is None:
            raise RuntimeError("Additional vCard info not loaded. Call acquire_resources() first.")
        return self.__avci

    async def _insert_profile_picture(
        self, vcard_object: vobject.base.Component, profile_picture_info: StoredProfilePictureInfo
    ) -> bool:
        if vcard_object.contents.get("photo"):
            return False

        photo = vcard_object.add("PHOTO")
        photo.value = (await self._nextcloud_storage.download_picture(profile_picture_info)).photo
        photo.encoding_param = "B"
        photo.type_param = profile_picture_info.mime_type.split("/")[-1].upper()
        return True

    def _insert_additional_info(
        self, vcard_object: vobject.base.Component, additional_info: AdditionalVCardInfo
    ) -> tuple[Sequence[str], Sequence[str]]:
        added_phone_numbers = []
        added_emails = []

        if additional_info.phone_numbers:
            existing_numbers = {
                phone_number_to_string(tel.value) for tel in vcard_object.contents.get("tel", [])
            }
            for number in additional_info.phone_numbers:
                if number.number not in existing_numbers:
                    tel = vcard_object.add("TEL")
                    tel.value = number.number
                    tel.type_param = number.number_type
                    added_phone_numbers.append(number.number)

        if additional_info.emails:
            existing_emails = {email.value for email in vcard_object.contents.get("email", [])}
            for email in additional_info.emails:
                if email.email not in existing_emails:
                    email_entry = vcard_object.add("EMAIL")
                    email_entry.value = email.email
                    email_entry.type_param = email.email_type
                    added_emails.append(email.email)

        return added_phone_numbers, added_emails

    async def enrich_vcard(  # noqa: PLR0912
        self, vcard_object: vobject.base.Component
    ) -> vobject.base.Component:
        """Enriches a vCard with additional information from NextCloudStorage.

        Args:
            vcard_content (bytes): The original vCard content.
        Returns:
            bytes: The enriched vCard content.
        """
        vcard_contents = vcard_object.contents

        phone = None
        if numbers := vcard_contents.get("tel", []):
            for number in numbers:
                phone = number.value
                # We prefer mobile numbers if available
                if number.type_param == ["CELL"]:
                    break

        email = None
        if emails := vcard_contents.get("email", []):
            email = emails[-1].value

        indentifier = VCardIdentifier(
            uid=vcard_object.uid.value,
            nick_name=n[0].value if (n := vcard_contents.get("nickname")) else None,
            email=email,
            phone=phone,
        )

        added_phones: Sequence[str] = []
        added_mails: Sequence[str] = []
        picture_added = False

        additional_info = self._avci.get_by_identifier(indentifier)
        numbers = []
        if vcard_numbers := vcard_contents.get("tel", []):
            for number in vcard_numbers:
                numbers.append(phone_number_to_string(number.value))

        if additional_info:
            added_phones, added_mails = self._insert_additional_info(vcard_object, additional_info)

        stored_profile_picture_info = None
        for number in [*numbers, *added_phones]:
            stored_profile_picture_info = self._sppic.get_by_phone_number(number)
            if stored_profile_picture_info:
                break

        if stored_profile_picture_info:
            picture_added = await self._insert_profile_picture(
                vcard_object, stored_profile_picture_info
            )

        if any([added_phones, added_mails, picture_added]):
            note_addition = "\n----\nAdded by CardDAV Utils:"
            if added_phones:
                note_addition += f"\nPhone numbers: {', '.join(added_phones)}"
            if added_mails:
                note_addition += f"\nEmails: {', '.join(added_mails)}"
            if picture_added:
                note_addition += "\nProfile picture"

            if note := vcard_contents.get("note"):
                note[0].value += note_addition
            else:
                note = vcard_object.add("NOTE")
                note.value = note_addition

        return vcard_object
