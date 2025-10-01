import asyncio
from pathlib import Path
from typing import Self

import httpx
import httpx_retries
from aiorem import AbstractResourceManager
from nextcloud_async import NextCloudAsync
from pydantic import BaseModel, ConfigDict


class NextCloudClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str
    base_url: str


class NextCloudClient(AbstractResourceManager):
    def __init__(self, username: str, password: str, base_url: str) -> None:
        self._httpx_client = httpx.AsyncClient(
            auth=(username, password),
            timeout=30,
            limits=httpx.Limits(max_connections=1024),
            transport=httpx_retries.RetryTransport(retry=httpx_retries.Retry(total=5)),
        )
        self._nca = NextCloudAsync(
            client=self._httpx_client, endpoint=base_url, user=username, password=password
        )

        # let's limit concurrent operations to avoid overwhelming the server
        self.__semaphore = asyncio.BoundedSemaphore(32)

    @classmethod
    def from_config(cls, config: NextCloudClientConfig) -> Self:
        return cls(**config.model_dump())

    async def acquire_resources(self) -> None:
        await self._httpx_client.__aenter__()

    async def release_resources(self) -> None:
        await self._httpx_client.__aexit__()

    async def list_files(self, path: str | Path) -> list[str]:
        async with self.__semaphore:
            return await self._nca.list_files(path)

    async def download_file_to_memory(self, path: str | Path) -> bytes:
        async with self.__semaphore:
            return await self._nca.download_file(path)

    async def delete_file(self, path: str | Path) -> None:
        async with self.__semaphore:
            await self._nca.delete(path)

    async def upload_file(self, data: bytes, file_path: str | Path) -> None:
        async with self.__semaphore:
            await self._nca.dav_query(
                method="PUT",
                sub=f"/remote.php/dav/files/{self._nca.user}/{Path(file_path).as_posix()}",
                data=data,
            )
