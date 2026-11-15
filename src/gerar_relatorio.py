"""
Gera as figuras (diagramas e gráficos do benchmark) e o Relatório Técnico em PDF
a partir das evidências produzidas por pipeline_etl.py, testes_qualidade.py e
benchmark.py.

Uso:
    python src/gerar_relatorio.py --aluno1 "Nome Completo 1" [--aluno2 "Nome Completo 2"]
"""
import argparse
import json
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, Paragraph, Preformatted,  # noqa: E402
                                SimpleDocTemplate, Spacer, Table, TableStyle)

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "saida"
DIR_REL = RAIZ / "relatorio"
DIR_FIG = DIR_REL / "figuras"

AZUL, LARANJA, AQUA, AMARELO, VIOLETA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6"
TXT, TXT2, GRADE = "#0b0b0b", "#52514e", "#e4e3df"
COR_ABORD = {"REL": AZUL, "CSV": LARANJA, "PQT": AQUA}
NOME_ABORD = {"REL": "Relacional 3FN (SQLite, JOINs)", "CSV": "Varredura integral CSV",
              "PQT": "Parquet particionado (pushdown)"}


def fmt(n, casas=0):
    s = f"{n:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------------------
# Diagramas
# ---------------------------------------------------------------------------
def caixa(ax, x, y, titulo, colunas, cor, largura=21):
    """Desenha uma tabela (cabeçalho + atributos) com canto superior esquerdo em (x, y)."""
    h_lin, h_cab = 2.7, 3.4
    altura = h_cab + h_lin * len(colunas) + 0.8
    ax.add_patch(FancyBboxPatch((x, y - altura), largura, altura, boxstyle="round,pad=0,rounding_size=0.8",
                                fc="white", ec=cor, lw=1.4, zorder=3))
    ax.add_patch(FancyBboxPatch((x, y - h_cab), largura, h_cab, boxstyle="round,pad=0,rounding_size=0.8",
                                fc=cor, ec=cor, lw=1.4, zorder=4))
    ax.text(x + largura / 2, y - h_cab / 2, titulo, ha="center", va="center", color="white",
            fontsize=8.2, weight="bold", zorder=5)
    for i, c in enumerate(colunas):
        peso = "bold" if c.startswith(("PK", "SK")) else "normal"
        ax.text(x + 0.9, y - h_cab - 0.4 - h_lin * (i + 0.5), c, ha="left", va="center", fontsize=6.6,
                color=TXT, weight=peso, zorder=5, family="DejaVu Sans")
    return {"x": x, "y": y, "w": largura, "h": altura, "cx": x + largura / 2, "cy": y - altura / 2}


def ligar(ax, a, b, rotulo="1 : N"):
    ax.plot([a["cx"], b["cx"]], [a["cy"], b["cy"]], color=TXT2, lw=1.1, zorder=1)
    ax.text((a["cx"] + b["cx"]) / 2, (a["cy"] + b["cy"]) / 2, rotulo, fontsize=6.3, color=TXT2,
            ha="center", va="center", zorder=2, bbox=dict(fc="white", ec="none", pad=0.6))


def diagrama_3fn(arq):
    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.set_xlim(0, 104); ax.set_ylim(0, 62.5); ax.axis("off")
    c = caixa(ax, 1, 58, "customers", ["PK customer_id", "customer_unique_id", "customer_zip_code_prefix",
                                       "customer_city", "customer_state"], AZUL)
    o = caixa(ax, 28, 58, "orders", ["PK order_id", "FK customer_id", "order_status",
                                     "order_purchase_timestamp", "order_approved_at",
                                     "order_delivered_carrier_date", "order_delivered_customer_date",
                                     "order_estimated_delivery_date"], AZUL, 23)
    p = caixa(ax, 56, 58, "order_payments", ["PK,FK order_id", "PK payment_sequential", "payment_type",
                                             "payment_installments", "payment_value"], AZUL)
    r = caixa(ax, 81, 58, "order_reviews", ["PK review_id", "FK order_id", "review_score",
                                            "review_comment_message", "review_creation_date"], AZUL)
    i = caixa(ax, 28, 25, "order_items", ["PK,FK order_id", "PK order_item_id", "FK product_id",
                                          "FK seller_id", "shipping_limit_date", "price", "freight_value"],
              AZUL, 23)
    pr = caixa(ax, 56, 25, "products", ["PK product_id", "FK product_category_name", "product_weight_g",
                                        "product_length/height/width_cm", "product_photos_qty"], AZUL)
    t = caixa(ax, 81, 25, "category_translation", ["PK product_category_name",
                                                   "product_category_name_english"], AZUL)
    s = caixa(ax, 1, 25, "sellers", ["PK seller_id", "seller_zip_code_prefix", "seller_city",
                                     "seller_state"], AZUL)
    for a, b in [(c, o), (o, p), (o, i), (i, pr), (pr, t), (s, i)]:
        ligar(ax, a, b)
    # orders -> reviews contornando order_payments por cima
    ax.plot([o["cx"], o["cx"], r["cx"], r["cx"]], [o["y"], 61, 61, r["y"]], color=TXT2, lw=1.1, zorder=1)
    ax.text((o["cx"] + r["cx"]) / 2, 61, "1 : N", fontsize=6.3, color=TXT2, ha="center", va="center",
            zorder=2, bbox=dict(fc="white", ec="none", pad=0.6))
    fig.tight_layout(); fig.savefig(arq, dpi=200); plt.close(fig)


def diagrama_star(arq):
    fig, ax = plt.subplots(figsize=(10, 7.0))
    ax.set_xlim(0, 104); ax.set_ylim(3, 76); ax.axis("off")
    f = caixa(ax, 37, 75, "fato_vendas", [
        "SK sk_venda", "FK sk_data_compra  -> dim_tempo", "FK sk_data_entrega -> dim_tempo",
        "FK sk_cliente", "FK sk_produto", "FK sk_vendedor", "FK sk_pagamento",
        "DD dd_order_id, dd_order_item_id", "qtd_itens", "valor_item", "valor_frete", "valor_bruto",
        "prazo_entrega_dias_uteis", "prazo_estimado_dias_uteis", "dias_uteis_atraso",
        "qtd_entregas_atrasadas"], LARANJA, 30)
    t = caixa(ax, 1, 75, "dim_tempo", ["SK sk_data (AAAAMMDD)", "data, ano, semestre", "trimestre, mes, nome_mes",
                                       "ano_mes, dia, semana_ano", "dia_semana, nome_dia_semana",
                                       "flag_fim_semana", "flag_feriado, nome_feriado", "flag_dia_util"], AQUA)
    c = caixa(ax, 1, 40, "dim_cliente", ["SK sk_cliente", "nk_customer_id", "id_cliente_unico", "cep_prefixo",
                                         "cidade, uf, regiao"], AQUA)
    p = caixa(ax, 80, 75, "dim_produto", ["SK sk_produto", "nk_product_id", "categoria, categoria_en",
                                          "peso_g, faixa_peso", "comprimento/altura/largura_cm",
                                          "volume_cm3, qtd_fotos"], AQUA)
    v = caixa(ax, 80, 40, "dim_vendedor", ["SK sk_vendedor", "nk_seller_id", "cep_prefixo",
                                           "cidade, uf, regiao"], AQUA)
    g = caixa(ax, 41.5, 18, "dim_pagamento (junk)", ["SK sk_pagamento", "tipo_pagamento, faixa_parcelas"], AQUA)
    for d in [t, c, p, v, g]:
        ligar(ax, d, f, "1 : N")
    fig.tight_layout(); fig.savefig(arq, dpi=200); plt.close(fig)


# ---------------------------------------------------------------------------
# Gráficos do benchmark
# ---------------------------------------------------------------------------
def estilo(ax):
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color(GRADE); ax.spines["bottom"].set_color(GRADE)
    ax.tick_params(colors=TXT2, labelsize=8.5)
    ax.yaxis.grid(True, color=GRADE, lw=0.7); ax.set_axisbelow(True)


def grafico_tempo(bench, arq):
    qs = ["Q1", "Q2", "Q3"]
    fig, ax = plt.subplots(figsize=(8.6, 3.6))
    largura = 0.26
    for k, ab in enumerate(["REL", "CSV", "PQT"]):
        vals = [next(r["mediana_ms"] for r in bench["consultas"] if r["consulta"] == q and r["abordagem"] == ab)
                for q in qs]
        xs = [i + (k - 1) * (largura + 0.02) for i in range(len(qs))]
        ax.bar(xs, vals, largura, color=COR_ABORD[ab], label=NOME_ABORD[ab], edgecolor="white", lw=1)
        for x, v in zip(xs, vals):
            ax.text(x, v + 12, fmt(v), ha="center", va="bottom", fontsize=7.5, color=TXT)
    ax.set_xticks(range(len(qs)))
    ax.set_xticklabels([f"{q}\n{d}" for q, d in zip(qs, ["Receita por categoria (2018)",
                                                         "Prazo por UF (1º tri/2018)",
                                                         "Black Friday nov/2017"])], fontsize=8.3)
    ax.set_ylabel("Tempo mediano (ms)", color=TXT2, fontsize=8.5)
    estilo(ax)
    ax.set_ylim(0, ax.get_ylim()[1] * 1.18)
    ax.legend(frameon=False, fontsize=8, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout(); fig.savefig(arq, dpi=200); plt.close(fig)


def grafico_disco(bench, arq):
    itens = list(bench["disco_mb"].items())
    fig, ax = plt.subplots(figsize=(8.6, 2.9))
    cores = [LARANJA, AZUL, LARANJA, AQUA, AQUA]
    nomes = [n for n, _ in itens][::-1]; vals = [v for _, v in itens][::-1]
    ax.barh(nomes, vals, color=cores[::-1], height=0.6, edgecolor="white")
    for y, v in enumerate(vals):
        ax.text(v + 1.2, y, f"{fmt(v, 1)} MB", va="center", fontsize=8, color=TXT)
    ax.set_xlabel("Espaço em disco (MB)", color=TXT2, fontsize=8.5)
    estilo(ax); ax.yaxis.grid(False); ax.xaxis.grid(True, color=GRADE, lw=0.7)
    ax.set_xlim(0, max(vals) * 1.15)
    fig.tight_layout(); fig.savefig(arq, dpi=200); plt.close(fig)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def registrar_fontes():
    fontes = Path("C:/Windows/Fonts")
    try:
        pdfmetrics.registerFont(TTFont("Corpo", str(fontes / "arial.ttf")))
        pdfmetrics.registerFont(TTFont("Corpo-B", str(fontes / "arialbd.ttf")))
        pdfmetrics.registerFont(TTFont("Corpo-I", str(fontes / "ariali.ttf")))
        pdfmetrics.registerFont(TTFont("Mono", str(fontes / "consola.ttf")))
        from reportlab.lib.fonts import addMapping
        addMapping("Corpo", 0, 0, "Corpo"); addMapping("Corpo", 1, 0, "Corpo-B")
        addMapping("Corpo", 0, 1, "Corpo-I"); addMapping("Corpo", 1, 1, "Corpo-B")
        return "Corpo", "Corpo-B", "Mono"
    except Exception:
        return "Helvetica", "Helvetica-Bold", "Courier"


def construir_pdf(args, met, bench, teste, arq_pdf):
    F, FB, FM = registrar_fontes()
    autores = " e ".join(a for a in (args.aluno1, args.aluno2) if a)
    ss = getSampleStyleSheet()
    corpo = ParagraphStyle("corpo", parent=ss["BodyText"], fontName=F, fontSize=9.6, leading=13.2,
                           alignment=TA_JUSTIFY, spaceAfter=5)
    h1 = ParagraphStyle("h1", parent=corpo, fontName=FB, fontSize=12.5, leading=16, spaceBefore=9, spaceAfter=5,
                        textColor=colors.HexColor("#184f95"), alignment=0)
    h2 = ParagraphStyle("h2", parent=h1, fontSize=10.3, leading=13, spaceBefore=5, spaceAfter=3)
    leg = ParagraphStyle("leg", parent=corpo, fontSize=8, leading=10, alignment=TA_CENTER,
                         textColor=colors.HexColor(TXT2), spaceAfter=7)
    cel = ParagraphStyle("cel", parent=corpo, fontSize=7.5, leading=9.2, alignment=0, spaceAfter=0)
    celb = ParagraphStyle("celb", parent=cel, fontName=FB, textColor=colors.white)
    titulo = ParagraphStyle("tit", parent=corpo, fontName=FB, fontSize=15, leading=19, alignment=TA_CENTER,
                            spaceAfter=3)
    sub = ParagraphStyle("sub", parent=corpo, alignment=TA_CENTER, fontSize=9.5, spaceAfter=1)
    largura_util = A4[0] - 3.6 * cm

    def tabela(linhas, larguras, cab_cor="#184f95", zebra=True):
        dados = [[Paragraph(str(c), celb) for c in linhas[0]]] + \
                [[Paragraph(str(c), cel) for c in l] for l in linhas[1:]]
        t = Table(dados, colWidths=[w * largura_util for w in larguras], repeatRows=1)
        est = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(cab_cor)),
               ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
               ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#d6d5d0")),
               ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
               ("LEFTPADDING", (0, 0), (-1, -1), 3.5), ("RIGHTPADDING", (0, 0), (-1, -1), 3.5)]
        if zebra:
            for i in range(1, len(dados)):
                if i % 2 == 0:
                    est.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f3f2ee")))
        t.setStyle(TableStyle(est))
        return t

    def figura(caminho, largura_frac, legenda_txt):
        img = Image(str(caminho))
        w = largura_util * largura_frac
        img.drawHeight = img.drawHeight * w / img.drawWidth
        img.drawWidth = w
        return KeepTogether([img, Paragraph(legenda_txt, leg)])

    # números
    m = met
    q = {(r["consulta"], r["abordagem"]): r for r in bench["consultas"]}
    ganho = {qq: (q[(qq, "REL")]["mediana_ms"] / q[(qq, "PQT")]["mediana_ms"],
                  q[(qq, "CSV")]["mediana_ms"] / q[(qq, "PQT")]["mediana_ms"]) for qq in ["Q1", "Q2", "Q3"]}
    gmin = min(min(v) for v in ganho.values()); gmax = max(max(v) for v in ganho.values())
    disco = bench["disco_mb"]
    ram = bench["ram"]
    pct_aceito = 100 * m["itens_aceitos"] / m["itens_em_escopo"]
    regras = {r["regra"]: r for r in m["regras"]}
    inj = {r["regra"]: r for r in teste}
    amb = bench["ambiente"]

    E = []
    E += [Paragraph("UNIVERSIDADE ANHEMBI MORUMBI", sub),
          Paragraph("Avaliação A3 — Engenharia de Dados  |  Prof. Roberto Jubran Junior", sub),
          Spacer(1, 6),
          Paragraph("Refatoração Dimensional, Governança de Dados e Persistência Colunar "
                    "do E-commerce Olist", titulo),
          Paragraph(f"Relatório Técnico  •  {autores}  •  "
                    f"{date.today().strftime('%d/%m/%Y')}", sub),
          Spacer(1, 8)]

    # 1 ---------------------------------------------------------------------
    E += [Paragraph("1. Resumo Executivo", h1),
          Paragraph(
              "O ambiente transacional da Olist é modelado em 3FN: ótimo para garantir ACID e evitar anomalias de "
              "escrita, mas caro para análise. Qualquer pergunta da diretoria (receita por categoria, prazo "
              "logístico por estado, comportamento na Black Friday) exige de 3 a 4 JOINs entre tabelas de "
              "centenas de milhares de linhas, funções de data em tempo de consulta e regras de negócio "
              "reescritas em SQL (ex.: mapear UF para região). Além disso, registros com campos ausentes "
              "ou fora do domínio entravam diretamente nas métricas financeiras.", corpo),
          Paragraph(
              f"Implementei um pipeline em Python (pandas + PyArrow + DuckDB) que (i) migra os dados para um "
              f"<b>Star Schema</b> Kimball com 1 fato e 5 dimensões, no grão de <b>1 item de pedido faturado e "
              f"entregue</b>; (ii) aplica <b>14 regras de Data Quality</b> em 4 dimensões (completude, "
              f"validade/conformidade, consistência/integridade e unicidade), desviando registros reprovados para "
              f"<i>quarentena_falhas.parquet</i>; e (iii) persiste a visão analítica em <b>Parquet/Snappy "
              f"particionado por ano/mês</b>. Dos {fmt(m['total_itens_origem'])} itens de origem, "
              f"{fmt(m['itens_aceitos'])} ({fmt(pct_aceito, 2)}% do escopo) foram carregados no DW e "
              f"{fmt(m['itens_quarentenados'])} foram quarentenados com causa registrada.", corpo),
          Paragraph(
              f"<b>Ganhos medidos:</b> as três consultas de negócio ficaram <b>{fmt(gmin, 0)}× a {fmt(gmax, 0)}× "
              f"mais rápidas</b> no Parquet do que no modelo relacional ou na varredura de CSV; a visão analítica "
              f"ocupa <b>{fmt(disco['Visão consolidada Parquet particionado (Snappy)'], 1)} MB</b> contra "
              f"{fmt(disco['Visão consolidada em CSV'], 1)} MB do mesmo conteúdo em CSV e "
              f"{fmt(disco['SQLite 3FN (com índices)'], 1)} MB do banco 3FN; e a leitura seletiva da Black Friday "
              f"materializa só {fmt(ram['parquet_seletivo_mb'], 2)} MB em RAM, contra "
              f"{fmt(ram['csv_pandas_mb'], 1)} MB para carregar os CSVs necessários em pandas.", corpo)]

    # 2 ---------------------------------------------------------------------
    diagrama_3fn(DIR_FIG / "diagrama_3fn.png"); diagrama_star(DIR_FIG / "diagrama_star.png")
    E += [Paragraph("2. Diagramas Arquiteturais Comparativos", h1),
          Paragraph(
              "<b>Origem (OLTP, 3FN).</b> Oito entidades normalizadas, ligadas por chaves naturais textuais "
              "(hashes MD5 de 32 caracteres). O fato de negócio \"venda de um item\" está espalhado entre "
              "<i>order_items</i> (valores), <i>orders</i> (datas e status), <i>customers</i> (geografia), "
              "<i>products</i>/<i>category_translation</i> (categoria) e <i>order_payments</i> (forma de pagamento, "
              "com N linhas por pedido).", corpo),
          figura(DIR_FIG / "diagrama_3fn.png", 0.93, "Figura 1 — Modelo transacional de origem (3FN)."),
          Paragraph(
              "<b>Destino (DW, Star Schema).</b> Uma fato central estreita com chaves substitutas inteiras e "
              "métricas aditivas, cercada por dimensões desnormalizadas de 1 nível (sem snowflake): a tradução da "
              "categoria foi absorvida por <i>dim_produto</i>, a região foi pré-calculada em <i>dim_cliente</i> e "
              "<i>dim_vendedor</i>, e o calendário (incluindo feriados nacionais) virou <i>dim_tempo</i>. Toda "
              "consulta analítica passa a ter no máximo 1 JOIN por dimensão filtrada.", corpo),
          figura(DIR_FIG / "diagrama_star.png", 0.93, "Figura 2 — Modelo dimensional implantado (Star Schema)."),
          ]

    # 3 ---------------------------------------------------------------------
    E += [Paragraph("3. Dicionário de Dados do Data Warehouse", h1),
          Paragraph(
              "<b>Grão.</b> Cada linha de <i>fato_vendas</i> representa <b>um item de pedido faturado e entregue "
              "ao cliente</b>, identificado de forma única por (dd_order_id, dd_order_item_id). É o nível mais "
              "atômico disponível: abaixo dele não há medida de negócio, e qualquer agregação (pedido, cliente, "
              "mês, categoria) é obtida por soma. Pedidos não entregues (cancelados, em trânsito, indisponíveis) "
              f"ficam fora do escopo porque ainda não têm prazo real de entrega ({fmt(m['itens_fora_escopo_status'])} "
              "itens, contabilizados à parte e não tratados como erro). Atributos de pedido (status, pagamento) "
              "são levados ao grão do item via dimensão, nunca como métrica, evitando dupla contagem.", corpo),
          Paragraph(
              "<b>Surrogate keys.</b> Todas as dimensões recebem SKs inteiras autoincrementais (int32), atribuídas "
              "em ordem da chave natural, portanto determinísticas entre execuções da mesma carga. A exceção "
              "intencional é <i>dim_tempo</i>, cuja SK é a data inteligente AAAAMMDD (int32), permitindo "
              "particionar e filtrar sem JOIN. As chaves naturais são mantidas nas dimensões (prefixo nk_) "
              "apenas para rastreabilidade.", corpo),
          Paragraph("3.1 fato_vendas", h2),
          tabela([["Coluna", "Tipo", "Descrição", "Aditividade"],
                  ["sk_venda", "int32", "Chave substituta da linha da fato", "—"],
                  ["sk_data_compra / sk_data_entrega", "int32", "FKs para dim_tempo (papéis: compra e entrega)", "—"],
                  ["sk_cliente, sk_produto, sk_vendedor, sk_pagamento", "int32", "FKs para as dimensões", "—"],
                  ["dd_order_id, dd_order_item_id", "texto, int16",
                   "Dimensões degeneradas (rastreio do pedido/item na origem)", "—"],
                  ["qtd_itens", "int16", "Sempre 1; permite COUNT via SUM", "Aditiva"],
                  ["valor_item", "float64", "Preço unitário do item (R$)", "Aditiva"],
                  ["valor_frete", "float64", "Frete rateado ao item (R$)", "Aditiva"],
                  ["valor_bruto", "float64", "valor_item + valor_frete (R$)", "Aditiva"],
                  ["prazo_entrega_dias_uteis", "int16",
                   "Dias úteis entre compra e entrega (seg–sex, sem feriados nacionais)", "Aditiva*"],
                  ["prazo_estimado_dias_uteis", "int16", "Dias úteis entre compra e data estimada", "Aditiva*"],
                  ["dias_uteis_atraso", "int16", "max(0, prazo real − prazo estimado)", "Aditiva"],
                  ["qtd_entregas_atrasadas", "int16", "1 se houve atraso, senão 0", "Aditiva"]],
                 [0.32, 0.11, 0.43, 0.14]),
          Paragraph("* somáveis; a média é obtida por SUM/qtd_itens.", leg),
          Paragraph("3.2 Dimensões", h2),
          tabela([["Dimensão (linhas)", "Atributos"],
                  [f"dim_tempo ({fmt(m['linhas_dw']['dim_tempo'])})",
                   "sk_data (AAAAMMDD), data, ano, semestre, trimestre, mes, nome_mes, ano_mes, dia, dia_semana "
                   "(1=seg), nome_dia_semana, semana_ano (ISO), flag_fim_semana, flag_feriado, nome_feriado, "
                   "flag_dia_util — calendário contínuo do 1º dia de compra ao último dia de entrega/estimativa"],
                  [f"dim_cliente ({fmt(m['linhas_dw']['dim_cliente'])})",
                   "sk_cliente, nk_customer_id, id_cliente_unico (customer_unique_id, pessoa), cep_prefixo, "
                   "cidade, uf, regiao (derivada). Grão = cliente no pedido, preservando o endereço vigente na compra"],
                  [f"dim_produto ({fmt(m['linhas_dw']['dim_produto'])})",
                   "sk_produto, nk_product_id, categoria (PT; nula → 'sem_categoria'), categoria_en (não catalogada → "
                   "'uncataloged'), peso_g, faixa_peso, comprimento_cm, altura_cm, largura_cm, volume_cm3, qtd_fotos"],
                  [f"dim_vendedor ({fmt(m['linhas_dw']['dim_vendedor'])})",
                   "sk_vendedor, nk_seller_id, cep_prefixo, cidade, uf, regiao (derivada)"],
                  [f"dim_pagamento ({fmt(m['linhas_dw']['dim_pagamento'])})",
                   "Junk dimension: sk_pagamento, tipo_pagamento (de maior valor no pedido; sem pagamento → "
                   "'nao_informado'), faixa_parcelas (à vista, 2–3x, 4–6x, 7x+)"]],
                 [0.2, 0.8])]

    # 4 ---------------------------------------------------------------------
    regras_txt = {
        "COMP-01": "order_purchase_timestamp.isna()",
        "COMP-02": "order_delivered_customer_date.isna()",
        "COMP-03": "price.isna() | freight_value.isna()",
        "VAL-01": "to_numeric/to_datetime(errors='coerce') falha em valor não nulo",
        "VAL-02": "price <= 0",
        "VAL-03": "freight_value < 0",
        "VAL-04": "delivered_customer_date < purchase_timestamp",
        "VAL-05": "~(product_weight_g > 0)",
        "VAL-06": "~customer_state.isin(27 UFs)",
        "INT-01": "order_id de item sem par em orders (LEFT JOIN)",
        "INT-02": "product_id sem par em products",
        "INT-03": "seller_id sem par em sellers",
        "INT-04": "customer_id do pedido sem par em customers",
        "UNI-01": "duplicated(['order_id','order_item_id'])",
    }
    linhas = [["Regra", "Dimensão", "Validação em código (pandas)", "Base real", "Injeção"]]
    for rid, txt in regras_txt.items():
        r = regras[rid]
        i = inj.get(rid)
        linhas.append([rid, r["dimensao"], f"<font name='{FM}'>{txt}</font>", fmt(r["violacoes"]),
                       f"{i['capturados']}/{i['injetados']}" if i else "—"])
    trat = m["tratamentos_sem_rejeicao"]
    E += [Paragraph("4. Matriz de Qualidade e Governança", h1),
          Paragraph(
              "O código não é passivo: os CSVs são lidos como texto (<i>dtype=str</i>) para que tipos mistos não "
              "sejam silenciosamente convertidos pelo parser; cada regra é uma máscara booleana vetorizada sobre o "
              "staging no grão do item (itens LEFT JOIN pedidos, clientes, produtos, vendedores e pagamentos, o "
              "que expõe chaves órfãs). Um registro reprovado em qualquer regra não entra no DW e gera uma linha "
              "por violação em <i>quarentena_falhas.parquet</i> com id_registro, regra, dimensão, motivo, "
              "snapshot JSON do registro original e timestamp da execução. Como a base Olist é relativamente "
              "limpa, um teste de <b>injeção de falhas</b> (<i>testes_qualidade.py</i>) corrompe propositalmente "
              "registros e comprova que cada barreira os captura sem vazamento para o DW (coluna \"Injeção\").",
              corpo),
          tabela(linhas, [0.09, 0.2, 0.47, 0.11, 0.13]),
          Spacer(1, 6),
          Paragraph("<b>Volumetria e tratamentos sem rejeição.</b>", corpo),
          tabela([["Etapa", "Itens", "%"],
                  ["Itens na origem (olist_order_items)", fmt(m["total_itens_origem"]), "100,00"],
                  ["Fora do escopo do grão (pedido não entregue)", fmt(m["itens_fora_escopo_status"]),
                   fmt(100 * m["itens_fora_escopo_status"] / m["total_itens_origem"], 2)],
                  ["Em escopo", fmt(m["itens_em_escopo"]), fmt(100 * m["itens_em_escopo"] / m["total_itens_origem"], 2)],
                  ["<b>Aceitos no DW (fato_vendas)</b>", f"<b>{fmt(m['itens_aceitos'])}</b>",
                   fmt(100 * m["itens_aceitos"] / m["total_itens_origem"], 2)],
                  ["<b>Quarentenados</b>", f"<b>{fmt(m['itens_quarentenados'])}</b>",
                   fmt(100 * m["itens_quarentenados"] / m["total_itens_origem"], 3)]],
                 [0.66, 0.17, 0.17]),
          Spacer(1, 5),
          Paragraph(
              f"A soma aceitos + quarentenados + fora de escopo é verificada por <i>assert</i> (conservação de "
              f"registros). Problemas que não invalidam a métrica foram <b>tratados</b> sem rejeitar a linha, "
              f"preservando o tipo da coluna: {fmt(trat['produtos_categoria_nula_imputada'])} produtos com categoria "
              f"nula receberam 'sem_categoria'; {fmt(trat['produtos_categoria_nao_catalogada'])} produtos de "
              f"categorias ausentes da tabela de tradução foram marcados 'uncataloged'; "
              f"{trat['produtos_dimensoes_nulas_mantidas_float_nullable']} produtos com medidas nulas mantiveram "
              f"NaN em coluna Float64 (não vira texto nem zero, e não distorce médias); "
              f"{trat['itens_sem_pagamento_imputado_nao_informado']} itens sem registro de pagamento receberam "
              f"'nao_informado'. Após a carga, novos <i>asserts</i> garantem: nenhuma FK órfã na fato, SKs únicas, "
              f"grão sem duplicidade, valores monetários válidos e zero nulos na fato.", corpo)]

    # 5 ---------------------------------------------------------------------
    grafico_tempo(bench, DIR_FIG / "benchmark_tempo.png"); grafico_disco(bench, DIR_FIG / "benchmark_disco.png")
    lb = [["Consulta", "Abordagem", "Mediana (ms)", "Mín–máx (ms)", "Dados lidos", "MB no disco", "Ganho do Parquet"]]
    for qq in ["Q1", "Q2", "Q3"]:
        for ab in ["REL", "CSV", "PQT"]:
            r = q[(qq, ab)]
            g = "—" if ab == "PQT" else f"{fmt(r['mediana_ms'] / q[(qq, 'PQT')]['mediana_ms'], 1)}×"
            lb.append([qq if ab == "REL" else "", NOME_ABORD[ab], f"<b>{fmt(r['mediana_ms'], 1)}</b>",
                       f"{fmt(r['min_ms'], 0)}–{fmt(r['max_ms'], 0)}", r["arquivos"], fmt(r["mb_lidos_disco"], 1), g])
    E += [Paragraph("5. Resultados Empíricos do Benchmark", h1),
          Paragraph(
              f"<b>Metodologia.</b> Três consultas de negócio, cada uma implementada nas três abordagens com a mesma "
              f"semântica (<i>sql/consultas_benchmark.sql</i>): <b>Q1</b> top 10 categorias por receita bruta em "
              f"2018; <b>Q2</b> prazo médio de entrega por UF no 1º trimestre de 2018; <b>Q3</b> receita da "
              f"Black Friday (nov/2017) por forma de pagamento e região. (a) <b>Relacional 3FN</b>: SQLite "
              f"{amb['sqlite']} (row-store, PKs e FKs indexadas), representando o OLTP; (b) <b>CSV</b>: DuckDB "
              f"{amb['duckdb']} lendo os CSVs brutos integralmente com os mesmos JOINs; (c) <b>Parquet</b>: DuckDB "
              f"sobre <i>vendas_particionadas/ano=/mes=</i>, com partition pruning, predicate pushdown e projeção de "
              f"colunas. Cada consulta roda 1 vez de aquecimento (equaliza o cache do sistema operacional) e "
              f"{amb['repeticoes']} vezes medidas com <i>time.perf_counter</i>, em conexão nova a cada execução; "
              f"reporto a mediana. Ambiente: Python {amb['python']}, {amb['so']}.", corpo),
          tabela(lb, [0.08, 0.24, 0.1, 0.1, 0.23, 0.1, 0.15]),
          Spacer(1, 6),
          figura(DIR_FIG / "benchmark_tempo.png", 0.86,
                 "Figura 3 — Tempo mediano de execução por consulta e abordagem (menor é melhor)."),
          figura(DIR_FIG / "benchmark_disco.png", 0.86,
                 "Figura 4 — Espaço em disco de cada representação dos dados."),
          Paragraph(
              f"<b>Evidência de pushdown.</b> O plano físico do DuckDB para Q3 mostra o filtro aplicado na "
              f"listagem de arquivos e a projeção de apenas 3 das 34 colunas antes de qualquer leitura:", corpo),
          Preformatted("READ_PARQUET\n  Projections: tipo_pagamento, regiao_cliente, valor_bruto\n"
                       "  File Filters: (ano = 2017)(CAST(mes AS INTEGER) = 11)\n  Scanning Files: 1/23",
                       ParagraphStyle("pre", fontName=FM, fontSize=7.8, leading=9.6, leftIndent=14,
                                      textColor=colors.HexColor("#184f95"), spaceAfter=6)),
          Paragraph(
              f"<b>Memória RAM.</b> Para responder Q3 em um dataframe, carregar em pandas os 4 CSVs envolvidos "
              f"consome <b>{fmt(ram['csv_pandas_mb'], 1)} MB</b>; a visão consolidada inteira em Arrow ocupa "
              f"{fmt(ram['parquet_visao_completa_mb'], 1)} MB; a leitura seletiva (1 partição, 3 colunas, "
              f"{fmt(ram['linhas_parquet_seletivo'])} linhas) ocupa <b>{fmt(ram['parquet_seletivo_mb'], 2)} MB</b>, "
              f"cerca de {fmt(ram['csv_pandas_mb'] / ram['parquet_seletivo_mb'], 0)}× menos.", corpo),
          Paragraph(
              "<b>Consistência dos resultados.</b> Q1 retornou valores idênticos nas três abordagens. Em Q2 o DW "
              "reporta dias <i>úteis</i> (pré-calculados na carga) enquanto o OLTP e o CSV só conseguem, a custo "
              "razoável, dias corridos — a diferença é semântica e intencional. Em Q3 o Parquet tem 1 item a menos "
              "na primeira linha: é exatamente o único item de nov/2017 quarentenado (COMP-02: pedido \"entregue\" sem data de entrega), ou seja, a camada "
              "analítica é mais confiável, não divergente.", corpo)]

    # 6 ---------------------------------------------------------------------
    E += [Paragraph("6. Discussão Crítica", h1),
          Paragraph(
              f"<b>Redundância controlada vs. normalização.</b> A visão consolidada repete em cada linha a "
              f"categoria, a UF, a região e o tipo de pagamento — exatamente o que a 3FN proíbe. No OLTP isso seria "
              f"um risco de anomalia de atualização; no DW é aceitável porque a carga é <i>append-only</i>, "
              f"controlada por um único pipeline com regras de qualidade, e o OLTP continua sendo a fonte da verdade. "
              f"A redundância é o preço de trocar JOINs em tempo de consulta por leitura sequencial.", corpo),
          Paragraph(
              f"<b>Custo de armazenamento.</b> A intuição de que desnormalizar \"ocupa mais\" não se confirmou em "
              f"formato colunar: os valores repetidos são justamente os que a codificação por dicionário e RLE do "
              f"Parquet comprimem melhor, e a Snappy atua sobre colunas homogêneas. O mesmo conteúdo cai de "
              f"{fmt(disco['Visão consolidada em CSV'], 1)} MB (CSV) para "
              f"{fmt(disco['Visão consolidada Parquet particionado (Snappy)'], 1)} MB (Parquet). Já o SQLite 3FN "
              f"ocupa {fmt(disco['SQLite 3FN (com índices)'], 1)} MB, mais que os próprios CSVs "
              f"({fmt(disco['CSV brutos OLTP (8 arquivos)'], 1)} MB), por armazenar hashes de 32 caracteres "
              f"repetidos em cada FK e índices B-tree necessários para os JOINs. O Star Schema em Parquet "
              f"({fmt(disco['Star Schema Parquet (fato + 5 dimensões)'], 1)} MB) é maior que a visão consolidada "
              f"porque as dimensões ainda guardam as chaves naturais textuais para rastreabilidade. Ressalva: "
              f"particionar por mês gera arquivos pequenos (≈0,3 MB); em volumes maiores o ideal é mirar "
              f"arquivos de 128 MB–1 GB, ou particionar só por ano.", corpo),
          Paragraph(
              "<b>Facilidade de consulta.</b> No 3FN, Q3 exige 4 tabelas, uma janela ROW_NUMBER() para escolher o "
              "pagamento principal entre N linhas por pedido, um CASE de 27 UFs para região e filtro em timestamp "
              "textual; no DW é um SELECT de uma tabela com WHERE ano = 2017 AND mes = 11. Isso reduz erros de "
              "analistas e padroniza a regra de negócio (a região e o pagamento principal são definidos uma vez, "
              "no ETL). Q2 mostra o outro lado: \"dias úteis com feriados nacionais\" é praticamente inviável em SQL "
              "ad hoc, mas é trivial quando pré-calculado na carga via dim_tempo.", corpo),
          Paragraph(
              "<b>Memória RAM e CPU.</b> O row-store precisa ler linhas inteiras e montar tabelas hash de JOIN em "
              "memória; um analista com pandas precisa carregar os CSVs completos. O formato colunar inverte isso: "
              "lê só as colunas projetadas das partições que passam no filtro, o que explica a redução de duas "
              "ordens de grandeza na RAM e permite analisar volumes maiores que a memória da máquina.", corpo),
          Paragraph(
              "<b>Limitações e próximos passos.</b> (i) O dataset (~110 mil itens) cabe em cache, então os tempos "
              "absolutos são pequenos e as razões tendem a <i>crescer</i> com o volume; (ii) SQLite é um proxy de "
              "MySQL/PostgreSQL — um SGBD servidor teria paralelismo, mas também concorrência por locks com a "
              "produção, que é o problema original; (iii) o DW tem latência de carga (batch) e não serve para "
              "consulta operacional em tempo real; (iv) evoluções naturais: carga incremental por partição, SCD tipo "
              "2 em dim_cliente/dim_produto, uma fato de pagamentos no grão próprio e orquestração (Airflow) com "
              "alertas quando a taxa de quarentena ultrapassar um limiar.", corpo),
          Paragraph(
              "<b>Reprodutibilidade.</b> Todo o processo é executado por <i>pipeline_etl.py</i> → "
              "<i>testes_qualidade.py</i> → <i>benchmark.py</i> → <i>gerar_relatorio.py</i>; todas as tabelas e "
              "gráficos deste relatório são gerados a partir dos JSONs de evidência em <i>saida/</i> (ver README.md).",
              corpo)]

    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont(F, 7.5); canvas.setFillColor(colors.HexColor(TXT2))
        canvas.drawString(1.8 * cm, 1.1 * cm, "A3 — Engenharia de Dados  •  Universidade Anhembi Morumbi")
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Página {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(arq_pdf), pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.7 * cm,
                            title="A3 Engenharia de Dados — Relatório Técnico",
                            author=autores)
    doc.build(E, onFirstPage=rodape, onLaterPages=rodape)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aluno1", default="Aluno 1")
    ap.add_argument("--aluno2", default=None, help="opcional (trabalho individual)")
    args = ap.parse_args()
    DIR_FIG.mkdir(parents=True, exist_ok=True)
    met = json.loads((SAIDA / "metricas_qualidade.json").read_text(encoding="utf-8"))
    bench = json.loads((SAIDA / "benchmark.json").read_text(encoding="utf-8"))
    teste = json.loads((SAIDA / "teste_injecao_falhas.json").read_text(encoding="utf-8"))
    alunos = [a for a in (args.aluno1, args.aluno2) if a]
    nome = "A3_Engenharia_Dados_" + "_".join(a.replace(" ", "") for a in alunos) + ".pdf"
    arq = DIR_REL / nome
    construir_pdf(args, met, bench, teste, arq)
    print(f"Relatório gerado: {arq}")


if __name__ == "__main__":
    main()
