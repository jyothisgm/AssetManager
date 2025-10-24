# common/utils/storage.py
from django.conf import settings
from django.utils.module_loading import import_string


def get_dynamic_storage():
    """
    Returns an instance of the storage backend defined in
    settings.DEFAULT_FILE_STORAGE (local, GCS, S3, etc.)
    Works for Django 5.2+ and older versions.
    """
    storage_path = getattr(
        settings,
        "DEFAULT_FILE_STORAGE",
        "django.core.files.storage.FileSystemStorage",
    )
    StorageClass = import_string(storage_path)
    return StorageClass()
