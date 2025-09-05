# camisas/urls.py
from django.urls import path
from . import views

app_name = "camisas"

urlpatterns = [
    # Home / dashboard
    path("", views.home, name="home"),

    # Empresas
    path("empresas/", views.empresa_list, name="empresa_list"),
    path("empresas/nova/", views.empresa_create, name="empresa_create"),
    path("empresas/<int:pk>/editar/", views.empresa_update, name="empresa_update"),

    # Clientes
    path("clientes/", views.cliente_list, name="cliente_list"),
    path("clientes/novo/", views.cliente_create, name="cliente_create"),
    path("clientes/<int:pk>/editar/", views.cliente_update, name="cliente_update"),

    # Insumos
    path("insumos/", views.insumo_list, name="insumo_list"),
    path("insumos/novo/", views.insumo_create, name="insumo_create"),
    path("insumos/<int:pk>/editar/", views.insumo_update, name="insumo_update"),
    path("insumos/<int:pk>/entrada/", views.insumo_entrada, name="insumo_entrada"),

    # Produtos / Variações
    path("produtos/", views.produto_list, name="produto_list"),
    path("produtos/novo/", views.produto_create, name="produto_create"),
    path("variacoes/novo/", views.variacao_create, name="variacao_create"),

    # Ficha técnica (por variação)
    path("ficha/<int:variacao_id>/", views.ficha_list, name="ficha_list"),
    path("ficha/<int:variacao_id>/add/", views.ficha_add_item, name="ficha_add_item"),

    # Ordem de produção (manual)
    path("op/nova/", views.op_create, name="op_create"),

    # Pedidos / Vendas
    path("pedidos/", views.pedido_list, name="pedido_list"),
    path("pedidos/novo/", views.pedido_create, name="pedido_create"),
    path("pedidos/<int:pk>/", views.pedido_detail, name="pedido_detail"),
    path("pedidos/<int:pk>/editar/", views.pedido_update, name="pedido_update"),
    path("pedidos/<int:pk>/orcamento/", views.pedido_orcamento, name="pedido_orcamento"),
    path("pedidos/<int:pk>/gerar-ops/", views.pedido_gerar_ops, name="pedido_gerar_ops"),
    path("pedidos/<int:pk>/faturar/", views.pedido_faturar, name="pedido_faturar"),
    path("pedidos/<int:pk>/item/", views.item_pedido_add, name="item_pedido_add"),
    path("pedidos/<int:pk>/arte/", views.pedido_upload_arte, name="pedido_upload_arte"),
    path("orcamento/<str:token>/", views.orcamento_publico, name="orcamento_publico"),
    path("pedido/<int:pk>/reabrir-orcamento/", views.pedido_reabrir_orcamento, name="pedido_reabrir_orcamento"),
    path("pedidos/<int:pk>/excluir/", views.pedido_delete, name="pedido_delete"),

    # Remessas (Terceirização)
    path("remessas/", views.remessa_list, name="remessa_list"),
    path("remessas/nova/", views.remessa_create, name="remessa_create"),
    path("remessas/<int:pk>/", views.remessa_detail, name="remessa_detail"),
    path("remessas/<int:pk>/receber/", views.remessa_receive, name="remessa_receive"),
    path("remessas/<int:pk>/imprimir/", views.remessa_print, name="remessa_print"),

    # Costureiras
    path("costureiras/", views.costureira_list, name="costureira_list"),
    path("costureiras/nova/", views.costureira_create, name="costureira_create"),
    path("costureiras/<int:pk>/editar/", views.costureira_update, name="costureira_update"),
    path("costureiras/<int:pk>/toggle/", views.costureira_toggle, name="costureira_toggle"),

    # Relatórios / Pagamentos costureira
    path("relatorios/pagamentos/", views.pagamentos_list, name="pagamentos_list"),
    path("relatorios/pagamentos/exportar/", views.pagamentos_export_csv, name="pagamentos_export_csv"),
    path("pagamentos/<int:pk>/marcar-pago/", views.pagamento_marcar_pago, name="pagamento_marcar_pago"),
    path("pagamentos/<int:pk>/marcar-pendente/", views.pagamento_marcar_pendente, name="pagamento_marcar_pendente"),

    path("frequencia/", views.frequencia_resumo, name="freq_resumo"),
    path("frequencia/editar/", views.frequencia_editar, name="freq_novo"),
    path("frequencia/<int:pk>/editar/", views.frequencia_editar, name="freq_editar"),
    path("frequencia/hoje/", views.frequencia_hoje, name="freq_hoje"),            # atalho p/ lançamento de hoje
    path("frequencia/funcionarios/", views.frequencia_funcionarios, name="freq_funcionarios"),
    path("frequencia/relatorio.csv", views.frequencia_relatorio_csv, name="freq_relatorio_csv"),
    path("frequencia/inline-upsert/", views.frequencia_inline_upsert, name="freq_inline_upsert"),
    path("frequencia/folha/", views.frequencia_folha, name="freq_folha"),
    # Despesas
    path("despesas/", views.despesa_list, name="despesa_list"),
    path("despesas/nova/", views.despesa_create, name="despesa_create"),
    path("despesas/<int:pk>/", views.despesa_update, name="despesa_update"),
    path("despesas/parcela/<int:pk>/pagar/", views.parcela_pagar, name="parcela_pagar"),

    path("pedido/<int:pedido_id>/coleta/novo/", views.coleta_criar, name="coleta_criar"),
    path("coleta/<int:coleta_id>/", views.coleta_gerenciar, name="coleta_gerenciar"),  # interno (mostra link)
    path("r/coleta/<str:token>/", views.coleta_public, name="coleta_public"),

    path("pedidos/<int:pk>/alterar-cliente/", views.pedido_alterar_cliente, name="pedido_alterar_cliente"),

    path("pedidos/<int:pk>/cotacao-concorrente/nova/", views.cotacao_concorrente_create, name="cotacao_concorrente_create"),
    path("cotacoes-concorrentes/<int:cot_id>/imprimir/", views.cotacao_concorrente_print, name="cotacao_concorrente_print"),
    # Homes
    path("pedidos/home/", views.pedidos_home, name="pedidos_home"),
    path("despesas/home/", views.despesas_home, name="despesas_home"),
    path("costureiras/home/", views.costureiras_home, name="costureiras_home"),
    path("clientes/home/", views.clientes_home, name="clientes_home"),

    # Remessas rápidas
    path("pedidos/<int:pk>/gerar-remessa/", views.pedido_gerar_remessa, name="pedido_gerar_remessa"),
    path("remessas/quick-create-by-produto/", views.remessa_quick_create_by_produto, name="remessa_quick_create_by_produto"),
    path("remessas/<int:pk>/gerar-proxima/", views.remessa_generate_next, name="remessa_generate_next"),

    
    # Cotação de preços
    path("pedidos/<int:pk>/cotacao/", views.pedido_cotacao_precos, name="pedido_cotacao_precos"),

    # ARTE (público: aprovação/recusa com assinatura)
    path("pedidos/<int:pk>/enviar-arte/", views.pedido_enviar_arte, name="pedido_enviar_arte"),
    path("arte/<str:token>/", views.arte_publica, name="arte_publica"),
]

# ---- Assinatura eletrônica: registre SEMPRE, com fallback de depuração ----
import logging
from django.http import JsonResponse, HttpResponseNotAllowed

logger = logging.getLogger(__name__)

_ESIG_IMPORT_ERR = None
try:
    from .views_esig import esign_create as _esign_create, esign_verify as _esign_verify
except Exception as exc:
    _ESIG_IMPORT_ERR = f"{type(exc).__name__}: {exc}"
    logger.warning("views_esig não carregou: %s", _ESIG_IMPORT_ERR)

    def _esign_create(request, pk):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        return JsonResponse(
            {"ok": False, "error": "views_esig.py não carregado", "detail": _ESIG_IMPORT_ERR},
            status=501,
        )

    def _esign_verify(request):
        return JsonResponse(
            {"ok": False, "error": "views_esig.py não carregado", "detail": _ESIG_IMPORT_ERR},
            status=501,
        )

urlpatterns += [
    path("assinaturas/<int:pk>/criar/", _esign_create, name="esign_create"),
    path("assinaturas/verify/", _esign_verify, name="esign_verify"),
]
