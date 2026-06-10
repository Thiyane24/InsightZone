import httpx
import os
import time

# Códigos HTTP da Meta que nunca resolvem com nova tentativa.
# Um 401 às 3h da manhã não vai resolver — parar imediatamente.
_ERROS_FATAIS = {400, 401, 403, 404}


def enviar_mensagem(phone_number: str, texto: str) -> bool:
    """
    Envia uma mensagem de texto simples pelo WhatsApp Cloud API v25.0.
    Devolve True em caso de sucesso, False em caso de falha permanente.
    """
    token    = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID")

    if not token or not phone_id:
        print("Erro: META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID em falta no .env")
        return False

    url     = f"https://graph.facebook.com/v25.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_number,
        "type": "text",
        "text": {"body": texto}
    }

    for attempt in range(3):
        try:
            r = httpx.post(
                url, json=payload, headers=headers,
                timeout=httpx.Timeout(5.0, read=15.0)   # connect 5s, read 15s
            )
            if r.status_code in _ERROS_FATAIS:
                print(f"Erro fatal ao enviar mensagem ({r.status_code}): {r.text}")
                return False
            r.raise_for_status()
            return True
        except httpx.TimeoutException as e:
            print(f"Timeout ao enviar mensagem (tentativa {attempt + 1}/3): {e}")
        except httpx.HTTPStatusError as e:
            print(f"HTTP error ao enviar mensagem (tentativa {attempt + 1}/3): {e}")
            if e.response.status_code in _ERROS_FATAIS:
                return False
        except Exception as e:
            print(f"Erro ao enviar mensagem (tentativa {attempt + 1}/3): {e}")

        if attempt < 2:
            time.sleep(2 ** attempt)

    return False


def main_function(phone_number: str, pdf_url: str, filename: str, mensagem: str = None) -> bool:
    """
    Envia o ficheiro PDF pelo WhatsApp Cloud API v25.0.
    Se mensagem for fornecida, envia-a primeiro como texto separado.
    Devolve True em caso de sucesso, False em caso de falha permanente.
    """
    token    = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID")

    if not token or not phone_id:
        print("Erro: META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID em falta no .env")
        return False

    if mensagem:
        enviar_mensagem(phone_number, mensagem)

    url     = f"https://graph.facebook.com/v25.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone_number,
        "type": "document",
        "document": {
            "link": pdf_url,
            "filename": filename
        }
    }

    for attempt in range(3):
        try:
            print(f"A enviar PDF para o WhatsApp: {pdf_url}")
            r = httpx.post(
                url, json=payload, headers=headers,
                timeout=httpx.Timeout(5.0, read=30.0)   # connect 5s, read 30s
            )
            if r.status_code in _ERROS_FATAIS:
                print(f"Erro fatal ao enviar PDF ({r.status_code}): {r.text}")
                enviar_mensagem(
                    phone_number,
                    "Nao foi possivel enviar o PDF. Envia o comando 2 para tentar reenviar o ultimo relatorio."
                )
                return False
            if r.status_code != 200:
                print(f"Meta API Error Response: {r.text}")
            r.raise_for_status()
            print("PDF enviado com sucesso para o utilizador!")
            return True
        except httpx.TimeoutException as e:
            print(f"Timeout ao enviar PDF (tentativa {attempt + 1}/3): {e}")
        except httpx.HTTPStatusError as e:
            print(f"HTTP error ao enviar PDF (tentativa {attempt + 1}/3): {e}")
            if e.response.status_code in _ERROS_FATAIS:
                enviar_mensagem(
                    phone_number,
                    "Nao foi possivel enviar o PDF. Envia o comando 2 para tentar reenviar o ultimo relatorio."
                )
                return False
        except Exception as e:
            print(f"Erro critico ao enviar PDF (tentativa {attempt + 1}/3): {e}")

        if attempt < 2:
            time.sleep(2 ** attempt)

    # 3 tentativas falharam notifica o utilizador
    enviar_mensagem(
        phone_number,
        "Nao consegui enviar o PDF apos 3 tentativas. Envia o comando 2 para tentar reenviar o ultimo relatorio."
    )
    return False