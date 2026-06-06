import os
from datetime import datetime, date

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

# ── PALETA DE CORES EXECUTIVA E CORPORATIVA (SLATE & NAVY) ────────────────────
PRIMARY    = colors.HexColor('#1E293B')   
ACCENT     = colors.HexColor('#0F766E')   
DIVIDER    = colors.HexColor('#CBD5E1')   
LIGHT_GREY = colors.HexColor('#F8FAFC')   
MID_GREY   = colors.HexColor('#64748B')   
WHITE      = colors.white                 
BLACK      = colors.HexColor('#0F172A')   
ALERT_BG   = colors.HexColor('#FEF3C7')   
ALERT_TXT  = colors.HexColor('#92400E')   

# ── DIMENSÕES DA PÁGINA (Padrão ISO A4) ───────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN = 15 * mm                          
UTIL_W = PAGE_W - (2 * MARGIN)            

def _styles():
    """Centraliza a tipografia e os estilos de parágrafo reutilizados no documento."""
    return {
        'biz_name': ParagraphStyle(
            'biz_name', fontName='Helvetica-Bold', fontSize=18,
            textColor=PRIMARY, alignment=TA_LEFT, spaceAfter=2
        ),
        'meta_sub': ParagraphStyle(
            'meta_sub', fontName='Helvetica', fontSize=9,
            textColor=MID_GREY, alignment=TA_LEFT, spaceAfter=1
        ),
        'section_title': ParagraphStyle(
            'section_title', fontName='Helvetica-Bold', fontSize=12,
            textColor=PRIMARY, spaceAfter=6, spaceBefore=12,
            keepWithNext=True  # CORREÇÃO: Junta o título à tabela subsequente prevenindo órfãos
        ),
        'kpi_lbl': ParagraphStyle('kpi_lbl', fontName='Helvetica', fontSize=8, textColor=MID_GREY, alignment=TA_CENTER),
        'kpi_val': ParagraphStyle('kpi_val', fontName='Helvetica-Bold', fontSize=11, textColor=PRIMARY, alignment=TA_CENTER),
        
        'table_hdr': ParagraphStyle('table_hdr', fontName='Helvetica-Bold', fontSize=9, textColor=WHITE, alignment=TA_LEFT),
        'table_hdr_c': ParagraphStyle('table_hdr_c', fontName='Helvetica-Bold', fontSize=9, textColor=WHITE, alignment=TA_CENTER),
        'table_cell': ParagraphStyle(
            'table_cell', fontName='Helvetica', fontSize=9, textColor=BLACK, alignment=TA_LEFT,
            wordWrap='CJK'  # CORREÇÃO: Garante auto-quebra em strings contínuas/longas
        ),
        'table_cell_c': ParagraphStyle(
            'table_cell_c', fontName='Helvetica', fontSize=9, textColor=BLACK, alignment=TA_CENTER,
            wordWrap='CJK'
        ),
        
        'alert_p': ParagraphStyle('alert_p', fontName='Helvetica', fontSize=9.5, textColor=ALERT_TXT, alignment=TA_JUSTIFY, leading=13),
        'footer': ParagraphStyle('footer', fontName='Helvetica', fontSize=8, textColor=MID_GREY, alignment=TA_CENTER),
    }

def _fmt_mzn(val: float) -> str:
    return f'MZN {val:,.2f}'

def _kpi_block(metricas: dict, is_mensal: bool):
    if is_mensal:
        total = metricas.get('total_mensal', 0)
        trans = metricas.get('transacoes_mensal', 1)
        ticket = metricas.get('ticket_medio_mensal', 0)
        melhor_dia = metricas.get('melhor_dia_mes', '—')
    else:
        total = metricas.get('total', 0)
        trans = metricas.get('total_transacoes', 1)
        ticket = metricas.get('ticket_medio', 0)
        melhor_dia = metricas.get('melhor_dia', '—')

    kpis = [
        ('FATURAÇÃO TOTAL', _fmt_mzn(total)),
        ('TRANSAÇÕES', str(trans)),
        ('TICKET MÉDIO', _fmt_mzn(ticket)),
        ('PICO DE VENDAS', str(melhor_dia)),
    ]

    styles = _styles()
    header_cells = [Paragraph(lbl, styles['kpi_lbl']) for lbl, _ in kpis]
    value_cells  = [Paragraph(val, styles['kpi_val']) for _, val in kpis]

    col_w = UTIL_W / 4
    # CORREÇÃO: Eliminado 'rowHeights' estático para permitir cálculo elástico do motor
    t = Table([header_cells, value_cells], colWidths=[col_w] * 4)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_GREY),
        ('BOX',        (0, 0), (-1, -1), 0.75, DIVIDER),
        ('INNERGRID',  (0, 0), (-1, -1), 0.5, DIVIDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t

def _performance_table(metricas: dict, is_mensal: bool):
    top_dict = metricas.get('top_produtos_mes', {}) if is_mensal else metricas.get('top_produtos', {})
    styles = _styles()
    headers = [
        Paragraph('Ranking', styles['table_hdr_c']),
        Paragraph('Produto Líder', styles['table_hdr']),
        Paragraph('Qtd Vendida', styles['table_hdr_c']),
        Paragraph('% Relevância Comercial', styles['table_hdr_c'])
    ]
    rows = [headers]
    
    total_unidades_top = sum(top_dict.values()) if top_dict else 0
    
    for i, (produto, qty) in enumerate(top_dict.items(), start=1):
        if i > 5: 
            break
        relevancia = (qty / total_unidades_top) * 100 if total_unidades_top > 0 else 0
        
        rows.append([
            Paragraph(f'{i}º', styles['table_cell_c']),
            Paragraph(str(produto).strip().title(), styles['table_cell']),
            Paragraph(str(int(qty)), styles['table_cell_c']),
            Paragraph(f'{relevancia:.1f}% do Top 5', styles['table_cell_c']),
        ])

    if len(rows) == 1:
        rows.append([Paragraph('—', styles['table_cell_c']), Paragraph('Nenhum dado encontrado', styles['table_cell']), Paragraph('0', styles['table_cell_c']), Paragraph('0.0%', styles['table_cell_c'])])

    # CORREÇÃO: Proporções exatas de colunas que totalizam 1.0 (100% de UTIL_W)
    t = Table(rows, colWidths=[UTIL_W * 0.12, UTIL_W * 0.48, UTIL_W * 0.18, UTIL_W * 0.22])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0),  PRIMARY),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ('BOX',           (0, 0), (-1, -1), 0.75, PRIMARY),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, DIVIDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t

def _actionable_insights(metricas: dict, is_mensal: bool):
    top_dict = metricas.get('top_produtos_mes', {}) if is_mensal else metricas.get('top_produtos', {})
    styles = _styles()
    
    if not top_dict or list(top_dict.keys())[0] == "Nenhum produto detetado":
        insights_texto = (
            "<b>Recomendação de Gestão:</b> Volume analítico de produtos insuficiente para este período. "
            "Recomenda-se assegurar a exportação correta das linhas comerciais nas próximas submissões."
        )
    else:
        produtos = list(top_dict.keys())
        top_1 = produtos[0].strip().upper()
        insights_texto = (
            f"<b>Recomendação de Gestão:</b> O produto <b>{top_1}</b> detém o maior volume de saída do período. "
            "Recomenda-se auditar o nível crítico de inventário com os vossos fornecedores para blindar o canal contra ruturas. "
            "Estrategicamente, considere arquitetar um pacote promocional casando este produto líder com os itens de menor tração, "
            "permitindo girar o stock de menor liquidez e expandir o Ticket Médio das transações."
        )

    t = Table([[Paragraph(insights_texto, styles['alert_p'])]], colWidths=[UTIL_W])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), ALERT_BG),
        ('BOX',        (0, 0), (-1, -1), 1, ALERT_TXT),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING',  (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    return t

def gerar_relatorio(metricas: dict, nome_negocio: str = "O meu negocio", output_dir: str = 'data/gold', semana_label: str = None) -> str:
    """
    CORREÇÃO COMPATIBILIDADE SÉNIOR:
    Para respeitar a assinatura original do MVP sem quebras, se o 'semana_label' 
    contiver a string estruturada de transação única (gerada no app.py), usamos esse nome diretamente.
    """
    os.makedirs(output_dir, exist_ok=True)
    is_mensal = (metricas.get('total') == metricas.get('total_mensal'))
    
    if semana_label and (semana_label.startswith("report_") or "_" in semana_label):
        filename_final = semana_label if semana_label.endswith(".pdf") else f"{semana_label}.pdf"
        periodo_visual = f"Período Comercial até {date.today().strftime('%d/%m/%Y')}"
    else:
        nome_ficheiro_limpo = nome_negocio.lower().replace(' ', '_')
        filename_final = f"InsightZone_{nome_ficheiro_limpo}_estrategico.pdf"
        periodo_visual = semana_label if semana_label else (f"Mês de {metricas.get('mes_nome', 'Junho')}" if is_mensal else f"Semana Comercial até {date.today().strftime('%d/%m/%Y')}")

    pdf_path = os.path.join(output_dir, filename_final)
    styles = _styles()
    story = []

    # Cabeçalho
    story.append(Paragraph(nome_negocio.upper(), styles['biz_name']))
    story.append(Paragraph(f"Relatório de Direção e Análise Estratégica  |  {periodo_visual}", styles['meta_sub']))
    story.append(Paragraph(f"Emitido em: {datetime.now().strftime('%d/%m/%Y %H:%M')} por InsightZone Core Engine", styles['meta_sub']))
    story.append(Spacer(1, 5 * mm))

    # Divisória
    divider = Table([['']], colWidths=[UTIL_W], rowHeights=[1.5])
    divider.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), PRIMARY)]))
    story.append(divider)
    story.append(Spacer(1, 4 * mm))

    # Blocos de Conteúdo
    story.append(Paragraph("I. Indicadores Vitais de Desempenho", styles['section_title']))
    story.append(_kpi_block(metricas, is_mensal))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("II. Análise de Escoamento e Mix (Top 5)", styles['section_title']))
    story.append(_performance_table(metricas, is_mensal))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("III. Diretrizes Operacionais Sugeridas", styles['section_title']))
    story.append(_actionable_insights(metricas, is_mensal))
    story.append(Spacer(1, 8 * mm))

    # Rodapé
    story.append(Spacer(1, 5 * mm))
    story.append(Table([['']], colWidths=[UTIL_W], rowHeights=[0.5], style=[('BACKGROUND', (0, 0), (-1, -1), DIVIDER)]))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph("Este documento contém dados proprietários e estratégicos obtidos via integração de sistemas. Classificação: Confidencial.", styles['footer']))

    # Compilação Multi-página Segura
    doc = SimpleDocTemplate(pdf_path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN)
    doc.build(story)

    print(f'Relatório Imutável Gerado: {pdf_path}')
    return pdf_path