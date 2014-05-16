import mimetypes
from pathlib import Path

from . import page, Resource
from .exceptions import NotFound


class StaticResource(Resource):
    """A very dumb resource serving static files

    To serve files from a directory public, but only js and css folders::

        static = StaticResource('./public', ['js', 'css'])
        site = Site(resources=[static, Root()])

    """

    default_mime = 'application/octed-stream'

    def __init__(self, base, folders=None):
        self.dir = Path(base).resolve()
        self.folders = folders

    @page
    def default(self, folder, *path):
        if self.folders is not None and folder not in self.folders:
            raise NotFound()
        try:
            opath = self.dir.joinpath(folder, *path)
            ctype = mimetypes.guess_type(str(opath))[0] or self.default_mime
            path = opath.resolve()
            path.relative_to(self.dir)  # check for /../ and symlinks
            with path.open('rb') as f:
                return ['200 OK',
                    [('Content-Type', ctype)],
                    f.read()]
        except (ValueError, OSError, RuntimeError):
            raise NotFound()
