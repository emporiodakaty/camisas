from __future__ import annotations

import json
import re
import hashlib
from uuid import uuid4
from unicodedata import normalize
from datetime import date, datetime
from decimal import Decimal
from .fields import SafeImageField
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinValueValidator
from django.db import models, IntegrityError, transaction
from django.db.models import IntegerField, Case, When  # ordenação de tamanhos
from django.db.models.fields.files import FieldFile
from django.utils.safestring import mark_safe
from django.utils import timezone
from cloudinary.models import CloudinaryField

# =========================
# Helpers de upload / número
# =========================
def logo_upload_to(instance: "Empresa", filename: str) -> str:
    return f"logos/{instance.pk or 'new'}/{filename}"


def arte_upload_to(instance: "Pedido", filename: str) -> str:
    return f"pedidos/{instance.pk or 'new'}/arte/{filename}"


def gerar_numero_orcamento() -> str:
    now = timezone.now()
    return f"ORC-{now.strftime('%Y%m%d-%H%M')}-{int(now.timestamp())%100000:05d}"


def gen_approval_token() -> str:
    return uuid4().hex


def gerar_numero_remessa() -> str:
    now = timezone.now()
    return f"R{now.strftime('%Y%m%d')}-{int(now.timestamp())%100000:05d}"


UNID_CHOICES = [
    ("m", "Metro"),
    ("un", "Unidade"),
    ("kg", "Quilo"),
    ("rolo", "Rolo"),
]

# Ordem oficial dos tamanhos (camisas)
SIZE_ORDER = ["DIVERSOS", "PP","P","M","G","GG","XGG","PPB","PB","MB","GB","GGB","XGGB"]


def size_order_case(field_name: str) -> Case:
    """Expressão ORDER BY que respeita a ordem de tamanhos declarada em SIZE_ORDER."""
    whens = [When(**{field_name: s, "then": i}) for i, s in enumerate(SIZE_ORDER)]
    return Case(*whens, default=len(SIZE_ORDER), output_field=IntegerField())


# =========================
# Util: tornar estruturas JSON-serializáveis
# =========================
def primitivize(obj):
    """Converte valores (Decimal, datas, FieldFile, modelos, dict/list) para tipos nativos/strings."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, FieldFile):
        return obj.name or ""
    if isinstance(obj, models.Model):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): primitivize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [primitivize(v) for v in obj]
    return obj


# =========================
# Cadastros
# =========================
class Empresa(models.Model):
    nome_fantasia = models.CharField(max_length=120)
    razao_social = models.CharField(max_length=180, blank=True, null=True)
    cnpj = models.CharField(max_length=18, blank=True, null=True)
    ie = models.CharField("Inscrição Estadual", max_length=30, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    telefone = models.CharField(max_length=30, blank=True, null=True)
    endereco = models.CharField(max_length=180, blank=True, null=True)
    cidade = models.CharField(max_length=80, blank=True, null=True)
    uf = models.CharField(max_length=2, blank=True, null=True)
    logo = CloudinaryField("logo", blank=True, null=True)

    class Meta:
        ordering = ("nome_fantasia",)

    def __str__(self) -> str:
        return self.nome_fantasia

    # --- Helpers seguros ---
    @property
    def logo_has_file(self) -> bool:
        f = getattr(self, "logo", None)
        return bool(f and getattr(f, "name", None))

    @property
    def logo_url_safe(self) -> str:
        if not self.logo_has_file:
            return ""
        try:
            return self.logo.url
        except Exception:
            return ""

    def logo_img_tag(self, height: int = 120) -> str:
        """Pré-visualização segura para usar no admin (readonly_fields)."""
        url = self.logo_url_safe
        if not url:
            return "—"
        return mark_safe(
            f'<img src="{url}" style="max-height:{height}px;border:1px solid #eee;padding:4px;border-radius:6px">'
        )

    logo_img_tag.short_description = "Logo"

    # Normaliza registros antigos: evita logo="" (string vazia)
    def save(self, *args, **kwargs):
        f = getattr(self, "logo", None)
        if isinstance(f, str) and f == "":
            self.logo = None
        elif f is not None and getattr(f, "name", None) in ("", None):
            self.logo = None
        super().save(*args, **kwargs)


class ParametrosEmpresa(models.Model):
    empresa = models.OneToOneField(Empresa, on_delete=models.CASCADE, related_name="parametros")
    margem_lucro_padrao = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("30.00"))
    acrescimo_padrao_percentual = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("0.00"))
    desconto_max_percentual = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("15.00"))
    impostos_percentual = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("0.00"))
    taxa_cartao_percentual = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("0.00"))
    custo_energia_mensal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    custo_internet_mensal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    outros_custos_fixos_mensais = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    custo_tinta_percentual = models.DecimalField(max_digits=7, decimal_places=4, default=Decimal("0.0000"))
    arredondar_para = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("1.00"))
    incluir_taxas_no_preco_base = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"Parâmetros • {self.empresa}"


class Cliente(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="clientes")
    nome = models.CharField(max_length=120)
    cpf_cnpj = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    telefone = models.CharField(max_length=30, blank=True, null=True)
    endereco = models.CharField(max_length=180, blank=True, null=True)
    observacoes = models.TextField(blank=True, null=True)

    def __str__(self) -> str:
        return self.nome


class CategoriaInsumo(models.Model):
    nome = models.CharField(max_length=80, unique=True)

    def __str__(self) -> str:
        return self.nome

    @staticmethod
    def seed_basicas():
        basicas = ["Tecido", "Linha", "Etiqueta", "Botão", "Papel de Estampa", "Filme/Transfer", "Caixa/Embalagem"]
        for n in basicas:
            CategoriaInsumo.objects.get_or_create(nome=n)


class Insumo(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="insumos")
    categoria = models.ForeignKey(CategoriaInsumo, on_delete=models.PROTECT, related_name="insumos")
    nome = models.CharField(max_length=120)
    unidade = models.CharField(max_length=10, choices=UNID_CHOICES, default="un")
    estoque_atual = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0"))
    custo_medio = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0"))
    ativo = models.BooleanField(default=True)

    class Meta:
        unique_together = ("empresa", "nome", "unidade")

    def __str__(self) -> str:
        return f"{self.nome} ({self.unidade})"

    def entrada(self, quantidade: Decimal, custo_unit: Decimal, observacao: str = "",
                *, costureira: "Costureira | None" = None, remessa: "Remessa | None" = None):
        quantidade = Decimal(quantidade or 0)
        custo_unit = Decimal(custo_unit or 0)
        total_ant = self.estoque_atual * self.custo_medio
        total_novo = quantidade * custo_unit
        novo_estoque = self.estoque_atual + quantidade
        if novo_estoque > 0:
            self.custo_medio = (total_ant + total_novo) / novo_estoque
        self.estoque_atual = novo_estoque
        self.save()
        MovimentoEstoque.objects.create(
            empresa=self.empresa, tipo="E", insumo=self,
            quantidade=quantidade, custo_unit=custo_unit, observacao=observacao,
            costureira=costureira, remessa=remessa
        )

    def saida(self, quantidade: Decimal, observacao: str = "",
              *, costureira: "Costureira | None" = None, remessa: "Remessa | None" = None):
        quantidade = Decimal(quantidade or 0)
        if quantidade > self.estoque_atual:
            raise ValueError("Estoque insuficiente para saída.")
        self.estoque_atual -= quantidade
        self.save()
        MovimentoEstoque.objects.create(
            empresa=self.empresa, tipo="S", insumo=self,
            quantidade=quantidade, custo_unit=self.custo_medio, observacao=observacao,
            costureira=costureira, remessa=remessa
        )


class Produto(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="produtos")
    nome = models.CharField(max_length=120)
    descricao = models.TextField(blank=True, null=True)
    ativo = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.nome

    def ensure_variacoes_para_tipos(self, tipos=None, preco_sugerido: Decimal = Decimal("0.00")) -> int:
        """
        Garante variações para todos os tipos informados.
        Retorna quantas variações foram criadas.
        """
        tipos = tipos or ["Padrão"]
        created = 0
        for tipo in tipos:
            if not self.variacoes.filter(tipo=tipo).exists():
                base = f"{self.pk}-{tipo}".upper().replace(" ", "")
                sku = base
                n = 1
                while VariacaoProduto.objects.filter(sku=sku).exists():
                    n += 1
                    sku = f"{base}-{n}"
                VariacaoProduto.objects.create(
                    produto=self,
                    tipo=tipo,
                    sku=sku,
                    preco_sugerido=preco_sugerido
                )
                created += 1
        return created



class VariacaoProduto(models.Model):
    produto = models.ForeignKey(
        "Produto",
        on_delete=models.CASCADE,
        related_name="variacoes"
    )
    tipo = models.CharField(max_length=40, default="Padrão")  # <-- substitui cor por tipo
    sku = models.CharField(
        max_length=40,
        unique=True,
        blank=True,
        editable=False,
        db_index=True
    )
    estoque_atual = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    custo_unitario = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0"))
    preco_sugerido = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    class Meta:
        unique_together = ("produto", "tipo")  # <-- atualizado
        verbose_name = "Variação de Produto"
        verbose_name_plural = "Variações de Produtos"

    def __str__(self) -> str:
        return f"{self.produto.nome} / {self.tipo}"

    # ---- helpers p/ SKU ----
    @staticmethod
    def _code(s: str) -> str:
        s = normalize("NFKD", (s or "")).encode("ascii", "ignore").decode()
        return re.sub(r"[^A-Z0-9]+", "", s.upper())

    def _sku_base(self) -> str:
        prod = self._code(getattr(self.produto, "nome", "PROD"))[:8]
        tipo = self._code(self.tipo)
        base = f"{self.produto_id or 'X'}-{prod}-{tipo}".strip("-")
        return base[:36]  # deixa espaço para sufixo -N

    def _generate_unique_sku(self) -> str:
        base = self._sku_base()
        sku = base
        n = 1
        while type(self).objects.filter(sku=sku).exists():
            n += 1
            tail = f"-{n}"
            sku = (base[: (40 - len(tail))] + tail)
        return sku

    def save(self, *args, **kwargs):
        if not self.sku:
            if not self.produto_id and self.produto and not self.produto.pk:
                self.produto.save()
            if not self.produto_id:
                super().save(*args, **kwargs)
            self.sku = self._generate_unique_sku()
        super().save(*args, **kwargs)


# =========================
# Ficha técnica (por variação) com fase de consumo
# =========================
FASE_CONSUMO = (
    ("AUTO", "Automático (por categoria: tecido=corte; demais=costura)"),
    ("CORTE", "Consumir na etapa de Corte"),
    ("COSTURA", "Consumir na etapa de Costura"),
)


def _resolver_fase_item(insumo_categoria_nome: str, fase_config: str) -> str:
    """Resolve se o insumo será baixado no CORTE ou na COSTURA."""
    if fase_config and fase_config != "AUTO":
        return fase_config
    # Heurística simples: 'Tecido' => CORTE; demais => COSTURA
    return "CORTE" if (insumo_categoria_nome or "").strip().lower() == "tecido" else "COSTURA"


class FichaTecnicaItem(models.Model):
    variacao = models.ForeignKey(VariacaoProduto, on_delete=models.CASCADE, related_name="ficha")
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT)
    quantidade = models.DecimalField(max_digits=12, decimal_places=4)
    fase = models.CharField(max_length=10, choices=FASE_CONSUMO, default="AUTO")  # NOVO

    class Meta:
        unique_together = ("variacao", "insumo")


class OrdemProducao(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="ordens")
    variacao = models.ForeignKey(VariacaoProduto, on_delete=models.PROTECT)
    quantidade = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    custo_mao_de_obra = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    custo_indireto_rateado = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    criado_em = models.DateTimeField(default=timezone.now)
    observacao = models.TextField(blank=True, null=True)

    def processar(self) -> Decimal:
        total_insumos = Decimal("0")
        for item in self.variacao.ficha.all():
            qt_total = (item.quantidade * self.quantidade).quantize(Decimal("0.0001"))
            total_insumos += (item.insumo.custo_medio * qt_total)
            item.insumo.saida(qt_total, observacao=f"OP#{self.pk} {self.variacao}")
        total = total_insumos + self.custo_mao_de_obra + self.custo_indireto_rateado
        custo_unit = (total / self.quantidade).quantize(Decimal("0.0001"))
        self.variacao.custo_unitario = custo_unit
        self.variacao.estoque_atual += self.quantidade
        self.variacao.save()
        MovimentoEstoque.objects.create(
            empresa=self.empresa, tipo="E", variacao=self.variacao,
            quantidade=self.quantidade, custo_unit=custo_unit,
            observacao=f"Produção OP#{self.pk}"
        )
        return custo_unit


# =========================
# Vendas / Pedido
# =========================
# imports usados aqui (confira se já existem no topo do models.py)
from decimal import Decimal
from django.db import models, IntegrityError
from django.utils import timezone
from django.core.files.base import ContentFile
import hashlib

# ... seus outros imports (Empresa, Cliente, SafeImageField, gen_approval_token, gerar_numero_orcamento, arte_upload_to, etc.)

class Pedido(models.Model):
    STATUS = (
        ("ORC", "Orçamento"),
        ("PEN", "Pendente"),
        ("PROD", "Em Produção"),
        ("FAT", "Faturado/Entregue"),
        ("CANC", "Cancelado"),
    )

    empresa = models.ForeignKey('Empresa', on_delete=models.PROTECT, related_name="pedidos")
    cliente = models.ForeignKey('Cliente', on_delete=models.PROTECT, related_name="pedidos")
    criado_em = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=4, choices=STATUS, default="ORC")
    observacao = models.TextField(blank=True, null=True)
    desconto_percentual = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("0.00"))
    acrescimo_percentual = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("0.00"))
    data_entrega = models.DateField(blank=True, null=True, verbose_name="Data de entrega")

    # >>> NOVO: controla se o orçamento deve ocultar totais/subtotais <<<
    orcamento_ocultar_total = models.BooleanField(
        default=False,
        help_text="Se marcado, esconde o bloco de totais e a coluna Subtotal no orçamento."
    )

    # orçamento
    numero_orcamento = models.CharField(max_length=40, blank=True, null=True)
    validade = models.DateField(blank=True, null=True)
    condicoes = models.TextField(blank=True, null=True)
    arte = CloudinaryField("arte", blank=True, null=True)


    # aprovação pública (ORÇAMENTO)
    APPROVAL_CHOICES = (("PEND", "Pendente"), ("APRV", "Aprovado"), ("REJ", "Recusado"))
    approval_token = models.CharField(max_length=64, unique=True, db_index=True, default=gen_approval_token, editable=False)
    approval_status = models.CharField(max_length=4, choices=APPROVAL_CHOICES, default="PEND")
    approval_decided_at = models.DateTimeField(blank=True, null=True)
    approval_decision_ip = models.GenericIPAddressField(blank=True, null=True)
    approval_name = models.CharField(max_length=120, blank=True, null=True)
    approval_email = models.EmailField(blank=True, null=True)
    approval_comment = models.TextField(blank=True, null=True)

    approval_signature = SafeImageField(upload_to="assinaturas/%Y/%m", blank=True, null=True)
    approval_user_agent = models.TextField(blank=True, default="")
    approval_timezone = models.CharField(max_length=64, blank=True, default="")
    approval_hash = models.CharField(max_length=64, blank=True, default="")

    # ====== Aprovação pública da ARTE (independente do orçamento) ======
    ART_CHOICES = (("PEND", "Pendente"), ("APRV", "Aprovado"), ("REJ", "Recusado"))
    artwork_token = models.CharField(max_length=64, unique=True, db_index=True, default=gen_approval_token, editable=False)
    artwork_status = models.CharField(max_length=4, choices=ART_CHOICES, default="PEND")
    artwork_decided_at = models.DateTimeField(blank=True, null=True)
    artwork_decision_ip = models.GenericIPAddressField(blank=True, null=True)
    artwork_name = models.CharField(max_length=120, blank=True, null=True)
    artwork_email = models.EmailField(blank=True, null=True)
    artwork_comment = models.TextField(blank=True, null=True)

    artwork_signature = SafeImageField(upload_to="assinaturas/%Y/%m", blank=True, null=True)
    artwork_user_agent = models.TextField(blank=True, default="")
    artwork_timezone = models.CharField(max_length=64, blank=True, default="")
    artwork_hash = models.CharField(max_length=64, blank=True, default="")

    # ---------- totais ----------
    def total_bruto(self) -> Decimal:
        return sum((i.preco_unitario * i.quantidade) for i in self.itens.all()) or Decimal("0.00")

    def total_com_descontos(self) -> Decimal:
        total = self.total_bruto()
        if self.acrescimo_percentual:
            total *= (Decimal("1") + self.acrescimo_percentual / Decimal("100"))
        if self.desconto_percentual:
            total *= (Decimal("1") - self.desconto_percentual / Decimal("100"))
        return total.quantize(Decimal("0.01"))

    # ---------- PAGAMENTOS ----------
    @property
    def total_pago(self) -> Decimal:
        return sum((p.valor for p in self.pagamentos.all()), Decimal("0.00"))

    @property
    def saldo_restante(self) -> Decimal:
        return self.total_com_descontos() - self.total_pago

    def registrar_sinal(self, usuario=None):
        """Registra automaticamente 50% de entrada e muda status para PRODUÇÃO"""
        if self.total_pago > 0:
            return  # evita duplicar

        sinal = (self.total_com_descontos() * Decimal("0.5")).quantize(Decimal("0.01"))
        Pagamento.objects.create(
            pedido=self,
            valor=sinal,
            descricao="Sinal (50%)",
            usuario=usuario,
        )
        self.status = "PROD"
        self.save(update_fields=["status"])

    def registrar_saldo_final(self, usuario=None):
        """Registra o saldo restante e conclui o pedido (FAT)."""
        saldo = self.saldo_restante
        if saldo <= 0:
            return
        Pagamento.objects.create(
            pedido=self,
            valor=saldo,
            descricao="Saldo final",
            usuario=usuario,
        )
        self.status = "FAT"
        self.save(update_fields=["status"])

    # ---------- utilidades ----------
    def save(self, *args, **kwargs):
        if (self.status == "ORC") and not self.numero_orcamento:
            self.numero_orcamento = gerar_numero_orcamento()

        if self._state.adding:
            attempts = 0
            while True:
                try:
                    if not self.approval_token:
                        self.approval_token = gen_approval_token()
                    if not self.artwork_token:
                        self.artwork_token = gen_approval_token()
                    super().save(*args, **kwargs)
                    break
                except IntegrityError:
                    attempts += 1
                    if attempts >= 5:
                        raise
                    self.approval_token = gen_approval_token()
                    self.artwork_token = gen_approval_token()
        else:
            update_fields = kwargs.get("update_fields", None)
            changed = False
            if not self.artwork_token:
                self.artwork_token = gen_approval_token()
                changed = True
            if changed and update_fields is not None:
                kwargs["update_fields"] = None
            super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Pedido #{self.pk} • {self.cliente}"

    # caminhos públicos
    def get_public_approval_path(self) -> str:
        from django.urls import reverse
        return reverse("camisas:orcamento_publico", args=[self.approval_token])

    # arquivos/urls seguros
    @property
    def arte_has_file(self) -> bool:
        f = getattr(self, "arte", None)
        return bool(f and getattr(f, "name", None))

    @property
    def arte_url_safe(self) -> str:
        f = getattr(self, "arte", None)
        return f.url if (f and getattr(f, "name", None)) else ""

    @property
    def approval_has_signature(self) -> bool:
        f = getattr(self, "approval_signature", None)
        return bool(f and getattr(f, "name", None))

    @property
    def approval_signature_url_safe(self) -> str:
        f = getattr(self, "approval_signature", None)
        return f.url if (f and getattr(f, "name", None)) else ""

    @property
    def artwork_has_signature(self) -> bool:
        f = getattr(self, "artwork_signature", None)
        return bool(f and getattr(f, "name", None))

    @property
    def artwork_signature_url_safe(self) -> str:
        f = getattr(self, "artwork_signature", None)
        return f.url if (f and getattr(f, "name", None)) else ""

    @property
    def should_hide_total(self) -> bool:
        return bool(self.orcamento_ocultar_total)


class ItemPedido(models.Model):
    pedido = models.ForeignKey("Pedido", on_delete=models.CASCADE, related_name="itens")
    variacao = models.ForeignKey("VariacaoProduto", on_delete=models.PROTECT)
    quantidade = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))]
    )
    preco_unitario = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))]
    )

    # === NOVOS CAMPOS PARA OPCIONAIS ===
    nome_personalizado = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="Nome impresso na camisa (opcional)"
    )
    numero_camisa = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Número da camisa (opcional)"
    )
    outra_info = models.CharField(
        max_length=120,
        blank=True,
        null=True,
        help_text="Outra informação a ser adicionada (opcional)"
    )
    incluir_short = models.BooleanField(
        default=False,
        help_text="Marque se o pedido inclui short"
    )
    tamanho_short = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Tamanho do short (se incluído)"
    )

    def subtotal(self) -> Decimal:
        return (self.preco_unitario * self.quantidade).quantize(Decimal("0.01"))

    def save(self, *args, **kwargs):
        # Se não informar preço, puxa o sugerido da variação
        if (self.preco_unitario is None or self.preco_unitario == 0) and self.variacao_id:
            self.preco_unitario = self.variacao.preco_sugerido or Decimal("0.00")
        super().save(*args, **kwargs)

    def __str__(self):
        extras = []
        if self.nome_personalizado:
            extras.append(f"Nome: {self.nome_personalizado}")
        if self.numero_camisa:
            extras.append(f"Nº {self.numero_camisa}")
        if self.incluir_short:
            extras.append(f"Short {self.tamanho_short or ''}")
        extras_txt = f" ({', '.join(extras)})" if extras else ""
        return f"{self.variacao} x{self.quantidade}{extras_txt}"
    
# camisas/models.py

class PersonalizacaoItem(models.Model):
    TAM_CAMISA = [
        ("PP", "PP"),
        ("P", "P"),
        ("M", "M"),
        ("G", "G"),
        ("GG", "GG"),
        ("XG", "XG"),
        ("PP-BL", "PP Baby Look"),
        ("P-BL", "P Baby Look"),
        ("M-BL", "M Baby Look"),
        ("G-BL", "G Baby Look"),
        ("GG-BL", "GG Baby Look"),
        ("XG-BL", "XG Baby Look"),
    ]

    TAM_SHORT = [
        ("P", "P"),
        ("M", "M"),
        ("G", "G"),
        ("GG", "GG"),
    ]

    item = models.ForeignKey(
        "ItemPedido",
        related_name="personalizacoes",
        on_delete=models.CASCADE
    )
    nome = models.CharField(max_length=100, blank=True, null=True)
    numero = models.CharField(max_length=10, blank=True, null=True)
    outra_info = models.CharField(max_length=200, blank=True, null=True)
    tamanho_camisa = models.CharField(
        max_length=10,
        choices=TAM_CAMISA,
        blank=True,
        null=True
    )

    # 🔹 quantidade agora é opcional
    quantidade = models.PositiveIntegerField(
        blank=True,
        null=True,
        default=None,
        help_text="Quantidade opcional"
    )

    incluir_short = models.BooleanField(default=False)
    tamanho_short = models.CharField(
        max_length=10,
        choices=TAM_SHORT,
        blank=True,
        null=True
    )

    def __str__(self):
        qtd = f"x{self.quantidade}" if self.quantidade else ""
        return f"{self.nome or ''} {self.numero or ''} {self.tamanho_camisa or ''} {qtd}".strip()



class Costureira(models.Model):
    nome = models.CharField(max_length=120)
    telefone = models.CharField(max_length=40, blank=True, null=True)

    # preços base por peça (podem ser sobrescritos por item na remessa)
    preco_corte_por_peca = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    preco_costura_por_peca = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    preco_correcao_por_peca = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    ativo = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.nome


class Remessa(models.Model):
    TIPO = (
        ("CORTE", "Corte"),
        ("COSTURA", "Costura"),
        ("CORRECAO", "Correção"),
    )
    STATUS = (
        ("ENVIADA", "Enviada"),
        ("PARCIAL", "Parcial"),
        ("CONCLUIDO", "Concluído"),
        ("CANCELADA", "Cancelada"),
    )

    numero = models.CharField(max_length=20, unique=True, db_index=True, default=gerar_numero_remessa, editable=False)
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="remessas")
    costureira = models.ForeignKey(Costureira, on_delete=models.PROTECT, related_name="remessas")
    tipo = models.CharField(max_length=10, choices=TIPO)
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, blank=True, null=True,
                                help_text="(opcional) ajuda a agrupar variações")
    kg_enviados = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"),
                                      help_text="Se enviou tecido/peças por peso")
    enviado_em = models.DateTimeField(default=timezone.now)
    recebido_em = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=12, choices=STATUS, default="ENVIADA")
    observacao = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ("-enviado_em", "-id")

    def __str__(self) -> str:
        return f"{self.numero} • {self.get_tipo_display()} • {self.costureira}"

    # ---- agregações ----
    def total_pecas_previstas(self) -> Decimal:
        return sum((i.qtd_prevista for i in self.itens.all()), Decimal("0"))

    def total_pecas_ok(self) -> Decimal:
        return sum((i.qtd_ok for i in self.itens.all()), Decimal("0"))

    def total_a_pagar(self) -> Decimal:
        return sum((i.a_pagar() for i in self.itens.all()), Decimal("0.00"))

    def preco_base_para_tipo(self) -> Decimal:
        c = self.costureira
        if self.tipo == "CORTE":
            return c.preco_corte_por_peca
        if self.tipo == "COSTURA":
            return c.preco_costura_por_peca
        return c.preco_correcao_por_peca

    def atualizar_status_por_itens(self):
        saldo_total = sum((it.saldo() for it in self.itens.all()), Decimal("0"))
        self.status = "PARCIAL" if (self.recebido_em and saldo_total > 0) else (
            "CONCLUIDO" if (self.recebido_em and saldo_total <= 0) else "ENVIADA"
        )

    def save(self, *args, **kwargs):
        if self._state.adding and not self.numero:
            attempts = 0
            while True:
                try:
                    self.numero = gerar_numero_remessa()
                    super().save(*args, **kwargs)
                    break
                except IntegrityError:
                    attempts += 1
                    if attempts >= 5:
                        raise
        else:
            super().save(*args, **kwargs)

    # ===== FLUXO =====
    @transaction.atomic
    def finalizar_recebimento(self, *, set_recebido_em: bool = True) -> "PagamentoCostureira | None":
        """
        Aplica recebimento:
        - CORTE: baixa insumos (fase CORTE); gera Pagamento.
        - COSTURA: baixa insumos (fase COSTURA); dá ENTRADA no produto; gera Pagamento.
        - CORRECAO: normalmente só pagamento (se houver OK).
        """
        if set_recebido_em and not self.recebido_em:
            self.recebido_em = timezone.now()

        total_pagto = Decimal("0.00")

        itens = (self.itens
                 .select_related("variacao", "variacao__produto")
                 .prefetch_related("variacao__ficha__insumo__categoria"))

        for it in itens:
            qtd_ok = it.qtd_ok or Decimal("0")
            if qtd_ok <= 0:
                continue

            # pagamento
            total_pagto += (it.preco_unitario_efetivo() * qtd_ok)

            # consumo/entrada por tipo
            if self.tipo == "CORTE":
                # baixa insumos de fase CORTE
                for fi in it.variacao.ficha.all():
                    fase_final = _resolver_fase_item(getattr(fi.insumo.categoria, "nome", ""), fi.fase)
                    if fase_final != "CORTE":
                        continue
                    qt_baixa = (fi.quantidade * qtd_ok).quantize(Decimal("0.0001"))
                    fi.insumo.saida(qt_baixa, observacao=f"Corte {self.numero} {it.variacao}",
                                    costureira=self.costureira, remessa=self)

            elif self.tipo == "COSTURA":
                # baixa insumos de fase COSTURA
                for fi in it.variacao.ficha.all():
                    fase_final = _resolver_fase_item(getattr(fi.insumo.categoria, "nome", ""), fi.fase)
                    if fase_final != "COSTURA":
                        continue
                    qt_baixa = (fi.quantidade * qtd_ok).quantize(Decimal("0.0001"))
                    fi.insumo.saida(qt_baixa, observacao=f"Costura {self.numero} {it.variacao}",
                                    costureira=self.costureira, remessa=self)
                # entrada de produto acabado
                it.variacao.estoque_atual += qtd_ok
                it.variacao.save(update_fields=["estoque_atual"])
                MovimentoEstoque.objects.create(
                    empresa=self.empresa, tipo="E", variacao=it.variacao,
                    quantidade=qtd_ok, custo_unit=it.variacao.custo_unitario,
                    costureira=self.costureira, remessa=self,
                    observacao=f"Entrada pós-costura {self.numero}"
                )

            else:  # CORRECAO
                pass

        # status e recebido_em
        self.atualizar_status_por_itens()
        self.save(update_fields=["status", "recebido_em"])

        # cria/atualiza pagamento
        if total_pagto > 0:
            pgto, _ = PagamentoCostureira.objects.update_or_create(
                remessa=self,
                defaults={
                    "empresa": self.empresa,
                    "costureira": self.costureira,
                    "valor_total": total_pagto.quantize(Decimal("0.00")),
                    "status": "PENDENTE",
                },
            )
            return pgto
        return None

    @transaction.atomic
    def gerar_remessa_posterior(self, *, tipo: str, costureira: "Costureira | None" = None) -> "Remessa":
        """
        Ex.: desta remessa (CORTE) -> cria remessa de COSTURA.
        Itens previstos = quantidades OK desta remessa.
        """
        r2 = Remessa.objects.create(
            empresa=self.empresa,
            costureira=costureira or self.costureira,
            tipo=tipo,
            produto=self.produto,
            observacao=f"Gerada a partir da {self.numero}",
            kg_enviados=Decimal("0.000"),
        )
        for it in self.itens.select_related("variacao").all():
            RemessaItem.objects.create(
                remessa=r2,
                variacao=it.variacao,
                qtd_prevista=it.qtd_ok,
            )
        return r2

    @classmethod
    @transaction.atomic
    def criar_com_itens_por_produto(cls, *, empresa, costureira, tipo, produto: Produto | None, kg_enviados=Decimal("0.000")) -> "Remessa":
        """
        Cria a remessa e, se houver produto, popula itens para TODAS as variações do produto,
        ordenadas por tamanho (SIZE_ORDER), com qtd_prevista=0.
        """
        r = cls.objects.create(
            empresa=empresa, costureira=costureira, tipo=tipo, produto=produto, kg_enviados=kg_enviados
        )
        if produto:
            vars_qs = produto.variacoes.annotate(_sz=size_order_case("tamanho")).order_by("_sz", "cor")
            for var in vars_qs:
                RemessaItem.objects.create(remessa=r, variacao=var, qtd_prevista=Decimal("0.00"))
        return r


class RemessaItem(models.Model):
    remessa = models.ForeignKey(Remessa, on_delete=models.CASCADE, related_name="itens")
    variacao = models.ForeignKey(VariacaoProduto, on_delete=models.PROTECT, related_name="itens_remessa")

    # plano
    qtd_prevista = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # retorno
    qtd_ok = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    qtd_perda = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    qtd_extravio = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    qtd_devolvida = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # preço (pode herdar do tipo da remessa/costureira)
    preco_unit = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Se vazio/zero, usa preço padrão da costureira para o tipo da remessa."
    )

    class Meta:
        unique_together = ("remessa", "variacao")

    def __str__(self) -> str:
        return f"{self.remessa.numero} • {self.variacao}"

    def saldo(self) -> Decimal:
        """quanto ainda faltaria para bater a previsão (após ok/perda/extravio/devolvida)"""
        consumido = (self.qtd_ok + self.qtd_perda + self.qtd_extravio + self.qtd_devolvida)
        return (self.qtd_prevista - consumido).quantize(Decimal("0.00"))

    def preco_unitario_efetivo(self) -> Decimal:
        return self.preco_unit or self.remessa.preco_base_para_tipo()

    def a_pagar(self) -> Decimal:
        return (self.preco_unitario_efetivo() * self.qtd_ok).quantize(Decimal("0.00"))


class PagamentoCostureira(models.Model):
    STATUS = (("PENDENTE", "Pendente"), ("PAGO", "Pago"))

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="pagamentos_costureiras")
    costureira = models.ForeignKey(Costureira, on_delete=models.PROTECT, related_name="pagamentos")
    remessa = models.OneToOneField(Remessa, on_delete=models.PROTECT, related_name="pagamento")
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=STATUS, default="PENDENTE")
    criado_em = models.DateTimeField(auto_now_add=True)
    pago_em = models.DateTimeField(blank=True, null=True)
    observacao = models.TextField(blank=True, null=True)

    def __str__(self) -> str:
        return f"Pgto {self.costureira} • {self.remessa.numero} • {self.get_status_display()}"


class MovimentoEstoque(models.Model):
    TIPO = (("E", "Entrada"), ("S", "Saída"))
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="movimentos")
    tipo = models.CharField(max_length=1, choices=TIPO)
    criado_em = models.DateTimeField(default=timezone.now)
    insumo = models.ForeignKey(Insumo, on_delete=models.PROTECT, blank=True, null=True)
    variacao = models.ForeignKey(VariacaoProduto, on_delete=models.PROTECT, blank=True, null=True)

    # vínculos (opcionais) com o fluxo de remessas
    costureira = models.ForeignKey("Costureira", on_delete=models.PROTECT, blank=True, null=True, related_name="movimentos")
    remessa = models.ForeignKey("Remessa", on_delete=models.PROTECT, blank=True, null=True, related_name="movimentos")

    quantidade = models.DecimalField(max_digits=12, decimal_places=4)
    custo_unit = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0"))
    observacao = models.CharField(max_length=160, blank=True, null=True)

    class Meta:
        ordering = ("-criado_em",)

    def __str__(self) -> str:
        alvo = self.insumo or self.variacao
        extra = f" • {self.remessa.numero}" if self.remessa_id else ""
        return f"{self.get_tipo_display()} {alvo} {self.quantidade}{extra}"


# =========================
# Auditoria (logs)
# =========================
class AuditLog(models.Model):
    ACTIONS = (
        ("create", "create"), ("update", "update"), ("delete", "delete"),
        ("approve_quote", "approve_quote"), ("reject_quote", "reject_quote"),
        ("login", "login"), ("logout", "logout"),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    username = models.CharField(max_length=150, blank=True, null=True)
    action = models.CharField(max_length=32, choices=ACTIONS)
    model = models.CharField(max_length=120)
    object_id = models.CharField(max_length=64)
    changes = models.JSONField(blank=True, null=True)
    path = models.CharField(max_length=300, blank=True, null=True)
    method = models.CharField(max_length=10, blank=True, null=True)
    ip = models.CharField(max_length=45, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        who = self.username or (self.user and self.user.get_username()) or "anon"
        return f"[{self.action}] {self.model}#{self.object_id} by {who} @ {self.created_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.changes is not None:
            safe = primitivize(self.changes)
            self.changes = json.loads(json.dumps(safe, cls=DjangoJSONEncoder))
        super().save(*args, **kwargs)

class CategoriaDespesa(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="categorias_despesa", null=True, blank=True)
    nome = models.CharField(max_length=120)

    class Meta:
        verbose_name = "Categoria de Despesa"
        verbose_name_plural = "Categorias de Despesa"
        unique_together = (("empresa", "nome"),)

    def __str__(self):
        return self.nome


class Fornecedor(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="fornecedores", null=True, blank=True)
    nome = models.CharField(max_length=160)
    cpf_cnpj = models.CharField(max_length=20, blank=True, null=True)
    telefone = models.CharField(max_length=40, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)

    class Meta:
        verbose_name = "Fornecedor"
        verbose_name_plural = "Fornecedores"

    def __str__(self):
        return self.nome


class Despesa(models.Model):
    STATUS = (("PEN", "Pendente"), ("PAGA", "Paga"), ("CANC", "Cancelada"))
    FPAG = (("PIX", "PIX"), ("BOLETO", "Boleto"), ("CARTAO", "Cartão"),
            ("TRANSF", "Transferência"), ("DINH", "Dinheiro"), ("OUTRO", "Outro"))

    empresa = models.ForeignKey(Empresa, on_delete=models.PROTECT, related_name="despesas")
    categoria = models.ForeignKey(CategoriaDespesa, on_delete=models.PROTECT, related_name="despesas")
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.PROTECT, related_name="despesas", null=True, blank=True)

    descricao = models.CharField(max_length=240)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    data_emissao = models.DateField(default=timezone.localdate)
    vencimento = models.DateField(null=True, blank=True)

    forma_pagamento = models.CharField(max_length=8, choices=FPAG, default="PIX")
    status = models.CharField(max_length=4, choices=STATUS, default="PEN")

    observacao = models.TextField(blank=True, null=True)
    # anexo (nota/recibo). Usamos FileField normal + helpers "safe"
    anexo = models.FileField(upload_to="despesas/%Y/%m", blank=True, null=True)

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-data_emissao", "-id")

    def __str__(self):
        return f"{self.descricao} • R$ {self.valor_total:.2f}"

    # helpers de arquivo (no mesmo padrão que você usa)
    @property
    def anexo_has_file(self) -> bool:
        f = getattr(self, "anexo", None)
        return bool(f and getattr(f, "name", None))

    @property
    def anexo_url_safe(self) -> str:
        f = getattr(self, "anexo", None)
        if not (f and getattr(f, "name", None)):
            return ""
        try:
            return f.url
        except Exception:
            return ""

    def recalc_from_parcelas(self, save: bool = True):
        """Se usar parcelas, mantém valor_total = soma(parcelas)."""
        total = self.parcelas.aggregate(s=models.Sum("valor"))["s"] or Decimal("0.00")
        self.valor_total = total
        if save:
            self.save(update_fields=["valor_total"])

    def sync_status_from_parcelas(self, save: bool = True):
        """Status = PAGA se todas as parcelas pagas; CANC se todas canceladas; senão PEND."""
        qs = self.parcelas.all()
        if not qs.exists():
            return
        all_paid = qs.filter(status="PAGA").count() == qs.count()
        all_canc = qs.filter(status="CANC").count() == qs.count()
        new = "PAGA" if all_paid else ("CANC" if all_canc else "PEN")
        if new != self.status:
            self.status = new
            if save:
                self.save(update_fields=["status"])


class ParcelaDespesa(models.Model):
    STATUS = (("PEN", "Pendente"), ("PAGA", "Paga"), ("CANC", "Cancelada"))

    despesa = models.ForeignKey(Despesa, on_delete=models.CASCADE, related_name="parcelas")
    numero = models.PositiveIntegerField(default=1)
    vencimento = models.DateField()
    valor = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    status = models.CharField(max_length=4, choices=STATUS, default="PEN")
    pago_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("vencimento", "numero")
        unique_together = (("despesa", "numero"),)

    def __str__(self):
        return f"Parcela {self.numero} de {self.despesa_id} • {self.vencimento}"

    def marcar_paga(self, when=None, save=True):
        self.status = "PAGA"
        self.pago_em = when or timezone.now()
        if save:
            self.save(update_fields=["status", "pago_em"])
            self.despesa.sync_status_from_parcelas(save=True)

class ESignature(models.Model):
    ROLE_CHOICES = [("empresa", "Empresa"), ("cliente", "Cliente")]
    pedido = models.ForeignKey("Pedido", on_delete=models.CASCADE, related_name="esignatures")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)  # "empresa" ou "cliente"
    signer_name = models.CharField(max_length=255)
    signed_at = models.DateTimeField()
    hash = models.CharField(max_length=128, db_index=True)        # HMAC-SHA256 em hex
    qr_data_url = models.TextField(blank=True)                    # data:image/png;base64,...
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-signed_at"]

class CotacaoConcorrente(models.Model):
    pedido = models.ForeignKey("Pedido", on_delete=models.CASCADE, related_name="cotacoes_concorrentes")
    # Empresa "falsa/concorrente"
    empresa_nome = models.CharField(max_length=160)
    cnpj = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    telefone = models.CharField(max_length=40, blank=True, null=True)

    validade = models.DateField(blank=True, null=True)
    observacao = models.TextField(blank=True, null=True)
    criado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-criado_em",)

    def __str__(self) -> str:
        return f"Cotação Concorrente #{self.pk} do Pedido #{self.pedido_id}"

    def total(self) -> Decimal:
        return sum((i.subtotal for i in self.itens.all()), Decimal("0.00"))

class CotacaoConcorrenteItem(models.Model):
    cotacao = models.ForeignKey(CotacaoConcorrente, on_delete=models.CASCADE, related_name="itens")
    item_nome = models.CharField(max_length=200)
    descricao = models.TextField(blank=True, null=True)
    unidade = models.CharField(max_length=10, default="UN")
    quantidade = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1"))
    valor_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ("id",)

    def __str__(self) -> str:
        return f"{self.item_nome} ({self.unidade})"

    @property
    def subtotal(self) -> Decimal:
        return (self.quantidade or 0) * (self.valor_unitario or 0)
    
# camisas/models.py
import uuid
from decimal import Decimal
from django.db import models

class OrcamentoExpress(models.Model):
    STATUS = (
        ("pendente", "Pendente"),
        ("aprovado", "Aprovado"),
        ("recusado", "Recusado"),
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    validade = models.DateField(null=True, blank=True)

    cliente_nome = models.CharField(max_length=120)
    cliente_whatsapp = models.CharField(max_length=20, help_text="Somente números. Ex: 63999999999")
    observacoes = models.TextField(blank=True, default="")

    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=12, choices=STATUS, default="pendente")
    aprovado_em = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Orçamento #{self.pk} - {self.cliente_nome}"

class OrcamentoExpressItem(models.Model):
    orcamento = models.ForeignKey(OrcamentoExpress, related_name="itens", on_delete=models.CASCADE)
    descricao = models.CharField(max_length=255)
    unidade = models.CharField(max_length=16, blank=True, default="")
    quantidade = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    valor_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    @property
    def subtotal(self):
        return (self.quantidade or 0) * (self.valor_unitario or 0)

# camisas/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone
from datetime import datetime, timedelta, date

class Funcionario(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        help_text="Opcional: vincular a um usuário do sistema"
    )
    nome = models.CharField(max_length=120)
    ativo = models.BooleanField(default=True)

    # Configuração individual
    jornada_diaria_min = models.PositiveIntegerField(default=480, help_text="Minutos/dia. Ex.: 480 = 8h")
    almoco_min = models.PositiveIntegerField(default=120, help_text="Minutos de almoço. Ex.: 120 = 2h")

    # (Opcional) horários contratados padrão — usados como sugestão no formulário
    h_in_manha   = models.TimeField(null=True, blank=True)
    h_out_manha  = models.TimeField(null=True, blank=True)
    h_in_tarde   = models.TimeField(null=True, blank=True)
    h_out_tarde  = models.TimeField(null=True, blank=True)

    def __str__(self):
        return self.nome


class FrequenciaDia(models.Model):
    """Um registro por funcionário por dia com até 4 batidas."""
    funcionario = models.ForeignKey(Funcionario, related_name="frequencias", on_delete=models.CASCADE)
    data = models.DateField()

    e1 = models.TimeField("Entrada manhã", null=True, blank=True)
    s1 = models.TimeField("Saída manhã",   null=True, blank=True)
    e2 = models.TimeField("Entrada tarde", null=True, blank=True)
    s2 = models.TimeField("Saída tarde",   null=True, blank=True)

    observacao = models.CharField(max_length=240, blank=True, default="")
    # Permite ajustar a meta de minutos só nesse dia (feriado/plantão/etc.)
    minutos_previstos_override = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("funcionario", "data")
        ordering = ["-data"]

    def __str__(self):
        return f"{self.funcionario} – {self.data:%d/%m/%Y}"

    # ---- Cálculos ----
    @property
    def minutos_previstos(self) -> int:
        return self.minutos_previstos_override or self.funcionario.jornada_diaria_min

    def _diff_minutes(self, t_ini, t_fim):
        """diferença em minutos, lidando com virada de dia (raríssimo no caso)."""
        if not (t_ini and t_fim):
            return 0
        dt = datetime.combine(self.data, t_fim) - datetime.combine(self.data, t_ini)
        mins = int(dt.total_seconds() // 60)
        if mins < 0:
            mins += 24 * 60
        return mins

    def minutos_trabalhados_fechado(self) -> int:
        """Somente períodos fechados (s1 e s2 informados)."""
        return self._diff_minutes(self.e1, self.s1) + self._diff_minutes(self.e2, self.s2)

    def minutos_trabalhados_ate_agora(self) -> int:
        """
        Considera períodos em aberto e o horário atual (útil no dia corrente).
        """
        total = self._diff_minutes(self.e1, self.s1)
        total += self._diff_minutes(self.e2, self.s2)

        now = timezone.localtime()
        hoje = now.date()

        # Se é o dia corrente e existe período aberto, soma parcial até agora
        if self.data == hoje:
            if self.e2 and not self.s2:
                # tarde em curso
                parcial = int((datetime.combine(self.data, now.time()) - datetime.combine(self.data, self.e2)).total_seconds() // 60)
                if parcial > 0:
                    total += parcial
            elif self.e1 and not self.s1 and not self.e2:
                # manhã em curso
                parcial = int((datetime.combine(self.data, now.time()) - datetime.combine(self.data, self.e1)).total_seconds() // 60)
                if parcial > 0:
                    total += parcial
        return max(0, total)

    def saldo_minutos(self) -> int:
        """Trabalhado (fechado) - Previsto."""
        return self.minutos_trabalhados_fechado() - self.minutos_previstos

    def saldo_minutos_corrente(self) -> int:
        """Trabalhado até agora - Previsto (para o dia corrente/incompleto)."""
        return self.minutos_trabalhados_ate_agora() - self.minutos_previstos

    # Formatações
    @staticmethod
    def fmt_hhmm(minutos: int) -> str:
        neg = minutos < 0
        m = abs(minutos)
        h, mi = divmod(m, 60)
        return f"-{h:02d}:{mi:02d}" if neg else f"{h:02d}:{mi:02d}"

# camisas/models.py
from django.db import models
from django.utils import timezone
import secrets

class ColetaPedido(models.Model):
    MODO_SIMPL = "SIMPLES"  # só quantidades por tamanho
    MODO_NOMES = "NOMES"    # tamanhos + nomes (opcional número)
    MODO_TIME  = "TIME"     # time: nome + número + tamanho (uma linha por pessoa)

    MODOS = [
        (MODO_SIMPL, "Quantidades por tamanho"),
        (MODO_NOMES, "Tamanhos + nomes"),
        (MODO_TIME,  "Time (nome + número + tamanho)"),
    ]

    pedido   = models.ForeignKey(
        "camisas.Pedido",
        on_delete=models.CASCADE,
        related_name="coletas"
    )
    # 🔹 agora cada coleta sabe qual item de pedido ela está personalizando
    item     = models.ForeignKey(
        "camisas.ItemPedido",
        on_delete=models.PROTECT,
        related_name="coletas",
        null=True, blank=True
    )

    modo     = models.CharField(max_length=12, choices=MODOS, default=MODO_SIMPL)
    token    = models.CharField(max_length=40, unique=True, db_index=True)
    expiracao     = models.DateTimeField(blank=True, null=True)
    criado_em     = models.DateTimeField(auto_now_add=True)
    concluido_em  = models.DateTimeField(blank=True, null=True)

    # quem preencheu
    cliente_nome  = models.CharField(max_length=120, blank=True, null=True)
    cliente_email = models.EmailField(blank=True, null=True)
    obs_cliente   = models.TextField(blank=True, null=True)

    # Resultado bruto (flexível)
    payload = models.JSONField(default=dict, blank=True)

    def __str__(self):  # admin
        return f"Coleta #{self.pk} • Pedido {self.pedido_id} • {self.get_modo_display()}"

    @staticmethod
    def novo_token() -> str:
        return secrets.token_urlsafe(16)

    @property
    def is_expirado(self) -> bool:
        return bool(self.expiracao and timezone.now() > self.expiracao)

    @property
    def is_concluido(self) -> bool:
        return bool(self.concluido_em)

    @property
    def public_path(self) -> str:
        from django.urls import reverse
        return reverse("camisas:coleta_public", kwargs={"token": self.token})

class PessoaColeta(models.Model):
    coleta = models.ForeignKey(ColetaPedido, on_delete=models.CASCADE, related_name="pessoas")
    nome = models.CharField(max_length=120)
    numero = models.CharField(max_length=10, blank=True, null=True)  # camisa com número (opcional)
    tamanho = models.CharField(max_length=10, blank=True, null=True)
    
    # Pagamento
    valor = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status_pagamento = models.CharField(
        max_length=10,
        choices=[("pendente", "Pendente"), ("pago", "Pago")],
        default="pendente"
    )
    pago_em = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"{self.nome} ({self.tamanho}) - {self.get_status_pagamento_display()}"

from django.db import models
from django.conf import settings

class Pagamento(models.Model):
    FORMA_CHOICES = (
        ("PIX", "Pix"),
        ("CRED", "Cartão de Crédito"),
        ("DEB", "Cartão de Débito"),
        ("DIN", "Dinheiro"),
    )

    pedido = models.ForeignKey(
        "Pedido", 
        on_delete=models.CASCADE, 
        related_name="pagamentos"
    )
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    data = models.DateTimeField(auto_now_add=True)
    descricao = models.CharField(
        max_length=120, 
        blank=True, 
        null=True,
        help_text="Ex: Sinal, Saldo final, Entrada"
    )
    forma = models.CharField(
        max_length=10, 
        choices=FORMA_CHOICES, 
        default="PIX"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )

    class Meta:
        ordering = ["data"]

    def __str__(self):
        return f"{self.get_forma_display()} {self.valor} em {self.data:%d/%m/%Y}"

