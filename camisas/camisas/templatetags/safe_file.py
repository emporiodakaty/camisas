# camisas/fields.py  (se ainda não tiver)
from django.db.models.fields.files import ImageField, ImageFieldFile

class SafeImageFieldFile(ImageFieldFile):
    @property
    def url(self):
        # retorna string vazia se não houver arquivo (em vez de ValueError)
        return super().url if self.name else ""

class SafeImageField(ImageField):
    attr_class = SafeImageFieldFile
