# camisas/apps.py
from django.apps import AppConfig
from django.db.models.signals import post_migrate

class CamisasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "camisas"

    def ready(self):
        # importa signals
        from . import audit  # noqa

        # aplica patch seguro em FieldFile e em TODAS as subclasses (ex.: SafeImageFieldFile)
        self._patch_fieldfile_tree()

        # cria/atualiza grupos após migrações
        def create_groups(sender, **kwargs):
            from django.contrib.auth.models import Group, Permission
            WANT = {
                "Vendas": [
                    "view_pedido","add_pedido","change_pedido",
                    "view_itempedido","add_itempedido","change_itempedido",
                    "view_cliente","add_cliente","change_cliente",
                ],
                "Producao": [
                    "view_ordemproducao","add_ordemproducao","change_ordemproducao",
                    "view_variacaoproduto","change_variacaoproduto",
                ],
                "Financeiro": ["view_pedido","change_pedido"],
                "Admin (App)": ["__all__"],
            }
            perms_all = Permission.objects.filter(content_type__app_label="camisas")
            perms_by_code = {p.codename: p for p in perms_all}

            for gname, codes in WANT.items():
                g, _ = Group.objects.get_or_create(name=gname)
                current = set(g.permissions.filter(content_type__app_label="camisas"))
                desired = set(perms_all) if "__all__" in codes else {
                    perms_by_code[c] for c in codes if c in perms_by_code
                }
                to_add = desired - current
                to_remove = current - desired
                if to_remove: g.permissions.remove(*to_remove)
                if to_add:    g.permissions.add(*to_add)

        post_migrate.connect(
            create_groups,
            sender=self,
            dispatch_uid="camisas.create_groups_once",
            weak=False,
        )

    # --------- PATCH EM FIELD FILE (base + subclasses) ---------
    def _patch_fieldfile_tree(self):
        """
        Deixa .url/.path/.file 'seguros' quando não há arquivo:
          - url/path: retornam "" em vez de exception
          - file: retorna None, preservando setter/deleter originais
        Aplica em FieldFile e em TODAS as subclasses (ex.: SafeImageFieldFile).
        """
        from django.db.models.fields.files import FieldFile

        if getattr(FieldFile, "_camisas_safe_patched_tree", False):
            return

        # pega as properties originais da classe base
        base_url  = FieldFile.url
        base_path = FieldFile.path
        base_file = FieldFile.file  # tem fget/fset/fdel válidos

        def make_safe_prop(prop_obj, empty_value):
            """Cria um getter que devolve empty_value se não houver name ou der erro."""
            def _get(self):
                if not getattr(self, "name", None):
                    return empty_value
                try:
                    return prop_obj.fget(self)
                except Exception:
                    return empty_value
            return _get

        def patch_class(cls):
            # Evita repatch
            if getattr(cls, "_camisas_safe_patched_tree_cls", False):
                return

            # url
            prop = getattr(cls, "url", None)
            if isinstance(prop, property):
                cls.url = property(
                    make_safe_prop(prop, ""),
                    None,
                    None,
                    getattr(prop, "__doc__", None),
                )

            # path
            prop = getattr(cls, "path", None)
            if isinstance(prop, property):
                cls.path = property(
                    make_safe_prop(prop, ""),
                    None,
                    None,
                    getattr(prop, "__doc__", None),
                )

            # file (preserva setter/deleter; se subclasse não tiver setter, usa o da base)
            prop = getattr(cls, "file", None)
            if isinstance(prop, property):
                fset = prop.fset or base_file.fset
                fdel = prop.fdel or base_file.fdel
                cls.file = property(
                    make_safe_prop(prop, None),
                    fset,
                    fdel,
                    getattr(prop, "__doc__", None),
                )

            cls._camisas_safe_patched_tree_cls = True

        # patch na base
        patch_class(FieldFile)

        # patch recursivo em todas as subclasses (inclui SafeImageFieldFile)
        def walk(subcls):
            for c in subcls.__subclasses__():
                patch_class(c)
                walk(c)
        walk(FieldFile)

        FieldFile._camisas_safe_patched_tree = True
