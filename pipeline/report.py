import os
from datetime import datetime, date

# IMPORTS LAZY: ReportLab so e carregado quando gerar_relatorio() e chamado.


# PALETA DE CORES
def _cores():
    from reportlab.lib import colors
    return {
        'PRIMARY':    colors.HexColor('#1E293B'),
        'ACCENT':     colors.HexColor('#0F766E'),
        'DIVIDER':    colors.HexColor('#CBD5E1'),
        'LIGHT_GREY': colors.HexColor('#F8FAFC'),
        'MID_GREY':   colors.HexColor('#64748B'),
        'WHITE':      colors.white,
        'BLACK':      colors.HexColor('#0F172A'),
        'ALERT_BG':   colors.HexColor('#FEF3C7'),
        'ALERT_TXT':  colors.HexColor('#92400E'),
        'DAILY_BG':   colors.HexColor('#F0FDF4'),
        'DAILY_TXT':  colors.HexColor('#166534'),
        'UP_COLOR':   colors.HexColor('#15803D'),
        'DOWN_COLOR': colors.HexColor('#B91C1C'),
    }


# DIMENSOES
def _dims():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    PAGE_W, PAGE_H = A4
    MARGIN = 15 * mm
    return PAGE_W, PAGE_H, MARGIN, PAGE_W - (2 * MARGIN)


# ESTILOS
def _styles():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    c = _cores()
    return {
        'biz_name':      ParagraphStyle('biz_name',      fontName='Helvetica-Bold', fontSize=18, leading=22,  textColor=c['PRIMARY'],   alignment=TA_LEFT,    spaceAfter=4),
        'meta_sub':      ParagraphStyle('meta_sub',      fontName='Helvetica',      fontSize=9,  leading=12,  textColor=c['MID_GREY'],  alignment=TA_LEFT,    spaceAfter=2),
        'section_title': ParagraphStyle('section_title', fontName='Helvetica-Bold', fontSize=12, leading=15,  textColor=c['PRIMARY'],   spaceAfter=6, spaceBefore=12, keepWithNext=True),
        'kpi_lbl':       ParagraphStyle('kpi_lbl',       fontName='Helvetica',      fontSize=8,               textColor=c['MID_GREY'],  alignment=TA_CENTER),
        'kpi_val':       ParagraphStyle('kpi_val',       fontName='Helvetica-Bold', fontSize=11,              textColor=c['PRIMARY'],   alignment=TA_CENTER),
        'table_hdr':     ParagraphStyle('table_hdr',     fontName='Helvetica-Bold', fontSize=9,               textColor=c['WHITE'],     alignment=TA_LEFT),
        'table_hdr_c':   ParagraphStyle('table_hdr_c',   fontName='Helvetica-Bold', fontSize=9,               textColor=c['WHITE'],     alignment=TA_CENTER),
        'table_cell':    ParagraphStyle('table_cell',    fontName='Helvetica',      fontSize=9,               textColor=c['BLACK'],     alignment=TA_LEFT,    wordWrap='CJK'),
        'table_cell_c':  ParagraphStyle('table_cell_c',  fontName='Helvetica',      fontSize=9,               textColor=c['BLACK'],     alignment=TA_CENTER,  wordWrap='CJK'),
        'alert_p':       ParagraphStyle('alert_p',       fontName='Helvetica',      fontSize=9.5, leading=13, textColor=c['ALERT_TXT'], alignment=TA_JUSTIFY),
        'footer':        ParagraphStyle('footer',        fontName='Helvetica',      fontSize=8,               textColor=c['MID_GREY'],  alignment=TA_CENTER),
        'daily_lbl':     ParagraphStyle('daily_lbl',     fontName='Helvetica',      fontSize=8,               textColor=c['DAILY_TXT'], alignment=TA_CENTER),
        'daily_val':     ParagraphStyle('daily_val',     fontName='Helvetica-Bold', fontSize=13,              textColor=c['DAILY_TXT'], alignment=TA_CENTER),
        'daily_p':       ParagraphStyle('daily_p',       fontName='Helvetica',      fontSize=9.5, leading=13, textColor=c['DAILY_TXT'], alignment=TA_JUSTIFY),
    }


def _fmt_mzn(val: float) -> str:
    return f'MZN {val:,.2f}'


# LABELS ADAPTATIVOS POR TIPO DE NEGOCIO
def _labels(tipo_negocio: str) -> dict:
    """
    Devolve um dicionario de labels adaptados ao tipo de negocio.
    Todos os textos visiveis no PDF passam por aqui — nunca hardcoded.
    """
    tipo = (tipo_negocio or "retalho").lower()
    e_servicos = tipo in ("servicos", "servico")

    if e_servicos:
        return {
            # KPIs
            "itens_vendidos":    "TRANSACCOES",
            "ticket_medio":      "VALOR MEDIO/SERVICO",
            "melhor_dia":        "MELHOR DIA",
            # Secao Top 5
            "top5_titulo":       "Analise de Servicos Prestados (Top 5)",
            "top5_col_item":     "Servico",
            "top5_col_ranking":  "Ranking",
            "top5_col_qty":      "Ocorrencias",
            "top5_col_rel":      "% Relevancia",
            "top5_sem_dados":    "Nenhum servico detetado",
            # Destaques do dia
            "destaque_item":     "SERVICO DO DIA",
            # Recomendacoes
            "insight_item":      "servico",
            "insight_acao":      (
                "Recomenda-se aferir a capacidade operacional disponivel para responder "
                "a maior procura deste servico. Considere criar um pacote combinado com "
                "servicos complementares para aumentar o valor medio por cliente."
            ),
        }
    else:
        # retalho, agropecuaria, outro
        return {
            "itens_vendidos":   "ITENS VENDIDOS",
            "ticket_medio":     "TICKET MEDIO",
            "melhor_dia":       "MELHOR DIA",
            "top5_titulo":      "Analise de Escoamento e Mix (Top 5)",
            "top5_col_item":    "Produto Lider",
            "top5_col_ranking": "Ranking",
            "top5_col_qty":     "Qtd Vendida",
            "top5_col_rel":     "% Relevancia Comercial",
            "top5_sem_dados":   "Nenhum produto detetado",
            "destaque_item":    "PRODUTO DO DIA",
            "insight_item":     "produto",
            "insight_acao":     (
                "Recomenda-se auditar o nivel critico de inventario com os vossos fornecedores "
                "para blindar o canal contra ruturas. Estrategicamente, considere arquitetar um "
                "pacote promocional casando este produto lider com os itens de menor tracao, "
                "permitindo girar o stock de menor liquidez e expandir o Ticket Medio das transacoes."
            ),
        }


def _kpi_block(metricas: dict, is_mensal: bool, styles: dict, UTIL_W: float):
    from reportlab.platypus import Table, Paragraph, TableStyle
    c   = _cores()
    lbl = _labels(metricas.get('tipo_negocio', 'retalho'))

    if is_mensal:
        total      = metricas.get('total_mensal', 0)
        trans      = metricas.get('transacoes_mensal', 1)
        ticket     = metricas.get('ticket_medio_mensal', 0)
        melhor_dia = metricas.get('melhor_dia_mes', '-')
    else:
        total      = metricas.get('total', 0)
        trans      = metricas.get('total_transacoes', 1)
        ticket     = metricas.get('ticket_medio', 0)
        melhor_dia = metricas.get('melhor_dia', '-')

    kpis = [
        ('FATURACAO TOTAL',       _fmt_mzn(total)),
        (lbl['itens_vendidos'],   str(trans)),
        (lbl['ticket_medio'],     _fmt_mzn(ticket)),
        (lbl['melhor_dia'],       str(melhor_dia)),
    ]

    header_cells = [Paragraph(l, styles['kpi_lbl']) for l, _ in kpis]
    value_cells  = [Paragraph(v, styles['kpi_val']) for _, v in kpis]

    col_w = UTIL_W / 4
    t = Table([header_cells, value_cells], colWidths=[col_w] * 4)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), c['LIGHT_GREY']),
        ('BOX',           (0, 0), (-1, -1), 0.75, c['DIVIDER']),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5,  c['DIVIDER']),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def _daily_highlights(metricas: dict, styles: dict, UTIL_W: float):
    """
    Bloco de destaque para relatorios diarios.
    Label "PRODUTO DO DIA" vs "SERVICO DO DIA" adapta-se ao tipo_negocio.
    """
    from reportlab.platypus import Table, Paragraph, TableStyle
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    c   = _cores()
    lbl = _labels(metricas.get('tipo_negocio', 'retalho'))

    produto_do_dia = metricas.get('produto_do_dia')
    hora_pico      = metricas.get('hora_pico')
    variacao_ontem = metricas.get('variacao_ontem')

    # Item do dia (produto ou servico)
    if produto_do_dia:
        nome_item  = str(produto_do_dia['nome']).strip().title()
        qty_item   = int(produto_do_dia['quantidade'])
        fat_item   = float(produto_do_dia['faturacao'])
        item_val   = f"{nome_item}\n{qty_item} un · {_fmt_mzn(fat_item)}"
    else:
        item_val = "-"

    hora_val = hora_pico if hora_pico else "-"

    if variacao_ontem is not None:
        sinal        = "+" if variacao_ontem >= 0 else "-"
        cor_var      = c['UP_COLOR'] if variacao_ontem >= 0 else c['DOWN_COLOR']
        variacao_str = f"{sinal} {abs(variacao_ontem):.1f}% vs ontem"
        style_var    = ParagraphStyle('var_color', fontName='Helvetica-Bold', fontSize=13,
                                      textColor=cor_var, alignment=TA_CENTER)
    else:
        variacao_str = "-"
        style_var    = styles['daily_val']

    kpis_diarios = [
        (lbl['destaque_item'],  item_val,       styles['daily_val']),
        ('HORA DE PICO',         hora_val,       styles['daily_val']),
        ('VARIACAO VS ONTEM',    variacao_str,   style_var),
    ]

    header_cells = [Paragraph(l, styles['daily_lbl'])  for l, _, _s in kpis_diarios]
    value_cells  = [Paragraph(v, style)                 for _, v, style in kpis_diarios]

    col_w = UTIL_W / 3
    t = Table([header_cells, value_cells], colWidths=[col_w] * 3)
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), c['DAILY_BG']),
        ('BOX',           (0, 0), (-1, -1), 1,    c['DAILY_TXT']),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5,  c['DIVIDER']),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def _performance_table(metricas: dict, is_mensal: bool, styles: dict, UTIL_W: float):
    from reportlab.platypus import Table, Paragraph, TableStyle
    c   = _cores()
    lbl = _labels(metricas.get('tipo_negocio', 'retalho'))

    top_dict = metricas.get('top_produtos_mes', {}) if is_mensal else metricas.get('top_produtos', {})

    headers = [
        Paragraph(lbl['top5_col_ranking'], styles['table_hdr_c']),
        Paragraph(lbl['top5_col_item'],    styles['table_hdr']),
        Paragraph(lbl['top5_col_qty'],     styles['table_hdr_c']),
        Paragraph(lbl['top5_col_rel'],     styles['table_hdr_c']),
    ]
    rows = [headers]

    total_unidades_top = sum(top_dict.values()) if top_dict else 0

    for i, (item, qty) in enumerate(top_dict.items(), start=1):
        if i > 5:
            break
        relevancia = (qty / total_unidades_top) * 100 if total_unidades_top > 0 else 0
        rows.append([
            Paragraph(f'{i}.',                          styles['table_cell_c']),
            Paragraph(str(item).strip().title(),        styles['table_cell']),
            Paragraph(str(int(qty)),                    styles['table_cell_c']),
            Paragraph(f'{relevancia:.1f}% do Top 5',   styles['table_cell_c']),
        ])

    if len(rows) == 1:
        rows.append([
            Paragraph('-',                               styles['table_cell_c']),
            Paragraph('Nenhum dado encontrado',          styles['table_cell']),
            Paragraph('0',                               styles['table_cell_c']),
            Paragraph('0.0%',                            styles['table_cell_c']),
        ])

    t = Table(rows, colWidths=[UTIL_W * 0.12, UTIL_W * 0.48, UTIL_W * 0.18, UTIL_W * 0.22])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0),  c['PRIMARY']),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [c['WHITE'], c['LIGHT_GREY']]),
        ('BOX',           (0, 0), (-1, -1), 0.75, c['PRIMARY']),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5,  c['DIVIDER']),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def _actionable_insights(metricas: dict, is_mensal: bool, styles: dict, UTIL_W: float):
    from reportlab.platypus import Table, Paragraph, TableStyle
    c   = _cores()
    lbl = _labels(metricas.get('tipo_negocio', 'retalho'))

    top_dict = metricas.get('top_produtos_mes', {}) if is_mensal else metricas.get('top_produtos', {})

    sem_dados = not top_dict or list(top_dict.keys())[0] in (
        "Nenhum produto detetado", "Nenhum servico detetado", "Sem dados validos"
    )

    if sem_dados:
        insights_texto = (
            "<b>Recomendacao de Gestao:</b> Volume analitico insuficiente para este periodo. "
            "Recomenda-se assegurar a exportacao correta dos registos nas proximas submissoes."
        )
    else:
        top_1 = list(top_dict.keys())[0].strip().upper()
        insights_texto = (
            f"<b>Recomendacao de Gestao:</b> O {lbl['insight_item']} <b>{top_1}</b> detém o maior "
            f"volume do periodo. {lbl['insight_acao']}"
        )

    t = Table([[Paragraph(insights_texto, styles['alert_p'])]], colWidths=[UTIL_W])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), c['ALERT_BG']),
        ('BOX',           (0, 0), (-1, -1), 1, c['ALERT_TXT']),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING',   (0, 0), (-1, -1), 12),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 12),
    ]))
    return t


def gerar_relatorio(
    metricas: dict,
    nome_negocio: str = "O meu negocio",
    output_dir: str = 'data/gold',
    semana_label: str = None,
    is_diario: bool = False,
    tipo_negocio: str = None,          # NOVO: se None, usa metricas["tipo_negocio"] ou "retalho"
) -> str:
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    import gc

    # Resolve tipo_negocio: argumento explicito > metricas > default
    tipo = (tipo_negocio or metricas.get('tipo_negocio') or 'retalho').lower()
    # Garante que as metricas tambem trazem o tipo para as funcoes auxiliares
    metricas = {**metricas, 'tipo_negocio': tipo}

    lbl = _labels(tipo)

    os.makedirs(output_dir, exist_ok=True)

    PAGE_W, PAGE_H, MARGIN, UTIL_W = _dims()
    c      = _cores()
    styles = _styles()

    is_mensal = (metricas.get('total') == metricas.get('total_mensal'))

    if semana_label and (semana_label.startswith("report_") or "_" in semana_label):
        filename_final = semana_label if semana_label.endswith(".pdf") else f"{semana_label}.pdf"
        if is_diario:
            periodo_visual = f"Relatorio Diario - {date.today().strftime('%d/%m/%Y')}"
        else:
            periodo_visual = f"Periodo Comercial ate {date.today().strftime('%d/%m/%Y')}"
    else:
        nome_ficheiro_limpo = nome_negocio.lower().replace(' ', '_')
        filename_final  = f"InsightZone_{nome_ficheiro_limpo}_estrategico.pdf"
        if is_diario:
            periodo_visual = f"Relatorio Diario - {date.today().strftime('%d/%m/%Y')}"
        else:
            periodo_visual = semana_label if semana_label else (
                f"Mes de {metricas.get('mes_nome', 'Junho')}" if is_mensal
                else f"Semana Comercial ate {date.today().strftime('%d/%m/%Y')}"
            )

    pdf_path = os.path.join(output_dir, filename_final)
    story = []

    # Cabecalho
    story.append(Paragraph(nome_negocio.upper(), styles['biz_name']))
    story.append(Paragraph(f"Relatorio de Direccao e Analise Estrategica  |  {periodo_visual}", styles['meta_sub']))
    story.append(Paragraph(f"Emitido em: {datetime.now().strftime('%d/%m/%Y %H:%M')} por InsightZone Core Engine", styles['meta_sub']))
    story.append(Spacer(1, 8 * mm))

    # Divisoria
    divider = Table([['']], colWidths=[UTIL_W], rowHeights=[1.5])
    divider.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), c['PRIMARY'])]))
    story.append(divider)
    story.append(Spacer(1, 4 * mm))

    # SECCAO DIARIA
    tem_metricas_diarias = any([
        metricas.get('produto_do_dia'),
        metricas.get('hora_pico'),
        metricas.get('variacao_ontem') is not None,
    ])

    if is_diario and tem_metricas_diarias:
        story.append(Paragraph("I. Destaques do Dia", styles['section_title']))
        story.append(_daily_highlights(metricas, styles, UTIL_W))
        story.append(Spacer(1, 4 * mm))
        num_kpi = "II"
        num_top = "III"
        num_dir = "IV"
    else:
        num_kpi = "I"
        num_top = "II"
        num_dir = "III"

    story.append(Paragraph(f"{num_kpi}. Indicadores Vitais de Desempenho", styles['section_title']))
    story.append(_kpi_block(metricas, is_mensal, styles, UTIL_W))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph(f"{num_top}. {lbl['top5_titulo']}", styles['section_title']))
    story.append(_performance_table(metricas, is_mensal, styles, UTIL_W))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph(f"{num_dir}. Directrizes Operacionais Sugeridas", styles['section_title']))
    story.append(_actionable_insights(metricas, is_mensal, styles, UTIL_W))
    story.append(Spacer(1, 8 * mm))

    # Rodape
    story.append(Spacer(1, 5 * mm))
    story.append(Table([['']], colWidths=[UTIL_W], rowHeights=[0.5],
                       style=[('BACKGROUND', (0, 0), (-1, -1), c['DIVIDER'])]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "Este documento contem dados proprietarios e estrategicos obtidos via integracao de sistemas. Classificacao: Confidencial.",
        styles['footer']
    ))

    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN
    )
    doc.build(story)

    del story
    gc.collect()

    print(f'Relatorio gerado: {pdf_path}')
    return pdf_path