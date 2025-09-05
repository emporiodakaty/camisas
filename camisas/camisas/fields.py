# camisas/fields.py
from django.db.models.fields.files import ImageField, ImageFieldFile

class SafeImageFieldFile(ImageFieldFile):
    # ---- url ----
    @property
    def url(self):
        if not self.name:
            return ""
        try:
            return super().url
        except Exception:
            return ""

    # ---- path ----
    @property
    def path(self):
        if not self.name:
            return ""
        try:
            return super().path
        except Exception:
            return ""

    # ---- file (com getter seguro, PRESERVANDO setter/deleter) ----
    _base_file_prop = ImageFieldFile.file  # property original (tem fget/fset/fdel)

    def _get_file(self):
        if not self.name:
            return None
        try:
            return SafeImageFieldFile._base_file_prop.fget(self)
        except Exception:
            return None

    def _set_file(self, value):
        # delega para o setter original (necessário para o Django atribuir o arquivo)
        return SafeImageFieldFile._base_file_prop.fset(self, value)

    def _del_file(self):
        return SafeImageFieldFile._base_file_prop.fdel(self)

    file = property(_get_file, _set_file, _del_file)

class SafeImageField(ImageField):
    attr_class = SafeImageFieldFile
