from .signature import (
    Sticker
    )
from .core import (
    BaseResource,
    ResourceInterface,
    resource,
    )
from .decorators import (
    decorator,
    preprocessor,
    postprocessor,
)
from .http import (
    Site,
    MethodResolver,
    PathResolver,
    page,
    )
from .exceptions import (
    PathRewrite,
    CompletionRedirect,
    )
from .util import (
    DictResourceMixin,
    )

__all__ = [
    # signature
    'Sticker',
    # core
    'BaseResource',
    'ResourceInterface',
    'resource',
    # http
    'Site',
    'MethodResolver',
    'PathResolver',
    'page',
    # decorators
    'decorator',
    'preprocessor',
    'postprocessor',
    # exceptions
    'PathRewrite',
    'CompletionRedirect',
    # util
    'DictResourceMixin',
    ]


class Resource(BaseResource):
    http_resolver = PathResolver()


class DictResource(DictResourceMixin, Resource):
    pass
