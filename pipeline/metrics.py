import gc
import pandas as pd
from datetime import datetime


def _parse_numero_pt(serie: pd.Series) -> pd.Series:
    """
    Converte uma coluna de texto com formato PT (ponto de milhar, vírgula decimal)
    para float. Valores que não sejam convertíveis tornam-se NaN.
    Exemplo: "1.500,00" → 1500.0 | "vinte" → NaN | "N/A" → NaN
    """
    return (
        serie.astype(str)
             .str.strip()
             .str.replace(r'\.(?=\d{3})', '', regex=True)   # remove ponto de milhar
             .str.replace(',', '.', regex=False)             # vírgula → ponto decimal
             .pipe(lambda s: pd.to_numeric(s, errors='coerce'))
    )


def _parse_datas_robusto(serie: pd.Series) -> pd.Series:
    """
    Tenta múltiplos formatos de data em sequência, sem ambiguidade.
    Formatos suportados:
      YYYY-MM-DD  (ISO)
      DD/MM/YYYY  (PT)
      Month D, YYYY  (EN: "June 3, 2026")
      DD-MM-YYYY
    Datas inválidas (ex: "32/06/2026", "ontem") ficam NaT.
    """
    s = serie.astype(str).str.strip()
    resultado = pd.Series([pd.NaT] * len(s), dtype='datetime64[ns]', index=serie.index)

    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%B %d, %Y', '%d-%m-%Y'):
        mask = resultado.isna()
        if not mask.any():
            break
        tentativa = pd.to_datetime(s.where(mask), format=fmt, errors='coerce')
        resultado = resultado.fillna(tentativa)

    return resultado


def _validar_silver(df: pd.DataFrame, col_total: str, col_qtd: str | None) -> pd.DataFrame:
    """
    Rejeita linhas sujas ANTES de qualquer agregação.
    Chamado uma vez, logo após a detecção de colunas.
    """
    # 1. Remover linhas completamente vazias
    df = df.dropna(how='all')

    # 2. Remover linhas que são headers repetidos (copy/paste errado)
    col_id_raw = next((c for c in df.columns if c in ('id', 'fatura', 'recibo', 'order_id', 'invoice')), None)
    if col_id_raw:
        df = df[df[col_id_raw].astype(str).str.lower() != col_id_raw.lower()]

    # 3. Total — formato PT + rejeitar nulo, zero e negativo
    if col_total and col_total in df.columns:
        df[col_total] = _parse_numero_pt(df[col_total])
        df = df[df[col_total].notna()]
        df = df[df[col_total] > 0]

    # 4. Quantidade — rejeitar nulo e negativo (se coluna existir)
    if col_qtd and col_qtd in df.columns:
        df[col_qtd] = _parse_numero_pt(df[col_qtd])
        df = df[df[col_qtd].notna()]
        df = df[df[col_qtd] > 0]

    # 5. Rejeitar linhas sem produto nem total (linhas incompletas críticas)
    col_prod = next((c for c in df.columns if 'prod' in c or 'item' in c), None)
    if col_prod and col_total:
        df = df.dropna(subset=[col_prod, col_total])

    return df.reset_index(drop=True)


def calcular_metricas(df: pd.DataFrame, frequencia_cliente: str = "semanal") -> dict:

    # 1. NORMALIZAÇÃO DE COLUNAS
    df.columns = [col.lower().strip() for col in df.columns]

    # 2. MAPEAMENTO DINÂMICO DE COLUNAS
    col_data    = next((c for c in df.columns if 'data' in c or 'date' in c), None)
    col_total   = next((c for c in df.columns if 'total' in c or 'revenue' in c or 'faturac' in c or 'valor' in c), None)
    col_produto = next((c for c in df.columns if 'prod' in c or 'item' in c), None)
    col_qtd     = next((c for c in df.columns if 'qtd' in c or 'quant' in c or 'qty' in c), None)

    # 3. PREÇO UNITÁRIO — formato PT (antes do fallback de total)
    col_preco = next((c for c in df.columns if 'prec' in c or 'price' in c), None)
    if col_preco:
        df[col_preco] = _parse_numero_pt(df[col_preco])

    # 4. FALLBACK: recalcula total a partir de preço × quantidade
    if not col_total and col_qtd and col_preco:
        df['total_calculado'] = (
            df[col_preco].fillna(0) * _parse_numero_pt(df[col_qtd]).fillna(0)
        )
        col_total = 'total_calculado'

    # ── VALIDAÇÃO SILVER ─────────────────────────────────────────────────────
    # Corre ANTES de qualquer groupby/sum/cálculo.
    # Rejeita: texto em campos numéricos, negativos, zeros, linhas vazias,
    # headers repetidos, formato PT mal convertido.
    df = _validar_silver(df, col_total, col_qtd)

    if df.empty:
        return _resultado_vazio()
    # ─────────────────────────────────────────────────────────────────────────

    # 5. PARSING DE DATAS — múltiplos formatos, sem ambiguidade
    if col_data:
        df[col_data] = _parse_datas_robusto(df[col_data])
        df = df.dropna(subset=[col_data])
        # BUG 2 FIX: usar o ano mais recente presente nos dados
        # (não forçar o ano corrente — o ficheiro pode ser de um ano anterior)
        # Rejeita apenas datas com mais de 2 anos de diferença (dados claramente errados)
        ano_mais_recente = int(df[col_data].dt.year.max())
        df = df[df[col_data].dt.year >= ano_mais_recente - 1]
        if df.empty:
            col_data = None

    if not col_data:
        df['data_fallback'] = pd.Timestamp(datetime.now().date())
        col_data = 'data_fallback'

    # 6. TIPOS NUMÉRICOS FINAIS (Total e Qtd já foram limpos em _validar_silver)
    if not col_total:
        df['total_zero'] = 0.0
        col_total = 'total_zero'

    if not col_qtd:
        df['qtd_um'] = 1
        col_qtd = 'qtd_um'

    # 7. KPIs CORE
    total_faturado = float(df[col_total].sum())

    # BUG 1 FIX: contar transacções únicas, não linhas
    # Estratégia 1 — coluna de ID de venda explícita (ex: 'id', 'fatura', 'recibo')
    # Estratégia 2 — agrupar por data + vendedor se existir coluna de vendedor
    # Estratégia 3 — fallback: contar linhas (cada linha = 1 item de 1 transacção única)
    col_id       = next((c for c in df.columns if c in ('id', 'fatura', 'recibo', 'order_id', 'invoice')), None)
    col_vendedor = next((c for c in df.columns if 'vend' in c or 'seller' in c or 'agent' in c), None)

    if col_id:
        # IDs únicos de venda — o caso ideal
        total_transacoes = int(df[col_id].nunique())
    elif col_vendedor and col_data:
        # Sem ID mas com vendedor: cada combinação data+vendedor = 1 transacção
        total_transacoes = int(df.groupby([df[col_data].dt.date, col_vendedor]).ngroups)
    else:
        # Sem ID nem vendedor: contar linhas (cada linha = 1 item vendido)
        # É o caso mais comum em ficheiros de mercearia/retalho sem sistema de POS
        total_transacoes = int(len(df))

    vendas_por_dia = df.groupby(df[col_data].dt.date)[col_total].sum()
    melhor_dia_str = (
        vendas_por_dia.idxmax().strftime('%Y-%m-%d')
        if not vendas_por_dia.empty
        else datetime.now().strftime('%Y-%m-%d')
    )

    # 8. TOP PRODUTOS
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

    # 9. MÉTRICAS AVANÇADAS
    mes_nome     = datetime.now().strftime('%B')
    ticket_medio = total_faturado / total_transacoes if total_transacoes > 0 else 0.0

    # 10. LIBERTAÇÃO EXPLÍCITA DA MEMÓRIA
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


def _resultado_vazio() -> dict:
    """Retorna estrutura vazia quando o ficheiro não tem dados válidos."""
    mes_nome = datetime.now().strftime('%B')
    return {
        "total": 0.0, "total_transacoes": 0, "ticket_medio": 0.0,
        "melhor_dia": datetime.now().strftime('%Y-%m-%d'),
        "top_produtos": {"Sem dados válidos": 0},
        "total_mensal": 0.0, "transacoes_mensal": 0, "ticket_medio_mensal": 0.0,
        "melhor_dia_mes": datetime.now().strftime('%Y-%m-%d'),
        "top_produtos_mes": {"Sem dados válidos": 0},
        "mes_nome": mes_nome, "variacao_pct": None,
    }