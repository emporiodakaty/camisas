# camisas/audit.py
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from django.forms.models import model_to_dict
from django.utils.module_loading import import_string
from .middleware import get_current_request, get_current_user
from .models import AuditLog

# Quais modelos auditar automaticamente:
AUDIT_MODELS = [
    "camisas.models.Empresa",
    "camisas.models.Cliente",
    "camisas.models.Produto",
    "camisas.models.VariacaoProduto",
    "camisas.models.Insumo",
    "camisas.models.Pedido",
    "camisas.models.ItemPedido",
    "camisas.models.OrdemProducao",
]

def is_audited(instance):
    full = f"{instance.__class__.__module__}.{instance.__class__.__name__}"
    return full in AUDIT_MODELS

def to_dict(instance):
    # evita serializar campos pesados/arquivos
    data = model_to_dict(instance)
    for k,v in list(data.items()):
        if hasattr(v, "read") or k.endswith("arquivo") or k.endswith("arte"):
            data[k] = str(v) if v else None
    return data

@receiver(pre_save)
def _pre_save_snapshot(sender, instance, **kwargs):
    if not is_audited(instance) or not instance.pk:
        return
    try:
        old = sender.objects.get(pk=instance.pk)
        instance.___audit_old = to_dict(old)
    except sender.DoesNotExist:
        instance.___audit_old = None

@receiver(post_save)
def _post_save_log(sender, instance, created, **kwargs):
    if not is_audited(instance):
        return
    req = get_current_request()
    usr = get_current_user()
    old = getattr(instance, "___audit_old", None)
    new = to_dict(instance)

    changes = None
    action = "create" if created else "update"
    if created:
        changes = {k: [None, new[k]] for k in new}
    else:
        diff = {}
        if old:
            for k in new:
                if old.get(k) != new.get(k):
                    diff[k] = [old.get(k), new.get(k)]
        changes = diff or None

    AuditLog.objects.create(
        user=usr if (usr and usr.is_authenticated) else None,
        username=(usr.get_username() if usr and usr.is_authenticated else None),
        action=action,
        model=instance.__class__.__name__,
        object_id=str(instance.pk),
        changes=changes,
        path=(req.path if req else None),
        method=(req.method if req else None),
        ip=(req.META.get("REMOTE_ADDR") if req else None),
        user_agent=(req.META.get("HTTP_USER_AGENT") if req else None),
    )

@receiver(post_delete)
def _post_delete_log(sender, instance, **kwargs):
    if not is_audited(instance):
        return
    req = get_current_request()
    usr = get_current_user()
    AuditLog.objects.create(
        user=usr if (usr and usr.is_authenticated) else None,
        username=(usr.get_username() if usr and usr.is_authenticated else None),
        action="delete",
        model=instance.__class__.__name__,
        object_id=str(getattr(instance, "pk", None) or "—"),
        changes=None,
        path=(req.path if req else None),
        method=(req.method if req else None),
        ip=(req.META.get("REMOTE_ADDR") if req else None),
        user_agent=(req.META.get("HTTP_USER_AGENT") if req else None),
    )

# helper para registrar ações customizadas (ex.: aprovar orçamento)
def log_custom_action(action: str, instance, extra_changes=None):
    req = get_current_request()
    usr = get_current_user()
    AuditLog.objects.create(
        user=usr if (usr and usr.is_authenticated) else None,
        username=(usr.get_username() if usr and usr.is_authenticated else None),
        action=action,
        model=instance.__class__.__name__,
        object_id=str(instance.pk),
        changes=extra_changes or None,
        path=(req.path if req else None),
        method=(req.method if req else None),
        ip=(req.META.get("REMOTE_ADDR") if req else None),
        user_agent=(req.META.get("HTTP_USER_AGENT") if req else None),
    )
