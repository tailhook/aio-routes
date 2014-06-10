import abc
import asyncio
import inspect


class Sticker(metaclass=abc.ABCMeta):
    """
    An object which is automatically put into arguments in the view if
    specified in annotation
    """
    __superseded = {}

    @classmethod
    @abc.abstractmethod
    @asyncio.coroutine
    def create(cls, resolver):
        """Creates an object of this class based on resolver"""

    @classmethod
    def supersede(cls, sub):
        oldsup = cls.__superseeded.get(cls, None)
        if oldsup is not None:
            if issubclass(sub, oldsup):
                pass  # just supersede it again
            elif issubclass(oldsup, sub):
                return  # already superseeded by more specific subclass
            else:
                raise RuntimeError("{!r} is already superseeded by {!r}"
                    .format(cls, oldsup))

        super().register(sub)
        cls.__superseded[cls] = sub



class ReprHack(str):
    """Used to print names in function signature"""
    __slots__ = ()
    def __repr__(self):
        return str(self)


def compile_signature(fun, partial):
    sig = inspect.signature(fun)
    fun_params = [
        inspect.Parameter('resolver',
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    args = []
    kwargs = []
    vars = {
        '__empty__': object(),
        }
    lines = []
    self = True
    varkw = None
    varpos = None
    nposargs = 0

    for name, param in sig.parameters.items():
        ann = param.annotation
        if param.default is not inspect.Parameter.empty:
            vars[name + '_def'] = param.default
            if ann is not inspect.Parameter.empty:
                # If we have annotation, we want to make sure that annotation
                # is not applied to a default value so we pass __empty__
                # and check for it later
                defname = ReprHack('__empty__')
            else:
                defname = ReprHack(name + '_def')
        else:
            defname = inspect.Parameter.empty
        if ann is not inspect.Parameter.empty:
            if isinstance(ann, type) and issubclass(ann, Sticker):
                lines.append('  {0} = yield from {0}_create(resolver)'
                    .format(name))
                vars[name + '_create'] = ann.create
            else:
                nposargs += 1
                lines.append('  if {0} is __empty__:'.format(name))
                lines.append('    {0} = {0}_def'.format(name))
                lines.append('  else:')
                if isinstance(ann, type) and ann.__module__ == 'builtins':
                    lines.append('    {0} = {1}({0})'.format(
                        name, ann.__name__))
                    fun_params.append(param.replace(
                        default=defname))
                else:
                    lines.append('    {0} = {0}_type({0})'.format(name))
                    vars[name + '_type'] = ann
                    fun_params.append(param.replace(
                        annotation=ReprHack(name + '_type'),
                        default=defname))
        elif not self:
            fun_params.append(param.replace(default=defname))
            nposargs += 1


        if param.kind == inspect.Parameter.VAR_KEYWORD:
            varkw = name
            assert varkw, "Empty argument name?"
        elif param.kind == inspect.Parameter.VAR_POSITIONAL:
            varpos = name
            assert varpos, "Empty argument name?"
        else:
            if param.kind == inspect.Parameter.KEYWORD_ONLY:
                kwargs.append('{0!r}: {0}'.format(name))
            elif not self:
                args.append(name)
        if self:
            self = False
    if not varpos and partial:
        for i, p in enumerate(fun_params):
            if p.kind == inspect.Parameter.KEYWORD_ONLY:
                fun_params.insert(i, inspect.Parameter('__tail__',
                    kind=inspect.Parameter.VAR_POSITIONAL))
                break
        else:
            fun_params.append(inspect.Parameter('__tail__',
                kind=inspect.Parameter.VAR_POSITIONAL))
    if not varkw:
        fun_params.append(inspect.Parameter('__kw__',
            kind=inspect.Parameter.VAR_KEYWORD))
    funsig = inspect.Signature(fun_params)
    lines.insert(0, 'def __sig__{}:'.format(funsig))
    if len(args) == 1:
        args = args[0] + ','
    else:
        args = ', '.join(args)
    kwarg_string = '{' + ', '.join(kwargs) + '}'
    if varkw:
        if kwargs:
            lines.append('  {}.update({})'.format(varkw, kwarg_string))
        kwarg_string = varkw
    if varpos:
        lines.append('  return ({}) + {}, 0, {}'.format(
            args, varpos,  kwarg_string))
    elif partial:
        lines.append('  return ({}), {}, {}'.format(
            args, nposargs, kwarg_string))
    else:
        lines.append('  return ({}), 0, {}'.format(args, kwarg_string))
    text = '\n'.join(lines)
    code = compile(text, '__sig__', 'exec')
    exec(code, vars)
    sigfun = asyncio.coroutine(vars['__sig__'])
    if __debug__:
        sigfun.__text__ = text
    return sigfun
