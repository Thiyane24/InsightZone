import httpx
import os

def enviar_mensagem(phone_number: str, texto: str):
    """Envia uma mensagem de texto simples pelo WhatsApp Cloud API v25.0."""
    token = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID") 
    
    if not token or not phone_id:
        print("Erro: META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID em falta no .env")
        return
        
    # CORREÇÃO: Atualizado para v25.0 correspondente ao teu painel Meta developers
    url = f"https://graph.facebook.com/v25.0/{phone_id}/messages"
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
    
    try:
        r = httpx.post(url, json=payload, headers=headers)
        r.raise_for_status()
    except Exception as e:
        print(f"Erro ao enviar mensagem de texto: {e}")


def main_function(phone_number: str, pdf_url: str, filename: str, mensagem: str = None):
    """Envia o ficheiro PDF de forma determinística para a API da Meta v25.0."""
    token = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID")
    
    if not token or not phone_id:
        print("Erro: META_ACCESS_TOKEN ou META_PHONE_NUMBER_ID em falta no .env")
        return

    # Se passaste uma mensagem contextual, enviamo-la primeiro como texto isolado
    # para evitar que a Meta rejeite o payload binário do documento
    if mensagem:
        enviar_mensagem(phone_number, mensagem)

    # CORREÇÃO: Atualizado para v25.0 correspondente ao teu painel Meta developers
    url = f"https://graph.facebook.com/v25.0/{phone_id}/messages"
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

    try:
        print(f"A enviar PDF para o WhatsApp: {pdf_url}")
        r = httpx.post(url, json=payload, headers=headers)
        
        if r.status_code != 200:
            print(f"Meta API Error Response: {r.text}")
            
        r.raise_for_status()
        print("PDF enviado com sucesso para o utilizador!")
    except Exception as e:
        print(f"Erro crítico ao enviar documento PDF: {e}")