class Scope(str):
    __slots__ = ['name']

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return '<Scope {}>'.format(self.name)

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)
