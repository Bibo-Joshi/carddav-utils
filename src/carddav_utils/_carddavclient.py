import asyncio
import datetime as dtm
from typing import Self
from urllib.parse import urljoin

import httpx
import httpx_retries
import vobject
from aiorem import AbstractResourceManager
from pydantic import BaseModel, ConfigDict


class CardDavClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str
    address_book_url: str


def _parse_http_date(http_date: str) -> dtm.datetime:
    try:
        return dtm.datetime.strptime(http_date, "%a, %d %b %Y %H:%M:%S %Z")  # noqa: DTZ007
    except ValueError:
        return dtm.datetime.min.replace(tzinfo=dtm.UTC)


class CustomRetry(httpx_retries.Retry):
    def is_retryable_method(self, method: str) -> bool:
        if method == "PROPFIND":
            return True
        return super().is_retryable_method(method)


class CardDavClient(AbstractResourceManager):
    def __init__(self, username: str, password: str, address_book_url: str) -> None:
        self._httpx_client = httpx.AsyncClient(
            auth=(username, password),
            timeout=30,
            limits=httpx.Limits(max_connections=1024),
            transport=httpx_retries.RetryTransport(retry=CustomRetry(total=5)),
        )
        self._address_book_url: str = address_book_url

        # Let's limit the number of concurrent requests to avoid overwhelming the server.
        self.__semaphore = asyncio.BoundedSemaphore(50)

    @classmethod
    def from_config(cls, config: CardDavClientConfig) -> Self:
        return cls(
            username=config.username,
            password=config.password,
            address_book_url=config.address_book_url,
        )

    async def acquire_resources(self) -> None:
        await self._httpx_client.__aenter__()

    async def release_resources(self) -> None:
        await self._httpx_client.__aexit__()

    async def download_address_book_to_memory(self) -> dict[str, vobject.base.Component]:
        """Downloads the entire address book and returns a dictionary mapping UIDs to vCard
        components."""
        async with self.__semaphore:
            response = await self._httpx_client.get(f"{self._address_book_url}?export", timeout=30)
            response.raise_for_status()
            return {
                vcard.uid.value: vcard
                for vcard in vobject.readComponents(response.content.decode("utf-8"))
            }

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

    async def delete_vcard(self, uid: str) -> None:
        """Deletes a vCard by its UID."""
        async with self.__semaphore:
            response = await self._httpx_client.delete(
                urljoin(self._address_book_url, f"{uid}.vcf")
            )
            response.raise_for_status()
