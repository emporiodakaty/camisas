# camisas/views.py — imports limpos e organizados
from __future__ import annotations

# ===== Stdlib =====
import base64
import hashlib
import json
from collections import OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal

# ===== Django =====
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import (
    Count, Sum, Max, F, Q, Value,
    DecimalField, DateTimeField, ExpressionWrapper,
)
from django.db.models.functions import Coalesce, Cast
from django.forms import inlineformset_factory
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from .forms import PersonalizacaoItemFormSet

from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

# ===== App =====
from .forms import (
    EmpresaForm, ParametrosEmpresaForm, ClienteForm, CategoriaInsumoForm,
    InsumoForm, EntradaInsumoForm, ProdutoForm, VariacaoForm,
    FichaItemForm, OrdemProducaoForm, PedidoForm, ItemPedidoForm,
    ArtePedidoForm,
    # Remessas
    RemessaForm, RemessaItemFormSet, RemessaReceiveFormSet,
    # Despesas
    DespesaForm, ParcelaFormSet, CotacaoConcorrenteItemForm, PessoaColetaForm, PersonalizacaoItem
)
from .models import (
    Empresa, ParametrosEmpresa, Cliente, CategoriaInsumo, Insumo,
    Produto, VariacaoProduto, FichaTecnicaItem, OrdemProducao,
    Pedido, ItemPedido, MovimentoEstoque,
    # Terceirização
    Costureira, Remessa, RemessaItem, PagamentoCostureira,
    # Despesas
    Despesa, ParcelaDespesa, CategoriaDespesa, Fornecedor,
    # Auxiliares
    SIZE_ORDER,
)
# opcional: só se existir no seu models
try:
    from .models import size_order_case  # noqa: F401
except Exception:
    size_order_case = None  # evita NameError se não existir

from .utils import gen_approval_token


# ============================
# Constantes de expressão
# ============================
Money = DecimalField(max_digits=18, decimal_places=2)
ZERO_MONEY = Value(Decimal("0.00"), output_field=Money)
LINE_TOTAL = ExpressionWrapper(F("preco_unitario") * F("quantidade"), output_field=Money)

QtyField = DecimalField(max_digits=18, decimal_places=2)
ZERO_QTY = Value(Decimal("0.00"), output_field=QtyField)

# Formset de Itens do Pedido (embutido no form do pedido)
ItemFormSet = inlineformset_factory(
    Pedido, ItemPedido, form=ItemPedidoForm, extra=1, can_delete=True
)

# ============================
# DASHBOARD (Home)
# ============================
@login_required
def home(request):
    empresa_id = request.GET.get("empresa") or None
    ini = request.GET.get("ini")
    fim = request.GET.get("fim")
    status = request.GET.get("status") or None

    # Janela padrão: últimos 30 dias
    if not ini or not fim:
        fim_date = date.today()
        ini_date = fim_date - timedelta(days=29)
    else:
        fim_date = date.fromisoformat(fim)
        ini_date = date.fromisoformat(ini)

    # ---------------------------
    # BASES de consulta
    # ---------------------------
    pedidos = Pedido.objects.select_related("cliente", "empresa")
    if empresa_id:
        pedidos = pedidos.filter(empresa_id=empresa_id)
    if status:
        pedidos = pedidos.filter(status=status)
    pedidos = pedidos.filter(criado_em__date__gte=ini_date, criado_em__date__lte=fim_date)

    base_kpi = Pedido.objects.all()
    if empresa_id:
        base_kpi = base_kpi.filter(empresa_id=empresa_id)

    # ---------------------------
    # RECEITAS
    # ---------------------------
    fat_qs = base_kpi.filter(status="FAT")
    if hasattr(Pedido, "faturado_em"):
        fat_qs = fat_qs.filter(faturado_em__date__gte=ini_date, faturado_em__date__lte=fim_date)
    else:
        fat_qs = fat_qs.filter(criado_em__date__gte=ini_date, criado_em__date__lte=fim_date)

    fat_total = ItemPedido.objects.filter(pedido__in=fat_qs).aggregate(
        v=Coalesce(Sum(LINE_TOTAL, output_field=Money), ZERO_MONEY)
    )["v"] or Decimal("0.00")
    qtd_faturados = fat_qs.count()

    pend_qs = base_kpi.exclude(status__in=["FAT", "CANC"]).filter(
        criado_em__date__gte=ini_date, criado_em__date__lte=fim_date
    )
    pend_total = ItemPedido.objects.filter(pedido__in=pend_qs).aggregate(
        v=Coalesce(Sum(LINE_TOTAL, output_field=Money), ZERO_MONEY)
    )["v"] or Decimal("0.00")

    ticket_medio = (fat_total / qtd_faturados) if qtd_faturados else Decimal("0.00")

    # ---------------------------
    # Totais por pedido
    # ---------------------------
    itens = ItemPedido.objects.filter(pedido__in=pedidos)
    totals_by_pedido = itens.values("pedido_id").annotate(
        total=Coalesce(Sum(LINE_TOTAL, output_field=Money), ZERO_MONEY)
    )
    total_map = {r["pedido_id"]: r["total"] for r in totals_by_pedido}

    # Produção no período
    ops = OrdemProducao.objects.all()
    if empresa_id:
        ops = ops.filter(empresa_id=empresa_id)
    ops = ops.filter(criado_em__date__gte=ini_date, criado_em__date__lte=fim_date)
    pecas_produzidas = ops.aggregate(
        q=Coalesce(Sum("quantidade", output_field=QtyField), ZERO_QTY)
    )["q"] or Decimal("0.00")

    # Clientes ativos/novos
    clientes_ativos = pedidos.values("cliente_id").distinct().count()
    first_ped = Pedido.objects.order_by("cliente_id", "criado_em")
    if empresa_id:
        first_ped = first_ped.filter(empresa_id=empresa_id)
    first_by_cliente = {}
    for p in first_ped.values("cliente_id", "criado_em"):
        cid = p["cliente_id"]
        if cid not in first_by_cliente:
            first_by_cliente[cid] = p["criado_em"].date()
    clientes_novos = sum(1 for _, d in first_by_cliente.items() if ini_date <= d <= fim_date)

    # KPIs
    kpis = {
        "window_label": f"{ini_date.strftime('%d/%m/%Y')} — {fim_date.strftime('%d/%m/%Y')}",
        "receita_faturado": float(fat_total),
        "receita_pendente": float(pend_total),
        "receita": float(fat_total),
        "qtd_pedidos": pedidos.count(),
        "ticket_medio": float(ticket_medio),
        "qtd_faturados": qtd_faturados,
        "pecas_produzidas": float(pecas_produzidas),
        "ops": ops.count(),
        "clientes_ativos": clientes_ativos,
        "clientes_novos": clientes_novos,
    }

    # Pedidos recentes
    recent = pedidos.order_by("-criado_em")[:10]
    pedidos_recent = [{
        "id": p.id,
        "cliente": getattr(p.cliente, "nome", str(p.cliente)),
        "status": p.status,
        "status_label": dict(Pedido.STATUS).get(p.status, p.status),
        "total": float(total_map.get(p.id, Decimal("0.00"))),
        "criado_em": p.criado_em,
    } for p in recent]

    # Baixo estoque
    baixo_estoque_qs = VariacaoProduto.objects.filter(estoque_atual__lte=5)
    if empresa_id:
        baixo_estoque_qs = baixo_estoque_qs.filter(produto__empresa_id=empresa_id)
    baixo_estoque = baixo_estoque_qs.values(
        "produto__nome", "tipo", "sku", "estoque_atual"
    )[:10]

    # Produção recente
    ops_recent = ops.order_by("-criado_em").values(
        "id",
        "variacao__produto__nome",
        "variacao__tipo",   # tamanho
        "variacao__sku",    # identificador
        "quantidade",
        "criado_em"
    )[:10]

    # Gráfico de vendas por dia
    day = ini_date
    sales_map = OrderedDict()
    while day <= fim_date:
        sales_map[day] = Decimal("0.00")
        day += timedelta(days=1)

    for p in pedidos:
        d = p.criado_em.date()
        if d in sales_map:
            sales_map[d] += total_map.get(p.id, Decimal("0.00"))

    dash_sales = {
        "labels": [d.strftime("%d/%m") for d in sales_map.keys()],
        "values": [float(v) for v in sales_map.values()],
    }

    top_qs = itens.values("variacao__produto__nome").annotate(
        receita=Coalesce(Sum(LINE_TOTAL, output_field=Money), ZERO_MONEY)
    ).order_by("-receita")[:8]
    dash_top_products = {
        "labels": [r["variacao__produto__nome"] for r in top_qs],
        "values": [float(r["receita"] or Decimal("0.00")) for r in top_qs],
    }

    status_qs = pedidos.values("status").annotate(q=Count("id")).order_by()
    dash_status = {
        "labels": [dict(Pedido.STATUS).get(s["status"], s["status"]) for s in status_qs],
        "values": [s["q"] for s in status_qs],
    }

    dash = {
        "sales": dash_sales,
        "top_products": dash_top_products,
        "status_breakdown": dash_status,
    }
    dash_json = mark_safe(json.dumps(dash, ensure_ascii=False))

    context = {
        "empresas": Empresa.objects.all().order_by("nome_fantasia"),
        "filtro": {"ini": ini_date.isoformat(), "fim": fim_date.isoformat()},
        "kpis": kpis,
        "pedidos_recent": pedidos_recent,
        "baixo_estoque": baixo_estoque,
        "ops_recent": ops_recent,
        "dash": dash_json,
        "dash_json": dash_json,
    }
    return render(request, "camisas/home.html", context)


# ============================
# EMPRESAS
# ============================
@login_required
def empresa_list(request):
    q = (request.GET.get('q') or '').strip()
    qs = Empresa.objects.all()
    if q:
        qs = qs.filter(
            Q(nome_fantasia__icontains=q) |
            Q(cnpj__icontains=q) |
            Q(cidade__icontains=q)
        )
    empresas = qs.order_by('nome_fantasia')
    return render(request, 'camisas/empresa_list.html', {
        'empresas': empresas,
        'q': q,
    })

@login_required
def empresa_create(request):
    if request.method == "POST":
        form = EmpresaForm(request.POST, request.FILES)
        if form.is_valid():
            e = form.save()
            messages.success(request, "Empresa criada.")
            return redirect("camisas:empresa_update", e.pk)
    else:
        form = EmpresaForm()
    return render(request, "camisas/empresa_form.html", {"form": form})

@login_required
def empresa_update(request, pk):
    e = get_object_or_404(Empresa, pk=pk)
    if request.method == "POST":
        form = EmpresaForm(request.POST, request.FILES, instance=e)
        if form.is_valid():
            form.save()
            messages.success(request, "Empresa atualizada.")
            return redirect("camisas:empresa_update", e.pk)
    else:
        form = EmpresaForm(instance=e)
    return render(request, "camisas/empresa_form.html", {"form": form, "obj": e})

# ============================
# CLIENTES
# ============================
@login_required
def cliente_list(request):
    q = (request.GET.get("q") or "").strip()
    empresa_id = request.GET.get("empresa") or ""

    qs = Cliente.objects.select_related("empresa")
    if q:
        qs = qs.filter(
            Q(nome__icontains=q) |
            Q(email__icontains=q) |
            Q(cpf_cnpj__icontains=q)
        )
    if empresa_id:
        qs = qs.filter(empresa_id=empresa_id)

    clientes = qs.order_by("nome")

    return render(request, "camisas/cliente_list.html", {
        "clientes": clientes,
        "q": q,
        "empresas": Empresa.objects.order_by("nome_fantasia"),
        "sel": {"empresa": empresa_id},
    })

@login_required
def cliente_create(request):
    if request.method == "POST":
        form = ClienteForm(request.POST)
        if form.is_valid():
            c = form.save()
            messages.success(request, "Cliente cadastrado.")
            return redirect("camisas:cliente_update", c.pk)
    else:
        form = ClienteForm()
    return render(request, "camisas/cliente_form.html", {"form": form})

@login_required
def cliente_update(request, pk):
    c = get_object_or_404(Cliente, pk=pk)
    if request.method == "POST":
        form = ClienteForm(request.POST, instance=c)
        if form.is_valid():
            form.save()
            messages.success(request, "Cliente atualizado.")
            return redirect("camisas:cliente_update", c.pk)
    else:
        form = ClienteForm(instance=c)
    return render(request, "camisas/cliente_form.html", {"form": form, "obj": c})

# ============================
# INSUMOS + ENTRADA
# ============================
@login_required
def insumo_list(request):
    q = request.GET.get("q", "")
    categoria = request.GET.get("categoria", "")
    empresa_id = request.GET.get("empresa", "")

    qs = Insumo.objects.select_related("empresa", "categoria").all()
    if q:
        qs = qs.filter(nome__icontains=q)
    if categoria:
        qs = qs.filter(categoria_id=categoria)
    if empresa_id:
        qs = qs.filter(empresa_id=empresa_id)

    ctx = {
        "rows": qs.order_by("nome"),
        "categorias": CategoriaInsumo.objects.all().order_by("nome"),
        "empresas": Empresa.objects.all().order_by("nome_fantasia"),
        "sel": {"q": q, "categoria": categoria, "empresa": empresa_id},
    }
    return render(request, "camisas/insumo_list.html", ctx)

@login_required
def insumo_create(request):
    if request.method == "POST":
        form = InsumoForm(request.POST)
        if form.is_valid():
            i = form.save()
            messages.success(request, "Insumo cadastrado.")
            return redirect("camisas:insumo_update", i.pk)
    else:
        form = InsumoForm()
    return render(request, "camisas/insumo_form.html", {"form": form})

@login_required
def insumo_update(request, pk):
    i = get_object_or_404(Insumo, pk=pk)
    if request.method == "POST":
        form = InsumoForm(request.POST, instance=i)
        if form.is_valid():
            form.save()
            messages.success(request, "Insumo atualizado.")
            return redirect("camisas:insumo_update", i.pk)
    else:
        form = InsumoForm(instance=i)
    return render(request, "camisas/insumo_form.html", {"form": form, "obj": i})

@login_required
def insumo_entrada(request, pk):
    insumo = get_object_or_404(Insumo, pk=pk)
    if request.method == "POST":
        form = EntradaInsumoForm(request.POST)
        if form.is_valid():
            q = form.cleaned_data["quantidade"]
            cu = form.cleaned_data["custo_unit"]
            obs = form.cleaned_data.get("observacao") or ""
            insumo.entrada(quantidade=Decimal(q), custo_unit=Decimal(cu), observacao=obs)
            messages.success(request, "Entrada registrada e custo médio atualizado.")
            return redirect("camisas:insumo_update", insumo.pk)
    else:
        form = EntradaInsumoForm()
    return render(request, "camisas/entrada_insumo.html", {"form": form, "insumo": insumo})

# ============================
# PRODUTOS / VARIAÇÕES
# ============================
@login_required
def produto_list(request):
    q = (request.GET.get("q") or "").strip()
    empresa_id = request.GET.get("empresa") or ""

    qs = Produto.objects.select_related("empresa")
    if q:
        qs = qs.filter(
            Q(nome__icontains=q) |
            Q(variacoes__sku__icontains=q)
        ).distinct()
    if empresa_id:
        qs = qs.filter(empresa_id=empresa_id)

    produtos = qs.order_by("nome")

    return render(request, "camisas/produto_list.html", {
        "produtos": produtos,
        "empresas": Empresa.objects.order_by("nome_fantasia"),
        "sel": {"q": q, "empresa": empresa_id},
        "rows": produtos,  # compatibilidade
    })

@login_required
def produto_create(request):
    if request.method == "POST":
        form = ProdutoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Produto cadastrado.")
            return redirect("camisas:produto_list")
    else:
        form = ProdutoForm()
    return render(request, "camisas/produto_form.html", {"form": form})

@login_required
def variacao_create(request):
    if request.method == "POST":
        form = VariacaoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Variação cadastrada.")
            return redirect("camisas:produto_list")
    else:
        form = VariacaoForm()
    return render(request, "camisas/variacao_form.html", {"form": form})

# ============================
# FICHA TÉCNICA (por variação)
# ============================
@login_required
def ficha_list(request, variacao_id: int):
    variacao = get_object_or_404(VariacaoProduto.objects.select_related("produto"), pk=variacao_id)
    itens = variacao.ficha.select_related("insumo", "insumo__categoria").all()
    return render(request, "camisas/ficha_list.html", {"variacao": variacao, "itens": itens})

@login_required
def ficha_add_item(request, variacao_id: int):
    variacao = get_object_or_404(VariacaoProduto, pk=variacao_id)
    if request.method == "POST":
        form = FichaItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.variacao = variacao
            item.save()
            messages.success(request, "Item adicionado à ficha técnica.")
            return redirect("camisas:ficha_list", variacao_id=variacao.pk)
    else:
        form = FichaItemForm()
    return render(request, "camisas/ficha_form.html", {"form": form, "variacao": variacao})

# ============================
# ORDEM DE PRODUÇÃO (manual)
# ============================
@login_required
def op_create(request):
    if request.method == "POST":
        form = OrdemProducaoForm(request.POST)
        if form.is_valid():
            op = form.save()
            op.processar()
            messages.success(request, f"OP #{op.pk} criada e processada.")
            return redirect("camisas:home")
    else:
        form = OrdemProducaoForm()
    return render(request, "camisas/op_form.html", {"form": form})

# ============================
# VENDAS / PEDIDOS
# ============================
@login_required
def pedido_list(request):
    status = request.GET.get("status") or ""
    empresa_id = request.GET.get("empresa") or ""
    q = (request.GET.get("q") or "").strip()

    qs = Pedido.objects.select_related("cliente", "empresa")

    if status:
        qs = qs.filter(status=status)
    if empresa_id:
        qs = qs.filter(empresa_id=empresa_id)
    if q:
        qs = qs.filter(
            Q(cliente__nome__icontains=q) |
            Q(numero_orcamento__icontains=q) |
            Q(approval_token__icontains=q)
        )

    # totais por pedido (1 consulta agregada)
    totals = (
        ItemPedido.objects
        .filter(pedido__in=qs)
        .values("pedido_id")
        .annotate(total=Coalesce(Sum(LINE_TOTAL, output_field=Money), ZERO_MONEY))
    )
    tmap = {r["pedido_id"]: r["total"] for r in totals}

    rows = []
    status_dict = dict(Pedido.STATUS)
    apr_dict = dict(Pedido.APPROVAL_CHOICES)

    for p in qs.order_by("-criado_em")[:300]:
        rows.append({
            "id": p.id,
            "numero_orcamento": p.numero_orcamento,
            "data_entrega": p.data_entrega,   # 👈 incluído aqui
            "cliente_id": getattr(p.cliente, "id", None),
            "cliente": getattr(p.cliente, "nome", str(p.cliente)),
            "empresa": getattr(p.empresa, "nome_fantasia", ""),
            "status": p.status,
            "status_label": status_dict.get(p.status, p.status),
            "total": tmap.get(p.id, ZERO_MONEY),
            "criado_em": p.criado_em,
            "approval_status": p.approval_status,
            "approval_status_label": apr_dict.get(p.approval_status, p.approval_status),
            "approval_token": p.approval_token,
            "approval_decided_at": p.approval_decided_at,
            "approval_name": p.approval_name,
            "approval_email": p.approval_email,
            "approval_decision_ip": p.approval_decision_ip,
            # habilita “Alterar cliente” somente para orçamentos
            "can_edit_client": (p.status == "ORC"),
        })

    ctx = {
        "empresas": Empresa.objects.all().order_by("nome_fantasia"),
        "rows": rows,
        "sel": {"status": status, "empresa": empresa_id, "q": q},
        "pedido": Pedido,  # para iterar STATUS no template
        # usado no collapse “Alterar cliente” da lista
        "clientes_all": Cliente.objects.only("id", "nome", "cpf_cnpj").order_by("nome"),
    }
    return render(request, "camisas/pedido_list.html", ctx)


@login_required
def pedido_create(request):
    # variações p/ JS (agora com "tipo" e sem "tamanho")
    variacoes_qs = VariacaoProduto.objects.select_related("produto").values(
        "id", "sku", "tipo", "preco_sugerido",
        "produto__nome", "produto__empresa_id"
    )
    variacoes_json = json.dumps(list(variacoes_qs), default=str)

    if request.method == "POST":
        form = PedidoForm(request.POST, request.FILES)
        pedido_fake = Pedido()
        formset = ItemFormSet(request.POST, instance=pedido_fake)

        # Anexa PersonalizacaoItemFormSet em cada form do item (POST)
        for idx, item_form in enumerate(formset.forms):
            item_form.personalizacoes = PersonalizacaoItemFormSet(
                request.POST,
                prefix=f"personalizacoes-{idx}",
                instance=item_form.instance,
            )

        all_p_valid = all(
            getattr(f, "personalizacoes", None) and f.personalizacoes.is_valid()
            for f in formset.forms
        )

        if form.is_valid() and formset.is_valid() and all_p_valid:
            pedido = form.save()
            formset.instance = pedido
            itens = formset.save()

            # salva personalizações já validadas
            for idx, (item_form, item) in enumerate(zip(formset.forms, itens)):
                pfs = PersonalizacaoItemFormSet(
                    request.POST,
                    prefix=f"personalizacoes-{idx}",
                    instance=item
                )
                pfs.is_valid()
                pfs.save()

            messages.success(request, "Pedido salvo com sucesso!")
            return redirect("camisas:pedido_detail", pedido.pk)

    else:
        form = PedidoForm()
        pedido_fake = Pedido()
        formset = ItemFormSet(instance=pedido_fake)

        # Anexa PersonalizacaoItemFormSet em cada form do item (GET)
        for idx, item_form in enumerate(formset.forms):
            item_form.personalizacoes = PersonalizacaoItemFormSet(
                prefix=f"personalizacoes-{idx}",
                instance=item_form.instance
            )

    return render(request, "camisas/pedido_form.html", {
        "form": form,
        "formset": formset,
        "variacoes_json": variacoes_json,
        "is_edit": False
    })

PersonalizacaoFormSet = inlineformset_factory(
    parent_model=ItemPedido,
    model=PersonalizacaoItem,
    fields=[
        "nome", "numero", "outra_info",
        "tamanho_camisa", "quantidade",
        "incluir_short", "tamanho_short",
    ],
    extra=1,
    can_delete=True,
)

@require_http_methods(["GET", "POST"])
def item_tamanhos_editar(request, item_id):
    """
    Edita os 'tamanhos' (PersonalizacaoItem) vinculados a um ItemPedido.
    O botão na tela de detalhes aponta para esta view.
    """
    item = get_object_or_404(ItemPedido.objects.select_related("pedido", "variacao__produto"), pk=item_id)
    pedido = item.pedido

    formset = PersonalizacaoFormSet(
        data=request.POST or None,
        instance=item,
        prefix="personalizacoes",
    )

    if request.method == "POST":
        if formset.is_valid():
            formset.save()
            messages.success(request, f"Tamanhos do item #{item.id} atualizados com sucesso.")
            return redirect("camisas:pedido_detail", pedido.pk)
        else:
            messages.error(request, "Corrija os erros abaixo para salvar os tamanhos.")

    context = {
        "pedido": pedido,
        "item": item,
        "formset": formset,
    }
    return render(request, "camisas/item_tamanhos_editar.html", context)


@login_required
def pedido_update(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    variacoes_qs = VariacaoProduto.objects.select_related("produto").values(
        "id", "sku", "tamanho", "cor", "preco_sugerido", "produto__nome", "produto__empresa_id"
    )
    variacoes_json = json.dumps(list(variacoes_qs), default=str)

    if request.method == "POST":
        form = PedidoForm(request.POST, request.FILES, instance=pedido)
        formset = ItemFormSet(request.POST, instance=pedido)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "Pedido atualizado!")
            return redirect("camisas:pedido_detail", pedido.pk)
    else:
        form = PedidoForm(instance=pedido)
        formset = ItemFormSet(instance=pedido)

    return render(request, "camisas/pedido_form.html", {
        "form": form, "formset": formset, "variacoes_json": variacoes_json, "is_edit": True
    })

@login_required
def pedido_detail(request, pk):
    p = get_object_or_404(
        Pedido.objects.select_related("cliente", "empresa"),
        pk=pk
    )

    # Garante token único para pedidos antigos que ficaram sem token
    if not p.approval_token:
        p.approval_token = gen_approval_token()
        p.save(update_fields=["approval_token"])

    itens = p.itens.select_related("variacao__produto")

    subtotal = itens.aggregate(
        t=Coalesce(Sum(LINE_TOTAL, output_field=Money), ZERO_MONEY)
    )["t"] or Decimal("0.00")

    desc_pct = p.desconto_percentual or Decimal("0")
    acr_pct  = p.acrescimo_percentual or Decimal("0")
    val_desc = (subtotal * (desc_pct / Decimal("100"))).quantize(Decimal("0.01"))
    val_acr  = (subtotal * (acr_pct  / Decimal("100"))).quantize(Decimal("0.01"))
    total    = (subtotal - val_desc + val_acr).quantize(Decimal("0.01"))

    # Link público pronto para usar no template
    approval_url = request.build_absolute_uri(
        reverse("camisas:orcamento_publico", args=[p.approval_token])
    )

    # Pega a coleta e pessoas vinculadas
    coleta_obj = p.coletas.last()
    pessoas = coleta_obj.pessoas.all() if coleta_obj else []

    ctx = {
        "pedido": p,
        "itens": itens,
        "subtotal": subtotal,
        "val_desc": val_desc,
        "val_acr": val_acr,
        "total": total,
        "approval_url": approval_url,
        "coleta": coleta_obj,
        "pessoas": pessoas,
    }
    return render(request, "camisas/pedido_detail.html", ctx)



from django.core.files.base import ContentFile  # se quiser salvar direto aqui (opcional)
# (o seu model Pedido.approve_with_signature já usa ContentFile internamente)


@csrf_protect
def orcamento_publico(request, token: str):
    p = get_object_or_404(
        Pedido.objects.select_related("cliente", "empresa").prefetch_related("itens__variacao__produto"),
        approval_token=token
    )

    if request.method == "POST":
        today = timezone.localdate()
        can_decide = (not p.validade or today <= p.validade) and (p.approval_status == "PEND")

        is_json = request.headers.get("Content-Type", "").startswith("application/json")
        if is_json:
            try:
                payload = json.loads(request.body.decode() or "{}")
            except Exception:
                payload = {}
            decision = "approve" if payload.get("aceite_termos") else (payload.get("decision") or "")
            sig_b64  = payload.get("assinatura_data_url") or ""
            name     = (payload.get("nome") or "").strip()
            email    = (payload.get("email") or None)
            comment  = (payload.get("comentario") or None)
            tz       = (payload.get("timezone") or "")
            ua       = request.META.get("HTTP_USER_AGENT", "")
        else:
            decision = (request.POST.get("decision") or "").strip()
            sig_b64  = request.POST.get("signature_png") or ""
            name     = (request.POST.get("name") or "").strip()
            email    = (request.POST.get("email") or "").strip() or None
            comment  = (request.POST.get("comment") or "").strip() or None
            tz       = (request.POST.get("tz") or "")
            ua       = (request.POST.get("ua") or request.META.get("HTTP_USER_AGENT", ""))

        ip = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")

        if not can_decide:
            if is_json:
                return JsonResponse({"ok": False, "error": "Orçamento não pode mais ser decidido."}, status=400)
            return HttpResponseRedirect(reverse("camisas:orcamento_publico", args=[p.approval_token]))

        if decision == "approve":
            # --- Assinatura obrigatória ---
            image_bin = None
            if sig_b64.startswith("data:image/png;base64,"):
                try:
                    image_bin = base64.b64decode(sig_b64.split(",", 1)[1])
                except Exception:
                    image_bin = None

            if not image_bin:
                if is_json:
                    return JsonResponse({"ok": False, "error": "Assinatura ausente."}, status=400)
                return HttpResponseRedirect(
                    f"{reverse('camisas:orcamento_publico', args=[p.approval_token])}?err=nosign"
                )

            # === SALVA SEM DISPARAR SIGNALS / SAVE() ===
            # 1) grava o arquivo direto no storage e pega o caminho salvo
            stamp = timezone.now()
            rel_path = f"assinaturas/{stamp:%Y/%m}/pedido_{p.pk}_{stamp:%Y%m%d_%H%M%S}.png"
            saved_path = default_storage.save(rel_path, ContentFile(image_bin))

            # 2) calcula hash e monta os campos
            digest = hashlib.sha256((name or "Cliente").encode("utf-8") + stamp.isoformat().encode("utf-8") + image_bin).hexdigest()
            new_status = "PEN" if p.status == "ORC" else p.status

            # 3) UPDATE direto no banco (bypassa signals e save override)
            (
                Pedido.objects
                .filter(pk=p.pk)
                .update(
                    approval_signature=saved_path,
                    approval_name=(name or "Cliente"),
                    approval_email=email,
                    approval_comment=comment,
                    approval_decision_ip=ip,
                    approval_user_agent=(ua or ""),
                    approval_timezone=(tz or ""),
                    approval_hash=digest,
                    approval_decided_at=stamp,
                    approval_status="APRV",
                    status=new_status,
                )
            )

            if is_json:
                return JsonResponse({"ok": True})

        else:
            # Recusar normalmente (também por UPDATE para evitar signals)
            now = timezone.now()
            (
                Pedido.objects
                .filter(pk=p.pk)
                .update(
                    approval_status="REJ",
                    approval_name=(name or None),
                    approval_email=email,
                    approval_comment=comment,
                    approval_decided_at=now,
                    approval_decision_ip=ip,
                )
            )
            if is_json:
                return JsonResponse({"ok": True})

        # PRG
        return HttpResponseRedirect(reverse("camisas:orcamento_publico", args=[p.approval_token]))

    # ====== GET ======
    itens = p.itens.select_related("variacao__produto")
    subtotal = sum((it.preco_unitario * it.quantidade) for it in itens) or Decimal("0.00")
    desc_pct = p.desconto_percentual or Decimal("0")
    acr_pct  = p.acrescimo_percentual or Decimal("0")
    val_desc = (subtotal * (desc_pct / Decimal("100"))).quantize(Decimal("0.01"))
    val_acr  = (subtotal * (acr_pct  / Decimal("100"))).quantize(Decimal("0.01"))
    total    = (subtotal - val_desc + val_acr).quantize(Decimal("0.01"))

    today = timezone.localdate()
    is_expired = bool(p.validade and today > p.validade)
    already_decided = p.approval_status in ("APRV", "REJ")
    can_decide = (not is_expired) and (not already_decided)

    feedback = "Assinatura é obrigatória para aprovar." if (request.GET.get("err") == "nosign") else None

    return render(request, "camisas/orcamento_publico.html", {
        "pedido": p, "empresa": p.empresa, "cliente": p.cliente,
        "itens": itens, "subtotal": subtotal, "val_desc": val_desc, "val_acr": val_acr, "total": total,
        "feedback": feedback,
        "is_expired": is_expired, "already_decided": already_decided, "can_decide": can_decide,
    })



@login_required
@require_POST
def pedido_reabrir_orcamento(request, pk):
    p = get_object_or_404(Pedido, pk=pk)
    novo = request.POST.get("novo") == "1"
    # método existe no model
    p.reset_approval(regenerate_token=novo, save=True)
    messages.success(request, f"Orçamento reaberto{' com novo link' if novo else ''}.")
    return redirect("camisas:pedido_detail", pk=p.pk)

@login_required
@require_POST
def pedido_delete(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    if pedido.status == "FAT":
        messages.error(request, "Não é possível excluir um pedido já faturado.")
        return redirect("camisas:pedido_detail", pk=pedido.pk)
    pid = pedido.pk
    pedido.delete()
    messages.success(request, f"Pedido #{pid} excluído com sucesso.")
    return redirect("camisas:pedido_list")

# ============================
# REMESSAS (Terceirização)
# ============================
@login_required
def remessa_list(request):
    q = request.GET.get("q") or ""
    tipo = request.GET.get("tipo") or ""
    status = request.GET.get("status") or ""
    empresa_id = request.GET.get("empresa") or ""

    remessas = Remessa.objects.select_related("empresa", "costureira").order_by("-enviado_em")

    if q:
        remessas = remessas.filter(Q(numero__icontains=q) | Q(costureira__nome__icontains=q))
    if tipo:
        remessas = remessas.filter(tipo=tipo)
    if status:
        remessas = remessas.filter(status=status)
    if empresa_id:
        remessas = remessas.filter(empresa_id=empresa_id)

    return render(request, "camisas/remessa_list.html", {
        "rows": remessas[:300],
        "empresas": Empresa.objects.all().order_by("nome_fantasia"),
        "sel": {"q": q, "tipo": tipo, "status": status, "empresa": empresa_id}
    })


def _build_cost_map():
    """Mapeia {costureira_id: {TIPO: preco}} para uso no JS."""
    data = {}
    for c in Costureira.objects.all():
        data[str(c.id)] = {
            "CORTE":    float(c.preco_corte_por_peca or 0),
            "COSTURA":  float(c.preco_costura_por_peca or 0),
            "CORRECAO": float(c.preco_correcao_por_peca or 0),
        }
    return json.dumps(data, cls=DjangoJSONEncoder)

@login_required
def remessa_create(request):
    # ------- GET inicial (filtros por querystring opcionais) -------
    if request.method == "GET":
        initial_main = {}
        empresa_id    = (request.GET.get("empresa") or "").strip()
        costureira_id = (request.GET.get("costureira") or "").strip()
        tipo          = (request.GET.get("tipo") or "").strip()
        produto_id    = (request.GET.get("produto") or "").strip()
        if empresa_id:    initial_main["empresa"] = empresa_id
        if costureira_id: initial_main["costureira"] = costureira_id
        if tipo:          initial_main["tipo"] = tipo
        if produto_id:    initial_main["produto"] = produto_id

        form = RemessaForm(initial=initial_main)

        # formset vazio (o usuário adiciona linhas pelo +)
        formset = RemessaItemFormSet(instance=None, queryset=None)

        ctx = {
            "form": form,
            "formset": formset,
            "tamanhos": SIZE_ORDER,
            "cost_map_json": _build_cost_map(),
        }
        return render(request, "camisas/remessa_form.html", ctx)

    # ------- POST (salvar) -------
    # 1) Monta o form principal e um "parent" temporário para o formset
    form = RemessaForm(request.POST)
    parent_tmp = form.instance  # instância do ModelForm (ainda sem PK)

    # IMPORTANTÍSSIMO: ligar o formset a uma instância (mesmo sem PK)
    formset = RemessaItemFormSet(request.POST, instance=parent_tmp)

    # Valida os dois fora da transação (para não “quebrar” a transação só por erro de validação)
    form_ok = form.is_valid()
    fs_ok = formset.is_valid()

    if form_ok and fs_ok:
        try:
            with transaction.atomic():
                # salva a remessa primeiro para ter PK
                remessa = form.save()

                # re-liga o formset na instância salva e salva os itens
                formset.instance = remessa
                itens = formset.save()  # aqui pode levantar IntegrityError se algo escapar; atomic cuida

                # status inicial
                remessa.status = "ENVIADA"
                remessa.save(update_fields=["status"])

            messages.success(request, f"Remessa {remessa.numero} criada com {len(itens)} item(ns).")
            return redirect("camisas:remessa_detail", remessa.pk)

        except Exception as e:
            # NÃO deixar a exceção “vazar” com a transação quebrada; exibimos erro no form
            form.add_error(None, f"Erro ao salvar a remessa: {e}")

    else:
        # se houver duplicadas, a BaseRemessaItemFormSet já adiciona os erros nas linhas
        messages.error(request, "Verifique os campos destacados e tente novamente.")

    # Renderiza de volta com os erros (fora de atomic) e com o mapa de custos para o JS
    ctx = {
        "form": form,
        "formset": formset,
        "tamanhos": SIZE_ORDER,
        "cost_map_json": _build_cost_map(),
    }
    return render(request, "camisas/remessa_form.html", ctx)


@login_required
@transaction.atomic
def remessa_quick_create_by_produto(request):
    """
    Atalho opcional: cria a remessa já com itens para todas as variações do produto.
    Espera POST com: empresa_id, costureira_id, tipo, produto_id, kg_enviados (opcional).
    """
    if request.method != "POST":
        messages.error(request, "Requisição inválida.")
        return redirect("camisas:remessa_list")

    empresa = get_object_or_404(Empresa, pk=request.POST.get("empresa_id"))
    costureira = get_object_or_404(Costureira, pk=request.POST.get("costureira_id"))
    tipo = (request.POST.get("tipo") or "").strip()
    produto = get_object_or_404(Produto, pk=request.POST.get("produto_id"))
    kg = Decimal(request.POST.get("kg_enviados") or "0")

    r = Remessa.criar_com_itens_por_produto(
        empresa=empresa, costureira=costureira, tipo=tipo,
        produto=produto, kg_enviados=kg
    )
    messages.success(request, f"Remessa {r.numero} criada com itens de todas as variações de {produto.nome}.")
    return redirect("camisas:remessa_detail", r.pk)

@login_required
def remessa_detail(request, pk):
    r = get_object_or_404(Remessa.objects.select_related("empresa", "costureira"), pk=pk)
    return render(request, "camisas/remessa_detail.html", {"r": r})

@login_required
@transaction.atomic
def remessa_receive(request, pk):
    """
    Recebimento:
      - salva quantidades (formset)
      - chama Remessa.finalizar_recebimento() para aplicar baixas/entradas e gerar/atualizar Pagamento
      - atualiza status e recebido_em automaticamente
    """
    r = get_object_or_404(Remessa, pk=pk)

    if request.method == "POST":
        formset = RemessaReceiveFormSet(request.POST, instance=r)
        if formset.is_valid():
            formset.save()
            try:
                # aplica efeitos (estoque/insumos/pagamento) e marca recebido_em/status
                pgto = r.finalizar_recebimento(set_recebido_em=True)

                if pgto:
                    messages.success(
                        request,
                        f"Remessa {r.numero} recebida. Pagamento gerado/atualizado: R$ {pgto.valor_total:.2f}."
                    )
                else:
                    messages.success(request, f"Remessa {r.numero} recebida.")
            except Exception as e:
                # caso haja algum problema na finalização (estoque/pagamento), avisa e mantém na tela
                messages.error(request, f"Não foi possível finalizar a remessa: {e}")
                return render(request, "camisas/remessa_receive.html", {"r": r, "formset": formset})

            return redirect("camisas:remessa_detail", r.pk)
    else:
        formset = RemessaReceiveFormSet(instance=r)

    return render(request, "camisas/remessa_receive.html", {"r": r, "formset": formset})

@login_required
@require_POST
@transaction.atomic
def remessa_generate_next(request, pk):
    """
    Gera a próxima remessa baseada nas quantidades OK.
    Ex.: se a atual for CORTE, gera COSTURA (mesma empresa/produto); costureira pode ser trocada via POST 'costureira_id'.
    """
    r = get_object_or_404(Remessa, pk=pk)
    next_tipo = request.POST.get("tipo") or ("COSTURA" if r.tipo == "CORTE" else "")
    if not next_tipo:
        messages.error(request, "Tipo da próxima remessa não informado.")
        return redirect("camisas:remessa_detail", r.pk)

    cost_id = request.POST.get("costureira_id")
    cost = get_object_or_404(Costureira, pk=cost_id) if cost_id else None

    r2 = r.gerar_remessa_posterior(tipo=next_tipo, costureira=cost)
    messages.success(request, f"Remessa {r2.numero} ({r2.get_tipo_display()}) gerada a partir da {r.numero}.")
    return redirect("camisas:remessa_detail", r2.pk)

@login_required
def remessa_print(request, pk):
    r = get_object_or_404(
        Remessa.objects
        .select_related("empresa", "costureira")
        .prefetch_related("itens__variacao__produto"),
        pk=pk
    )
    return render(request, "camisas/remessa_print.html", {"r": r})

# ============================
# FATURAMENTO
# ============================
@login_required
def pedido_faturar(request, pk):
    p = get_object_or_404(Pedido, pk=pk)

    # valida estoque
    faltas = []
    for it in p.itens.select_related("variacao"):
        if it.variacao.estoque_atual < it.quantidade:
            faltas.append(f"{it.variacao} (falta {it.quantidade - it.variacao.estoque_atual})")
    if faltas:
        messages.error(request, "Estoque insuficiente para faturar: " + "; ".join(faltas))
        return HttpResponseRedirect(reverse("camisas:pedido_detail", args=[p.pk]))

    # baixa de estoque das variações
    for it in p.itens.select_related("variacao"):
        v = it.variacao
        v.estoque_atual -= it.quantidade
        v.save(update_fields=["estoque_atual"])
        MovimentoEstoque.objects.create(
            empresa=p.empresa,
            tipo="S",
            variacao=v,
            quantidade=it.quantidade,
            custo_unit=v.custo_unitario,
            observacao=f"Faturamento Pedido #{p.pk}",
        )

    p.status = "FAT"
    p.save(update_fields=["status"])
    messages.success(request, "Pedido faturado e estoque baixado.")
    return HttpResponseRedirect(reverse("camisas:pedido_detail", args=[p.pk]))

from decimal import Decimal
from django.db import transaction
from django.db.models import Sum, DecimalField, ExpressionWrapper, F, Value
from django.db.models.functions import Coalesce
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages

from .models import Pedido, ItemPedido, OrdemProducao

Money = DecimalField(max_digits=18, decimal_places=2)
ZERO_MONEY = Value(Decimal("0.00"), output_field=Money)
LINE_TOTAL = ExpressionWrapper(F("preco_unitario") * F("quantidade"), output_field=Money)

@login_required
def pedido_orcamento(request, pk):
    p = get_object_or_404(Pedido.objects.select_related("cliente", "empresa"), pk=pk)
    itens = p.itens.select_related("variacao__produto")

    subtotal = itens.aggregate(
        t=Coalesce(Sum(LINE_TOTAL, output_field=Money), ZERO_MONEY)
    )["t"] or Decimal("0.00")

    desc_pct = p.desconto_percentual or Decimal("0")
    acr_pct  = p.acrescimo_percentual or Decimal("0")
    val_desc = (subtotal * (desc_pct / Decimal("100"))).quantize(Decimal("0.01"))
    val_acr  = (subtotal * (acr_pct  / Decimal("100"))).quantize(Decimal("0.01"))
    total    = (subtotal - val_desc + val_acr).quantize(Decimal("0.01"))

    return render(request, "camisas/orcamento.html", {
        "pedido": p,
        "empresa": p.empresa,
        "cliente": p.cliente,
        "itens": itens,
        "subtotal": subtotal,
        "val_desc": val_desc,
        "val_acr": val_acr,
        "total": total,
    })

@login_required
@transaction.atomic
def pedido_gerar_ops(request, pk):
    p = get_object_or_404(Pedido, pk=pk)
    created = 0

    for it in p.itens.select_related("variacao"):
        op = OrdemProducao.objects.create(
            empresa=p.empresa,
            variacao=it.variacao,
            quantidade=it.quantidade,
            custo_mao_de_obra=Decimal("0.00"),
            custo_indireto_rateado=Decimal("0.00"),
            observacao=f"Gerado do Pedido #{p.pk}",
        )
        op.processar()
        created += 1

    if created:
        p.status = "PROD"
        p.save(update_fields=["status"])
        messages.success(request, f"{created} OP(s) geradas e processadas. Estoque atualizado.")
    else:
        messages.info(request, "Pedido sem itens para gerar OP.")

    return redirect("camisas:pedido_detail", p.pk)

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages

from .models import Pedido
from .forms import ItemPedidoForm, ArtePedidoForm


@login_required
def item_pedido_add(request, pk):
    """Tela simples para adicionar um item a um pedido já existente."""
    pedido = get_object_or_404(Pedido, pk=pk)
    if request.method == "POST":
        form = ItemPedidoForm(request.POST)
        if form.is_valid():
            it = form.save(commit=False)
            it.pedido = pedido
            it.save()
            messages.success(request, "Item adicionado ao pedido.")
            return redirect("camisas:pedido_detail", pedido.pk)
    else:
        form = ItemPedidoForm()
    return render(request, "camisas/item_pedido_form.html", {"form": form, "pedido": pedido})


@login_required
def pedido_upload_arte(request, pk):
    """POST para trocar/definir a arte do pedido diretamente do orçamento."""
    pedido = get_object_or_404(Pedido, pk=pk)
    if request.method == "POST":
        form = ArtePedidoForm(request.POST, request.FILES, instance=pedido)
        if form.is_valid():
            form.save()
            messages.success(request, "Arte atualizada com sucesso.")
        else:
            messages.error(request, "Não foi possível atualizar a arte. Verifique o arquivo.")
        return redirect("camisas:pedido_orcamento", pk=pedido.pk)
    return redirect("camisas:pedido_orcamento", pk=pedido.pk)

# camisas/views.py (trechos novos)
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import CostureiraForm, PagamentoFiltroForm
from .models import Costureira, PagamentoCostureira, Remessa

# -------------------------
# COSTUREIRAS (CRUD)
# -------------------------
@login_required
def costureira_list(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("ativo") or "").strip()  # "1" ativos, "0" inativos, "" todos
    qs = Costureira.objects.all().order_by("nome")
    if q:
        qs = qs.filter(nome__icontains=q)
    if status == "1":
        qs = qs.filter(ativo=True)
    elif status == "0":
        qs = qs.filter(ativo=False)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "camisas/costureira_list.html", {
        "rows": page_obj.object_list,
        "page_obj": page_obj,
        "sel": {"q": q, "ativo": status},
    })


@login_required
def costureira_create(request):
    if request.method == "POST":
        form = CostureiraForm(request.POST)
        if form.is_valid():
            c = form.save()
            messages.success(request, f"Costureira '{c.nome}' criada.")
            return redirect("camisas:costureira_list")
        messages.error(request, "Verifique os campos destacados.")
    else:
        form = CostureiraForm()
    return render(request, "camisas/costureira_form.html", {"form": form})


@login_required
def costureira_update(request, pk):
    c = get_object_or_404(Costureira, pk=pk)
    if request.method == "POST":
        form = CostureiraForm(request.POST, instance=c)
        if form.is_valid():
            form.save()
            messages.success(request, f"Costureira '{c.nome}' atualizada.")
            return redirect("camisas:costureira_list")
        messages.error(request, "Verifique os campos destacados.")
    else:
        form = CostureiraForm(instance=c)
    return render(request, "camisas/costureira_form.html", {"form": form, "obj": c})


@login_required
@transaction.atomic
def costureira_toggle(request, pk):
    c = get_object_or_404(Costureira, pk=pk)
    c.ativo = not c.ativo
    c.save(update_fields=["ativo"])
    messages.success(request, f"Costureira '{c.nome}' agora está {'ATIVA' if c.ativo else 'INATIVA'}.")
    return redirect("camisas:costureira_list")


# -------------------------
# RELATÓRIOS / PAGAMENTOS
# -------------------------
def _filtra_pagamentos(request):
    form = PagamentoFiltroForm(request.GET or None)
    qs = PagamentoCostureira.objects.select_related("remessa", "empresa", "costureira").order_by("-criado_em")

    if form.is_valid():
        empresa = form.cleaned_data.get("empresa")
        costureira = form.cleaned_data.get("costureira")
        status = form.cleaned_data.get("status")
        tipo = form.cleaned_data.get("tipo")
        data_de = form.cleaned_data.get("data_de")
        data_ate = form.cleaned_data.get("data_ate")

        if empresa:
            qs = qs.filter(empresa=empresa)
        if costureira:
            qs = qs.filter(costureira=costureira)
        if status:
            qs = qs.filter(status=status)
        if tipo:
            qs = qs.filter(remessa__tipo=tipo)
        # intervalo por data de criação do pagamento
        if data_de:
            qs = qs.filter(criado_em__date__gte=data_de)
        if data_ate:
            qs = qs.filter(criado_em__date__lte=data_ate)
    else:
        # ainda assim devolve form para exibir erros, se houver
        pass

    return form, qs


@login_required
def pagamentos_list(request):
    form, qs = _filtra_pagamentos(request)

    # KPIs (após filtro)
    total_pendente = sum((p.valor_total for p in qs.filter(status="PENDENTE")), Decimal("0"))
    total_pago     = sum((p.valor_total for p in qs.filter(status="PAGO")), Decimal("0"))
    qtd_pendente   = qs.filter(status="PENDENTE").count()
    qtd_pago       = qs.filter(status="PAGO").count()

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "camisas/rel_pagamentos.html", {
        "form": form,
        "rows": page_obj.object_list,
        "page_obj": page_obj,
        "kpi": {
            "total_pendente": total_pendente,
            "total_pago": total_pago,
            "qtd_pendente": qtd_pendente,
            "qtd_pago": qtd_pago,
        },
    })


@login_required
@transaction.atomic
def pagamento_marcar_pago(request, pk):
    pg = get_object_or_404(PagamentoCostureira, pk=pk)
    if pg.status != "PAGO":
        pg.status = "PAGO"
        pg.pago_em = timezone.now()
        pg.save(update_fields=["status", "pago_em"])
        messages.success(request, f"Pagamento da remessa {pg.remessa.numero} marcado como PAGO.")
    return redirect("camisas:pagamentos_list")


@login_required
@transaction.atomic
def pagamento_marcar_pendente(request, pk):
    pg = get_object_or_404(PagamentoCostureira, pk=pk)
    if pg.status != "PENDENTE":
        pg.status = "PENDENTE"
        pg.pago_em = None
        pg.save(update_fields=["status", "pago_em"])
        messages.success(request, f"Pagamento da remessa {pg.remessa.numero} retornou para PENDENTE.")
    return redirect("camisas:pagamentos_list")


@login_required
def pagamentos_export_csv(request):
    _, qs = _filtra_pagamentos(request)
    # CSV simples
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="pagamentos_costureiras.csv"'
    header = "Empresa,Costureira,Remessa,Tipo,Status,Valor,Criado em,Pago em\n"
    resp.write(header)
    for p in qs:
        row = [
            p.empresa.nome_fantasia,
            p.costureira.nome,
            p.remessa.numero,
            p.remessa.get_tipo_display(),
            p.get_status_display(),
            f"{p.valor_total:.2f}".replace(".", ","),
            p.criado_em.strftime("%d/%m/%Y %H:%M"),
            p.pago_em.strftime("%d/%m/%Y %H:%M") if p.pago_em else "",
        ]
        # aspas e separador
        resp.write(",".join(f'"{c}"' for c in row) + "\n")
    return resp


@login_required
def despesa_list(request):
    qs = Despesa.objects.select_related("empresa","categoria","fornecedor")
    emp = request.GET.get("empresa") or ""
    st  = request.GET.get("status") or ""
    de  = request.GET.get("de") or ""
    ate = request.GET.get("ate") or ""

    if emp: qs = qs.filter(empresa_id=emp)
    if st:  qs = qs.filter(status=st)
    if de:  qs = qs.filter(data_emissao__gte=de)
    if ate: qs = qs.filter(data_emissao__lte=ate)

    total = qs.aggregate(s=Sum("valor_total"))["s"] or 0
    empresas = Empresa.objects.all().order_by("nome_fantasia")
    return render(request, "camisas/despesa_list.html", {
        "despesas": qs[:500],  # limite prudente
        "total": total,
        "empresas": empresas,
    })

@login_required
def despesa_create(request):
    if request.method == "POST":
        form = DespesaForm(request.POST, request.FILES)
        if form.is_valid():
            desp = form.save()
            # criar parcelas automaticamente se informado
            n = form.cleaned_data.get("parcelas_qty") or 1
            first = form.cleaned_data.get("primeira_parcela") or desp.vencimento or desp.data_emissao
            if n > 1:
                # split: arredonda centavos na última
                quota = (desp.valor_total / n).quantize(Decimal("0.01"))
                vals = [quota]*(n-1) + [desp.valor_total - quota*(n-1)]
                for i, v in enumerate(vals, start=1):
                    ParcelaDespesa.objects.create(
                        despesa=desp, numero=i, vencimento=first + timezone.timedelta(days=30*(i-1)), valor=v
                    )
                desp.sync_status_from_parcelas(save=True)
            messages.success(request, "Despesa criada.")
            return redirect("camisas:despesa_update", desp.pk)
        # se inválido, ainda cria formset vazio pra mostrar a área de parcelas manual
        formset = ParcelaFormSet()
    else:
        form = DespesaForm()
        formset = ParcelaFormSet()
    return render(request, "camisas/despesa_form.html", {"form": form, "formset": formset, "is_edit": False})

@login_required
def despesa_update(request, pk):
    desp = get_object_or_404(Despesa, pk=pk)
    if request.method == "POST":
        form = DespesaForm(request.POST, request.FILES, instance=desp)
        formset = ParcelaFormSet(request.POST, instance=desp)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            # manter valor_total = soma das parcelas, se houver ao menos 1
            if desp.parcelas.exists():
                desp.recalc_from_parcelas(save=True)
                desp.sync_status_from_parcelas(save=True)
            messages.success(request, "Despesa atualizada.")
            return redirect("camisas:despesa_update", desp.pk)
    else:
        form = DespesaForm(instance=desp)
        form.fields["parcelas_qty"].widget.attrs["placeholder"] = "ex.: 3"
        formset = ParcelaFormSet(instance=desp)
    return render(request, "camisas/despesa_form.html", {"form": form, "formset": formset, "is_edit": True, "despesa": desp})

@login_required
def parcela_pagar(request, pk):
    par = get_object_or_404(ParcelaDespesa, pk=pk)
    if request.method == "POST":
        par.marcar_paga()
        messages.success(request, "Parcela marcada como PAGA.")
    return redirect("camisas:despesa_update", par.despesa_id)

# camisas/views.py
from datetime import timedelta
from decimal import Decimal
# topo do camisas/views.py
import datetime as dt

from django.db.models import Sum, Count, F, DecimalField
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .models import (
    Empresa, Pedido, ItemPedido, VariacaoProduto,  # pedidos
    Despesa, CategoriaDespesa, Fornecedor,         # despesas
    Remessa, RemessaItem, OrdemProducao, Costureira  # costureiras/produção
)

def _periodo(request):
    """Lê ?ini=YYYY-MM-DD&fim=YYYY-MM-DD; default: últimos 30 dias."""
    ini_str = request.GET.get("ini")
    fim_str = request.GET.get("fim")
    today   = timezone.localdate()
    ini = timezone.datetime.fromisoformat(ini_str).date() if ini_str else (today - timedelta(days=30))
    fim = timezone.datetime.fromisoformat(fim_str).date() if fim_str else today
    return ini, fim

@login_required
def pedidos_home(request):
    ini, fim = _periodo(request)
    empresa_id = request.GET.get("empresa") or None

    ped_qs = Pedido.objects.select_related("cliente","empresa").filter(criado_em__date__gte=ini, criado_em__date__lte=fim)
    if empresa_id: ped_qs = ped_qs.filter(empresa_id=empresa_id)

    # receita bruta (itens) no período
    receita = ped_qs.aggregate(
        s=Sum(
            F("itens__preco_unitario") * F("itens__quantidade"),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    )["s"] or Decimal("0")

    kpis = {
        "periodo": f"{ini.strftime('%d/%m/%Y')} – {fim.strftime('%d/%m/%Y')}",
        "receita": receita,
        "qtd": ped_qs.count(),
        "orc": ped_qs.filter(status="ORC").count(),
        "pen": ped_qs.filter(status="PEN").count(),
        "prod": ped_qs.filter(status="PROD").count(),
        "fat": ped_qs.filter(status="FAT").count(),
    }

    # top produtos por receita (bruta)
    top_prod = (
        ItemPedido.objects
        .filter(pedido__in=ped_qs)
        .values("variacao__produto__nome")
        .annotate(total=Sum(F("preco_unitario")*F("quantidade"), output_field=DecimalField(max_digits=14, decimal_places=2)))
        .order_by("-total")[:8]
    )

    recent = ped_qs.order_by("-criado_em").values("id","cliente__nome","status","criado_em")[:12]

    context = {
        "empresas": Empresa.objects.all(),
        "kpis": kpis,
        "top_prod": top_prod,
        "recent": recent,
        "ini": ini, "fim": fim,
    }
    return render(request, "camisas/mod_pedidos_home.html", context)

@login_required
def despesas_home(request):
    ini, fim = _periodo(request)
    empresa_id = request.GET.get("empresa") or None

    qs = Despesa.objects.select_related("empresa","categoria","fornecedor")\
         .filter(data_emissao__gte=ini, data_emissao__lte=fim)
    if empresa_id: qs = qs.filter(empresa_id=empresa_id)

    kpis = {
        "periodo": f"{ini.strftime('%d/%m/%Y')} – {fim.strftime('%d/%m/%Y')}",
        "total": qs.aggregate(s=Sum("valor_total"))["s"] or Decimal("0"),
        "pend":  qs.filter(status="PEN").aggregate(s=Sum("valor_total"))["s"] or Decimal("0"),
        "paga":  qs.filter(status="PAGA").aggregate(s=Sum("valor_total"))["s"] or Decimal("0"),
        "qtd":   qs.count(),
    }

    por_cat = (qs.values("categoria__nome")
                 .annotate(total=Sum("valor_total"))
                 .order_by("-total")[:10])

    recent = qs.order_by("-data_emissao","-id")[:12]

    context = {
        "empresas": Empresa.objects.all(),
        "kpis": kpis,
        "por_cat": por_cat,
        "recent": recent,
        "ini": ini, "fim": fim,
    }
    return render(request, "camisas/mod_despesas_home.html", context)

@login_required
def costureiras_home(request):
    # --- filtros (empresa, datas) ---
    empresa_id = (request.GET.get("empresa") or "").strip() or None
    ini_str = (request.GET.get("ini") or "").strip() or None
    fim_str = (request.GET.get("fim") or "").strip() or None

    now = timezone.now()                                  # aware
    ini_date = dt.date.fromisoformat(ini_str) if ini_str else (now - dt.timedelta(days=30)).date()
    fim_date = dt.date.fromisoformat(fim_str) if fim_str else now.date()

    # construir datetimes NAIVE e torná-los aware no timezone atual
    dt_ini = timezone.make_aware(dt.datetime.combine(ini_date, dt.time.min))
    dt_fim = timezone.make_aware(dt.datetime.combine(fim_date, dt.time.max))

    # --- queryset base de remessas ---
    remessas_qs = Remessa.objects.select_related("costureira", "empresa")
    if empresa_id:
        remessas_qs = remessas_qs.filter(empresa_id=empresa_id)

    remessas_env = remessas_qs.filter(enviado_em__range=(dt_ini, dt_fim))
    remessas_rec = remessas_qs.filter(recebido_em__range=(dt_ini, dt_fim))

    # Campo decimal padrão para coalesce/casts
    DEC = DecimalField(max_digits=12, decimal_places=2)

    # --- KPIs ---
    pecas_ok = (
        RemessaItem.objects
        .filter(remessa__in=remessas_rec)
        .aggregate(total=Coalesce(
            Sum(Cast("qtd_ok", DEC)),
            Value(Decimal("0.00"), output_field=DEC),
            output_field=DEC
        ))["total"]
    ) or Decimal("0.00")

    remessas_count = remessas_env.count()

    ops_qs = OrdemProducao.objects.all()
    if empresa_id:
        ops_qs = ops_qs.filter(empresa_id=empresa_id)
    ops_count = ops_qs.filter(criado_em__range=(dt_ini, dt_fim)).count()

    costureiras_ativas = remessas_env.values("costureira").distinct().count()

    kpis = {
        "periodo": f"{ini_date.strftime('%d/%m')}–{fim_date.strftime('%d/%m')}",
        "pecas_ok": pecas_ok,
        "remessas": remessas_count,
        "ops": ops_count,
        "costureiras_ativas": costureiras_ativas,
    }

    # --- Peças OK por costureira (Top 10) ---
    por_cost = (
        RemessaItem.objects
        .filter(remessa__in=remessas_rec)
        .values("remessa__costureira__nome")
        .annotate(total=Coalesce(
            Sum(Cast("qtd_ok", DEC)),
            Value(Decimal("0.00"), output_field=DEC),
            output_field=DEC
        ))
        .order_by("-total")[:10]
    )

    # --- Remessas recentes (enviado_em; senão recebido_em) ---
    recent = (
        remessas_qs
        .annotate(data_ref=Coalesce("enviado_em", "recebido_em", output_field=DateTimeField()))
        .order_by("-data_ref")[:12]
    )

    empresas = Empresa.objects.all().order_by("nome_fantasia")

    ctx = {
        "empresas": empresas,
        "ini": ini_date,
        "fim": fim_date,
        "kpis": kpis,
        "por_cost": por_cost,
        "recent": recent,
    }
    return render(request, "camisas/costureiras_home.html", ctx)


@login_required
def clientes_home(request):
    # Filtros opcionais por período (aplicados sobre os PEDIDOS)
    ini = request.GET.get("ini") or ""
    fim = request.GET.get("fim") or ""
    try:
        d_ini = date.fromisoformat(ini) if ini else None
    except Exception:
        d_ini = None
    try:
        d_fim = date.fromisoformat(fim) if fim else None
    except Exception:
        d_fim = None

    pedidos = Pedido.objects.select_related("cliente")
    if d_ini or d_fim:
        start = d_ini or date.min
        end = d_fim or date.max
        pedidos = pedidos.filter(criado_em__date__range=(start, end))

    # expressão para somar receita via itens (preço * qtd)
    valor_item = ExpressionWrapper(
        F("itens__preco_unitario") * F("itens__quantidade"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )

    # KPIs (com base nos pedidos filtrados)
    clientes_ativos = pedidos.values("cliente_id").distinct().count()
    receita = pedidos.aggregate(total=Sum(valor_item))["total"] or Decimal("0.00")
    qtd_pedidos = pedidos.count()

    # Clientes “recentes”: pelo último pedido
    clientes_qs = Cliente.objects.annotate(
        total_pedidos=Count("pedidos", distinct=True),
        last_pedido=Max("pedidos__criado_em"),
        receita_total=Sum(
            ExpressionWrapper(
                F("pedidos__itens__preco_unitario") * F("pedidos__itens__quantidade"),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        ),
    )

    # Só para a listagem de “recentes”, priorizamos quem tem pedidos
    clientes_recent = clientes_qs.order_by("-last_pedido", "-id")[:12]

    kpis = {
        "clientes_total": Cliente.objects.count(),
        "clientes_ativos": clientes_ativos,
        "receita_periodo": receita,
        "qtd_pedidos_periodo": qtd_pedidos,
        "window_label": f"{ini or 'início'} → {fim or 'hoje'}",
    }

    return render(request, "camisas/clientes_home.html", {
        "kpis": kpis,
        "clientes_recent": clientes_recent,
        "filtro": {"ini": ini, "fim": fim},
    })

@login_required
@transaction.atomic
def pedido_gerar_remessa(request, pk):
    pedido = get_object_or_404(
        Pedido.objects.select_related("empresa", "cliente"),
        pk=pk
    )

    if request.method == "GET":
        costureiras = Costureira.objects.filter(ativo=True).order_by("nome")
        produtos = Produto.objects.filter(empresa=pedido.empresa, ativo=True).order_by("nome")
        return render(request, "camisas/pedido_gerar_remessa.html", {
            "pedido": pedido,
            "costureiras": costureiras,
            "produtos": produtos,
            "remessa_tipos": Remessa.TIPO,  # <- o template espera isso
        })

    # POST
    costureira_id = request.POST.get("costureira")
    tipo_req = (request.POST.get("tipo") or "").strip()
    produto_id = request.POST.get("produto") or None

    costureira = get_object_or_404(Costureira, pk=costureira_id)

    # valida 'tipo' nas choices
    tipos_validos = {val for (val, _label) in Remessa.TIPO}
    tipo = tipo_req if tipo_req in tipos_validos else next(iter(tipos_validos))

    produto = Produto.objects.filter(pk=produto_id).first() if produto_id else None

    itens_qs = (
        pedido.itens
        .select_related("variacao", "variacao__produto")
        .all()
    )

    if not itens_qs.exists():
        messages.warning(request, "Este pedido não possui itens para gerar remessa.")
        return redirect("camisas:pedido_detail", pedido.pk)

    # cria a remessa (cabeçalho)
    remessa = Remessa.objects.create(
        empresa=pedido.empresa,
        costureira=costureira,
        tipo=tipo,
        produto=produto,
        kg_enviados=Decimal("0"),
        observacao=f"Gerada a partir do Pedido #{pedido.pk}",
    )

    # cria itens (somente com quantidade > 0)
    bulk = []
    for it in itens_qs:
        if it.quantidade and it.quantidade > 0:
            bulk.append(RemessaItem(
                remessa=remessa,
                variacao=it.variacao,       # <== instância VariacaoProduto correta
                qtd_prevista=it.quantidade,
                preco_unit=Decimal("0"),    # 0 => deixa preço padrão ser aplicado no recebimento
            ))

    if not bulk:
        messages.warning(request, "Nenhum item com quantidade > 0 para gerar na remessa.")
        remessa.delete()
        return redirect("camisas:pedido_detail", pedido.pk)

    RemessaItem.objects.bulk_create(bulk)

    messages.success(
        request,
        f"Remessa #{remessa.pk} criada a partir do pedido #{pedido.pk}."
    )
    return redirect("camisas:remessa_detail", remessa.pk)

from decimal import Decimal, ROUND_HALF_UP
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.urls import reverse

from .models import Pedido
try:
    from .models import ESignature
except Exception:
    ESignature = None  # permite rodar mesmo sem o modelo

def _dec(v, default="0"):
    if v in (None, "", False):
        return Decimal(default)
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal(default)

@login_required
def pedido_cotacao_precos(request, pk):
    pedido = get_object_or_404(
        Pedido.objects
              .select_related("empresa", "cliente")
              .prefetch_related("itens__variacao__produto"),
        pk=pk
    )

    # --- Totais (sempre como Decimal) ---
    subtotal = _dec(pedido.total_bruto())
    total    = _dec(pedido.total_com_descontos())

    # --- Desconto e acréscimo (em R$) ---
    desc_pct = _dec(getattr(pedido, "desconto_percentual", None))
    val_desc = subtotal * desc_pct / Decimal("100")
    val_acr  = total - (subtotal - val_desc)

    # --- Normalizações ---
    CENT = Decimal("0.01")
    val_desc = (val_desc if val_desc > 0 else Decimal("0")).quantize(CENT, rounding=ROUND_HALF_UP)
    val_acr  = (val_acr  if val_acr  > 0 else Decimal("0")).quantize(CENT, rounding=ROUND_HALF_UP)
    subtotal = subtotal.quantize(CENT, rounding=ROUND_HALF_UP)
    total    = total.quantize(CENT,    rounding=ROUND_HALF_UP)

    # --- Frete opcional via GET (?frete_valor=123.45) ---
    frete_valor_param = request.GET.get("frete_valor")
    frete_valor = None
    if frete_valor_param not in (None, "", "0", "0.0", "0.00"):
        fv = _dec(frete_valor_param, "0")
        if fv > 0:
            frete_valor = fv.quantize(CENT, rounding=ROUND_HALF_UP)

    # --- Metadados ---
    cot = {
        "processo": request.GET.get("proc", ""),
        "modalidade": request.GET.get("mod", "Cotação"),
        "edital": request.GET.get("edital", ""),
        "validade": request.GET.get("val", "30 dias"),
        "prazo_entrega": request.GET.get("prazo", "Até 15 dias"),
        "local_entrega": request.GET.get("local", pedido.cliente.endereco or ""),
        "condicoes_pagamento": request.GET.get("pag", "30 dias após atesto"),
        "garantia": request.GET.get("garantia", "90 dias"),
        "frete": request.GET.get("frete", "CIF"),
        "frete_valor": frete_valor,
    }

    # --- Assinatura eletrônica da EMPRESA ---
    esig_at = None
    esig_hash = None
    esig_qr = None
    esig_verify_url = None

    if ESignature is not None and hasattr(pedido, "esignatures"):
        esig = pedido.esignatures.filter(role="empresa").order_by("-signed_at").first()
        if esig:
            esig_at = esig.signed_at
            esig_hash = esig.hash
            esig_qr = esig.qr_data_url
            # URL de verificação (com fallback se a rota não existir)
            try:
                verify_path = reverse("camisas:esign_verify")
            except Exception:
                verify_path = "/assinaturas/verify/"
            esig_verify_url = request.build_absolute_uri(
                f"{verify_path}?p={pedido.pk}&r=empresa&t={esig.signed_at.isoformat()}&h={esig.hash}"
            )

    # Fallbacks (apenas para preencher visualmente; o template já evita mostrar botão se já houver assinatura)
    if not esig_at:
        esig_at = getattr(pedido, "esig_datetime", None) \
                  or getattr(pedido, "approval_signed_at", None) \
                  or timezone.now()
    if not esig_hash:
        esig_hash = getattr(pedido, "esig_hash", None) \
                    or getattr(pedido, "approval_signature_hash", None) \
                    or "—"

    # --- URL para CRIAR assinatura (necessária para o botão aparecer) ---
    try:
        esign_create_url = reverse("camisas:esign_create", args=[pedido.pk])
    except Exception:
        # se você preferir esconder o botão quando a rota não existe, troque por: esign_create_url = None
        esign_create_url = f"/assinaturas/{pedido.pk}/criar/"

    context = {
        "pedido": pedido,
        "empresa": pedido.empresa,
        "cliente": pedido.cliente,
        "itens": pedido.itens.all(),
        "subtotal": subtotal,
        "total": total,
        "val_desc": val_desc,
        "val_acr": val_acr,
        "cot": cot,
        # Assinatura eletrônica (empresa)
        "esig_at": esig_at,
        "esig_hash": esig_hash,
        "esig_qr": esig_qr,
        "esig_verify_url": esig_verify_url,
        # URL para o botão "Gerar assinatura eletrônica"
        "esign_create_url": esign_create_url,
        "now": timezone.now(),
    }
    return render(request, "camisas/cotacao_precos.html", context)




@login_required
def pedido_enviar_arte(request, pk: int):
    """
    Tela interna: mostra link público da ARTE para enviar ao cliente,
    status e previews (arte e assinatura da arte).
    """
    pedido = get_object_or_404(
        Pedido.objects.select_related("empresa", "cliente"),
        pk=pk
    )

    # Garante que exista um token de ARTE
    if not getattr(pedido, "artwork_token", None):
        # use seu gerador de token de arte, se existir; senão, reusa o do orçamento
        _gen = globals().get("gen_artwork_token", gen_approval_token)
        pedido.artwork_token = _gen()
        # garante estado padrão
        if not getattr(pedido, "artwork_status", None):
            pedido.artwork_status = "PEND"
        pedido.save(update_fields=["artwork_token", "artwork_status"])

    public_path = reverse("camisas:arte_publica", args=[pedido.artwork_token])
    full_url = f"{request.scheme}://{request.get_host()}{public_path}"

    return render(request, "camisas/pedido_enviar_arte.html", {
        "pedido": pedido,
        "empresa": pedido.empresa,
        "cliente": pedido.cliente,
        "public_path": public_path,
        "full_url": full_url,
    })


@require_http_methods(["GET", "POST"])
@transaction.atomic
def arte_publica(request, token: str):
    """
    Página pública para o cliente aprovar/recusar a ARTE com assinatura.
    """
    pedido = get_object_or_404(
        Pedido.objects.select_related("empresa", "cliente"),
        artwork_token=token
    )

    feedback = ""
    if request.method == "POST":
        decision = request.POST.get("decision")
        name = (request.POST.get("name") or "").strip()
        email = (request.POST.get("email") or "").strip() or None
        comment = (request.POST.get("comment") or "").strip() or None
        tz = request.POST.get("tz") or ""
        ua = request.POST.get("ua") or request.META.get("HTTP_USER_AGENT", "")
        ip = request.META.get("REMOTE_ADDR")

        if decision not in {"approve", "reject"}:
            messages.error(request, "Operação inválida.")
            return redirect(request.path)

        # Aprovação exige assinatura
        if decision == "approve":
            sig_b64 = request.POST.get("signature_png", "")
            if not sig_b64:
                messages.error(request, "Assine no quadro para aprovar a arte.")
                return redirect(request.path)
            if sig_b64.startswith("data:image"):
                sig_b64 = sig_b64.split(",", 1)[1]
            try:
                image_bin = base64.b64decode(sig_b64)
            except Exception:
                messages.error(request, "Assinatura inválida.")
                return redirect(request.path)

            # Hash “carimbo” da assinatura + contexto
            stamp = timezone.now().isoformat()
            digest = hashlib.sha256(
                (name + (email or "") + (ip or "") + stamp).encode("utf-8") + image_bin
            ).hexdigest()

            fname = f"arte_{pedido.pk}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.png"

            # Remove arquivo anterior (se houver) para evitar lixo
            if getattr(pedido, "artwork_signature", None) and getattr(pedido.artwork_signature, "name", ""):
                pedido.artwork_signature.delete(save=False)

            pedido.artwork_signature.save(fname, ContentFile(image_bin), save=False)
            pedido.artwork_status = "APRV"
            pedido.artwork_decided_at = timezone.now()
            pedido.artwork_name = name
            pedido.artwork_email = email
            pedido.artwork_comment = comment
            pedido.artwork_user_agent = ua
            pedido.artwork_timezone = tz
            pedido.artwork_hash = digest
            pedido.artwork_decision_ip = ip
            pedido.save(update_fields=[
                "artwork_signature", "artwork_status", "artwork_decided_at",
                "artwork_name", "artwork_email", "artwork_comment",
                "artwork_user_agent", "artwork_timezone", "artwork_hash",
                "artwork_decision_ip",
            ])
            feedback = "Arte aprovada com sucesso. Obrigado!"
        else:
            # recusa não exige assinatura
            pedido.artwork_status = "REJ"
            pedido.artwork_decided_at = timezone.now()
            pedido.artwork_name = name
            pedido.artwork_email = email
            pedido.artwork_comment = comment
            pedido.artwork_user_agent = ua
            pedido.artwork_timezone = tz
            pedido.artwork_decision_ip = ip
            pedido.save(update_fields=[
                "artwork_status", "artwork_decided_at",
                "artwork_name", "artwork_email", "artwork_comment",
                "artwork_user_agent", "artwork_timezone",
                "artwork_decision_ip",
            ])
            feedback = "Registro de recusa efetuado."

    return render(request, "camisas/arte_publica.html", {
        "pedido": pedido,
        "empresa": pedido.empresa,
        "cliente": pedido.cliente,
        "feedback": feedback,
    })

# camisas/views_esig.py
from django.shortcuts import get_object_or_404, render
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.urls import reverse
from secrets import compare_digest

from .models import Pedido, ESignature
from .esig_utils import canonical_payload, compute_hash, make_qr_data_url

def esign_create(request, pk):
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido")

    pedido = get_object_or_404(Pedido, pk=pk)
    role = request.POST.get("role")  # "empresa" ou "cliente"
    if role not in ("empresa", "cliente"):
        return HttpResponseBadRequest("role inválido")

    signer_name = pedido.empresa.nome_fantasia if role == "empresa" else str(pedido.cliente)
    signed_at = timezone.now()
    payload = canonical_payload(pedido.id, role, signer_name, signed_at.isoformat())
    sig_hash = compute_hash(payload)

    # URL pública de verificação (ex.: /assinaturas/verify/?p=...&r=...&t=...&h=...)
    verify_url = request.build_absolute_uri(
        reverse("camisas:esign_verify") + f"?p={pedido.id}&r={role}&t={signed_at.isoformat()}&h={sig_hash}"
    )
    qr_data_url = make_qr_data_url(verify_url)

    esig = ESignature.objects.create(
        pedido=pedido, role=role, signer_name=signer_name,
        signed_at=signed_at, hash=sig_hash, qr_data_url=qr_data_url
    )

    return JsonResponse({
        "id": esig.id,
        "hash": esig.hash,
        "signed_at": esig.signed_at.isoformat(),
        "verify_url": verify_url,
        "qr_data_url": qr_data_url,
    })

def esign_verify(request):
    # Checagem simples: confere se existe uma assinatura com hash idêntico
    p = request.GET.get("p")
    r = request.GET.get("r")
    t = request.GET.get("t")
    h = request.GET.get("h")
    if not all([p, r, t, h]):
        return HttpResponseBadRequest("Parâmetros insuficientes")

    esig = ESignature.objects.filter(pedido_id=p, role=r, hash=h).first()
    valid = bool(esig) and compare_digest(esig.hash, h)

    return render(request, "camisas/esig_verify.html", {
        "valid": valid,
        "pedido_id": p, "role": r, "signed_at": t, "hash": h,
        "assinado_por": esig.signer_name if esig else "—",
    })

# camisas/views.py
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages

from .models import Pedido, CotacaoConcorrente, CotacaoConcorrenteItem
from .forms import CotacaoConcorrenteForm, CotacaoConcorrenteItemFormSet

# camisas/views.py
from django.forms import inlineformset_factory

@login_required
@transaction.atomic
def cotacao_concorrente_create(request, pk: int):
    """
    Cria uma cotação concorrente para um pedido.
    Pré-preenche itens a partir do pedido, mas preços ficam em branco para digitação.
    """
    pedido = get_object_or_404(
        Pedido.objects.select_related("empresa", "cliente"),
        pk=pk
    )

    if request.method == "POST":
        form = CotacaoConcorrenteForm(request.POST)
        if form.is_valid():
            cot = form.save(commit=False)
            cot.pedido = pedido
            cot.save()

            # importante: manter o mesmo prefix do GET
            formset = CotacaoConcorrenteItemFormSet(request.POST, instance=cot, prefix="itens")
            if formset.is_valid():
                formset.save()
                messages.success(request, "Cotação concorrente criada.")
                return redirect("camisas:cotacao_concorrente_print", cot.pk)
            else:
                # se itens inválidos, aborta a transação com erro
                messages.error(request, "Há erros nos itens da cotação.")
                raise transaction.TransactionManagementError("Itens inválidos.")
        else:
            # reexibe com erros + itens enviados
            dummy = CotacaoConcorrente(pedido=pedido, empresa_nome="—")
            formset = CotacaoConcorrenteItemFormSet(request.POST, instance=dummy, prefix="itens")
            return render(request, "camisas/cotacao_concorrente_form.html", {
                "pedido": pedido,
                "form": form,
                "formset": formset,
            })

    # GET: montar os itens iniciais a partir do pedido
    form = CotacaoConcorrenteForm()
    cot_fake = CotacaoConcorrente(pedido=pedido, empresa_nome="")

    initial_items = []
    for it in pedido.itens.select_related("variacao", "variacao__produto").all():
        produto = getattr(it.variacao, "produto", None)
        nome = getattr(produto, "nome", "Item")

        # anexa variação no nome, se houver
        tamanho = getattr(it.variacao, "tamanho", "") or ""
        cor = getattr(it.variacao, "cor", "") or ""
        vari_txt = " / ".join([v for v in (tamanho, cor) if v])
        if vari_txt:
            nome = f"{nome} ({vari_txt})"

        # descrição: NÃO acessar it.descricao (não existe em ItemPedido)
        desc_prod = getattr(produto, "descricao", "") or ""

        initial_items.append({
            "item_nome": nome,
            "descricao": desc_prod,   # pode ficar vazio caso o produto não tenha descrição
            "unidade": "UN",
            "quantidade": it.quantidade,
            "valor_unitario": None,   # você digita
        })

    # Formset dinâmico com 'extra' = nº de itens do pedido (no mínimo 1)
    extra_n = max(1, len(initial_items))
    ItemFS = inlineformset_factory(
        CotacaoConcorrente,
        CotacaoConcorrenteItem,
        form=CotacaoConcorrenteItemForm,
        extra=extra_n,
        can_delete=True,
    )
    formset = ItemFS(instance=cot_fake, prefix="itens", initial=initial_items)

    return render(request, "camisas/cotacao_concorrente_form.html", {
        "pedido": pedido,
        "form": form,
        "formset": formset,
    })

@login_required
def cotacao_concorrente_print(request, cot_id: int):
    """
    Impressão da cotação concorrente.
    """
    cot = get_object_or_404(
        CotacaoConcorrente.objects.select_related("pedido", "pedido__empresa", "pedido__cliente").prefetch_related("itens"),
        pk=cot_id
    )
    # totais
    subtotal = sum((i.subtotal for i in cot.itens.all()), Decimal("0.00"))
    total = subtotal  # sem descontos/acréscimos aqui (se quiser, adicione no modelo)

    return render(request, "camisas/cotacao_concorrente_print.html", {
        "cot": cot,
        "pedido": cot.pedido,
        "empresa": cot.pedido.empresa,
        "cliente": cot.pedido.cliente,
        "subtotal": subtotal,
        "total": total,
    })

# camisas/views.py
from calendar import monthrange
from datetime import date, datetime
import csv

# camisas/views.py  (apenas a view abaixo precisa ser trocada)

from calendar import monthrange
from datetime import date, datetime
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from .models import Funcionario, FrequenciaDia
from .forms import FrequenciaDiaForm, FiltroFrequenciaForm

def _primeiro_dia_mes(dt: date) -> date:
    return dt.replace(day=1)

def _ultimo_dia_mes(dt: date) -> date:
    _, last = monthrange(dt.year, dt.month)
    return dt.replace(day=last)

def _funcionario_padrao(user):
    return Funcionario.objects.filter(user=user, ativo=True).first() or Funcionario.objects.filter(ativo=True).first()

# camisas/views.py
from datetime import date, datetime, timedelta  # 👈 importa timedelta aqui
from calendar import monthrange
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from .models import Funcionario, FrequenciaDia
from .forms import FiltroFrequenciaForm

def _primeiro_dia_mes(dt: date) -> date:
    return dt.replace(day=1)

def _ultimo_dia_mes(dt: date) -> date:
    _, last = monthrange(dt.year, dt.month)
    return dt.replace(day=last)

def _funcionario_padrao(user):
    return (Funcionario.objects.filter(user=user, ativo=True).first()
            or Funcionario.objects.filter(ativo=True).first())

@login_required
def frequencia_resumo(request):
    today = timezone.localdate()
    func_default = _funcionario_padrao(request.user)

    # Se não veio nada, redireciona para o mês atual do funcionário padrão
    if request.method == "GET" and ("func" not in request.GET or "mes" not in request.GET) and func_default:
        return redirect(f"{reverse('camisas:freq_resumo')}?func={func_default.id}&mes={today:%Y-%m}")

    form = FiltroFrequenciaForm(request.GET or None)
    form_ok = form.is_valid()

    # Variáveis de navegação SEMPRE presentes (sem depender do form)
    q_func = request.GET.get("func")
    q_mes  = request.GET.get("mes") or f"{today:%Y-%m}"
    if q_func:
        try:
            nav_func = Funcionario.objects.get(pk=int(q_func))
        except (ValueError, Funcionario.DoesNotExist):
            nav_func = func_default
    else:
        nav_func = func_default
    nav_mes_str = q_mes
    nav_fid = getattr(nav_func, "id", "")

    ctx = {
        "form": form,
        "form_ok": form_ok,
        "linhas": [],
        "totais": None,
        # navegação segura para o partial
        "nav_func": nav_func,
        "nav_mes_str": nav_mes_str,
        "nav_fid": nav_fid,
        "csv_qs": "",
    }

    if form_ok:
        func = form.cleaned_data["func"]
        mes  = form.cleaned_data["mes"]   # qualquer dia do mês
        ini = _primeiro_dia_mes(mes)
        fim = _ultimo_dia_mes(mes)

        regs = {
            f.data: f
            for f in FrequenciaDia.objects.filter(funcionario=func, data__range=(ini, fim))
        }

        linhas, total_prev, total_trab = [], 0, 0
        d = ini
        while d <= fim:
            reg = regs.get(d)
            prev = reg.minutos_previstos if reg else func.jornada_diaria_min
            trab = reg.minutos_trabalhados_fechado() if reg else 0
            saldo = trab - prev
            total_prev += prev
            total_trab += trab

            wd = d.weekday()  # 0=Seg .. 5=Sáb .. 6=Dom
            linhas.append({
                "data": d,
                "reg": reg,
                "hh_prev": FrequenciaDia.fmt_hhmm(prev),
                "hh_trab": FrequenciaDia.fmt_hhmm(trab),
                "hh_saldo": FrequenciaDia.fmt_hhmm(saldo),
                "saldo": saldo,
                "wd": wd,
                "is_sat": wd == 5,
                "is_sun": wd == 6,
                "is_weekend": wd >= 5,
            })
            d += timedelta(days=1)  # 👈 usa datetime.timedelta

        ctx.update({
            "linhas": linhas,
            "func": func,
            "mes_ini": ini, "mes_fim": fim,
            "mes_str": f"{mes:%Y-%m}",
            "totais": {
                "hh_prev": FrequenciaDia.fmt_hhmm(total_prev),
                "hh_trab": FrequenciaDia.fmt_hhmm(total_trab),
                "hh_saldo": FrequenciaDia.fmt_hhmm(total_trab - total_prev),
            },
            # para o partial sempre ter dados coerentes
            "nav_func": func,
            "nav_mes_str": f"{mes:%Y-%m}",
            "nav_fid": func.id,
            "csv_qs": f"?func={func.id}&mes={mes:%Y-%m}",
        })

    return render(request, "camisas/frequencia_resumo.html", ctx)



@login_required
def frequencia_inline_upsert(request):
    """
    Salva (cria/atualiza) um dia a partir do resumo mensal.
    Espera POST com: func, data (YYYY-MM-DD), mes (YYYY-MM), e1,s1,e2,s2, (opc) observacao, (opc) min_prev
    """
    if request.method != "POST":
        return redirect("camisas:freq_resumo")

    fid = request.POST.get("func")
    dstr = request.POST.get("data")
    mes  = request.POST.get("mes")

    func = get_object_or_404(Funcionario, pk=fid, ativo=True)
    try:
        dia = datetime.strptime(dstr, "%Y-%m-%d").date()
    except Exception:
        messages.error(request, "Data inválida para lançamento.")
        goto = mes or timezone.localdate().strftime("%Y-%m")
        return redirect(f"{reverse('camisas:freq_resumo')}?func={func.id}&mes={goto}")

    obj, _created = FrequenciaDia.objects.get_or_create(funcionario=func, data=dia)
    obj.e1 = _parse_hhmm(request.POST.get("e1"))
    obj.s1 = _parse_hhmm(request.POST.get("s1"))
    obj.e2 = _parse_hhmm(request.POST.get("e2"))
    obj.s2 = _parse_hhmm(request.POST.get("s2"))

    # opcionais
    if "observacao" in request.POST:
        obj.observacao = (request.POST.get("observacao") or "")[:240]
    if request.POST.get("min_prev", "").strip():
        try:
            obj.minutos_previstos_override = max(0, int(request.POST.get("min_prev")))
        except Exception:
            pass

    obj.save()
    messages.success(request, f"Lançado {dia.strftime('%d/%m/%Y')} para {func.nome}.")
    goto = mes or f"{dia:%Y-%m}"
    return redirect(f"{reverse('camisas:freq_resumo')}?func={func.id}&mes={goto}")


@login_required
def frequencia_editar(request, pk=None):
    """
    Cria/edita um lançamento diário.
    Aceita ?func=ID&data=YYYY-MM-DD para pré-preencher (quando novo).
    """
    instance = get_object_or_404(FrequenciaDia, pk=pk) if pk else None
    initial = {}
    if not instance:
        fid = request.GET.get("func")
        dstr= request.GET.get("data")
        if fid:
            initial["funcionario"] = get_object_or_404(Funcionario, pk=fid)
        if dstr:
            initial["data"] = datetime.strptime(dstr, "%Y-%m-%d").date()

    form = FrequenciaDiaForm(request.POST or None, instance=instance, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        return redirect(f"{reverse('camisas:freq_resumo')}?func={obj.funcionario_id}&mes={obj.data:%Y-%m}")

    # cálculo “até agora” se for o dia corrente
    min_prev = instance.minutos_previstos if instance else (initial.get("funcionario").jornada_diaria_min if initial.get("funcionario") else 480)
    min_trab_agora = instance.minutos_trabalhados_ate_agora() if instance else 0
    saldo_agora = min_trab_agora - min_prev

    # dados para nav
    func_for_nav = instance.funcionario if instance else initial.get("funcionario") or _funcionario_padrao(request.user)
    mes_for_nav = (instance.data if instance else initial.get("data") or timezone.localdate())

    return render(request, "camisas/frequencia_form.html", {
        "form": form, "obj": instance,
        "min_prev": min_prev,
        "hh_prev": FrequenciaDia.fmt_hhmm(min_prev),
        "hh_trab_agora": FrequenciaDia.fmt_hhmm(min_trab_agora),
        "hh_saldo_agora": FrequenciaDia.fmt_hhmm(saldo_agora),
        "nav_func": func_for_nav, "nav_mes_str": f"{mes_for_nav:%Y-%m}",
    })

@login_required
def frequencia_hoje(request):
    """
    Atalho: abre (ou cria) o lançamento de HOJE para o funcionário escolhido.
    ?func=ID opcional; se não vier, tenta o do usuário logado.
    """
    func = None
    fid = request.GET.get("func")
    if fid:
        func = get_object_or_404(Funcionario, pk=fid, ativo=True)
    else:
        func = _funcionario_padrao(request.user)
    if not func:
        raise Http404("Nenhum funcionário ativo encontrado.")

    hoje = timezone.localdate()
    obj, _created = FrequenciaDia.objects.get_or_create(funcionario=func, data=hoje)
    return redirect("camisas:freq_editar", pk=obj.pk)

@login_required
def frequencia_funcionarios(request):
    """
    Lista de funcionários com jornada/almoco/hora-padrão e link para Admin.
    """
    funcs = Funcionario.objects.all().order_by("-ativo", "nome")
    items = []
    for f in funcs:
        try:
            admin_url = reverse("admin:camisas_funcionario_change", args=[f.pk])
        except NoReverseMatch:
            admin_url = None
        items.append({
            "obj": f,
            "admin_url": admin_url or "/admin/camisas/funcionario/%d/change/" % f.pk,
        })
    return render(request, "camisas/frequencia_funcionarios.html", {"items": items})

@login_required
def frequencia_relatorio_csv(request):
    """
    Exporta CSV do mês solicitado: ?func=ID&mes=YYYY-MM
    """
    fid = request.GET.get("func")
    mes = request.GET.get("mes")
    if not (fid and mes):
        return redirect("camisas:freq_resumo")

    func = get_object_or_404(Funcionario, pk=fid)
    try:
        dt = datetime.strptime(mes, "%Y-%m").date()
    except ValueError:
        dt = timezone.localdate().replace(day=1)

    ini, fim = _primeiro_dia_mes(dt), _ultimo_dia_mes(dt)
    rows = FrequenciaDia.objects.filter(funcionario=func, data__range=(ini, fim)).order_by("data")

    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="frequencia_{func.pk}_{mes}.csv"'
    w = csv.writer(resp)
    w.writerow(["Data", "Entrada Manhã", "Saída Manhã", "Entrada Tarde", "Saída Tarde",
                "Previsto (min)", "Trabalhado (min)", "Saldo (min)", "Previsto (hh:mm)", "Trabalhado (hh:mm)", "Saldo (hh:mm)", "Obs."])
    for r in rows:
        prev = r.minutos_previstos
        trab = r.minutos_trabalhados_fechado()
        saldo= trab - prev
        w.writerow([
            r.data.strftime("%Y-%m-%d"),
            r.e1 or "", r.s1 or "", r.e2 or "", r.s2 or "",
            prev, trab, saldo,
            FrequenciaDia.fmt_hhmm(prev), FrequenciaDia.fmt_hhmm(trab), FrequenciaDia.fmt_hhmm(saldo),
            r.observacao or "",
        ])
    return resp

# -- helper seguro p/ "HH:MM" (retorna datetime.time ou None) --
def _parse_hhmm(s: str | None):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%H:%M", "%H%M"):
        try:
            return datetime.strptime(s, fmt).time()
        except Exception:
            pass
    return None

@login_required
def frequencia_folha(request):
    """Folha de frequência para impressão/assinatura (1 coluna)."""
    today = timezone.localdate()
    func_default = _funcionario_padrao(request.user)

    # redireciona para defaults se faltar param
    if request.method == "GET" and ("func" not in request.GET or "mes" not in request.GET) and func_default:
        return redirect(f"{reverse('camisas:freq_folha')}?func={func_default.id}&mes={today:%Y-%m}")

    # filtros
    try:
        fid = int(request.GET.get("func", "0"))
    except ValueError:
        fid = 0
    mes_str = request.GET.get("mes") or f"{today:%Y-%m}"

    func = Funcionario.objects.filter(pk=fid, ativo=True).first() or func_default

    # mês de referência
    try:
        ano, mes = mes_str.split("-")
        ref = date(int(ano), int(mes), 1)
    except Exception:
        ref = today.replace(day=1)
        mes_str = f"{ref:%Y-%m}"

    ini, fim = _primeiro_dia_mes(ref), _ultimo_dia_mes(ref)

    # linhas (todos os dias)
    WD_LABEL = ["Segunda","Terça","Quarta","Quinta","Sexta","Sábado","Domingo"]
    linhas = []
    d = ini
    while d <= fim:
        wd = d.weekday()  # 0=Seg ... 6=Dom
        linhas.append({
            "data": d,
            "dia": f"{d:%d}",
            "label": WD_LABEL[wd],
            "is_sat": wd == 5,
            "is_sun": wd == 6,
        })
        d += timedelta(days=1)

    # ---------- EMPRESA ----------
    # 1) tenta ?empresa=ID
    empresa = None
    emp_qs = request.GET.get("empresa")
    if emp_qs:
        try:
            empresa = Empresa.objects.filter(pk=int(emp_qs)).first()
        except Exception:
            empresa = None
    # 2) senão, usa empresa do funcionário (se houver FK)
    if not empresa and func:
        empresa = getattr(func, "empresa", None)
    # 3) fallback: primeira empresa da base
    if not empresa:
        empresa = Empresa.objects.order_by("id").first()

    # monta campos achatados p/ template
    if empresa:
        empresa_nome = empresa.nome_fantasia or empresa.razao_social or ""
        empresa_razao = empresa.razao_social or ""
        empresa_cnpj = empresa.cnpj or ""
        empresa_ie = empresa.ie or ""
        empresa_email = empresa.email or ""
        empresa_telefone = empresa.telefone or ""

        # endereço completo: "endereco - cidade / UF" (só com o que existir)
        partes_esq = [empresa.endereco] if empresa.endereco else []
        dir_cityuf = " / ".join([p for p in [empresa.cidade, empresa.uf] if p])
        if dir_cityuf:
            partes_esq.append(dir_cityuf)
        empresa_endereco_full = " - ".join(partes_esq)

        empresa_logo_url = empresa.logo_url_safe if empresa.logo_has_file else ""
    else:
        empresa_nome = empresa_razao = empresa_cnpj = empresa_ie = ""
        empresa_email = empresa_telefone = empresa_endereco_full = ""
        empresa_logo_url = ""

    # rótulos jornada/almoco
    jornada_min = getattr(func, "jornada_diaria_min", 480)   # 8h
    almoco_min  = getattr(func, "intervalo_almoco_min", 120) # 2h
    def _fmt_horas(m):
        h, r = divmod(int(m or 0), 60)
        return f"{h}h" if r == 0 else f"{h}h{r:02d}"

    ctx = {
        "func": func,
        "mes_ref": ref,
        "mes_str": mes_str,
        "linhas": linhas,
        "jornada_label": _fmt_horas(jornada_min),
        "almoco_label": _fmt_horas(almoco_min),

        # empresa achatada (sempre definidos, mesmo se não houver empresa)
        "empresa_nome": empresa_nome,
        "empresa_razao": empresa_razao,
        "empresa_cnpj": empresa_cnpj,
        "empresa_ie": empresa_ie,
        "empresa_email": empresa_email,
        "empresa_telefone": empresa_telefone,
        "empresa_endereco_full": empresa_endereco_full,
        "empresa_logo_url": empresa_logo_url,

        # opcional: enviar o próprio objeto também
        "empresa": empresa,
    }
    return render(request, "camisas/frequencia_folha.html", ctx)

# camisas/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.contrib import messages
from django.http import Http404
from django.utils import timezone

from .models import Pedido, ColetaPedido, VariacaoProduto
from .forms import ColetaCreateForm

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.http import Http404
from django.contrib import messages
from django.utils import timezone
from .models import Pedido, ColetaPedido, PessoaColeta
from .forms import ColetaCreateForm


def _sizes_for_pedido(pedido):
    """
    Sugere tamanhos com base no padrão do seu PersonalizacaoItem.
    (Evita depender de 'variacao__tamanho', que pode não existir)
    """
    # chaves válidas no seu model:
    padrao = [x[0] for x in PersonalizacaoItem.TAM_CAMISA]
    # se quiser filtrar pelo(s) item(ns) do pedido no futuro, dá pra ajustar aqui
    return padrao or ["PP", "P", "M", "G", "GG", "XG"]


def _primeiro_item_do_pedido(pedido):
    """
    Retorna um ItemPedido para receber as personalizações.
    Tenta via related_name comum; se não houver, faz fallback via query.
    """
    item = None
    # tentativas comuns
    for attr in ("itens", "itempedido_set"):
        if hasattr(pedido, attr):
            qs = getattr(pedido, attr).all()
            item = qs.first()
            if item:
                return item
    # fallback genérico
    try:
        from .models import ItemPedido
        item = ItemPedido.objects.filter(pedido=pedido).first()
    except Exception:
        item = None
    return item


def aplicar_coleta_no_pedido(coleta):
    """
    Converte os registros de PessoaColeta da coleta concluída
    para linhas agregadas em PersonalizacaoItem (com quantidade)
    vinculadas ao 'primeiro' ItemPedido do Pedido.

    Estratégia:
    - agrupa por (nome, numero, tamanho)
    - soma quantidades (1 por pessoa/tamanho na coleta atual)
    - cria/atualiza PersonalizacaoItem no item alvo
    """
    pedido = coleta.pedido
    item_alvo = _primeiro_item_do_pedido(pedido)
    if not item_alvo:
        return 0  # nada aplicado

    # agrega quantidades por (nome, numero, tamanho)
    bucket = {}
    for p in coleta.pessoas.all():
        key = (p.nome or "", p.numero or "", p.tamanho or "")
        bucket[key] = bucket.get(key, 0) + 1

    aplicadas = 0
    for (nome, numero, tam), qtd in bucket.items():
        if not (nome or numero or tam):
            continue

        # tenta encontrar uma personalização existente igual para somar
        obj = PersonalizacaoItem.objects.filter(
            item=item_alvo,
            nome=nome or None,
            numero=numero or None,
            tamanho_camisa=tam or None,
        ).first()

        if obj:
            # soma quantidades
            obj.quantidade = (obj.quantidade or 0) + qtd
            obj.save()
        else:
            PersonalizacaoItem.objects.create(
                item=item_alvo,
                nome=nome or None,
                numero=numero or None,
                outra_info=None,
                tamanho_camisa=tam or None,
                quantidade=qtd,
                incluir_short=False,
                tamanho_short=None,
            )
        aplicadas += 1

    return aplicadas


# ---------- Views ----------

@login_required
def coleta_criar(request, pedido_id):
    pedido = get_object_or_404(
        Pedido.objects.select_related("empresa", "cliente"),
        pk=pedido_id
    )

    if request.method == "POST":
        # ----- 1) Lê e valida o MODO -----
        modo_raw = (request.POST.get("modo") or "").strip().upper()
        modos_validos = dict(ColetaPedido.MODOS).keys()
        if modo_raw not in modos_validos:
            modo = ColetaPedido.MODO_SIMPL
            messages.warning(
                request,
                "Tipo de coleta inválido. Usando 'Quantidades por tamanho'."
            )
        else:
            modo = modo_raw

        # ----- 2) Lê expiração (opcional) -----
        expiracao = None
        expiracao_str = (request.POST.get("expiracao") or "").strip()
        if expiracao_str:
            try:
                dt = datetime.strptime(expiracao_str, "%Y-%m-%dT%H:%M")
                expiracao = timezone.make_aware(dt, timezone.get_current_timezone()) \
                    if timezone.is_naive(dt) else dt
            except Exception:
                messages.warning(
                    request,
                    "Não foi possível ler a data de expiração; o link será criado sem expiração."
                )

        # ----- 3) Cria a coleta -----
        coleta = ColetaPedido.objects.create(
            pedido=pedido,
            modo=modo,
            token=ColetaPedido.novo_token(),
            expiracao=expiracao,
            # 🔹 opcional: já associar a um item específico
            # item_id=request.POST.get("item_id") or None
        )

        modo_label = dict(ColetaPedido.MODOS).get(modo, modo)
        messages.success(
            request,
            f"Link de coleta criado ({modo_label})."
        )
        return redirect("camisas:coleta_gerenciar", coleta_id=coleta.id)

    # GET → renderiza o template
    return render(
        request,
        "camisas/coleta_criar.html",
        {
            "pedido": pedido,
            "default_modo": ColetaPedido.MODO_SIMPL,
            "modos": ColetaPedido.MODOS,
        }
    )


# --- PÚBLICO: preencher tamanhos no padrão PersonalizacaoItem ---
@login_required
def coleta_public(request, token):
    coleta = (ColetaPedido.objects
              .select_related("pedido", "pedido__empresa", "pedido__cliente")
              .filter(token=token).first())
    if not coleta:
        raise Http404("Link inválido.")
    if coleta.is_expirado:
        return render(request, "camisas/coleta_public_bloqueada.html",
                      {"coleta": coleta, "motivo": "expirada"})
    if coleta.is_concluido and request.method == "GET":
        return render(request, "camisas/coleta_public_sucesso.html", {"coleta": coleta})

    pedido  = coleta.pedido
    empresa = getattr(pedido, "empresa", None)
    cliente = getattr(pedido, "cliente", None)

    # 🔹 pega o item do pedido que receberá as personalizações
    item_pedido = pedido.itens.first()  # aqui pode trocar por lógica mais específica

    def gl(name1, name2=None):
        lst = request.POST.getlist(name1)
        if not lst and name2:
            lst = request.POST.getlist(name2)
        return lst

    if request.method == "POST":
        nome_cli = (request.POST.get("nome") or "").strip()
        email = (request.POST.get("email") or "").strip()
        obs = (request.POST.get("obs") or "").strip()

        modo = coleta.modo
        tem_valido = False

        try:
            if modo == ColetaPedido.MODO_SIMPL:
                pares = []
                for k, v in request.POST.items():
                    if not k.startswith("q_"): 
                        continue
                    tam = k[2:].strip()
                    q = int(v or "0")
                    if tam and q > 0:
                        pares.append((tam, q))

                if not pares:
                    sizes_simple = gl("sizes_simple[]")
                    qtys_simple  = gl("qtys_simple[]")
                    for i in range(max(len(sizes_simple), len(qtys_simple))):
                        tam = (sizes_simple[i] if i < len(sizes_simple) else "").strip()
                        q = int(qtys_simple[i] or "0")
                        if tam and q > 0:
                            pares.append((tam, q))

                tem_valido = any(q > 0 for _, q in pares)
                if not tem_valido:
                    messages.error(request, "Informe ao menos uma linha com Tamanho e Quantidade maior que zero.")
                    return render(request, "camisas/coleta_public.html",
                                  {"coleta": coleta, "pedido": pedido, "empresa": empresa, "cliente": cliente})

                for tam, q in pares:
                    PersonalizacaoItem.objects.create(
                        item=item_pedido,
                        tamanho_camisa=tam,
                        quantidade=q
                    )

            else:
                nomes       = gl("pi_nome[]", "names[]")
                numeros     = gl("pi_numero[]", "numbers[]")
                outras      = gl("pi_outra_info[]", "others[]")
                tamanhos    = gl("pi_tam_camisa[]", "sizes[]")
                quantidades = gl("pi_qtd[]", "qtys[]")
                tam_short   = gl("pi_tam_short[]", "short_sizes[]")
                shorts_on   = gl("pi_incluir_short[]", "shorts[]")

                n_rows = max(len(nomes), len(numeros), len(outras), len(tamanhos), len(quantidades))

                for i in range(n_rows):
                    n = (nomes[i] if i < len(nomes) else "").strip()
                    num = (numeros[i] if i < len(numeros) else "").strip()
                    outra = (outras[i] if i < len(outras) else "").strip()
                    tam = (tamanhos[i] if i < len(tamanhos) else "").strip()
                    qtd = int(quantidades[i] or "1") if i < len(quantidades) else 1

                    if modo == ColetaPedido.MODO_NOMES and (not n or not tam):
                        continue
                    if modo == ColetaPedido.MODO_TIME and (not n or not tam or qtd <= 0):
                        continue

                    inc_short = False
                    if i < len(tam_short) and tam_short[i]:
                        inc_short = True
                    elif i < len(shorts_on) and shorts_on[i] in ("on", "true", "1"):
                        inc_short = True

                    PersonalizacaoItem.objects.create(
                        item=item_pedido,
                        nome=n,
                        numero=num if modo == ColetaPedido.MODO_TIME else "",
                        outra_info=outra,
                        tamanho_camisa=tam,
                        quantidade=qtd,
                        incluir_short=inc_short,
                        tamanho_short=(tam_short[i] if inc_short and i < len(tam_short) else None)
                    )

                    tem_valido = True

                if not tem_valido:
                    messages.error(request, "Adicione ao menos uma linha válida.")
                    return render(request, "camisas/coleta_public.html",
                                  {"coleta": coleta, "pedido": pedido, "empresa": empresa, "cliente": cliente})

            # 🔹 Atualiza coleta como concluída
            coleta.cliente_nome  = nome_cli or getattr(cliente, "nome", "") or None
            coleta.cliente_email = email or getattr(cliente, "email", "") or None
            coleta.obs_cliente   = obs or None
            coleta.concluido_em  = timezone.now()
            coleta.save()

            return render(request, "camisas/coleta_public_sucesso.html", {"coleta": coleta})

        except Exception as e:
            messages.error(request, f"Houve um erro: {e}")
            return render(request, "camisas/coleta_public.html",
                          {"coleta": coleta, "pedido": pedido, "empresa": empresa, "cliente": cliente})

    return render(request, "camisas/coleta_public.html",
                  {"coleta": coleta, "pedido": pedido, "empresa": empresa, "cliente": cliente})


@login_required
def coleta_gerenciar(request, coleta_id):
    coleta = get_object_or_404(
        ColetaPedido.objects.select_related("pedido", "pedido__empresa", "pedido__cliente"),
        pk=coleta_id
    )
    pedido = coleta.pedido

    public_path = coleta.public_path  # ex.: reverse('camisas:coleta_public', kwargs={'token': coleta.token})
    full_url = f"{request.scheme}://{request.get_host()}{public_path}"

    # Texto do WhatsApp
    wa_text = f"Olá, segue o link para informar os tamanhos da sua encomenda (Pedido #{pedido.pk}): {full_url}"

    # 2 formas equivalentes (use UMA)
    # Forma A: quote_plus
    wa_link = f"https://wa.me/?text={quote_plus(wa_text)}"

    # Forma B: urlencode
    # wa_link = "https://wa.me/?" + urlencode({"text": wa_text})

    return render(request, "camisas/coleta_gerenciar.html", {
        "coleta": coleta,
        "pedido": pedido,
        "empresa": getattr(pedido, "empresa", None),
        "cliente": getattr(pedido, "cliente", None),
        "full_url": full_url,
        "wa_link": wa_link,
    })



from urllib.parse import quote_plus, urlencode

from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.urls import reverse

@login_required
@require_POST
def pedido_alterar_cliente(request, pk):
    next_url = request.POST.get("next") or reverse("camisas:pedido_list")
    try:
        pedido = Pedido.objects.select_related("cliente").get(pk=pk)
    except Pedido.DoesNotExist:
        messages.error(request, "Pedido não encontrado.")
        return redirect(next_url)

    # Regra: só permite alterar cliente quando o pedido está em ORÇAMENTO
    if pedido.status != "ORC":
        messages.warning(request, "Só é possível alterar o cliente de pedidos em ORÇAMENTO.")
        return redirect(next_url)

    cid = request.POST.get("cliente_id", "").strip()
    if not cid:
        messages.error(request, "Selecione um cliente válido.")
        return redirect(next_url)

    try:
        cliente = Cliente.objects.get(pk=int(cid))
    except (ValueError, Cliente.DoesNotExist):
        messages.error(request, "Cliente inválido.")
        return redirect(next_url)

    pedido.cliente = cliente
    pedido.save(update_fields=["cliente"])
    messages.success(request, f"Cliente do pedido #{pedido.id} alterado para {cliente.nome}.")
    return redirect(next_url)

from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

@login_required
def pessoa_coleta_edit(request, coleta_id, pessoa_id):
    coleta = get_object_or_404(ColetaPedido, pk=coleta_id)
    pessoa = get_object_or_404(PessoaColeta, pk=pessoa_id, coleta=coleta)

    if request.method == "POST":
        form = PessoaColetaForm(request.POST, instance=pessoa)
        if form.is_valid():
            form.save()
            messages.success(request, "Pessoa da coleta atualizada com sucesso!")
            return redirect("camisas:coleta_gerenciar", coleta_id=coleta.id)
        else:
            messages.error(request, "Corrija os erros abaixo.")
    else:
        form = PessoaColetaForm(instance=pessoa)

    return render(request, "camisas/pessoa_coleta_edit.html", {
        "form": form,
        "coleta": coleta,
        "pessoa": pessoa,
    })

@login_required
def pessoa_coleta_pagamento(request, coleta_id, pessoa_id):
    coleta = get_object_or_404(ColetaPedido, pk=coleta_id)
    pessoa = get_object_or_404(PessoaColeta, pk=pessoa_id, coleta=coleta)

    if request.method == "POST":
        valor = request.POST.get("valor")
        if valor:
            pessoa.valor = Decimal(valor.replace(",", "."))
        pessoa.status_pagamento = "pago"
        pessoa.pago_em = timezone.now()
        pessoa.save()
        messages.success(request, f"Pagamento registrado para {pessoa.nome}.")
        return redirect("camisas:pedido_detail", pk=coleta.pedido.pk)

    return render(request, "camisas/pessoa_coleta_pagamento.html", {"pessoa": pessoa, "coleta": coleta})

@login_required
def pessoa_coleta_add(request, coleta_id):
    coleta = get_object_or_404(ColetaPedido, pk=coleta_id)
    if request.method == "POST":
        form = PessoaColetaForm(request.POST)
        if form.is_valid():
            pessoa = form.save(commit=False)
            pessoa.coleta = coleta
            pessoa.save()
            messages.success(request, f"Pessoa {pessoa.nome} adicionada com sucesso.")
            return redirect("camisas:coleta_gerenciar", coleta_id=coleta.id)
    else:
        form = PessoaColetaForm()

    return render(request, "camisas/pessoa_coleta_form.html", {
        "form": form,
        "coleta": coleta,
        "pedido": coleta.pedido,
    })