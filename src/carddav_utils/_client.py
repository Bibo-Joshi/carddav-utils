import asyncio
import datetime as dtm
import re
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx
from aiorem import AbstractResourceManager

from ._vcardinfo import VCardInfo


def _parse_http_date(http_date: str) -> dtm.datetime:
    try:
        return dtm.datetime.strptime(http_date, "%a, %d %b %Y %H:%M:%S %Z")  # noqa: DTZ007
    except ValueError:
        return dtm.datetime.min.replace(tzinfo=dtm.UTC)


class CardDavClient(AbstractResourceManager):
    def __init__(self, username: str, password: str, address_book_url: str) -> None:
        self._httpx_client = httpx.AsyncClient(
            auth=(username, password), timeout=30, limits=httpx.Limits(max_connections=1024)
        )
        self._address_book_url: str = address_book_url

        # Let's limit the number of concurrent requests to avoid overwhelming the server.
        self.__semaphore = asyncio.BoundedSemaphore(50)
        self.__vcard_cache: dict[str, bytes] = {}

    async def acquire_resources(self) -> None:
        await self._httpx_client.__aenter__()

    async def release_resources(self) -> None:
        await self._httpx_client.__aexit__()

    async def download_vcard_to_memory(self, uid: str) -> bytes:
        """Downloads a vCard by its UID and returns its content as a string."""
        if uid in self.__vcard_cache:
            return self.__vcard_cache[uid]
        async with self.__semaphore:
            response = await self._httpx_client.get(urljoin(self._address_book_url, f"{uid}.vcf"))
            response.raise_for_status()
            content = response.content
            self.__vcard_cache[uid] = content
            return content

    async def upload_vcard(self, uid: str, vcard: bytes | str, etag: str | None = None) -> None:
        """IMPORTANT: Does currently not use an e-tag to check if the remote vCard has the same
        status as the base for the local vCard. This means that the upload may override changes on
        the remote.
        """
        async with self.__semaphore:
            headers = {"content-type": "text/vcard"}
            if etag is not None:
                headers["If-Match"] = etag
            response = await self._httpx_client.put(
                urljoin(self._address_book_url, f"{uid}.vcf"),
                headers=headers,
                content=vcard.encode("utf-8") if isinstance(vcard, str) else vcard,
            )
            response.raise_for_status()
            # Important to update the cache only after a successful upload
            self.__vcard_cache[uid] = vcard.encode("utf-8") if isinstance(vcard, str) else vcard

    async def delete_vcard(self, uid: str) -> None:
        """Deletes a vCard by its UID."""
        async with self.__semaphore:
            response = await self._httpx_client.delete(
                urljoin(self._address_book_url, f"{uid}.vcf")
            )
            response.raise_for_status()

    async def get_vcard_infos(self) -> dict[str, VCardInfo]:
        async with self.__semaphore:
            response = await self._httpx_client.request(
                "PROPFIND", self._address_book_url, headers={"Depth": "1"}
            )
        xml_data = response.raise_for_status().content.decode()
        vcards = self._parse_carddav_vcards(xml_data)
        return {vcard.uid: vcard for vcard in vcards}

    @staticmethod
    def _parse_carddav_vcards(xml_string: str) -> list[VCardInfo]:
        # XML namespaces
        NS = {"d": "DAV:", "card": "urn:ietf:params:xml:ns:carddav"}
        root = ElementTree.fromstring(xml_string)
        vcards: list[VCardInfo] = []

        for response in root.findall("d:response", NS):
            propstat = response.find("d:propstat", NS)
            if propstat is None:
                continue

            prop = propstat.find("d:prop", NS)
            if prop is None:
                continue

            resourcetype = prop.find("d:resourcetype", NS)

            # Skip if resourcetype has <d:collection> or <card:addressbook>
            if resourcetype is not None and (
                resourcetype.find("d:collection", NS) is not None
                or resourcetype.find("card:addressbook", NS) is not None
            ):
                # skip forlders and addressbooks
                continue

            # Extract UID from href
            href = response.findtext("d:href", namespaces=NS)
            if not href:
                continue

            uid_match = re.search(r"/([^/]+)\.vcf$", href)
            if not uid_match:
                continue

            uid = uid_match.group(1)

            etag = prop.findtext("d:getetag", default="", namespaces=NS)  # .strip('"')

            content_type = prop.findtext("d:getcontenttype", default="", namespaces=NS)
            content_length_str = prop.findtext("d:getcontentlength", default="0", namespaces=NS)
            try:
                content_length = int(content_length_str)
            except ValueError:
                content_length = 0

            last_modified_str = prop.findtext("d:getlastmodified", default="", namespaces=NS)
            last_modified = _parse_http_date(last_modified_str)

            vcard = VCardInfo(
                uid=uid,
                etag=etag,
                content_type=content_type,
                content_length=content_length,
                last_modified=last_modified,
            )
            vcards.append(vcard)

        return vcards
