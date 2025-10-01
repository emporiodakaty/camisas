# camisas/admin.py
from decimal import Decimal
from django import forms
from django.contrib import admin, messages
from django.contrib.admin.sites import AlreadyRegistered
from django.db.models import F, Sum, DecimalField, ExpressionWrapper
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.apps import apps

from .models import (
    # Cadastros
    Empresa, ParametrosEmpresa, Cliente,
    CategoriaInsumo, Insumo,
    Produto, VariacaoProduto,
    FichaTecnicaItem,

    # Produção
    OrdemProducao,

    # Vendas / Pedido
    Pedido, ItemPedido, PersonalizacaoItem, Pagamento,

    # Fluxo externo
    Costureira, Remessa, RemessaItem, PagamentoCostureira,

    # Estoque / Auditoria
    MovimentoEstoque, AuditLog,

    # Financeiro
    CategoriaDespesa, Fornecedor, Despesa, ParcelaDespesa,

    # Concorrentes
    CotacaoConcorrente, CotacaoConcorrenteItem,

    # RH / Ponto
    Funcionario, FrequenciaDia,

    # Coleta
    ColetaPedido, PessoaColeta,

    # Assinaturas / Orçamentos Express
    ESignature, OrcamentoExpress, OrcamentoExpressItem,

    # Designer / Artes
    ArteDesign,
)

# ==== helpers ================================================================
Money = DecimalField(max_digits=18, decimal_places=2)
ITEM_SUBTOTAL_EXPR = ExpressionWrapper(
    F("itens__preco_unitario") * F("itens__quantidade"),
    output_field=Money,
)

# =============================================================================
# Inlines
# =============================================================================
class ItemPedidoInline(admin.TabularInline):
    model = ItemPedido
    extra = 0
    raw_id_fields = ("variacao",)
    fields = ("variacao", "quantidade", "preco_unitario", "subtotal_display")
    readonly_fields = ("subtotal_display",)

    def subtotal_display(self, obj):
        if not obj.pk:
            return "-"
        try:
            return f"R$ {obj.subtotal():.2f}"
        except Exception:
            return "-"
    subtotal_display.short_description = "Subtotal"

class PersonalizacaoItemInline(admin.TabularInline):
    model = PersonalizacaoItem
    extra = 0
    fields = ("nome", "numero", "tamanho_camisa", "quantidade", "incluir_short", "tamanho_short", "outra_info")

class RemessaItemInline(admin.TabularInline):
    model = RemessaItem
    extra = 0
    raw_id_fields = ("variacao",)
    fields = (
        "variacao", "qtd_prevista",
        "qtd_ok", "qtd_perda", "qtd_extravio", "qtd_devolvida",
        "preco_unit", "a_pagar_display",
    )
    readonly_fields = ("a_pagar_display",)

    def a_pagar_display(self, obj):
        try:
            return f"R$ {obj.a_pagar():.2f}"
        except Exception:
            return "R$ 0,00"
    a_pagar_display.short_description = "A pagar (item)"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # VariacaoProduto usa 'tipo'
        return qs.select_related("variacao", "variacao__produto").order_by(
            "variacao__produto__nome", "variacao__tipo"
        )

class ParcelaInline(admin.TabularInline):
    model = ParcelaDespesa
    extra = 0
    fields = ("numero", "vencimento", "valor", "status", "pago_em")
    readonly_fields = ("pago_em",)
    ordering = ("numero",)

class CotacaoConcorrenteItemInline(admin.TabularInline):
    model = CotacaoConcorrenteItem
    extra = 0

class OrcamentoExpressItemInline(admin.TabularInline):
    model = OrcamentoExpressItem
    extra = 0
    fields = ("descricao", "unidade", "quantidade", "valor_unitario", "subtotal_display")
    readonly_fields = ("subtotal_display",)
    def subtotal_display(self, obj):
        try:
            return f"R$ {obj.subtotal:.2f}"
        except Exception:
            return "R$ 0,00"
    subtotal_display.short_description = "Subtotal"

# =============================================================================
# Empresa / Parâmetros / Cliente
# =============================================================================
@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nome_fantasia", "tem_logo")
    readonly_fields = ("logo_img_tag",)
    fields = (
        "nome_fantasia","razao_social","cnpj","ie","email","telefone",
        "endereco","cidade","uf","logo","logo_img_tag"
    )

    def tem_logo(self, obj):
        return obj.logo_has_file
    tem_logo.boolean = True
    tem_logo.short_description = "Logo?"

@admin.register(ParametrosEmpresa)
class ParametrosEmpresaAdmin(admin.ModelAdmin):
    list_display = ("empresa", "margem_lucro_padrao", "impostos_percentual", "taxa_cartao_percentual")
    search_fields = ("empresa__nome_fantasia",)
    raw_id_fields = ("empresa",)

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "telefone", "email")
    search_fields = ("nome", "cpf_cnpj", "email", "telefone")
    list_filter = ("empresa",)
    raw_id_fields = ("empresa",)

# =============================================================================
# Categoria / Insumo
# =============================================================================
@admin.register(CategoriaInsumo)
class CategoriaInsumoAdmin(admin.ModelAdmin):
    list_display = ("nome",)
    search_fields = ("nome",)

@admin.register(Insumo)
class InsumoAdmin(admin.ModelAdmin):
    list_display = ("nome", "categoria", "unidade", "estoque_atual", "custo_medio", "ativo")
    list_filter = ("categoria", "unidade", "ativo")
    search_fields = ("nome",)
    raw_id_fields = ("empresa", "categoria")

# =============================================================================
# Produto / Variação
# =============================================================================
@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "ativo")
    search_fields = ("nome",)
    list_filter = ("empresa", "ativo")
    raw_id_fields = ("empresa",)

class VariacaoAdminForm(forms.ModelForm):
    class Meta:
        model = VariacaoProduto
        fields = ["produto", "tipo", "estoque_atual", "custo_unitario", "preco_sugerido"]
        widgets = {
            "estoque_atual":  forms.NumberInput(attrs={"step": "0.01",   "min": "0"}),
            "custo_unitario": forms.NumberInput(attrs={"step": "0.0001", "min": "0"}),
            "preco_sugerido": forms.NumberInput(attrs={"step": "0.01",   "min": "0"}),
        }

@admin.register(VariacaoProduto)
class VariacaoProdutoAdmin(admin.ModelAdmin):
    form = VariacaoAdminForm
    readonly_fields = ("sku",)
    fields = ("produto", "tipo", "sku", "estoque_atual", "custo_unitario", "preco_sugerido")
    list_display = ("produto", "tipo", "sku", "estoque_atual", "custo_unitario", "preco_sugerido")
    list_filter = ("produto", "tipo")
    search_fields = ("sku", "produto__nome")
    raw_id_fields = ("produto",)
    list_per_page = 50
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.order_by("produto__nome", "tipo", "sku")

# =============================================================================
# Ficha Técnica
# =============================================================================
@admin.register(FichaTecnicaItem)
class FichaTecnicaItemAdmin(admin.ModelAdmin):
    list_display = ("variacao", "insumo", "quantidade", "fase")
    list_filter = ("variacao__produto", "insumo__categoria", "fase")
    search_fields = ("variacao__produto__nome", "insumo__nome")
    raw_id_fields = ("variacao", "insumo")

# =============================================================================
# Ordem de Produção
# =============================================================================
@admin.register(OrdemProducao)
class OrdemProducaoAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "variacao", "quantidade", "custo_mao_de_obra", "custo_indireto_rateado", "criado_em")
    list_filter = ("empresa", "variacao__produto")
    date_hierarchy = "criado_em"
    search_fields = ("variacao__produto__nome", "variacao__sku")
    raw_id_fields = ("empresa", "variacao")

# =============================================================================
# Pedido / Itens / Personalizações / Pagamentos (cliente)
# =============================================================================
@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "cliente", "status", "etapa_producao", "total_bruto_display", "total_liquido_display", "criado_em", "has_arte")
    list_filter = ("empresa", "status", "etapa_producao")
    date_hierarchy = "criado_em"
    search_fields = ("id", "cliente__nome", "numero_orcamento")
    raw_id_fields = ("empresa", "cliente")
    inlines = [ItemPedidoInline]

    def total_bruto_display(self, obj):
        try:
            return f"R$ {obj.total_bruto():.2f}"
        except Exception:
            return "R$ 0,00"
    total_bruto_display.short_description = "Total bruto"

    def total_liquido_display(self, obj):
        try:
            return f"R$ {obj.total_com_descontos():.2f}"
        except Exception:
            return "R$ 0,00"
    total_liquido_display.short_description = "Total c/ descontos"

    def has_arte(self, obj):
        return obj.arte_has_file
    has_arte.boolean = True
    has_arte.short_description = "Arte?"

@admin.register(ItemPedido)
class ItemPedidoAdmin(admin.ModelAdmin):
    list_display = ("pedido", "variacao", "quantidade", "preco_unitario", "subtotal_display")
    list_filter = ("pedido__empresa",)
    search_fields = ("pedido__id", "variacao__sku", "variacao__produto__nome")
    raw_id_fields = ("pedido", "variacao")
    inlines = [PersonalizacaoItemInline]

    def subtotal_display(self, obj):
        try:
            return f"R$ {obj.subtotal():.2f}"
        except Exception:
            return "R$ 0,00"
    subtotal_display.short_description = "Subtotal"

@admin.register(PersonalizacaoItem)
class PersonalizacaoItemAdmin(admin.ModelAdmin):
    list_display = ("item", "nome", "numero", "tamanho_camisa", "quantidade", "incluir_short", "tamanho_short")
    search_fields = ("item__pedido__id", "nome", "numero")
    raw_id_fields = ("item",)

@admin.register(Pagamento)
class PagamentoAdmin(admin.ModelAdmin):
    list_display = ("pedido", "valor", "forma", "descricao", "data", "usuario")
    list_filter = ("forma", "usuario")
    date_hierarchy = "data"
    search_fields = ("pedido__id", "descricao", "usuario__username")
    raw_id_fields = ("pedido", "usuario")

# =============================================================================
# Costureira / Remessa / Pagamento Costureira
# =============================================================================
@admin.register(Costureira)
class CostureiraAdmin(admin.ModelAdmin):
    list_display = ("nome", "telefone", "preco_corte_por_peca", "preco_costura_por_peca", "preco_correcao_por_peca", "ativo")
    list_filter = ("ativo",)
    search_fields = ("nome", "telefone")

@admin.register(Remessa)
class RemessaAdmin(admin.ModelAdmin):
    list_display = (
        "numero", "empresa", "costureira", "tipo", "status",
        "enviado_em", "recebido_em", "kg_enviados",
        "pecas_ok_display", "total_a_pagar_display", "imprimir_link",
    )
    list_filter = ("empresa", "costureira", "produto", "tipo", "status")
    search_fields = ("numero", "costureira__nome", "produto__nome")
    date_hierarchy = "enviado_em"
    raw_id_fields = ("empresa", "costureira", "produto")
    inlines = [RemessaItemInline]

    def pecas_ok_display(self, obj):
        try:
            return f"{obj.total_pecas_ok():.0f}"
        except Exception:
            return "0"
    pecas_ok_display.short_description = "Peças OK"

    def total_a_pagar_display(self, obj):
        try:
            return f"R$ {obj.total_a_pagar():.2f}"
        except Exception:
            return "R$ 0,00"
    total_a_pagar_display.short_description = "Total a pagar"

    def imprimir_link(self, obj):
        try:
            url = reverse("camisas:remessa_print", args=[obj.id])
            return mark_safe(f'<a href="{url}" target="_blank" rel="noopener">Imprimir</a>')
        except Exception:
            return "-"
    imprimir_link.short_description = "Imprimir"

@admin.register(RemessaItem)
class RemessaItemAdmin(admin.ModelAdmin):
    list_display = ("remessa", "variacao", "qtd_prevista", "qtd_ok", "qtd_perda", "qtd_extravio", "qtd_devolvida", "preco_unit", "a_pagar_display")
    list_filter = ("remessa__empresa", "remessa__tipo", "remessa__status")
    search_fields = ("remessa__numero", "variacao__sku", "variacao__produto__nome")
    raw_id_fields = ("remessa", "variacao")

    def a_pagar_display(self, obj):
        try:
            return f"R$ {obj.a_pagar():.2f}"
        except Exception:
            return "R$ 0,00"
    a_pagar_display.short_description = "A pagar (item)"

@admin.register(PagamentoCostureira)
class PagamentoCostureiraAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "costureira", "remessa", "valor_total", "status", "criado_em", "pago_em")
    list_filter = ("empresa", "costureira", "status")
    search_fields = ("remessa__numero", "costureira__nome")
    date_hierarchy = "criado_em"
    raw_id_fields = ("empresa", "costureira", "remessa")

# =============================================================================
# Movimento de Estoque
# =============================================================================
@admin.register(MovimentoEstoque)
class MovimentoEstoqueAdmin(admin.ModelAdmin):
    list_display = ("criado_em", "empresa", "tipo", "insumo", "variacao", "quantidade", "custo_unit", "observacao", "costureira", "remessa")
    list_filter = ("empresa", "tipo", "insumo__categoria", "costureira")
    date_hierarchy = "criado_em"
    search_fields = ("insumo__nome", "variacao__sku", "observacao", "remessa__numero", "costureira__nome")
    raw_id_fields = ("empresa", "insumo", "variacao", "costureira", "remessa")

# =============================================================================
# Auditoria
# =============================================================================
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "model", "object_id", "username", "ip", "path", "method")
    list_filter = ("action", "model", "username", "ip", "method")
    search_fields = ("model", "object_id", "username", "path", "ip", "user_agent")
    readonly_fields = ("user", "username", "action", "model", "object_id", "changes", "path", "method", "ip", "user_agent", "created_at")

# =============================================================================
# Despesas / Fornecedor
# =============================================================================
@admin.register(Despesa)
class DespesaAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "categoria", "descricao", "valor_total", "status", "data_emissao", "vencimento")
    list_filter = ("empresa", "categoria", "status", "forma_pagamento")
    search_fields = ("descricao", "fornecedor__nome")
    date_hierarchy = "data_emissao"
    raw_id_fields = ("empresa", "categoria", "fornecedor")
    inlines = [ParcelaInline]

@admin.register(CategoriaDespesa)
class CategoriaDespesaAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa")
    list_filter = ("empresa",)
    search_fields = ("nome",)
    raw_id_fields = ("empresa",)

@admin.register(Fornecedor)
class FornecedorAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "cpf_cnpj", "telefone", "email")
    list_filter = ("empresa",)
    search_fields = ("nome", "cpf_cnpj", "email", "telefone")
    raw_id_fields = ("empresa",)

@admin.register(ParcelaDespesa)
class ParcelaDespesaAdmin(admin.ModelAdmin):
    list_display = ("despesa", "numero", "vencimento", "valor", "status", "pago_em")
    list_filter = ("status",)
    date_hierarchy = "vencimento"
    search_fields = ("despesa__descricao",)
    raw_id_fields = ("despesa",)

# =============================================================================
# Cotações Concorrentes
# =============================================================================
@admin.register(CotacaoConcorrente)
class CotacaoConcorrenteAdmin(admin.ModelAdmin):
    list_display = ("id", "pedido", "empresa_nome", "cnpj", "criado_em")
    search_fields = ("empresa_nome", "cnpj", "pedido__id")
    raw_id_fields = ("pedido",)
    inlines = [CotacaoConcorrenteItemInline]

@admin.register(CotacaoConcorrenteItem)
class CotacaoConcorrenteItemAdmin(admin.ModelAdmin):
    list_display = ("cotacao", "item_nome", "unidade", "quantidade", "valor_unitario", "subtotal_display")
    raw_id_fields = ("cotacao",)
    search_fields = ("cotacao__pedido__id", "item_nome")
    def subtotal_display(self, obj):
        try:
            return f"R$ {obj.subtotal:.2f}"
        except Exception:
            return "R$ 0,00"
    subtotal_display.short_description = "Subtotal"

# =============================================================================
# Funcionários / Frequência
# =============================================================================
@admin.register(Funcionario)
class FuncAdmin(admin.ModelAdmin):
    list_display = ("nome", "ativo", "jornada_diaria_min", "almoco_min")
    list_filter  = ("ativo",)
    search_fields = ("nome",)

@admin.register(FrequenciaDia)
class FreqAdmin(admin.ModelAdmin):
    list_display = ("data", "funcionario", "e1", "s1", "e2", "s2")
    list_filter  = ("funcionario", "data")
    search_fields = ("funcionario__nome",)
    date_hierarchy = "data"
    raw_id_fields = ("funcionario",)

# =============================================================================
# Coleta (Pedidos)
# =============================================================================
@admin.register(ColetaPedido)
class ColetaPedidoAdmin(admin.ModelAdmin):
    list_display = ("id", "pedido", "modo", "concluido_em", "expiracao", "criado_em")
    list_filter = ("modo", "concluido_em", "expiracao")
    search_fields = ("pedido__id", "token", "cliente_nome", "cliente_email")
    raw_id_fields = ("pedido", "item")

@admin.register(PessoaColeta)
class PessoaColetaAdmin(admin.ModelAdmin):
    list_display = ("coleta", "nome", "numero", "tamanho", "valor", "status_pagamento", "pago_em")
    list_filter = ("status_pagamento",)
    search_fields = ("coleta__pedido__id", "nome", "numero")
    raw_id_fields = ("coleta",)

# =============================================================================
# Assinaturas eletrônicas / Orçamento Express
# =============================================================================
@admin.register(ESignature)
class ESignatureAdmin(admin.ModelAdmin):
    list_display = ("pedido", "role", "signer_name", "signed_at", "hash_short", "qr_thumb")
    list_filter = ("role",)
    date_hierarchy = "signed_at"
    search_fields = ("pedido__id", "signer_name", "hash")
    raw_id_fields = ("pedido",)

    def hash_short(self, obj):
        h = (obj.hash or "").strip()
        return h[:10] + "…" if h else "—"
    hash_short.short_description = "Hash"

    def qr_thumb(self, obj):
        if obj.qr_data_url:
            return mark_safe(f'<img src="{obj.qr_data_url}" style="max-height:48px;border:1px solid #e5e7eb;padding:2px;border-radius:6px" />')
        return "—"
    qr_thumb.short_description = "QR"

@admin.register(OrcamentoExpress)
class OrcamentoExpressAdmin(admin.ModelAdmin):
    list_display = ("id", "cliente_nome", "cliente_whatsapp", "total", "status", "validade", "criado_em", "aprovado_em")
    list_filter = ("status",)
    date_hierarchy = "criado_em"
    search_fields = ("cliente_nome", "cliente_whatsapp")
    inlines = [OrcamentoExpressItemInline]

@admin.register(OrcamentoExpressItem)
class OrcamentoExpressItemAdmin(admin.ModelAdmin):
    list_display = ("orcamento", "descricao", "unidade", "quantidade", "valor_unitario", "subtotal_display")
    raw_id_fields = ("orcamento",)
    search_fields = ("orcamento__id", "descricao")
    def subtotal_display(self, obj):
        try:
            return f"R$ {obj.subtotal:.2f}"
        except Exception:
            return "R$ 0,00"
    subtotal_display.short_description = "Subtotal"

# =============================================================================
# Designer / ArteDesign
# =============================================================================
@admin.register(ArteDesign)
class ArteDesignAdmin(admin.ModelAdmin):
    list_display = ("id", "titulo", "empresa", "cliente", "status", "pedido", "criado_em")
    list_filter  = ("empresa", "status", "criado_em")
    search_fields = ("titulo", "descricao", "cliente__nome")
    raw_id_fields = ("empresa", "cliente", "pedido")

# =============================================================================
# Fallback: registra automaticamente qualquer modelo NÃO registrado
# =============================================================================
def _autoregister_remaining_models():
    app_cfg = apps.get_app_config("camisas")
    for model in app_cfg.get_models():
        # pular se já registrado por decorators/@register acima
        if model in admin.site._registry:
            continue
        try:
            admin.site.register(model)
        except AlreadyRegistered:
            # segurança extra (não deve acontecer, mas ok)
            pass

_autoregister_remaining_models()
