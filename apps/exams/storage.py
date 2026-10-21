from django.utils.deconstruct import deconstructible
from django.conf import settings
from django.core.files.storage import FileSystemStorage


@deconstructible
class PrivateFileSystemStorage(FileSystemStorage):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('location', settings.PRIVATE_MEDIA_ROOT)
        kwargs.setdefault('base_url', '/private-files-not-served/')
        super().__init__(*args, **kwargs)

    def url(self, _name):
        raise ValueError('Private answer sheets must be served through the authorized download endpoint.')

    def deconstruct(self):
        return (f'{self.__class__.__module__}.{self.__class__.__name__}', (), {})
