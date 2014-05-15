import asyncio
import logging
from pathlib import PurePosixPath as Path
from urllib.parse import urlsplit
import aiohttp.server

from .request import BaseRequest


log = logging.getLogger(__name__)


class Request(BaseRequest):

    def __init__(self, proto, message, payload):
        split_url = urlsplit(message.path)
        self.path = Path(split_url.path)
        self.content_type = message['Content-Type']
        self.cookie = message['Cookie']
        self.body = payload


class HttpProto(aiohttp.server.ServerHttpProtocol):

    def __init__(self, site):
        self.__site = site
        super().__init__()

    @asyncio.coroutine
    def handle_request(self, message, payload):
        try:
            req = Request(self, message, payload)
            try:
                status, headers, data = yield from self.__site.dispatch(req)
            except Exception as e:
                log.exception("Sending 500 because of:", exc_info=e)
                status = 500
                headers = {}
                data = b'500 Internal Server Error'
            resp = aiohttp.Response(self.writer, status,
                message.version, message.should_close)
            if isinstance(headers, dict):
                headers = headers.items()
            resp.add_headers(*headers)
            resp.send_headers()
            resp.write(data)
            resp.write_eof()
        except Exception as e:
            log.exception("Exception while processing request", exc_info=e)
