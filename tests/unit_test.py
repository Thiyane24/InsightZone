"""
InsightZone — Suite de Testes (MVP)
=====================================
Cobertura focada nos 3 módulos de alto risco:
  1. pipeline/metrics.py  — calcular_metricas, _parse_numero_pt, _detectar_col_produto
  2. pipeline/reader.py   — ingest, normalização, heurística de colunas
  3. pipeline/sender.py   — enviar_mensagem e main_function (erros fatais, retry, notificação)

Sem ligações reais a BD, Meta API, Cloudinary ou disco de produção.
"""

import hashlib
import hmac
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# ── PATH SETUP ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

os.environ.setdefault("WEBHOOK_VERIFY_TOKEN", "token_teste_secreto")
os.environ.setdefault("META_APP_SECRET",      "segredo_hmac_teste")
os.environ.setdefault("META_ACCESS_TOKEN",    "token_meta_fake")
os.environ.setdefault("META_PHONE_NUMBER_ID", "12345678")
os.environ.setdefault("DATABASE_URL",         "postgresql://fake:fake@localhost/fake")
os.environ.setdefault("CLOUD_NAME",           "fake_cloud")
os.environ.setdefault("API_KEY",              "fake_api_key")
os.environ.setdefault("API_SECRET",           "fake_api_secret")


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _df_retalho() -> pd.DataFrame:
    return pd.DataFrame({
        "data":      ["2026-06-07", "2026-06-07", "2026-06-07"],
        "valor":     [150000.0,     250000.0,     50000.0],
        "produto":   ["Rato Optico Pro", "Teclado Mecanico", "Tapete Gaming"],
        "quantidade":[45,           12,           5],
    })


def _df_servicos() -> pd.DataFrame:
    return pd.DataFrame({
        "data":      ["2026-06-07", "2026-06-07"],
        "valor":     [5000.0,       2500.0],
        "servico":   ["Consultoria", "Instalacao"],
        "quantidade":[1,            2],
    })


# ═══════════════════════════════════════════════════════════════════════════════
# 1. METRICS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMetrics:

    def test_calcular_metricas_retalho_basico(self):
        """calcular_metricas devolve KPIs correctos para DataFrame de retalho."""
        from pipeline.metrics import calcular_metricas
        res = calcular_metricas(_df_retalho(), tipo_negocio="retalho")

        assert res["total"]             == pytest.approx(450000.0)
        assert res["total_transacoes"]  == 3
        assert res["ticket_medio"]      == pytest.approx(150000.0)
        assert res["tipo_negocio"]      == "retalho"

    def test_calcular_metricas_servicos_propaga_tipo(self):
        """tipo_negocio='servicos' é propagado nas métricas devolvidas."""
        from pipeline.metrics import calcular_metricas
        res = calcular_metricas(_df_servicos(), tipo_negocio="servicos")

        assert res["tipo_negocio"] == "servicos"
        assert res["total"]        == pytest.approx(7500.0)

    def test_calcular_metricas_df_vazio_devolve_estrutura_valida(self):
        """DataFrame vazio devolve _resultado_vazio sem levantar excepção."""
        from pipeline.metrics import calcular_metricas
        res = calcular_metricas(pd.DataFrame(), tipo_negocio="retalho")

        assert res["total"]             == 0.0
        assert res["total_transacoes"]  == 0
        assert res["tipo_negocio"]      == "retalho"

    def test_parse_numero_pt_formatos_variados(self):
        """_parse_numero_pt converte formato PT e EN, rejeita texto."""
        from pipeline.metrics import _parse_numero_pt
        serie  = pd.Series(["1.500,00", "2500.50", "vinte", "N/A", "1.000"])
        result = _parse_numero_pt(serie)

        assert result[0] == pytest.approx(1500.0)
        assert result[1] == pytest.approx(2500.50)
        assert pd.isna(result[2])
        assert pd.isna(result[3])
        assert not pd.isna(result[4])

    def test_detectar_col_produto_retalho(self):
        """_detectar_col_produto detecta 'produto' para retalho."""
        from pipeline.metrics import _detectar_col_produto
        assert _detectar_col_produto(["data", "produto", "valor"], "retalho") == "produto"

    def test_detectar_col_produto_servicos(self):
        """_detectar_col_produto detecta 'servico' para serviços."""
        from pipeline.metrics import _detectar_col_produto
        assert _detectar_col_produto(["data", "servico", "valor"], "servicos") == "servico"

    def test_detectar_col_produto_nenhuma_coluna(self):
        """_detectar_col_produto devolve None quando não há coluna reconhecível."""
        from pipeline.metrics import _detectar_col_produto
        assert _detectar_col_produto(["data", "valor", "quantidade"], "retalho") is None

    def test_calcular_metricas_valores_negativos_sao_rejeitados(self):
        """Linhas com valor <= 0 são filtradas pelo _validar_silver."""
        from pipeline.metrics import calcular_metricas
        df = pd.DataFrame({
            "data":      ["2026-06-07", "2026-06-07"],
            "valor":     [-100.0,       500.0],
            "produto":   ["X",          "Y"],
            "quantidade":[1,            2],
        })
        res = calcular_metricas(df, tipo_negocio="retalho")

        assert res["total"]            == pytest.approx(500.0)
        assert res["total_transacoes"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 2. READER
# ═══════════════════════════════════════════════════════════════════════════════

class TestReader:

    def test_ingest_csv_normaliza_colunas(self, tmp_path):
        """ingest lê CSV e normaliza colunas para data/quantidade/valor."""
        from pipeline.reader import ingest
        csv = tmp_path / "vendas.csv"
        csv.write_text("data,quantidade,valor,produto\n2026-06-07,10,500,Arroz\n")
        df  = ingest(str(csv))

        assert {"data", "quantidade", "valor"} <= set(df.columns)
        assert len(df) == 1

    def test_ingest_xlsx_normaliza_colunas(self, tmp_path):
        """ingest lê XLSX e normaliza colunas."""
        from pipeline.reader import ingest
        xlsx = tmp_path / "vendas.xlsx"
        pd.DataFrame({
            "data": ["2026-06-07"], "quantidade": [5],
            "valor": [250.0],       "produto": ["Feijao"],
        }).to_excel(str(xlsx), index=False)
        df = ingest(str(xlsx))

        assert "valor" in df.columns
        assert len(df) == 1

    def test_ingest_formato_nao_suportado_levanta_erro(self, tmp_path):
        """ingest levanta ValueError para extensão desconhecida."""
        from pipeline.reader import ingest
        f = tmp_path / "dados.txt"
        f.write_text("nada")
        with pytest.raises(ValueError, match="Formato nao suportado"):
            ingest(str(f))

    def test_ingest_csv_vazio_levanta_erro(self, tmp_path):
        """ingest levanta ValueError para CSV sem linhas de dados."""
        from pipeline.reader import ingest
        csv = tmp_path / "vazio.csv"
        csv.write_text("")
        with pytest.raises(ValueError):
            ingest(str(csv))

    def test_ingest_preserva_coluna_produto(self, tmp_path):
        """ingest não renomeia 'produto' — preserva para metrics.py detectar."""
        from pipeline.reader import ingest
        csv = tmp_path / "vendas.csv"
        csv.write_text("data,quantidade,valor,produto\n2026-06-07,3,150,Frango\n")
        df  = ingest(str(csv))
        assert "produto" in df.columns

    def test_ingest_preserva_coluna_servico(self, tmp_path):
        """ingest não renomeia 'servico' — preserva para metrics.py detectar."""
        from pipeline.reader import ingest
        csv = tmp_path / "servicos.csv"
        csv.write_text("data,quantidade,valor,servico\n2026-06-07,1,5000,Consultoria\n")
        df  = ingest(str(csv))
        assert "servico" in df.columns

    def test_ingest_sem_colunas_minimas_levanta_erro(self, tmp_path):
        """ingest levanta ValueError se não encontra data/quantidade/valor."""
        from pipeline.reader import ingest
        csv = tmp_path / "mal.csv"
        csv.write_text("nome,descricao\nJoao,Produto X\n")
        with pytest.raises(ValueError, match="colunas necessarias"):
            ingest(str(csv))

    def test_ingest_heuristica_mapeamento(self, tmp_path):
        """ingest mapeia 'qty'→quantidade e 'total'→valor via heurística."""
        from pipeline.reader import ingest
        csv = tmp_path / "h.csv"
        csv.write_text("date,qty,total,produto\n2026-06-07,10,500,Arroz\n")
        df  = ingest(str(csv))

        assert "quantidade" in df.columns
        assert "valor"      in df.columns


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SENDER
# ═══════════════════════════════════════════════════════════════════════════════

class TestSender:

    def test_enviar_mensagem_sucesso(self):
        """enviar_mensagem devolve True em resposta 200."""
        from pipeline.sender import enviar_mensagem

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("pipeline.sender.httpx.post", return_value=mock_resp):
            assert enviar_mensagem("258840000001", "Ola!") is True

    def test_enviar_mensagem_erro_fatal_nao_retenta(self):
        """enviar_mensagem para imediatamente em 401 sem retentar."""
        import httpx
        from pipeline.sender import enviar_mensagem

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text        = "Unauthorized"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_resp
        )

        with patch("pipeline.sender.httpx.post", return_value=mock_resp) as mock_post:
            result = enviar_mensagem("258840000001", "Ola!")

        assert result is False
        assert mock_post.call_count == 1    # parou na 1ª tentativa

    def test_main_function_sucesso(self):
        """main_function devolve True quando PDF enviado com sucesso."""
        from pipeline.sender import main_function

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        with patch("pipeline.sender.httpx.post", return_value=mock_resp):
            assert main_function("258840000001", "https://cdn.com/r.pdf", "r.pdf") is True

    def test_main_function_notifica_utilizador_apos_3_falhas(self):
        """main_function notifica o utilizador se as 3 tentativas falharem."""
        import httpx
        from pipeline.sender import main_function

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text        = "Server Error"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=mock_resp
        )

        with patch("pipeline.sender.httpx.post", return_value=mock_resp), \
             patch("pipeline.sender.enviar_mensagem") as mock_notif, \
             patch("pipeline.sender.time.sleep"):
            result = main_function("258840000001", "https://cdn.com/r.pdf", "r.pdf")

        assert result is False
        assert mock_notif.called

    def test_main_function_envia_mensagem_antes_do_pdf(self):
        """main_function envia a mensagem de texto antes de enviar o PDF."""
        from pipeline.sender import main_function

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mensagens_enviadas = []
        with patch("pipeline.sender.httpx.post", return_value=mock_resp), \
             patch("pipeline.sender.enviar_mensagem",
                   side_effect=lambda n, t: mensagens_enviadas.append(t)):
            main_function("258840000001", "https://cdn.com/r.pdf", "r.pdf",
                          mensagem="O teu relatorio:")

        assert len(mensagens_enviadas) == 1
        assert "relatorio" in mensagens_enviadas[0].lower()