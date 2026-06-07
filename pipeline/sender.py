import httpx
import os
import time


def enviar_mensagem(phone_number: str, texto: str):
    """Envia uma mensagem de texto simples pelo WhatsApp Cloud API v25.0."""
    token    = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID")

    if not token or not phone_id:
        print("Erro: META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID em falta no .env")
        return

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
            r = httpx.post(url, json=payload, headers=headers, timeout=15)
            r.raise_for_status()
            return
        except Exception as e:
            print(f"Erro ao enviar mensagem de texto (tentativa {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)


def main_function(phone_number: str, pdf_url: str, filename: str, mensagem: str = None):
    """Envia o ficheiro PDF de forma determinística para a API da Meta v25.0."""
    token    = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID")

    if not token or not phone_id:
        print("Erro: META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID em falta no .env")
        return

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
            r = httpx.post(url, json=payload, headers=headers, timeout=30)

            if r.status_code != 200:
                print(f"Meta API Error Response: {r.text}")

            r.raise_for_status()
            print("PDF enviado com sucesso para o utilizador!")
            return
        except Exception as e:
            print(f"Erro critico ao enviar documento PDF (tentativa {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)