import os
from datetime import datetime, date

# ── IMPORTS LAZY: ReportLab só é carregado quando gerar_relatorio() é chamado.
# Em modo standby o processo não ocupa a memória das bibliotecas de renderização.
# (Aprox. 15–20 MB poupados por worker inactivo.)


# ── PALETA DE CORES ───────────────────────────────────────────────────────────
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
    }


# ── DIMENSÕES ─────────────────────────────────────────────────────────────────
def _dims():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    PAGE_W, PAGE_H = A4
    MARGIN = 15 * mm
    return PAGE_W, PAGE_H, MARGIN, PAGE_W - (2 * MARGIN)


# ── ESTILOS (construídos uma vez por chamada a gerar_relatorio) ───────────────
def _styles():
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    c = _cores()
    return {
        'biz_name':     ParagraphStyle('biz_name',     fontName='Helvetica-Bold', fontSize=18, leading=22,  textColor=c['PRIMARY'],   alignment=TA_LEFT,    spaceAfter=4),
        'meta_sub':     ParagraphStyle('meta_sub',     fontName='Helvetica',      fontSize=9,  leading=12,  textColor=c['MID_GREY'],  alignment=TA_LEFT,    spaceAfter=2),
        'section_title':ParagraphStyle('section_title',fontName='Helvetica-Bold', fontSize=12, leading=15,  textColor=c['PRIMARY'],   spaceAfter=6, spaceBefore=12, keepWithNext=True),
        'kpi_lbl':      ParagraphStyle('kpi_lbl',      fontName='Helvetica',      fontSize=8,                textColor=c['MID_GREY'],  alignment=TA_CENTER),
        'kpi_val':      ParagraphStyle('kpi_val',      fontName='Helvetica-Bold', fontSize=11,               textColor=c['PRIMARY'],   alignment=TA_CENTER),
        'table_hdr':    ParagraphStyle('table_hdr',    fontName='Helvetica-Bold', fontSize=9,                textColor=c['WHITE'],     alignment=TA_LEFT),
        'table_hdr_c':  ParagraphStyle('table_hdr_c',  fontName='Helvetica-Bold', fontSize=9,                textColor=c['WHITE'],     alignment=TA_CENTER),
        'table_cell':   ParagraphStyle('table_cell',   fontName='Helvetica',      fontSize=9,                textColor=c['BLACK'],     alignment=TA_LEFT,    wordWrap='CJK'),
        'table_cell_c': ParagraphStyle('table_cell_c', fontName='Helvetica',      fontSize=9,                textColor=c['BLACK'],     alignment=TA_CENTER,  wordWrap='CJK'),
        'alert_p':      ParagraphStyle('alert_p',      fontName='Helvetica',      fontSize=9.5, leading=13,  textColor=c['ALERT_TXT'], alignment=TA_JUSTIFY),
        'footer':       ParagraphStyle('footer',       fontName='Helvetica',      fontSize=8,                textColor=c['MID_GREY'],  alignment=TA_CENTER),
    }


def _fmt_mzn(val: float) -> str:
    return f'MZN {val:,.2f}'


def _kpi_block(metricas: dict, is_mensal: bool, styles: dict, UTIL_W: float):
    from reportlab.platypus import Table, Paragraph
    from reportlab.platypus import TableStyle
    c = _cores()

    if is_mensal:
        total     = metricas.get('total_mensal', 0)
        trans     = metricas.get('transacoes_mensal', 1)
        ticket    = metricas.get('ticket_medio_mensal', 0)
        melhor_dia = metricas.get('melhor_dia_mes', '—')
    else:
        total     = metricas.get('total', 0)
        trans     = metricas.get('total_transacoes', 1)
        ticket    = metricas.get('ticket_medio', 0)
        melhor_dia = metricas.get('melhor_dia', '—')

    kpis = [
        ('FATURAÇÃO TOTAL', _fmt_mzn(total)),
        ('TRANSAÇÕES',      str(trans)),
        ('TICKET MÉDIO',    _fmt_mzn(ticket)),
        ('PICO DE VENDAS',  str(melhor_dia)),
    ]

    header_cells = [Paragraph(lbl, styles['kpi_lbl']) for lbl, _ in kpis]
    value_cells  = [Paragraph(val, styles['kpi_val']) for _, val in kpis]

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


def _performance_table(metricas: dict, is_mensal: bool, styles: dict, UTIL_W: float):
    from reportlab.platypus import Table, Paragraph
    from reportlab.platypus import TableStyle
    c = _cores()

    top_dict = metricas.get('top_produtos_mes', {}) if is_mensal else metricas.get('top_produtos', {})

    headers = [
        Paragraph('Ranking',                styles['table_hdr_c']),
        Paragraph('Produto Líder',           styles['table_hdr']),
        Paragraph('Qtd Vendida',             styles['table_hdr_c']),
        Paragraph('% Relevância Comercial',  styles['table_hdr_c']),
    ]
    rows = [headers]

    total_unidades_top = sum(top_dict.values()) if top_dict else 0

    for i, (produto, qty) in enumerate(top_dict.items(), start=1):
        if i > 5:
            break
        relevancia = (qty / total_unidades_top) * 100 if total_unidades_top > 0 else 0
        rows.append([
            Paragraph(f'{i}º',                             styles['table_cell_c']),
            Paragraph(str(produto).strip().title(),        styles['table_cell']),
            Paragraph(str(int(qty)),                       styles['table_cell_c']),
            Paragraph(f'{relevancia:.1f}% do Top 5',       styles['table_cell_c']),
        ])

    if len(rows) == 1:
        rows.append([
            Paragraph('—',                       styles['table_cell_c']),
            Paragraph('Nenhum dado encontrado',  styles['table_cell']),
            Paragraph('0',                       styles['table_cell_c']),
            Paragraph('0.0%',                    styles['table_cell_c']),
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
    from reportlab.platypus import Table, Paragraph
    from reportlab.platypus import TableStyle
    c = _cores()

    top_dict = metricas.get('top_produtos_mes', {}) if is_mensal else metricas.get('top_produtos', {})

    if not top_dict or list(top_dict.keys())[0] == "Nenhum produto detetado":
        insights_texto = (
            "<b>Recomendação de Gestão:</b> Volume analítico de produtos insuficiente para este período. "
            "Recomenda-se assegurar a exportação correta das linhas comerciais nas próximas submissões."
        )
    else:
        top_1 = list(top_dict.keys())[0].strip().upper()
        insights_texto = (
            f"<b>Recomendação de Gestão:</b> O produto <b>{top_1}</b> detém o maior volume de saída do período. "
            "Recomenda-se auditar o nível crítico de inventário com os vossos fornecedores para blindar o canal contra ruturas. "
            "Estrategicamente, considere arquitetar um pacote promocional casando este produto líder com os itens de menor tração, "
            "permitindo girar o stock de menor liquidez e expandir o Ticket Médio das transações."
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
    semana_label: str = None
) -> str:
    # Imports lazy: só aqui é que ReportLab entra em memória
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
    from reportlab.platypus import TableStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    os.makedirs(output_dir, exist_ok=True)

    PAGE_W, PAGE_H, MARGIN, UTIL_W = _dims()
    c = _cores()
    styles = _styles()   # construído uma única vez para todo o documento

    is_mensal = (metricas.get('total') == metricas.get('total_mensal'))

    if semana_label and (semana_label.startswith("report_") or "_" in semana_label):
        filename_final  = semana_label if semana_label.endswith(".pdf") else f"{semana_label}.pdf"
        periodo_visual  = f"Período Comercial até {date.today().strftime('%d/%m/%Y')}"
    else:
        nome_ficheiro_limpo = nome_negocio.lower().replace(' ', '_')
        filename_final  = f"InsightZone_{nome_ficheiro_limpo}_estrategico.pdf"
        periodo_visual  = semana_label if semana_label else (
            f"Mes de {metricas.get('mes_nome', 'Junho')}" if is_mensal
            else f"Semana Comercial até {date.today().strftime('%d/%m/%Y')}"
        )

    pdf_path = os.path.join(output_dir, filename_final)
    story = []

    # Cabeçalho
    story.append(Paragraph(nome_negocio.upper(), styles['biz_name']))
    story.append(Paragraph(f"Relatório de Direção e Análise Estratégica  |  {periodo_visual}", styles['meta_sub']))
    story.append(Paragraph(f"Emitido em: {datetime.now().strftime('%d/%m/%Y %H:%M')} por InsightZone Core Engine", styles['meta_sub']))
    story.append(Spacer(1, 8 * mm))

    # Divisória
    divider = Table([['']], colWidths=[UTIL_W], rowHeights=[1.5])
    divider.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), c['PRIMARY'])]))
    story.append(divider)
    story.append(Spacer(1, 4 * mm))

    # Conteúdo
    story.append(Paragraph("I. Indicadores Vitais de Desempenho", styles['section_title']))
    story.append(_kpi_block(metricas, is_mensal, styles, UTIL_W))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("II. Análise de Escoamento e Mix (Top 5)", styles['section_title']))
    story.append(_performance_table(metricas, is_mensal, styles, UTIL_W))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("III. Directrizes Operacionais Sugeridas", styles['section_title']))
    story.append(_actionable_insights(metricas, is_mensal, styles, UTIL_W))
    story.append(Spacer(1, 8 * mm))

    # Rodapé
    story.append(Spacer(1, 5 * mm))
    story.append(Table([['']], colWidths=[UTIL_W], rowHeights=[0.5],
                       style=[('BACKGROUND', (0, 0), (-1, -1), c['DIVIDER'])]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "Este documento contém dados proprietários e estratégicos obtidos via integração de sistemas. Classificação: Confidencial.",
        styles['footer']
    ))

    doc = SimpleDocTemplate(
        pdf_path, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN
    )
    doc.build(story)

    # Liberta a lista story (pode incluir buffers de imagem internos do ReportLab)
    del story
    import gc
    gc.collect()

    print(f'Relatório gerado: {pdf_path}')
    return pdf_path