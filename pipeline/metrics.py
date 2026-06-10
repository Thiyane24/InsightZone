import gc
import pandas as pd
from datetime import datetime, timedelta


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
    df = df.dropna(how='all')

    col_id_raw = next((c for c in df.columns if c in ('id', 'fatura', 'recibo', 'order_id', 'invoice')), None)
    if col_id_raw:
        df = df[df[col_id_raw].astype(str).str.lower() != col_id_raw.lower()]

    if col_total and col_total in df.columns:
        df[col_total] = _parse_numero_pt(df[col_total])
        df = df[df[col_total].notna()]
        df = df[df[col_total] > 0]

    if col_qtd and col_qtd in df.columns:
        df[col_qtd] = _parse_numero_pt(df[col_qtd])
        df = df[df[col_qtd].notna()]
        df = df[df[col_qtd] > 0]

    col_prod = next((c for c in df.columns if 'prod' in c or 'item' in c), None)
    if col_prod and col_total:
        df = df.dropna(subset=[col_prod, col_total])

    return df.reset_index(drop=True)


def _hora_de_pico(df: pd.DataFrame, col_data: str) -> str | None:
    """
    Detecta a hora com mais vendas no DataFrame.
    Só funciona se a coluna de data tiver componente de hora (ex: "2026-06-10 14:30").
    Devolve string "14h-15h" ou None se não houver informação de hora.
    """
    try:
        horas = df[col_data].dt.hour
        # Se todos os valores de hora são 0, provavelmente é só data sem hora
        if horas.nunique() <= 1:
            return None
        hora_pico = int(horas.value_counts().idxmax())
        return f"{hora_pico:02d}h–{hora_pico + 1:02d}h"
    except Exception:
        return None


def _variacao_ontem(df: pd.DataFrame, col_data: str, col_total: str) -> float | None:
    """
    Compara a faturação de hoje com a de ontem.
    Devolve a variação em percentagem (positivo = crescimento, negativo = queda).
    Devolve None se não houver dados de ontem no DataFrame.
    """
    try:
        hoje   = datetime.now().date()
        ontem  = hoje - timedelta(days=1)

        vendas_por_dia = df.groupby(df[col_data].dt.date)[col_total].sum()

        total_hoje  = vendas_por_dia.get(hoje, None)
        total_ontem = vendas_por_dia.get(ontem, None)

        # Precisa de ter os dois dias para calcular variação
        if total_hoje is None or total_ontem is None or total_ontem == 0:
            return None

        return round(((total_hoje - total_ontem) / total_ontem) * 100, 1)
    except Exception:
        return None


def calcular_metricas(
    df: pd.DataFrame,
    frequencia_cliente: str = "semanal",
    periodo: str | None = None,        # NOVO: "hoje", "semana", "mes" ou None (comportamento anterior)
) -> dict:
    """
    Calcula métricas de vendas a partir de um DataFrame.

    Parâmetro `periodo`:
      - None      → comportamento anterior (filtra pelo ano mais recente)
      - "hoje"    → só as linhas de hoje — usado pelo scheduler diário
      - "semana"  → semana corrente (segunda a domingo)
      - "mes"     → mês corrente
    """

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

    # 4. CÁLCULO DO TOTAL REAL
    if col_qtd:
        qtd_serie = _parse_numero_pt(df[col_qtd])
        if not col_total and col_preco:
            df['total_calculado'] = df[col_preco].fillna(0) * qtd_serie.fillna(0)
            col_total = 'total_calculado'

    # ── VALIDAÇÃO SILVER ──────────────────────────────────────────────────────
    df = _validar_silver(df, col_total, col_qtd)

    if df.empty:
        return _resultado_vazio()
    # ─────────────────────────────────────────────────────────────────────────

    # 5. PARSING DE DATAS — múltiplos formatos, sem ambiguidade
    if col_data:
        df[col_data] = _parse_datas_robusto(df[col_data])
        df = df.dropna(subset=[col_data])

        # ── FILTRO DE PERÍODO ─────────────────────────────────────────────────
        # NOVO: filtra o DataFrame conforme o período pedido.
        # Sem período → comportamento original (ano mais recente).
        hoje = datetime.now().date()

        if periodo == "hoje":
            df = df[df[col_data].dt.date == hoje]

        elif periodo == "semana":
            # Segunda-feira da semana corrente até hoje
            inicio_semana = hoje - timedelta(days=hoje.weekday())
            df = df[(df[col_data].dt.date >= inicio_semana) & (df[col_data].dt.date <= hoje)]

        elif periodo == "mes":
            df = df[
                (df[col_data].dt.year  == hoje.year) &
                (df[col_data].dt.month == hoje.month)
            ]

        else:
            # Comportamento original: só o ano mais recente
            ano_mais_recente = int(df[col_data].dt.year.max())
            df = df[df[col_data].dt.year == ano_mais_recente]
        # ─────────────────────────────────────────────────────────────────────

        if df.empty:
            col_data = None

    if not col_data:
        df['data_fallback'] = pd.Timestamp(datetime.now().date())
        col_data = 'data_fallback'

    # 6. TIPOS NUMÉRICOS FINAIS
    if not col_total:
        df['total_zero'] = 0.0
        col_total = 'total_zero'

    if not col_qtd:
        df['qtd_um'] = 1
        col_qtd = 'qtd_um'

    # 7. KPIs CORE
    total_faturado = float(df[col_total].sum())

    col_id       = next((c for c in df.columns if c in ('id', 'fatura', 'recibo', 'order_id', 'invoice')), None)
    col_vendedor = next((c for c in df.columns if 'vend' in c or 'seller' in c or 'agent' in c), None)

    if col_id:
        total_transacoes = int(df[col_id].nunique())
    elif col_vendedor and col_data:
        total_transacoes = int(df.groupby([df[col_data].dt.date, col_vendedor]).ngroups)
    else:
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

    # ── MÉTRICAS DIÁRIAS ──────────────────────────────────────────────────────
    # NOVO: só calculadas quando periodo == "hoje" ou frequencia_cliente == "diario"
    # Para os outros períodos ficam None — o report.py ignora-as se forem None.

    hora_pico         = None
    variacao_ontem    = None
    produto_do_dia    = None

    if periodo == "hoje" or frequencia_cliente == "diario":

        # Hora de pico — precisa de coluna de data com componente de hora
        hora_pico = _hora_de_pico(df, col_data)

        # Variação face a ontem — precisa de dados de ontem no mesmo ficheiro
        # Para relatórios diários o ficheiro enviado pelo cliente pode ter vários dias,
        # o que permite esta comparação.
        variacao_ontem = _variacao_ontem(df, col_data, col_total)

        # Produto mais vendido do dia — o #1 do top já existe, mas isolamos aqui
        # para o report.py o poder destacar visualmente de forma diferente do Top 5.
        if col_produto and top_produtos_dict:
            primeiro = list(top_produtos_dict.keys())[0]
            if primeiro != "Nenhum produto detetado":
                produto_do_dia = {
                    "nome":       primeiro,
                    "quantidade": top_produtos_dict[primeiro],
                    "faturacao":  float(
                        df[df[col_produto].astype(str) == primeiro][col_total].sum()
                    ),
                }
    # ─────────────────────────────────────────────────────────────────────────

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

        "variacao_pct":        None,        # reservado para comparação multi-período futura

        # ── Métricas diárias (None quando não aplicável) ──────────────────────
        "hora_pico":           hora_pico,       # "14h–15h" ou None
        "variacao_ontem":      variacao_ontem,  # float (%) ou None
        "produto_do_dia":      produto_do_dia,  # dict {nome, quantidade, faturacao} ou None
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
        # Métricas diárias também vazias
        "hora_pico": None, "variacao_ontem": None, "produto_do_dia": None,
    }