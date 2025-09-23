# camisas/forms.py
from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory, BaseInlineFormSet

from .models import (
    Empresa, ParametrosEmpresa, Cliente, CategoriaInsumo, Insumo,
    Produto, VariacaoProduto, FichaTecnicaItem, OrdemProducao,
    Pedido, ItemPedido,
    Remessa, RemessaItem,
    FASE_CONSUMO, SIZE_ORDER,
    Costureira, PagamentoCostureira, PessoaColeta
)

# =============================================================================
# UX: aplica classes Bootstrap automaticamente
# =============================================================================
class BootstrapFormMixin:
    """Adiciona 'form-control' ou 'form-select' a todos os campos."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            w = f.widget
            cls = w.attrs.get("class", "")
            if isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs["class"] = (cls + " form-select").strip()
            else:
                w.attrs["class"] = (cls + " form-control").strip()


# =============================================================================
# EMPRESA / PARÂMETROS
# =============================================================================
class EmpresaForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Empresa
        fields = "__all__"


class ParametrosEmpresaForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ParametrosEmpresa
        fields = "__all__"


# =============================================================================
# CLIENTE
# =============================================================================
class ClienteForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Cliente
        fields = "__all__"


# =============================================================================
# INSUMOS
# =============================================================================
class CategoriaInsumoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CategoriaInsumo
        fields = ["nome"]


class InsumoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Insumo
        fields = ["empresa", "categoria", "nome", "unidade",
                  "estoque_atual", "custo_medio", "ativo"]
        widgets = {
            "estoque_atual": forms.NumberInput(attrs={"step": "0.0001", "min": "0"}),
            "custo_medio":   forms.NumberInput(attrs={"step": "0.0001", "min": "0"}),
        }


class EntradaInsumoForm(BootstrapFormMixin, forms.Form):
    quantidade = forms.DecimalField(
        decimal_places=4, max_digits=12, min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"step": "0.0001", "min": "0"})
    )
    custo_unit = forms.DecimalField(
        decimal_places=4, max_digits=12, min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"step": "0.0001", "min": "0"})
    )
    observacao = forms.CharField(required=False)


# =============================================================================
# PRODUTO / VARIAÇÃO / FICHA TÉCNICA
# =============================================================================

# Mantido para compatibilidade com imports existentes (ex.: views):
TAMANHOS_PADRAO = list(SIZE_ORDER)
TAMANHOS_CHOICES = [(t, t) for t in SIZE_ORDER]

class ProdutoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Produto
        fields = ["empresa", "nome", "descricao", "ativo"]


class VariacaoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = VariacaoProduto
        fields = [
            "produto", "tipo",
            "estoque_atual", "custo_unitario", "preco_sugerido",
        ]  # SKU é gerado automaticamente e não editável
        widgets = {
            "estoque_atual":  forms.NumberInput(attrs={"step": "0.01",   "min": "0"}),
            "custo_unitario": forms.NumberInput(attrs={"step": "0.0001", "min": "0"}),
            "preco_sugerido": forms.NumberInput(attrs={"step": "0.01",   "min": "0"}),
        }
        help_texts = {
            "preco_sugerido": "Preço sugerido da variação.",
            "custo_unitario": "Custo médio da variação (informativo).",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Exibe o SKU somente leitura quando a variação já existe
        if self.instance and self.instance.pk:
            self.fields["sku_view"] = forms.CharField(
                label="SKU",
                required=False,
                initial=self.instance.sku or "",
                widget=forms.TextInput(
                    attrs={"readonly": "readonly", "class": "form-control"}
                ),
            )
            self.order_fields([
                "produto", "tipo", "sku_view",
                "estoque_atual", "custo_unitario", "preco_sugerido",
            ])

    def clean(self):
        data = super().clean()
        for f in ("estoque_atual", "custo_unitario", "preco_sugerido"):
            v = data.get(f)
            if v is not None and v < 0:
                self.add_error(f, "Não pode ser negativo.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        # Protege o SKU: mantém o já existente e nunca aceita alteração via POST
        if obj.pk:
            obj.sku = VariacaoProduto.objects.only("sku").get(pk=obj.pk).sku
        if commit:
            obj.save()
        return obj



class FichaItemForm(BootstrapFormMixin, forms.ModelForm):
    fase = forms.ChoiceField(choices=FASE_CONSUMO, required=True, label="Fase de consumo")

    class Meta:
        model = FichaTecnicaItem
        fields = ["insumo", "quantidade", "fase"]
        widgets = {
            "quantidade": forms.NumberInput(attrs={"step": "0.0001", "min": "0"}),
        }


# =============================================================================
# ORDEM DE PRODUÇÃO
# =============================================================================
class OrdemProducaoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = OrdemProducao
        fields = ["empresa", "variacao", "quantidade",
                  "custo_mao_de_obra", "custo_indireto_rateado", "observacao"]


# =============================================================================
# PEDIDO / ITENS
# =============================================================================
class PedidoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Pedido
        fields = [
            "empresa", "cliente", "status",
            "numero_orcamento", "validade", "data_entrega",  # <-- ADICIONADO
            "condicoes", "arte",
            "desconto_percentual", "acrescimo_percentual", "observacao",
        ]
        widgets = {
            "validade": forms.DateInput(attrs={"type": "date"}),
            "data_entrega": forms.DateInput(attrs={"type": "date"}),  # <-- NOVO
            "arte": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "desconto_percentual": forms.NumberInput(attrs={
                "step": "0.01", "min": "0", "max": "100"
            }),
            "acrescimo_percentual": forms.NumberInput(attrs={
                "step": "0.01", "min": "0", "max": "100"
            }),
        }

    def clean_desconto_percentual(self):
        v = self.cleaned_data.get("desconto_percentual") or Decimal("0")
        if v < 0 or v > 100:
            raise ValidationError("O desconto deve estar entre 0% e 100%.")
        return v

    def clean_acrescimo_percentual(self):
        v = self.cleaned_data.get("acrescimo_percentual") or Decimal("0")
        if v < 0 or v > 100:
            raise ValidationError("O acréscimo deve estar entre 0% e 100%.")
        return v


class ItemPedidoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ItemPedido
        fields = [
            "variacao",
            "quantidade",
            "preco_unitario",
            "nome_personalizado",
            "numero_camisa",
            "outra_info",
            "incluir_short",
            "tamanho_short",
        ]
        widgets = {
            "quantidade": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "preco_unitario": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "nome_personalizado": forms.TextInput(attrs={"placeholder": "Ex.: João"}),
            "numero_camisa": forms.TextInput(attrs={"placeholder": "Ex.: 10"}),
            "outra_info": forms.TextInput(attrs={"placeholder": "Ex.: Capitão"}),
            "incluir_short": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "tamanho_short": forms.TextInput(attrs={"placeholder": "Ex.: M"}),
        }

from django.forms import inlineformset_factory
from .models import ItemPedido, PersonalizacaoItem

# camisas/forms.py
# camisas/forms.py
class PersonalizacaoItemForm(forms.ModelForm):
    class Meta:
        model = PersonalizacaoItem
        fields = [
            "nome",
            "numero",
            "outra_info",
            "tamanho_camisa",
            "quantidade",
            "incluir_short",
            "tamanho_short",
        ]
        widgets = {
            "tamanho_camisa": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "quantidade": forms.NumberInput(attrs={
                "class": "form-control form-control-sm",
                "min": "1",
                "step": "1",
            }),
            "tamanho_short": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 🔹 garante que o campo não será obrigatório
        self.fields["quantidade"].required = False


PersonalizacaoItemFormSet = inlineformset_factory(
    ItemPedido,
    PersonalizacaoItem,
    form=PersonalizacaoItemForm,
    extra=1,
    can_delete=True
)

class ArtePedidoForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Pedido
        fields = ["arte"]


# =============================================================================
# REMESSAS
# =============================================================================
class RemessaForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Remessa
        fields = ("empresa", "costureira", "tipo", "produto", "kg_enviados", "observacao")
        widgets = {
            "kg_enviados": forms.NumberInput(attrs={"step": "0.001", "min": "0"}),
        }


class RemessaItemForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = RemessaItem
        fields = ("variacao", "qtd_prevista", "preco_unit")
        widgets = {
            "qtd_prevista": forms.NumberInput(attrs={"step": "1", "min": "0"}),      # inteiro por peça
            "preco_unit":   forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "0 = preço padrão"}),
        }

    def clean_qtd_prevista(self):
        v = self.cleaned_data.get("qtd_prevista")
        if v is None:
            return Decimal("0")
        if v < 0:
            raise ValidationError("Não pode ser negativo.")
        return v

    def clean_preco_unit(self):
        v = self.cleaned_data.get("preco_unit")
        if v is None:
            return Decimal("0")
        if v < 0:
            raise ValidationError("Não pode ser negativo.")
        return v


class BaseRemessaItemFormSet(BaseInlineFormSet):
    """
    - Impede variações duplicadas na mesma remessa.
    - Descarta silenciosamente linhas realmente vazias (sem variação, qtd=0 e preço=0).
    """
    def clean(self):
        super().clean()
        vistos = set()
        duplicado = False
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            cd = form.cleaned_data
            if not cd or cd.get("DELETE"):
                continue

            variacao = cd.get("variacao")
            qtd = cd.get("qtd_prevista") or Decimal("0")
            preco = cd.get("preco_unit") or Decimal("0")

            # linha totalmente vazia -> marca para excluir
            if not variacao and qtd == 0 and preco == 0:
                form.cleaned_data["DELETE"] = True
                continue

            if not variacao:
                # se informou qtd/preço mas não variou a variação, marca erro
                form.add_error("variacao", "Selecione a variação.")
                continue

            key = variacao.pk
            if key in vistos:
                duplicado = True
                form.add_error("variacao", "Variação repetida nesta remessa. Use apenas uma linha por variação.")
            else:
                vistos.add(key)

        if duplicado:
            raise ValidationError("Há variações repetidas na tabela. Remova as duplicadas.")


RemessaItemFormSet = inlineformset_factory(
    Remessa,
    RemessaItem,
    form=RemessaItemForm,
    formset=BaseRemessaItemFormSet,
    extra=0,            # <- não cria linhas obrigatórias
    can_delete=True,
    min_num=0,
    validate_min=False,
    validate_max=False,
)


# ----- Recebimento -----
class RemessaReceiveItemForm(BootstrapFormMixin, forms.ModelForm):
    """Form do recebimento: aceita campos vazios e transforma em 0.
       Se o preço ficar vazio/zero, o modelo aplicará o preço padrão
       (via RemessaItem.preco_unitario_efetivo / Remessa.preco_base_para_tipo)."""

    class Meta:
        model = RemessaItem
        fields = ("qtd_ok", "qtd_perda", "qtd_extravio", "qtd_devolvida", "preco_unit")
        widgets = {
            "qtd_ok":        forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "qtd_perda":     forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "qtd_extravio":  forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "qtd_devolvida": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "preco_unit":    forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "0 = preço padrão"}),
        }

    def clean(self):
        cleaned = super().clean()

        # zera vazios
        for fld in ("qtd_ok", "qtd_perda", "qtd_extravio", "qtd_devolvida", "preco_unit"):
            val = cleaned.get(fld)
            if val in (None, ""):
                cleaned[fld] = Decimal("0")

        # não permite negativos
        for fld in ("qtd_ok", "qtd_perda", "qtd_extravio", "qtd_devolvida",):
            if cleaned[fld] is not None and cleaned[fld] < 0:
                self.add_error(fld, "Valor não pode ser negativo.")

        # alerta se ultrapassar previsão (apenas aviso, não bloqueia)
        inst = self.instance
        if inst and inst.pk and inst.qtd_prevista is not None:
            soma = (cleaned["qtd_ok"] + cleaned["qtd_perda"] +
                    cleaned["qtd_extravio"] + cleaned["qtd_devolvida"])
            if soma > inst.qtd_prevista:
                self.add_error("qtd_ok", f"A soma das quantidades ({soma}) excede o previsto ({inst.qtd_prevista}).")

        return cleaned


RemessaReceiveFormSet = inlineformset_factory(
    Remessa, RemessaItem,
    form=RemessaReceiveItemForm,
    extra=0, can_delete=False
)


# --- COSTUREIRA ---
class CostureiraForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Costureira
        fields = ("nome", "telefone",
                  "preco_corte_por_peca", "preco_costura_por_peca", "preco_correcao_por_peca",
                  "ativo")
        widgets = {
            "preco_corte_por_peca":   forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "preco_costura_por_peca": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "preco_correcao_por_peca":forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }


# --- FILTRO DE PAGAMENTOS ---
STATUS_PG_CHOICES = (("", "Todos"),) + PagamentoCostureira.STATUS
TIPO_REMESSA_CHOICES = (("", "Todos"),) + Remessa.TIPO

class PagamentoFiltroForm(BootstrapFormMixin, forms.Form):
    empresa     = forms.ModelChoiceField(queryset=Empresa.objects.all(), required=False, empty_label="Todas")
    costureira  = forms.ModelChoiceField(queryset=Costureira.objects.all(), required=False, empty_label="Todas")
    tipo        = forms.ChoiceField(choices=TIPO_REMESSA_CHOICES, required=False)
    status      = forms.ChoiceField(choices=STATUS_PG_CHOICES, required=False)
    data_de     = forms.DateField(required=False, widget=forms.DateInput(attrs={"type":"date"}))
    data_ate    = forms.DateField(required=False, widget=forms.DateInput(attrs={"type":"date"}))

# camisas/forms.py (adicione)
from django.forms import inlineformset_factory, BaseInlineFormSet
from .models import Despesa, ParcelaDespesa, CategoriaDespesa, Fornecedor

class CategoriaDespesaForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CategoriaDespesa
        fields = ["empresa", "nome"]

class FornecedorForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Fornecedor
        fields = ["empresa", "nome", "cpf_cnpj", "telefone", "email"]

class DespesaForm(BootstrapFormMixin, forms.ModelForm):
    # campo opcional só pra UX: se informar > 1, a view cria parcelas iguais
    parcelas_qty = forms.IntegerField(min_value=1, required=False, label="Parcelas (auto)")
    primeira_parcela = forms.DateField(required=False, label="Vencimento 1ª parcela",
                                       widget=forms.DateInput(attrs={"type": "date"}))

    class Meta:
        model = Despesa
        fields = ["empresa","categoria","fornecedor","descricao","valor_total","data_emissao",
                  "vencimento","forma_pagamento","status","observacao","anexo"]

        widgets = {
            "data_emissao": forms.DateInput(attrs={"type":"date"}),
            "vencimento":   forms.DateInput(attrs={"type":"date"}),
            "valor_total":  forms.NumberInput(attrs={"step":"0.01", "min":"0"}),
        }

class BaseParcelaFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        # opcional: valida duplicatas de número
        numeros = []
        for f in self.forms:
            if not hasattr(f, "cleaned_data"): 
                continue
            cd = f.cleaned_data
            if cd.get("DELETE"): 
                continue
            n = cd.get("numero")
            if n in numeros:
                f.add_error("numero", "Número de parcela repetido.")
            else:
                numeros.append(n)

ParcelaFormSet = inlineformset_factory(
    Despesa, ParcelaDespesa,
    fields=("numero","vencimento","valor","status"),
    extra=0, can_delete=True,
    formset=BaseParcelaFormSet
)

# camisas/forms.py
from django import forms
from django.forms import inlineformset_factory
from .models import CotacaoConcorrente, CotacaoConcorrenteItem

class CotacaoConcorrenteForm(forms.ModelForm):
    class Meta:
        model = CotacaoConcorrente
        fields = ("empresa_nome", "cnpj", "email", "telefone", "validade", "observacao")
        widgets = {
            "validade": forms.DateInput(attrs={"type": "date"}),
            "observacao": forms.Textarea(attrs={"rows": 3}),
        }

class CotacaoConcorrenteItemForm(forms.ModelForm):
    class Meta:
        model = CotacaoConcorrenteItem
        fields = ("item_nome", "descricao", "unidade", "quantidade", "valor_unitario")
        widgets = {"descricao": forms.Textarea(attrs={"rows": 2})}

CotacaoConcorrenteItemFormSet = inlineformset_factory(
    CotacaoConcorrente,
    CotacaoConcorrenteItem,
    form=CotacaoConcorrenteItemForm,
    extra=0,
    can_delete=True,
)

# camisas/forms.py
from django import forms
from .models import FrequenciaDia, Funcionario

class TimeInput(forms.TimeInput):
    input_type = "time"
    format = "%H:%M"

class FrequenciaDiaForm(forms.ModelForm):
    class Meta:
        model = FrequenciaDia
        fields = ["funcionario", "data", "e1", "s1", "e2", "s2", "observacao", "minutos_previstos_override"]
        widgets = {
            "funcionario": forms.Select(attrs={"class":"form-select"}),
            "data": forms.DateInput(attrs={"type":"date","class":"form-control"}),
            "e1": TimeInput(attrs={"class":"form-control"}),
            "s1": TimeInput(attrs={"class":"form-control"}),
            "e2": TimeInput(attrs={"class":"form-control"}),
            "s2": TimeInput(attrs={"class":"form-control"}),
            "observacao": forms.TextInput(attrs={"class":"form-control"}),
            "minutos_previstos_override": forms.NumberInput(attrs={"class":"form-control", "min":"0", "step":"1"}),
        }

class FiltroFrequenciaForm(forms.Form):
    func = forms.ModelChoiceField(
        label="Funcionário",
        queryset=Funcionario.objects.filter(ativo=True),
        widget=forms.Select(attrs={"class":"form-select"})
    )
    # aceita '2025-08' e também '2025-08-01'
    mes  = forms.DateField(
        label="Mês",
        input_formats=["%Y-%m", "%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type":"month","class":"form-control"})
    )

# camisas/forms.py
from django import forms
from django.utils import timezone
from .models import ColetaPedido

class ColetaCreateForm(forms.ModelForm):
    class Meta:
        model = ColetaPedido
        fields = ["modo", "expiracao"]

        widgets = {
            "expiracao": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
        help_texts = {
            "expiracao": "Opcional. Deixe em branco para não expirar.",
        }

    def clean_expiracao(self):
        v = self.cleaned_data.get("expiracao")
        if v and v < timezone.now():
            raise forms.ValidationError("A data de expiração não pode ser no passado.")
        return v

# camisas/forms.py
from django import forms
from .models import PessoaColeta

class PessoaColetaForm(forms.ModelForm):
    class Meta:
        model = PessoaColeta
        fields = ["nome", "numero", "tamanho", "status_pagamento", "valor"]

        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control"}),
            "numero": forms.TextInput(attrs={"class": "form-control"}),
            "tamanho": forms.TextInput(attrs={"class": "form-control"}),
            "status_pagamento": forms.Select(attrs={"class": "form-select"}),
            "valor": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }


# camisas/forms.py
from django import forms
from .models import Cliente

class AlterarClientePedidoForm(forms.Form):
    cliente = forms.ModelChoiceField(
        label="Novo cliente",
        queryset=Cliente.objects.all().order_by("nome"),
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

class PessoaColetaForm(forms.ModelForm):
    class Meta:
        model = PessoaColeta
        fields = ["nome", "numero", "tamanho", "valor", "status_pagamento"]
