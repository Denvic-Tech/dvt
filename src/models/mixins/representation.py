class RepresentationMixin:

    @staticmethod
    def convert_long_value(value):
        value = str(value)

        if len(value) > 50:
            value = f"{value[:20]}...{value[-20:]}"

        return value

    def __repr__(self):
        items = " ".join([
            f'{key}={self.convert_long_value(value)}'
            for key, value in self.__dict__.items()
            if not key.startswith('_')
        ])
        return f'<{self.__class__.__name__} {items}>'

    def __str__(self):
        return self.__repr__()
