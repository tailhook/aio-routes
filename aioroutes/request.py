from .signature import Sticker


@Sticker.register
class BaseRequest(object):
    pass
