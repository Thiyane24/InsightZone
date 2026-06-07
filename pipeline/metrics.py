import gc
import pandas as pd
from datetime import datetime


def calcular_metricas(df: pd.DataFrame, frequencia_cliente: str = "semanal") -> dict:

    # 1. NORMALIZAÇÃO DE COLUNAS
    df.columns = [col.lower().strip() for col in df.columns]

    # 2. MAPEAMENTO DINÂMICO DE COLUNAS
    col_data    = next((c for c in df.columns if 'data' in c or 'date' in c), None)
    col_total   = next((c for c in df.columns if 'total' in c or 'revenue' in c or 'faturac' in c or 'valor' in c), None)
    col_produto = next((c for c in df.columns if 'prod' in c or 'item' in c), None)
    col_qtd     = next((c for c in df.columns if 'qtd' in c or 'quant' in c or 'qty' in c), None)

    # 3. FALLBACK: recalcula total a partir de preço × quantidade
    if not col_total and col_qtd:
        col_preco = next((c for c in df.columns if 'prec' in c or 'price' in c), None)
        if col_preco:
            df['total_calculado'] = (
                pd.to_numeric(df[col_preco], errors='coerce').fillna(0)
                * pd.to_numeric(df[col_qtd], errors='coerce').fillna(0)
            )
            col_total = 'total_calculado'

    # 4. PARSING DE DATAS
    #  criar coluna de fallback antes de tentar usá-la
    if col_data:
        df[col_data] = pd.to_datetime(df[col_data], errors='coerce')
        df = df.dropna(subset=[col_data])
        # Se ficou vazio depois do dropna, usa fallback
        if df.empty:
            df = df.copy()
            col_data = None

    if not col_data:
        df = df.copy()
        df['data_fallback'] = pd.Timestamp(datetime.now().date())
        col_data = 'data_fallback'

    # 5. TIPOS NUMÉRICOS
    if col_total:
        df[col_total] = pd.to_numeric(df[col_total], errors='coerce').fillna(0.0)
    else:
        df['total_zero'] = 0.0
        col_total = 'total_zero'

    if col_qtd:
        df[col_qtd] = pd.to_numeric(df[col_qtd], errors='coerce').fillna(1)
    else:
        df['qtd_um'] = 1
        col_qtd = 'qtd_um'

    # 6. KPIs CORE
    total_faturado   = float(df[col_total].sum())
    col_id           = next((c for c in df.columns if c in ('id', 'fatura', 'recibo', 'order_id', 'invoice')), None)
    total_transacoes = int(df[col_id].nunique()) if col_id else int(len(df))

    vendas_por_dia = df.groupby(df[col_data].dt.date)[col_total].sum()
    melhor_dia_str = (
        vendas_por_dia.idxmax().strftime('%Y-%m-%d')
        if not vendas_por_dia.empty
        else datetime.now().strftime('%Y-%m-%d')
    )

    # 7. TOP PRODUTOS converter para tipos Python nativos antes de libertar o df
    if col_produto:
        top_produtos_dict = (
            df.groupby(col_produto)[col_qtd]
              .sum()
              .sort_values(ascending=False)
              .head(5)
              .to_dict()
        )
        top_produtos_dict = {str(k): int(v) for k, v in top_produtos_dict.items()}
    else:
        top_produtos_dict = {"Nenhum produto detetado": 0}

    # 8. MÉTRICAS AVANÇADAS
    mes_nome     = datetime.now().strftime('%B')
    ticket_medio = total_faturado / total_transacoes if total_transacoes > 0 else 0.0

    # 9. LIBERTAÇÃO EXPLÍCITA DA MEMÓRIA
    del df
    gc.collect()

    return {
        "total":               total_faturado,
        "total_transacoes":    total_transacoes,
        "ticket_medio":        ticket_medio,
        "melhor_dia":          melhor_dia_str,
        "top_produtos":        top_produtos_dict,

        # Aliases mensais (compatibilidade com report.py)
        "total_mensal":        total_faturado,
        "transacoes_mensal":   total_transacoes,
        "ticket_medio_mensal": ticket_medio,
        "melhor_dia_mes":      melhor_dia_str,
        "top_produtos_mes":    top_produtos_dict,
        "mes_nome":            mes_nome,

        "variacao_pct": None,
    }