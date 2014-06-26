import asyncio
import logging
import aiohttp.server

from .http import BaseHTTPRequest, FORM_CONTENT_TYPE


log = logging.getLogger(__name__)


class Request(BaseHTTPRequest):

    def __init__(self, proto, message):
        self.uri = message.path
        self.content_type = message.headers.get('CONTENT-TYPE', None)
        self.cookie = ''
        if 'COOKIE' in message.headers:
            self.cookie = ','.join(message.headers.getall('COOKIE'))
        super().__init__()


class HttpProto(aiohttp.server.ServerHttpProtocol):

    def __init__(self, site):
        self.__site = site
        super().__init__()

    @asyncio.coroutine
    def handle_request(self, message, payload):
        try:
            req = Request(self, message)
            if req.content_type == FORM_CONTENT_TYPE:
                req.body = yield from payload.read()
            else:
                req.payload = payload
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
            resp.add_header('CONTENT-LENGTH', str(len(data)))
            resp.send_headers()
            resp.write(data)
            resp.write_eof()
        except Exception as e:
            log.exception("Exception while processing request", exc_info=e)
