# camisas/views_esig.py
from decimal import Decimal
from datetime import datetime
import inspect
import hashlib

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from .models import Pedido
try:
    from .models import ESignature
except Exception:
    ESignature = None

# importa helpers reais do seu projeto
from .esig_utils import canonical_payload, compute_hash, make_qr_data_url


def _as_decimal(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _call_canonical_payload(pedido_id, role, signer_name, signed_at, total, modalidade, validade):
    """Adapta à assinatura do seu canonical_payload (7, 4, 1 dict, etc.)."""
    sig = inspect.signature(canonical_payload)
    required_pos = [
        p for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty
    ]
    arity = len(required_pos)

    if arity >= 7:
        return canonical_payload(pedido_id, role, signer_name, signed_at, total, modalidade, validade)

    if arity == 4:
        return canonical_payload(pedido_id, role, signer_name, signed_at)

    if arity == 1:
        payload = {
            "pedido_id": pedido_id,
            "role": role,
            "signer_name": signer_name,
            "signed_at": signed_at.isoformat(),
            "total": str(total),
            "modalidade": modalidade,
            "validade": validade,
        }
        return canonical_payload(payload)

    # Fallback local se a assinatura for algo diferente
    return (
        f"pedido={pedido_id}|role={role}|signer={signer_name}|"
        f"signed_at={signed_at.isoformat()}|total={total:.2f}|"
        f"modalidade={modalidade}|validade={validade}"
    )


def _call_compute_hash(payload_str, pedido_id, role, signer_name, signed_at, total, modalidade, validade):
    """
    Adapta à assinatura do seu compute_hash:
      - 7 args: compute_hash(pedido_id, role, signer_name, signed_at, total, modalidade, validade)
      - 4 args: compute_hash(pedido_id, role, signer_name, signed_at)
      - 1 arg : compute_hash(payload_str)
    Fallback: SHA-256 do payload_str.
    """
    sig = inspect.signature(compute_hash)
    required_pos = [
        p for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty
    ]
    arity = len(required_pos)

    try:
        if arity >= 7:
            return compute_hash(pedido_id, role, signer_name, signed_at, total, modalidade, validade)
        if arity == 4:
            return compute_hash(pedido_id, role, signer_name, signed_at)
        if arity == 1:
            return compute_hash(payload_str)

        # Tenta por kwargs nomeados (caso a função aceite kwargs flexíveis)
        return compute_hash(
            pedido_id=pedido_id, role=role, signer_name=signer_name, signed_at=signed_at,
            total=total, modalidade=modalidade, validade=validade, payload=payload_str
        )
    except Exception:
        # Fallback: hash local SHA-256 do payload canônico
        return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()


@login_required
@require_POST
def esign_create(request, pk):
    """Gera assinatura eletrônica da EMPRESA para o Pedido <pk>."""
    pedido = get_object_or_404(Pedido, pk=pk)

    role = (request.POST.get("role") or "empresa").strip().lower()
    signer_name = (getattr(pedido.empresa, "nome_fantasia", None) or "").strip() or "Empresa"
    signed_at = timezone.now()

    modalidade = request.POST.get("modalidade") or request.GET.get("mod") or "Cotação"
    if getattr(pedido, "validade", None):
        validade = pedido.validade.strftime("%d/%m/%Y")
    else:
        validade = request.POST.get("validade") or request.GET.get("val") or "30 dias"

    total = _as_decimal(pedido.total_com_descontos())

    # 1) Monta o payload canônico compatível
    payload_str = _call_canonical_payload(
        pedido.id, role, signer_name, signed_at, total, modalidade, validade
    )

    # 2) Calcula o hash compatível com o compute_hash do seu projeto
    sig_hash = _call_compute_hash(
        payload_str, pedido.id, role, signer_name, signed_at, total, modalidade, validade
    )

    # 3) QR/URL de verificação
    verify_url = request.build_absolute_uri(
        reverse("camisas:esign_verify") +
        f"?p={pedido.pk}&r={role}&t={signed_at.isoformat()}&h={sig_hash}"
        f"&mod={modalidade}&val={validade}"
    )
    qr_data_url = make_qr_data_url(verify_url)

    # 4) Persiste (se houver modelo)
    if ESignature is not None:
        try:
            ESignature.objects.create(
                pedido=pedido,
                role=role,
                signer_name=signer_name,
                signed_at=signed_at,
                hash=sig_hash,
                qr_data_url=qr_data_url,
                payload=payload_str,
            )
        except Exception:
            # se a tabela/modelo não existir, apenas segue sem persistir
            pass

    return JsonResponse({
        "ok": True,
        "hash": sig_hash,
        "qr_data_url": qr_data_url,
        "signed_at": signed_at.isoformat(),
        "verify_url": verify_url,
    })


@login_required
def esign_verify(request):
    """Recalcula o hash e informa se confere com o 'h' informado."""
    p = request.GET.get("p")
    r = (request.GET.get("r") or "").strip().lower()
    t = request.GET.get("t")
    h = request.GET.get("h")
    modalidade = request.GET.get("mod") or "Cotação"
    validade = request.GET.get("val") or "30 dias"

    if not all([p, r, t, h]):
        return HttpResponseBadRequest("Parâmetros obrigatórios: p, r, t, h")

    pedido = get_object_or_404(Pedido, pk=p)

    try:
        dt = datetime.fromisoformat(t)
        signed_at = dt if dt.tzinfo else timezone.make_aware(dt, timezone.get_current_timezone())
    except Exception:
        return HttpResponseBadRequest("Parâmetro 't' inválido (ISO 8601).")

    signer_name = (getattr(pedido.empresa, "nome_fantasia", None) or "").strip() or "Empresa"
    total = _as_decimal(pedido.total_com_descontos())

    payload_str = _call_canonical_payload(
        pedido.id, r, signer_name, signed_at, total, modalidade, validade
    )
    expected_hash = _call_compute_hash(
        payload_str, pedido.id, r, signer_name, signed_at, total, modalidade, validade
    )

    return JsonResponse({
        "ok": True,
        "match": (expected_hash == h),
        "expected": expected_hash,
        "given": h,
        "pedido": pedido.pk,
        "role": r,
        "signer_name": signer_name,
        "signed_at": signed_at.isoformat(),
    })
