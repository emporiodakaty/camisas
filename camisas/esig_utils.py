# camisas/esig_utils.py
from django.conf import settings
import hashlib, base64, io

try:
    import qrcode
except Exception:
    qrcode = None


def canonical_payload(pedido_id, role, signer_name, signed_at):
    """
    Gera uma string canônica e estável com os campos da assinatura.
    Aceita datetime em 'signed_at' e converte para ISO 8601.
    """
    if hasattr(signed_at, "isoformat"):
        signed_at = signed_at.isoformat()
    # Normaliza tipos/espacos
    pid = int(pedido_id)
    role = (role or "").strip()
    signer_name = (signer_name or "").strip()
    signed_at = str(signed_at)
    return f"{pid}|{role}|{signer_name}|{signed_at}"


def compute_hash(
    pedido_id=None,
    role=None,
    signer_name=None,
    signed_at=None,
    payload: str | None = None,
    secret: str | None = None,
):
    """
    Calcula o hash SHA-256. Pode receber:
    - payload pronto (string), OU
    - os campos (pedido_id, role, signer_name, signed_at) para montar o payload canônico.
    """
    if payload is None:
        payload = canonical_payload(pedido_id, role, signer_name, signed_at)
    secret = secret or settings.SECRET_KEY
    msg = f"{payload}|{secret}"
    return hashlib.sha256(msg.encode("utf-8")).hexdigest()


def make_qr_data_url(text: str | None) -> str | None:
    """
    Gera um data URL (PNG base64) de QR Code para 'text'.
    Requer 'qrcode[pil]'; se não estiver instalado, retorna None.
    """
    if not text or not qrcode:
        return None
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"
