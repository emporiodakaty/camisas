# scripts/seed_precos.py
import os
import sys
from pathlib import Path
from decimal import Decimal
import django

# ==== CONFIGURA DJANGO ====
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fabrica.settings")
django.setup()

from camisas.models import Produto, VariacaoProduto, Empresa

# ==== EMPRESA PADRÃO ====
empresa, _ = Empresa.objects.get_or_create(nome_fantasia="Empresa Padrão")

# ==== FUNÇÃO AUXILIAR ====
def criar_produto(nome_base, categoria, variacoes):
    produto, _ = Produto.objects.get_or_create(
        empresa=empresa,
        nome=f"{nome_base} - {categoria}",
        defaults={"descricao": f"Categoria {categoria}"}
    )
    for tipo, preco in variacoes:
        var, created = VariacaoProduto.objects.get_or_create(
            produto=produto,
            tipo=tipo,  # agora só o tipo curto
            defaults={"preco_sugerido": Decimal(preco)}
        )
        if not created:
            var.preco_sugerido = Decimal(preco)
            var.save()
    print(f"✔ {produto.nome} cadastrado com {len(variacoes)} variações.")


# ==== LISTA DE PRODUTOS ====
PRODUTOS = {
    "MALHA PV": {
        "Camiseta Gola Role": [
            ("Estampa DTF Branca", "48.00"),
            ("Estampa DTF Colorida", "48.00"),
            ("Pintada Branca", "45.00"),
            ("Pintada Colorida", "45.00"),
            ("Bordado Branca", "48.00"),
            ("Bordado Colorida", "50.00"),
        ],
        "Camiseta Gola V": [
            ("Estampa DTF Branca", "48.00"),
            ("Estampa DTF Colorida", "48.00"),
            ("Pintada Branca", "45.00"),
            ("Pintada Colorida", "45.00"),
            ("Bordado Branca", "48.00"),
            ("Bordado Colorida", "50.00"),
        ],
        "Camiseta Gola Polo": [
            ("Estampa DTF Branca", "60.00"),
            ("Estampa DTF Colorida", "60.00"),
            ("Pintada Branca", "58.00"),
            ("Pintada Colorida", "60.00"),
            ("Bordado Branca", "65.00"),
            ("Bordado Colorida", "65.00"),
        ],
    },
    "MALHA ALGODÃO": {
        "Camiseta Gola Role": [
            ("Estampa DTF Branca", "48.00"),
            ("Estampa DTF Colorida", "50.00"),
            ("Pintada Branca", "46.00"),
            ("Pintada Colorida", "48.00"),
            ("Bordado Branca", "48.00"),
            ("Bordado Colorida", "50.00"),
        ],
        "Camiseta Gola V": [
            ("Estampa DTF Branca", "48.00"),
            ("Estampa DTF Colorida", "50.00"),
            ("Pintada Branca", "46.00"),
            ("Pintada Colorida", "48.00"),
            ("Bordado Branca", "48.00"),
            ("Bordado Colorida", "50.00"),
        ],
        "Camiseta Gola Polo": [
            ("Estampa DTF Branca", "60.00"),
            ("Estampa DTF Colorida", "62.00"),
            ("Pintada Branca", "58.00"),
            ("Pintada Colorida", "60.00"),
            ("Bordado Branca", "65.00"),
            ("Bordado Colorida", "67.00"),
        ],
    },
    "MALHA PROTEÇÃO": {
        "Poliéster Frente e Costa": [
            ("Branca", "75.00"),
            ("Colorida", "85.00"),
        ],
    },
    "MALHA PP": {
        "Camiseta Gola Role": [
            ("Estampa Central Branca", "40.00"),
            ("Estampa Central Colorida", "43.00"),
            ("Pintada Branca", "43.00"),
            ("Pintada Colorida", "45.00"),
            ("Bordado Branca", "45.00"),
            ("Bordado Colorida", "50.00"),
        ],
        "Camiseta Gola V": [
            ("Estampa Central Branca", "40.00"),
            ("Estampa Central Colorida", "43.00"),
            ("Estampa DTF Branca", "45.00"),
            ("Estampa DTF Colorida", "48.00"),
            ("Bordado Branca", "45.00"),
            ("Bordado Colorida", "48.00"),
        ],
        "Camiseta Gola Polo": [
            ("Estampa Central Branca", "55.00"),
            ("Estampa Central Colorida", "58.00"),
            ("Estampa DTF Branca", "58.00"),
            ("Estampa DTF Colorida", "60.00"),
            ("Bordado Branca", "65.00"),
            ("Bordado Colorida", "65.00"),
        ],
    },
    "MALHA DRY FIT": {
        "Camiseta Gola Role": [
            ("Estampa Total Branca", "55.00"),
            ("Estampa Total Colorida", "55.00"),
            ("Estampa Central Branca", "50.00"),
            ("Estampa Central Colorida", "52.00"),
            ("Bordado Branca", "50.00"),
            ("Bordado Colorida", "52.00"),
        ],
        "Camiseta Gola V": [
            ("Estampa Total Branca", "50.00"),
            ("Estampa Total Colorida", "55.00"),
            ("Estampa Central Branca", "42.00"),
            ("Estampa Central Colorida", "45.00"),
            ("Bordado Branca", "50.00"),
            ("Bordado Colorida", "52.00"),
        ],
        "Camiseta Gola Polo": [
            ("Estampa Total Branca", "55.00"),
            ("Estampa Total Colorida", "58.00"),
            ("Estampa Central Branca", "50.00"),
            ("Estampa Central Colorida", "52.00"),
            ("Bordado Branca", "55.00"),
            ("Bordado Colorida", "57.00"),
        ],
    },
}


# ==== EXECUÇÃO ====
for categoria, produtos in PRODUTOS.items():
    for nome_base, variacoes in produtos.items():
        criar_produto(nome_base, categoria, variacoes)

print("✅ Produtos e variações cadastrados com sucesso!")
