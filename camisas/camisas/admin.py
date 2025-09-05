from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.db.models import F, Sum, DecimalField, ExpressionWrapper, Value, Q
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.apps import apps
from decimal import Decimal

from django.contrib import admin, messages
from django.db.models import F, Sum, Value, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe

from .models import Pedido
# Evita ImportError em tempo de autodiscover do admin
ItemPedido = apps.get_model('camisas', 'ItemPedido')

from .models import (
    Empresa, ParametrosEmpresa, Cliente, CategoriaInsumo, Insumo,
    Produto, VariacaoProduto, FichaTecnicaItem, OrdemProducao,
    Pedido, MovimentoEstoque, AuditLog,
    # --- terceirização ---
    Costureira, Remessa, RemessaItem, PagamentoCostureira,
    # --- helpers de tamanho ---
    SIZE_ORDER, size_order_case,
)

# ==== helpers para totais =====================================================
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
    extra = 1
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
        # Ordena itens pelo tamanho oficial e cor
        qs = super().get_queryset(request)
        return qs.select_related("variacao", "variacao__produto").annotate(
            _sz=size_order_case("variacao__tamanho")
        ).order_by("variacao__produto__nome", "_sz", "variacao__cor")

# =============================================================================
# Empresa
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

# =============================================================================
# Parâmetros
# =============================================================================
@admin.register(ParametrosEmpresa)
class ParametrosEmpresaAdmin(admin.ModelAdmin):
    list_display = ("empresa", "margem_lucro_padrao", "impostos_percentual", "taxa_cartao_percentual")
    search_fields = ("empresa__nome_fantasia",)

# =============================================================================
# Cliente
# =============================================================================
@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "telefone", "email")
    search_fields = ("nome", "cpf_cnpj", "email", "telefone")
    list_filter = ("empresa",)

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
    actions = ("completar_variacoes_padrao",)

    def completar_variacoes_padrao(self, request, queryset):
        total = 0
        for p in queryset:
            total += p.ensure_variacoes_para_tamanhos(SIZE_ORDER, cores=["Branco"])
        self.message_user(
            request,
            f"Criadas {total} variações (tamanhos padrão) nos produtos selecionados.",
            level=messages.SUCCESS,
        )
    completar_variacoes_padrao.short_description = "Completar variações padrão (12 tamanhos)"


class VariacaoAdminForm(forms.ModelForm):
    # Exibe "tamanho" como select com a ordem oficial
    tamanho = forms.ChoiceField(choices=[(s, s) for s in SIZE_ORDER], label="Tamanho")

    class Meta:
        model = VariacaoProduto
        fields = [
            "produto", "tamanho", "cor",
            "estoque_atual", "custo_unitario", "preco_sugerido",
        ]
        widgets = {
            "estoque_atual":  forms.NumberInput(attrs={"step": "0.01",   "min": "0"}),
            "custo_unitario": forms.NumberInput(attrs={"step": "0.0001", "min": "0"}),
            "preco_sugerido": forms.NumberInput(attrs={"step": "0.01",   "min": "0"}),
        }


@admin.register(VariacaoProduto)
class VariacaoProdutoAdmin(admin.ModelAdmin):
    form = VariacaoAdminForm

    # SKU é gerado no model -> apenas exibir
    readonly_fields = ("sku",)

    # Ordem e campos do formulário no admin
    fields = (
        "produto", "tamanho", "cor",
        "sku",  # somente leitura
        "estoque_atual", "custo_unitario", "preco_sugerido",
    )

    list_display = (
        "produto", "tamanho", "cor", "sku",
        "estoque_atual", "custo_unitario", "preco_sugerido",
    )
    list_filter = ("produto", "tamanho", "cor")
    search_fields = ("sku", "produto__nome")
    raw_id_fields = ("produto",)
    list_per_page = 50

    def get_queryset(self, request):
        # Ordena por produto, depois pela ordem oficial de tamanhos e cor
        qs = super().get_queryset(request)
        return qs.annotate(_sz=size_order_case("tamanho")).order_by("produto__nome", "_sz", "cor", "sku")

# =============================================================================
# Ficha Técnica (com fase de consumo)
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
# Pedido — com assinatura eletrônica
# =============================================================================

# ----- filtro: com/sem assinatura -----
class HasSignatureFilter(admin.SimpleListFilter):
    title = "assinatura"
    parameter_name = "has_signature"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Com assinatura"),
            ("no",  "Sem assinatura"),
        )

    def queryset(self, request, queryset):
        val = self.value()
        if val == "yes":
            # tem nome de arquivo e não é vazio
            return queryset.filter(approval_signature__isnull=False).exclude(approval_signature="")
        if val == "no":
            # sem arquivo ou vazio
            return queryset.filter(Q(approval_signature__isnull=True) | Q(approval_signature=""))
        return queryset

class ItemPedidoInline(admin.TabularInline):
    model = Pedido.itens.rel.related_model  # ou importe seu ItemPedido diretamente
    extra = 0


# ---------------- Filtros auxiliares ----------------

class HasSignatureFilter(admin.SimpleListFilter):
    title = "Assinatura (orçamento)"
    parameter_name = "has_sig"

    def lookups(self, request, model_admin):
        return (("yes", "Com assinatura"), ("no", "Sem assinatura"))

    def queryset(self, request, qs):
        if self.value() == "yes":
            return qs.exclude(approval_signature="")
        if self.value() == "no":
            return qs.filter(approval_signature="")
        return qs


class HasArtworkSignatureFilter(admin.SimpleListFilter):
    title = "Assinatura (arte)"
    parameter_name = "has_art_sig"

    def lookups(self, request, model_admin):
        return (("yes", "Com assinatura"), ("no", "Sem assinatura"))

    def queryset(self, request, qs):
        # Campo pode não existir se as migrações ainda não foram aplicadas
        if not hasattr(qs.model, "artwork_signature"):
            return qs
        if self.value() == "yes":
            return qs.exclude(artwork_signature="")
        if self.value() == "no":
            return qs.filter(artwork_signature="")
        return qs


# ---------------- Admin ----------------

@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = (
        "id", "numero_orcamento", "empresa", "cliente", "status",
        "criado_em", "total_bruto_display", "total_final_display",
        "approval_status", "approval_signature_exists",
        "artwork_status_safe", "artwork_signature_exists",
        "orcamento_ocultar_total",  # <<< NOVO: mostra a flag na lista
    )
    list_filter = (
        "status", "empresa", "approval_status",
        "orcamento_ocultar_total",               # <<< NOVO: filtro por flag
        HasSignatureFilter, HasArtworkSignatureFilter
    )
    search_fields = (
        "numero_orcamento", "cliente__nome", "cliente__cpf_cnpj",
        "approval_token", "approval_name", "approval_email",
        "artwork_token", "artwork_name", "artwork_email",
    )
    date_hierarchy = "criado_em"
    inlines = [ItemPedidoInline]
    raw_id_fields = ("empresa", "cliente")
    list_per_page = 40

    readonly_fields = (
        # Totais + links públicos
        "totais_box", "orcamento_public_url",
        # Orçamento (público)
        "approval_status", "approval_decided_at", "approval_decision_ip",
        "approval_name", "approval_email", "approval_comment",
        "approval_signature_preview", "approval_user_agent",
        "approval_timezone", "approval_hash",
        # Arte (público)
        "artwork_public_url", "artwork_status", "artwork_decided_at", "artwork_decision_ip",
        "artwork_name", "artwork_email", "artwork_comment",
        "artwork_signature_preview", "artwork_user_agent", "artwork_timezone", "artwork_hash",
        # Preview de arte enviada
        "arte_preview",
    )

    fieldsets = (
        ("Dados do Pedido", {
            "fields": (
                ("empresa", "cliente", "status"),
                ("numero_orcamento", "validade"),
                "observacao",
            )
        }),
        ("Condições / Arte (arquivo da estampa)", {
            "fields": ("condicoes", "arte", "arte_preview")
        }),
        # <<< NOVO: uma seção só para a flag de exibição do orçamento
        ("Orçamento – Opções de exibição", {
            "fields": ("orcamento_ocultar_total",),
            "description": "Se marcado, o orçamento público e a impressão não exibem a coluna Subtotal nem o bloco de Totais."
        }),
        ("Totais (somente leitura)", {
            "fields": ("totais_box",),
            "description": "Os totais são calculados a partir dos itens (quantidade × preço) com desconto/acréscimo."
        }),
        ("Aprovação pública do ORÇAMENTO", {
            "fields": (
                "orcamento_public_url", "approval_status", "approval_decided_at",
                "approval_name", "approval_email", "approval_comment",
                "approval_decision_ip",
                "approval_signature_preview", "approval_user_agent",
                "approval_timezone", "approval_hash",
            )
        }),
        ("Aprovação pública da ARTE", {
            "fields": (
                "artwork_public_url", "artwork_status", "artwork_decided_at",
                "artwork_name", "artwork_email", "artwork_comment",
                "artwork_decision_ip",
                "artwork_signature_preview", "artwork_user_agent",
                "artwork_timezone", "artwork_hash",
            )
        }),
        ("Percentuais", {
            "fields": ("desconto_percentual", "acrescimo_percentual"),
        }),
    )

    # ---------- Query otimizada para totais ----------
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        subtotal_expr = ExpressionWrapper(
            F("itens__preco_unitario") * F("itens__quantidade"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
        return qs.annotate(
            _subtotal=Coalesce(
                Sum(subtotal_expr),
                Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2)),
            )
        )

    # ---------- Totais ----------
    def total_bruto_display(self, obj):
        try:
            return f"R$ {obj.total_bruto():.2f}"
        except Exception:
            return "R$ 0,00"
    total_bruto_display.short_description = "Subtotal"

    def total_final_display(self, obj):
        try:
            return f"R$ {obj.total_com_descontos():.2f}"
        except Exception:
            return "R$ 0,00"
    total_final_display.short_description = "Total"

    def totais_box(self, obj):
        try:
            subtotal = obj.total_bruto()
            desc_p = (obj.desconto_percentual or Decimal("0")) / Decimal("100")
            acr_p  = (obj.acrescimo_percentual or Decimal("0")) / Decimal("100")
            val_desc = (subtotal * desc_p).quantize(Decimal("0.01"))
            val_acr  = (subtotal * acr_p).quantize(Decimal("0.01"))
            total = (subtotal - val_desc + val_acr).quantize(Decimal("0.01"))
            html = f"""
            <div style="line-height:1.6">
              <div><strong>Subtotal:</strong> R$ {subtotal:.2f}</div>
              <div><strong>Desconto ({obj.desconto_percentual or 0}%):</strong> − R$ {val_desc:.2f}</div>
              <div><strong>Acréscimo ({obj.acrescimo_percentual or 0}%):</strong> + R$ {val_acr:.2f}</div>
              <hr/>
              <div><strong>Total:</strong> R$ {total:.2f}</div>
            </div>
            """
        except Exception:
            html = "<em>Não foi possível calcular.</em>"
        return mark_safe(html)
    totais_box.short_description = "Totais"

    # ---------- Previews seguros ----------
    def arte_preview(self, obj):
        url = getattr(obj, "arte_url_safe", "") or ""
        return mark_safe(f'<img src="{url}" style="max-height:160px;border:1px solid #e5e7eb;border-radius:6px;">') if url else "-"
    arte_preview.short_description = "Arte"

    def approval_signature_preview(self, obj):
        url = getattr(obj, "approval_signature_url_safe", "") or ""
        return mark_safe(f'<img src="{url}" style="max-height:140px;border:1px solid #e5e7eb;border-radius:6px;">') if url else "-"
    approval_signature_preview.short_description = "Assinatura (orçamento)"

    def approval_signature_exists(self, obj):
        has_sig = getattr(obj, "approval_has_signature", None)
        if has_sig is None:
            has_sig = bool(getattr(obj, "approval_signature", None) and getattr(obj.approval_signature, "name", ""))
        return bool(has_sig)
    approval_signature_exists.boolean = True
    approval_signature_exists.short_description = "Assin. orçamento?"

    # ---------- Arte pública ----------
    def artwork_public_url(self, obj):
        token = getattr(obj, "artwork_token", "")
        if not token:
            return "-"
        try:
            url = reverse("camisas:arte_publica", args=[token])
            return mark_safe(f'<a href="{url}" target="_blank" rel="noopener">{url}</a>')
        except Exception:
            return "-"
    artwork_public_url.short_description = "Link público da ARTE"

    def artwork_signature_preview(self, obj):
        url = getattr(obj, "artwork_signature_url_safe", "") or ""
        if not url and hasattr(obj, "artwork_signature"):
            try:
                url = obj.artwork_signature.url
            except Exception:
                url = ""
        return mark_safe(f'<img src="{url}" style="max-height:140px;border:1px solid #e5e7eb;border-radius:6px;">') if url else "-"
    artwork_signature_preview.short_description = "Assinatura (arte)"

    def artwork_signature_exists(self, obj):
        f = getattr(obj, "artwork_signature", None)
        return bool(f and getattr(f, "name", ""))
    artwork_signature_exists.boolean = True
    artwork_signature_exists.short_description = "Assin. arte?"

    def artwork_status_safe(self, obj):
        # Usa o display quando disponível
        if hasattr(obj, "get_artwork_status_display"):
            return obj.get_artwork_status_display()
        return getattr(obj, "artwork_status", "-") or "-"
    artwork_status_safe.short_description = "Status arte"

    # ---------- Orçamento público ----------
    def orcamento_public_url(self, obj):
        try:
            url = reverse("camisas:orcamento_publico", args=[obj.approval_token])
            return mark_safe(f'<a href="{url}" target="_blank" rel="noopener">{url}</a>')
        except Exception:
            return "-"
    orcamento_public_url.short_description = "Link público do ORÇAMENTO"

    # ---------- Ações ----------
    actions = (
        # Orçamento
        "marcar_aprovado", "marcar_recusado",
        "resetar_fluxo_aprovacao", "resetar_fluxo_com_novo_token",
        # Arte
        "marcar_arte_aprovada", "marcar_arte_recusada",
        "resetar_fluxo_arte", "resetar_fluxo_arte_novo_token",
    )

    # Orçamento
    def marcar_aprovado(self, request, queryset):
        n = 0
        for p in queryset:
            p.approval_status = "APRV"
            p.approval_decided_at = timezone.now()
            if p.status == "ORC":
                p.status = "PEN"
            p.save(update_fields=["approval_status", "approval_decided_at", "status"])
            n += 1
        messages.success(request, f"{n} orçamento(s) marcados como APROVADO.")

    marcar_aprovado.short_description = "Marcar orçamento como APROVADO"

    def marcar_recusado(self, request, queryset):
        n = queryset.update(approval_status="REJ", approval_decided_at=timezone.now())
        messages.success(request, f"{n} orçamento(s) marcados como RECUSADO.")
    marcar_recusado.short_description = "Marcar orçamento como RECUSADO"

    def resetar_fluxo_aprovacao(self, request, queryset):
        n = 0
        for p in queryset:
            p.reset_approval(regenerate_token=False, save=True)
            n += 1
        messages.success(request, f"{n} orçamento(s) resetados (mesmo token).")
    resetar_fluxo_aprovacao.short_description = "Resetar fluxo (mantém token)"

    def resetar_fluxo_com_novo_token(self, request, queryset):
        n = 0
        for p in queryset:
            p.reset_approval(regenerate_token=True, save=True)
            n += 1
        messages.success(request, f"{n} orçamento(s) resetados (novo token).")
    resetar_fluxo_com_novo_token.short_description = "Resetar fluxo (novo token)"

    # Arte
    def marcar_arte_aprovada(self, request, queryset):
        if not hasattr(Pedido, "artwork_status"):
            messages.warning(request, "Os campos de arte ainda não estão migrados.")
            return
        n = queryset.update(artwork_status="APRV", artwork_decided_at=timezone.now())
        messages.success(request, f"{n} arte(s) marcadas como APROVADA(s).")
    marcar_arte_aprovada.short_description = "ARTE: marcar como APROVADA"

    def marcar_arte_recusada(self, request, queryset):
        if not hasattr(Pedido, "artwork_status"):
            messages.warning(request, "Os campos de arte ainda não estão migrados.")
            return
        n = queryset.update(artwork_status="REJ", artwork_decided_at=timezone.now())
        messages.success(request, f"{n} arte(s) marcadas como RECUSADA(s).")
    marcar_arte_recusada.short_description = "ARTE: marcar como RECUSADA"

    def resetar_fluxo_arte(self, request, queryset):
        # usa o helper do modelo que você definiu: reset_artwork_approval
        if not hasattr(Pedido, "reset_artwork_approval"):
            messages.warning(request, "O método reset_artwork_approval não existe no modelo Pedido.")
            return
        n = 0
        for p in queryset:
            p.reset_artwork_approval(regenerate_token=False, save=True)
            n += 1
        messages.success(request, f"{n} fluxo(s) de ARTE resetado(s) (mesmo link).")
    resetar_fluxo_arte.short_description = "ARTE: resetar fluxo (mesmo link)"

    def resetar_fluxo_arte_novo_token(self, request, queryset):
        if not hasattr(Pedido, "reset_artwork_approval"):
            messages.warning(request, "O método reset_artwork_approval não existe no modelo Pedido.")
            return
        n = 0
        for p in queryset:
            p.reset_artwork_approval(regenerate_token=True, save=True)
            n += 1
        messages.success(request, f"{n} fluxo(s) de ARTE resetado(s) (novo link).")
    resetar_fluxo_arte_novo_token.short_description = "ARTE: resetar fluxo (novo link)"


# =============================================================================
# TERCEIRIZAÇÃO
# =============================================================================
@admin.register(Costureira)
class CostureiraAdmin(admin.ModelAdmin):
    list_display = ("nome", "telefone", "preco_corte_por_peca", "preco_costura_por_peca", "preco_correcao_por_peca")
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
    readonly_fields = ()

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

    # ---- Ações em massa ----
    actions = ("finalizar_recebimento", "gerar_pagamento", "gerar_remessa_costura")

    def finalizar_recebimento(self, request, queryset):
        """
        Aplica baixas/entradas e cria/atualiza Pagamento usando Remessa.finalizar_recebimento().
        Conta criados/atualizados pela existência prévia do pagamento.
        """
        criados, atualizados, erros = 0, 0, 0
        for r in queryset:
            try:
                existed = PagamentoCostureira.objects.filter(remessa=r).exists()
                pgto = r.finalizar_recebimento()
                if pgto:
                    if existed:
                        atualizados += 1
                    else:
                        criados += 1
            except Exception as e:
                erros += 1
                messages.error(request, f"{r.numero}: {e}")
        messages.success(
            request,
            f"Recebimento finalizado. Pagamentos: {criados} criado(s), {atualizados} atualizado(s)."
            + (f" Erros: {erros}." if erros else "")
        )
    finalizar_recebimento.short_description = "Finalizar recebimento (baixas/entradas + pagamento)"

    def gerar_pagamento(self, request, queryset):
        """Gera/atualiza pagamentos sem mexer em estoque (útil para ajustes)."""
        criados, atualizados = 0, 0
        for r in queryset:
            total = r.total_a_pagar()
            if total <= 0:
                continue
            pgto, created = PagamentoCostureira.objects.get_or_create(
                remessa=r,
                defaults=dict(
                    empresa=r.empresa,
                    costureira=r.costureira,
                    valor_total=total,
                )
            )
            if not created:
                pgto.valor_total = total
                pgto.save(update_fields=["valor_total"])
                atualizados += 1
            else:
                criados += 1
        messages.success(request, f"Pagamentos: {criados} criado(s), {atualizados} atualizado(s).")
    gerar_pagamento.short_description = "Gerar/atualizar pagamento(s) (não mexe no estoque)"

    def gerar_remessa_costura(self, request, queryset):
        """Para remessas de CORTE selecionadas, cria uma remessa de COSTURA com previsão = peças OK."""
        links = []
        criadas, ignoradas = 0, 0
        for r in queryset:
            if r.tipo != "CORTE":
                ignoradas += 1
                continue
            try:
                r2 = r.gerar_remessa_posterior(tipo="COSTURA")
                url = reverse("admin:camisas_remessa_change", args=[r2.id])
                links.append(f'<a href="{url}">{r2.numero}</a>')
                criadas += 1
            except Exception as e:
                messages.error(request, f"{r.numero}: {e}")
        msg = f"{criadas} remessa(s) de COSTURA criada(s)."
        if ignoradas:
            msg += f" (Ignoradas {ignoradas} não-CORTE.)"
        if links:
            msg += " Abrir: " + ", ".join(links[:5]) + (" ..." if len(links) > 5 else "")
        messages.success(request, mark_safe(msg))
    gerar_remessa_costura.short_description = "Gerar remessa de COSTURA a partir da seleção (CORTE)"

@admin.register(PagamentoCostureira)
class PagamentoCostureiraAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "costureira", "remessa", "valor_total", "status", "criado_em", "pago_em")
    list_filter = ("empresa", "costureira", "status")
    search_fields = ("remessa__numero", "costureira__nome")
    date_hierarchy = "criado_em"
    raw_id_fields = ("empresa", "costureira", "remessa")
    actions = ("marcar_pago",)

    def marcar_pago(self, request, queryset):
        n = queryset.update(status="PAGO", pago_em=timezone.now())
        messages.success(request, f"{n} pagamento(s) marcados como PAGO.")
    marcar_pago.short_description = "Marcar como PAGO"

# =============================================================================
# Movimento de Estoque
# =============================================================================
@admin.register(MovimentoEstoque)
class MovimentoEstoqueAdmin(admin.ModelAdmin):
    list_display = (
        "criado_em", "empresa", "tipo",
        "insumo", "variacao", "quantidade", "custo_unit", "observacao",
        "costureira", "remessa",
    )
    list_filter = ("empresa", "tipo", "insumo__categoria", "costureira")
    date_hierarchy = "criado_em"
    search_fields = ("insumo__nome", "variacao__sku", "observacao", "remessa__numero", "costureira__nome")
    raw_id_fields = ("empresa", "insumo", "variacao", "costureira", "remessa")

# =============================================================================
# Auditoria (somente leitura)
# =============================================================================
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "model", "object_id", "username", "ip", "path", "method")
    list_filter = ("action", "model", "username", "ip", "method")
    search_fields = ("model", "object_id", "username", "path", "ip", "user_agent")
    readonly_fields = ("user", "username", "action", "model", "object_id", "changes",
                       "path", "method", "ip", "user_agent", "created_at")

    def has_view_permission(self, request, obj=None):
        return True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

# camisas/admin.py (adicione abaixo das outras regs)
from django.contrib import admin, messages
from .models import CategoriaDespesa, Fornecedor, Despesa, ParcelaDespesa

class ParcelaInline(admin.TabularInline):
    model = ParcelaDespesa
    extra = 0
    fields = ("numero", "vencimento", "valor", "status", "pago_em")
    readonly_fields = ("pago_em",)
    ordering = ("numero",)

@admin.register(Despesa)
class DespesaAdmin(admin.ModelAdmin):
    list_display = ("id", "empresa", "categoria", "descricao", "valor_total", "status", "data_emissao", "vencimento")
    list_filter = ("empresa", "categoria", "status", "forma_pagamento")
    search_fields = ("descricao", "fornecedor__nome")
    date_hierarchy = "data_emissao"
    raw_id_fields = ("empresa", "categoria", "fornecedor")
    inlines = [ParcelaInline]
    actions = ("marcar_como_paga",)

    def marcar_como_paga(self, request, queryset):
        n = 0
        for d in queryset:
            d.parcelas.update(status="PAGA", pago_em=timezone.now())
            d.status = "PAGA"
            d.save(update_fields=["status"])
            n += 1
        messages.success(request, f"{n} despesa(s) marcadas como PAGA.")
    marcar_como_paga.short_description = "Marcar despesas (todas as parcelas) como PAGA"

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

# camisas/admin.py
from django.contrib import admin
from .models import CotacaoConcorrente, CotacaoConcorrenteItem

class CotacaoConcorrenteItemInline(admin.TabularInline):
    model = CotacaoConcorrenteItem
    extra = 0

@admin.register(CotacaoConcorrente)
class CotacaoConcorrenteAdmin(admin.ModelAdmin):
    list_display = ("id", "pedido", "empresa_nome", "cnpj", "criado_em")
    search_fields = ("empresa_nome", "cnpj", "pedido__id")
    inlines = [CotacaoConcorrenteItemInline]

# camisas/admin.py
from django.contrib import admin
from .models import Funcionario, FrequenciaDia

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

# camisas/admin.py
from django.contrib import admin
from .models import ColetaPedido

@admin.register(ColetaPedido)
class ColetaPedidoAdmin(admin.ModelAdmin):
    list_display = ("id", "pedido", "modo", "concluido_em", "expiracao", "criado_em")
    list_filter = ("modo", "concluido_em", "expiracao")
    search_fields = ("pedido__id", "token", "cliente_nome", "cliente_email")
