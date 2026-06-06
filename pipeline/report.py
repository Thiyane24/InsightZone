import os
from datetime import datetime, date

import matplotlib
matplotlib.use('Agg')  
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT


# Paleta de cores
ACCENT     = colors.HexColor('#2C3E50')   
DIVIDER    = colors.HexColor('#BDC3C7')   
LIGHT_GREY = colors.HexColor('#F7F7F7')   
MID_GREY   = colors.HexColor('#7F8C8D')   
WHITE      = colors.white
BLACK      = colors.HexColor('#1A1A1A')
BAR_COLOUR = '#5B6E7C'                    
POS_COLOUR = '#27AE60'                    
NEG_COLOUR = '#C0392B'                    

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm


# Styles 
def _styles():
    return {
        'header_business': ParagraphStyle(
            'header_business',
            fontName='Helvetica-Bold', fontSize=16,
            textColor=ACCENT, alignment=TA_CENTER, spaceAfter=2
        ),
        'header_sub': ParagraphStyle(
            'header_sub',
            fontName='Helvetica', fontSize=10,
            textColor=MID_GREY, alignment=TA_CENTER, spaceAfter=1
        ),
        'insight': ParagraphStyle(
            'insight',
            fontName='Helvetica-Oblique', fontSize=11,
            textColor=ACCENT, alignment=TA_CENTER,
            spaceAfter=6, spaceBefore=4
        ),
        'section_title': ParagraphStyle(
            'section_title',
            fontName='Helvetica-Bold', fontSize=11,
            textColor=ACCENT, spaceAfter=4, spaceBefore=8
        ),
        'footer': ParagraphStyle(
            'footer',
            fontName='Helvetica', fontSize=8,
            textColor=MID_GREY, alignment=TA_CENTER
        ),
        'top_item': ParagraphStyle(
            'top_item',
            fontName='Helvetica', fontSize=11,
            textColor=BLACK, spaceAfter=3, leftIndent=6
        ),
    }


# Helpers 
def _semana_label() -> str:
    """Retorna exemplo 'Semana 02–08 Jun 2026'"""
    today = date.today()
    start = today.strftime('%d')
    month = today.strftime('%b %Y')
    return f'Semana até {start} {month}'


def _insight_phrase(metricas: dict) -> str:
    """Generates the single most important insight sentence."""
    total = metricas['total']
    melhor = metricas['melhor_dia']
    top = metricas['top_produtos']
    top_nome = top.index[0] if len(top) > 0 else '—'

    variacao = metricas.get('variacao_pct')
    if variacao is not None:
        sinal = '+' if variacao >= 0 else ''
        return (
            f'Vendas {sinal}{variacao:.1f}% vs semana passada — '
            f'melhor dia foi {melhor} com {top_nome} a liderar.'
        )
    return (
        f'Total de {_fmt_currency(total)} esta semana — '
        f'melhor dia foi {melhor} e o produto mais vendido foi {top_nome}.'
    )


def _fmt_currency(value: float) -> str:
    return f'MZN {value:,.2f}'


def _kpi_table(metricas: dict, styles: dict):
    """4-KPI row: total, transacções, melhor dia, top produto."""
    top_nome = metricas['top_produtos'].index[0] if len(metricas['top_produtos']) > 0 else '—'

    kpis = [
        ('Revenue total', _fmt_currency(metricas['total'])),
        ('Transaccoes', str(metricas['total_transacoes'])),
        ('Melhor dia', str(metricas['melhor_dia'])),
        ('Top produto', str(top_nome)),
    ]

    label_style = ParagraphStyle('kpi_label', fontName='Helvetica', fontSize=9,
                                  textColor=MID_GREY, alignment=TA_CENTER)
    value_style = ParagraphStyle('kpi_value', fontName='Helvetica-Bold', fontSize=15,
                                  textColor=ACCENT, alignment=TA_CENTER)

    header_cells = [Paragraph(label, label_style) for label, _ in kpis]
    value_cells  = [Paragraph(val,   value_style)  for _, val   in kpis]

    col_w = (PAGE_W - 2 * MARGIN) / 4
    t = Table([header_cells, value_cells], colWidths=[col_w] * 4, rowHeights=[14, 22])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_GREY),
        ('BOX',        (0, 0), (-1, -1), 0.5, DIVIDER),
        ('INNERGRID',  (0, 0), (-1, -1), 0.5, DIVIDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING',   (0, 0), (-1, -1), 4),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
    ]))
    return t


def _bar_chart(metricas: dict, output_path: str) -> str:
    """Renders vendas por dia as a bar chart. Returns the image path."""
    vendas = metricas['vendas_por_dia']

    fig, ax = plt.subplots(figsize=(6.5, 2.6), dpi=100)
    bars = ax.bar(
        [str(d) for d in vendas.index],
        vendas.values,
        color=BAR_COLOUR,
        width=0.55,
        edgecolor='none'
    )

    # Value labels on top of each bar
    for bar in bars:
        h = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2, h + max(vendas.values) * 0.01,
            f'{h:,.0f}', ha='center', va='bottom', fontsize=8, color='#333333'
        )

    ax.set_ylabel('MZN', fontsize=9, color='#555555')
    ax.tick_params(axis='x', labelsize=8, colors='#333333', rotation=15)
    ax.tick_params(axis='y', labelsize=8, colors='#888888')
    ax.yaxis.grid(True, linestyle='--', alpha=0.4, color='#CCCCCC')
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)

    fig.tight_layout(pad=0.5)
    fig.savefig(output_path, dpi=100, bbox_inches='tight')
    plt.close(fig)
    return output_path


def _top_produtos_table(metricas: dict):
    """Simple two-column table: rank + produto + quantidade."""
    top = metricas['top_produtos'].head(5)

    label_style = ParagraphStyle('tp_label', fontName='Helvetica-Bold', fontSize=9,
                                  textColor=WHITE, alignment=TA_CENTER)
    row_style   = ParagraphStyle('tp_row',   fontName='Helvetica', fontSize=10,
                                  textColor=BLACK)

    header = [
        Paragraph('#',          label_style),
        Paragraph('Produto',    label_style),
        Paragraph('Quantidade', label_style),
    ]
    rows = [header]
    for i, (produto, qty) in enumerate(top.items(), start=1):
        rows.append([
            Paragraph(str(i),       row_style),
            Paragraph(str(produto), row_style),
            Paragraph(str(int(qty) if qty == int(qty) else qty), row_style),
        ])

    col_w = PAGE_W - 2 * MARGIN
    t = Table(rows, colWidths=[col_w * 0.1, col_w * 0.65, col_w * 0.25])
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0),  ACCENT),
        ('BACKGROUND',    (0, 1), (-1, -1), LIGHT_GREY),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ('BOX',           (0, 0), (-1, -1), 0.5, DIVIDER),
        ('INNERGRID',     (0, 0), (-1, -1), 0.5, DIVIDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING',   (0, 0), (-1, -1), 8),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
        ('ALIGN',         (0, 0), (0, -1),  'CENTER'),
        ('ALIGN',         (2, 0), (2, -1),  'CENTER'),
    ]))
    return t


def _variacao_table(metricas: dict):
    """Comparação semana anterior — only rendered if variacao_pct exists."""
    variacao = metricas.get('variacao_pct')
    if variacao is None:
        return None

    sinal  = '+' if variacao >= 0 else ''
    cor    = POS_COLOUR if variacao >= 0 else NEG_COLOUR
    symbol = '+' if variacao >= 0 else '-'

    val_style = ParagraphStyle('var_val', fontName='Helvetica-Bold', fontSize=13,
                                textColor=colors.HexColor(cor), alignment=TA_CENTER)
    lbl_style = ParagraphStyle('var_lbl', fontName='Helvetica', fontSize=9,
                                textColor=MID_GREY, alignment=TA_CENTER)

    col_w = PAGE_W - 2 * MARGIN
    t = Table(
        [[Paragraph(f'{sinal}{variacao:.1f}%', val_style)],
         [Paragraph('vs semana anterior', lbl_style)]],
        colWidths=[col_w]
    )
    t.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, -1), LIGHT_GREY),
        ('BOX',           (0, 0), (-1, -1), 0.5, DIVIDER),
        ('TOPPADDING',    (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    return t


#  Main  function 
def gerar_relatorio(
    metricas: dict,
    nome_negocio: str,
    output_dir: str = 'data/gold',
    semana_label: str = None,
) -> str:
    """
    Builds the InsightZone PDF report.

    Args:
        metricas:      dict returned by calcular_metricas()
        nome_negocio:  client business name, e.g. 'Salão da Mayra'
        output_dir:    where to save the PDF (gold layer)
        semana_label:  optional override, e.g. 'Semana 02-08 Jun 2026'

    Returns:
        Absolute path to the generated PDF.
    """
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs('data/tmp', exist_ok=True)

    semana  = semana_label or _semana_label()
    hoje    = datetime.now().strftime('%d/%m/%Y %H:%M')
    slug    = nome_negocio.lower().replace(' ', '_')
    semana_slug = semana.replace(' ', '_').replace('/', '-')
    pdf_path   = os.path.join(output_dir, f'InsightZone_{slug}_{semana_slug}.pdf')
    chart_path = f'data/tmp/chart_{slug}.png'

    styles = _styles()
    story  = []

    # 1. Cabeçalho 
    story.append(Paragraph(nome_negocio, styles['header_business']))
    story.append(Paragraph(f'{semana}  •  Gerado em {hoje}', styles['header_sub']))
    story.append(Spacer(1, 4 * mm))

    # Divider line
    divider = Table([['']], colWidths=[PAGE_W - 2 * MARGIN], rowHeights=[1])
    divider.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), DIVIDER)]))
    story.append(divider)
    story.append(Spacer(1, 4 * mm))

    #  2. Frase de insight 
    story.append(Paragraph(_insight_phrase(metricas), styles['insight']))
    story.append(Spacer(1, 3 * mm))

    #  3. 4 KPIs 
    story.append(Paragraph('Resumo da semana', styles['section_title']))
    story.append(_kpi_table(metricas, styles))
    story.append(Spacer(1, 5 * mm))

    #  4. Gráfico de barras 
    story.append(Paragraph('Vendas por dia', styles['section_title']))
    _bar_chart(metricas, chart_path)
    chart_w = PAGE_W - 2 * MARGIN
    story.append(Image(chart_path, width=chart_w, height=chart_w * 0.4))
    story.append(Spacer(1, 5 * mm))

    # 5. Top 5 produtos 
    story.append(Paragraph('Top 5 produtos', styles['section_title']))
    story.append(_top_produtos_table(metricas))
    story.append(Spacer(1, 5 * mm))

    #  6. Comparação semana anterior 
    variacao_tbl = _variacao_table(metricas)
    if variacao_tbl:
        story.append(Paragraph('Comparação semana anterior', styles['section_title']))
        story.append(variacao_tbl)
        story.append(Spacer(1, 5 * mm))

    #  7. Rodapé 
    story.append(Spacer(1, 4 * mm))
    story.append(divider)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        f'{nome_negocio}  •  {semana}  •  Gerado pelo InsightZone',
        styles['footer']
    ))

    #  Build do pdf
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN,  bottomMargin=MARGIN,
    )
    doc.build(story)

    # Clean up temp chart file
    if os.path.exists(chart_path):
        os.remove(chart_path)

    print(f'Relatório gerado {pdf_path}')
    return pdf_path