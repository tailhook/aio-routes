import abc


class WebException(Exception):
    """Base for all exceptions which render error code (and page) to client"""

    @abc.abstractmethod
    def default_response(self):
        pass


class Forbidden(WebException):

    def default_response(self):
        return (b'403 Forbidden',
                b'Content-Type\0text/html\0',
                b'<!DOCTYPE html>'
                b'<html>'
                    b'<head>'
                        b'<title>403 Forbidden</title>'
                    b'</head>'
                    b'<body>'
                    b'<h1>403 Forbidden</h1>'
                    b'</body>'
                b'</html>'
                )


class InternalError(WebException):

    def default_response(self):
        return (b'500 Internal Server Error',
                b'Content-Type\0text/html\0',
                b'<!DOCTYPE html>'
                b'<html>'
                    b'<head>'
                        b'<title>500 Internal Server Error</title>'
                    b'</head>'
                    b'<body>'
                    b'<h1>500 Internal Server Error</h1>'
                    b'</body>'
                b'</html>'
                )


class NotFound(WebException):

    def default_response(self):
        return (b'404 Not Found',
                b'Content-Type\0text/html\0',
                b'<!DOCTYPE html>'
                b'<html>'
                    b'<head>'
                        b'<title>404 Page Not Found</title>'
                    b'</head>'
                    b'<body>'
                    b'<h1>404 Page Not Found</h1>'
                    b'</body>'
                b'</html>'
                )


class MethodNotAllowed(WebException):

    def default_response(self):
        return (b'405 Method Not Allowed',
                b'Content-Type\0text/html\0',
                b'<!DOCTYPE html>'
                b'<html>'
                    b'<head>'
                        b'<title>405 Method Not Allowed</title>'
                    b'</head>'
                    b'<body>'
                    b'<h1>405 Method Not Allowed</h1>'
                    b'</body>'
                b'</html>'
                )


class Redirect(WebException):

    def __init__(self, location, status_code, status_text):
        self.statusline = '{:d} {}'.format(status_code, status_text)
        self.location = location

    def location_header(self):
        return b'Location\0' + self.location.encode('ascii') + b'\0'

    def headers(self):
        return (b'Content-Type\0text/html\0'
                + self.location_header())

    def default_response(self):
        return (self.statusline, self.headers(),
                '<!DOCTYPE html>'
                '<html>'
                    '<head>'
                        '<title>{0.statusline}</title>'
                    '</head>'
                    '<body>'
                    '<h1>{0.statusline}</h1>'
                    '<a href="{0.location}">Follow</a>'
                    '</body>'
                '</html>'.format(self)
                )


class CompletionRedirect(Redirect):
    """Temporary redirect which sends code 303

    With :param:`cookie` set it is often used for login forms. Without
    parameter set it is used to provide "success" page for various web forms
    and other non-idempotent actions
    """

    def __init__(self, location, cookie=None, *,
        status_code=303, status_text="See Other"):
        super().__init__(location,
            status_code=status_code, status_text=status_text)
        self.cookie = cookie

    def headers(self):
        sup = super().headers()
        if self.cookie is not None:
            sup += self.cookie.output(header='Set-Cookie\0',
                                      sep='\0').encode('ascii') + b'\0'
        return sup


class ChildNotFound(Exception):
    """Raised by resolve_local to notify that there is not such child"""


class NiceError(Exception):
    """Error that is safe to present to user"""


class InternalRedirect(Exception, metaclass=abc.ABCMeta):

    @abc.abstractmethod
    def update_request(self, request):
        pass


class PathRewrite(InternalRedirect):

    def __init__(self, new_path):
        self.new_path = new_path

    def update_request(self, request):
        request.uri = self.new_path
        del request.parsed_uri

