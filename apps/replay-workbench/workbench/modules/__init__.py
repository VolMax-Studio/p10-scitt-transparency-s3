"""Built-in module registry. A module is selected by the application, never by an uploaded archive."""


def default_module():
    from .s3 import S3Module
    return S3Module.shipped()
