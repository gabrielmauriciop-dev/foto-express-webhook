import os
import json
import time
import uuid
import unicodedata
import urllib.request
import urllib.error
from collections import defaultdict, deque

from flask import Flask, request, jsonify
from openai import OpenAI


app = Flask(__name__)


# =========================================================
# CONFIGURACAO
# =========================================================

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OWNER_WHATSAPP = os.environ.get("OWNER_WHATSAPP", "")

GRAPH_API_VERSION = "v26.0"
OPENAI_MODEL = "gpt-5.6-luna"

TEMP_DIR = "/tmp/foto_express"
MAX_REFERENCES = 10

os.makedirs(TEMP_DIR, exist_ok=True)

client = OpenAI(api_key=OPENAI_API_KEY)


# =========================================================
# MEMORIA TEMPORARIA
# =========================================================

conversations = defaultdict(lambda: deque(maxlen=24))

customer_photos = defaultdict(list)

orders = defaultdict(lambda: {
    "status": "ATENDIMENTO",
    "style": "",
    "package": "",
    "reference_count": 0,
    "owner_notified": False,
    "payment_receipt_received": False,
})

processed_messages = {}

MESSAGE_TTL = 60 * 60 * 24


# =========================================================
# AGENTE FOTO EXPRESS
# =========================================================

AGENT_INSTRUCTIONS = """
Voce e o atendente comercial da Foto Express no WhatsApp.

Voce atende clientes brasileiros que querem transformar fotos
comuns em ensaios fotograficos profissionais.

Seja humano, simpatico, breve e comercial.

Nunca diga que e uma inteligencia artificial.

==================================================
SERVICO
==================================================

O cliente envia uma ou varias fotos de referencia.

A Foto Express cria fotografias profissionais preservando
a identidade da pessoa.

O cliente pode enviar varias referencias.

Quando receber uma foto, confirme o recebimento.

Se parecer que o cliente ainda vai enviar outras fotos,
diga de forma breve que pode mandar as outras.

Quando ele terminar de enviar as referencias, ele pode
escrever "pronto" ou "terminei".

Nunca diga que o ensaio esta pronto se o sistema nao
informou isso.

==================================================
PRECOS
==================================================

4 fotos = R$10
10 fotos = R$20
20 fotos = R$35

O pacote principal e:

10 fotos por R$20.

Nao despeje todos os precos sem necessidade.

Quando for apropriado, recomende 10 fotos por R$20.

Se o cliente achar caro ou recusar o pacote de R$20:
ofereca 4 fotos por R$10.

Se quiser mais fotos:
ofereca 20 fotos por R$35.

Se perguntar todos os precos:
informe os tres.

Nunca altere precos.
Nunca invente desconto.
Nunca prometa fotos extras.

==================================================
PREVIA
==================================================

O cliente ve uma previa antes de pagar.

Esse e um dos principais diferenciais da Foto Express.

Quando houver inseguranca, explique isso naturalmente.

==================================================
PAGAMENTO
==================================================

Nunca invente chave PIX.

Nunca considere um print de comprovante como confirmacao
definitiva de pagamento.

Se o sistema informar:

[SISTEMA: COMPROVANTE RECEBIDO]

diga que o comprovante foi recebido e que o pagamento
sera conferido.

Somente considere o pagamento confirmado quando receber:

[SISTEMA: PAGAMENTO CONFIRMADO PELO RESPONSAVEL]

==================================================
PRODUCAO
==================================================

Quando receber:

[SISTEMA: REFERENCIAS FINALIZADAS]

significa que o cliente terminou de mandar as referencias
e o pedido foi encaminhado para producao.

Responda brevemente dizendo que o material foi recebido
e sera preparado.

Quando receber:

[SISTEMA: PRODUCAO CONCLUIDA]

significa que o responsavel terminou de produzir o ensaio.

Nao invente imagens, links ou anexos.

==================================================
CONVERSA
==================================================

Use portugues brasileiro.

Normalmente responda em 1 a 4 frases.

Use poucos emojis.

Nao reinicie a conversa.

Nao repita saudacao em cada mensagem.

Leia o historico.

Se o cliente ja informou o estilo, nao pergunte novamente.

Entenda respostas curtas pelo contexto, como:

sim
quero
pode ser
fechado
10
20
essa
essas

==================================================
ESCALONAMENTO
==================================================

Encaminhe para o responsavel quando houver:

reclamacao seria
reembolso
problema de pagamento
questao juridica
cliente muito insatisfeito
situacao que voce nao consegue resolver

Nao invente solucoes.

==================================================
REGRA PRINCIPAL
==================================================

Responda ao que o cliente realmente disse considerando
todo o historico.

Nao use respostas fixas.

Nao invente acontecimentos.
"""


# =========================================================
# UTILIDADES
# =========================================================

def mask_phone(phone):
    if not phone:
        return "desconhecido"

    if len(phone) <= 4:
        return "****"

    return "*" * (len(phone) - 4) + phone[-4:]


def phone_suffix(phone):
    if not phone:
        return "????"

    return phone[-4:]


def normalize_text(text):
    text = text.lower().strip()

    text = unicodedata.normalize(
        "NFD",
        text
    )

    text = "".join(
        char
        for char in text
        if unicodedata.category(char) != "Mn"
    )

    return text


def cleanup_processed_messages():
    now = time.time()

    expired = [
        message_id
        for message_id, timestamp
        in processed_messages.items()
        if now - timestamp > MESSAGE_TTL
    ]

    for message_id in expired:
        processed_messages.pop(message_id, None)


def already_processed(message_id):
    if not message_id:
        return False

    cleanup_processed_messages()

    if message_id in processed_messages:
        return True

    processed_messages[message_id] = time.time()

    return False


def find_customer_by_suffix(suffix):
    suffix = suffix.strip()

    matches = []

    for customer in orders.keys():
        if customer.endswith(suffix):
            matches.append(customer)

    if len(matches) == 1:
        return matches[0]

    return None


# =========================================================
# META GRAPH API
# =========================================================

def graph_request(path, method="GET", payload=None):

    if not WHATSAPP_TOKEN:
        raise RuntimeError(
            "WHATSAPP_TOKEN nao configurado"
        )

    url = (
        f"https://graph.facebook.com/"
        f"{GRAPH_API_VERSION}/{path}"
    )

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url=url,
        data=data,
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        },
        method=method,
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=30
        ) as response:

            body = response.read().decode("utf-8")

            if not body:
                return {}

            return json.loads(body)

    except urllib.error.HTTPError as error:

        body = error.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"Meta HTTP {error.code}: {body}"
        )


def send_whatsapp_message(to, text):

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": text[:4096],
        },
    }

    return graph_request(
        f"{PHONE_NUMBER_ID}/messages",
        method="POST",
        payload=payload,
    )


# =========================================================
# DOWNLOAD DAS FOTOS
# =========================================================

def get_media_info(media_id):

    if not media_id:
        raise RuntimeError("Media ID vazio")

    return graph_request(
        media_id,
        method="GET"
    )


def extension_from_mime(mime_type):

    mime_type = (
        mime_type
        .lower()
        .split(";")[0]
        .strip()
    )

    extensions = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    return extensions.get(
        mime_type,
        ".jpg"
    )


def download_media_file(media_url, destination):

    req = urllib.request.Request(
        url=media_url,
        headers={
            "Authorization":
                f"Bearer {WHATSAPP_TOKEN}",
        },
        method="GET",
    )

    with urllib.request.urlopen(
        req,
        timeout=60
    ) as response:

        content = response.read()

    if not content:
        raise RuntimeError(
            "Arquivo de imagem vazio"
        )

    with open(destination, "wb") as file:
        file.write(content)

    return len(content)


def receive_customer_photo(sender, image_data):

    media_id = image_data.get("id", "")

    webhook_mime = image_data.get(
        "mime_type",
        ""
    )

    if not media_id:
        raise RuntimeError(
            "Imagem sem Media ID"
        )

    media_info = get_media_info(media_id)

    media_url = media_info.get("url", "")

    mime_type = (
        media_info.get("mime_type")
        or webhook_mime
        or "image/jpeg"
    )

    extension = extension_from_mime(
        mime_type
    )

    customer_dir = os.path.join(
        TEMP_DIR,
        sender
    )

    os.makedirs(
        customer_dir,
        exist_ok=True
    )

    filename = (
        f"{int(time.time())}_"
        f"{uuid.uuid4().hex[:10]}"
        f"{extension}"
    )

    destination = os.path.join(
        customer_dir,
        filename
    )

    size = download_media_file(
        media_url,
        destination
    )

    customer_photos[sender].append({
        "path": destination,
        "mime_type": mime_type,
        "size": size,
        "received_at": time.time(),
    })

    # Limite temporario.
    customer_photos[sender] = (
        customer_photos[sender][-MAX_REFERENCES:]
    )

    orders[sender]["reference_count"] = len(
        customer_photos[sender]
    )

    orders[sender]["status"] = "RECEBENDO_REFERENCIAS"

    print(
        f"FOTO BAIXADA | cliente={phone_suffix(sender)} "
        f"| referencias={orders[sender]['reference_count']}",
        flush=True,
    )

    return destination


# =========================================================
# AGENTE OPENAI
# =========================================================

def build_conversation_input(
    sender,
    current_message
):

    result = []

    for item in conversations[sender]:
        result.append({
            "role": item["role"],
            "content": item["content"],
        })

    result.append({
        "role": "user",
        "content": current_message,
    })

    return result


def ask_agent(sender, customer_message):

    response = client.responses.create(
        model=OPENAI_MODEL,
        reasoning={
            "effort": "low"
        },
        instructions=AGENT_INSTRUCTIONS,
        input=build_conversation_input(
            sender,
            customer_message
        ),
    )

    answer = (
        response.output_text or ""
    ).strip()

    if not answer:
        answer = (
            "Recebi sua mensagem 😊 "
            "Pode me explicar um pouquinho mais?"
        )

    conversations[sender].append({
        "role": "user",
        "content": customer_message,
    })

    conversations[sender].append({
        "role": "assistant",
        "content": answer,
    })

    return answer


def respond_with_agent(sender, customer_message):

    try:

        answer = ask_agent(
            sender,
            customer_message
        )

        send_whatsapp_message(
            sender,
            answer
        )

        print(
            f"AGENTE RESPONDEU | "
            f"cliente={phone_suffix(sender)}",
            flush=True,
        )

    except Exception as error:

        print(
            f"ERRO AGENTE: {error}",
            flush=True,
        )

        send_whatsapp_message(
            sender,
            (
                "Tive um probleminha para processar "
                "sua mensagem agora. 😊 "
                "Pode tentar novamente em instantes?"
            ),
        )


# =========================================================
# AVISOS PARA O PROPRIETARIO
# =========================================================

def notify_owner_ready(sender):

    if not OWNER_WHATSAPP:
        print(
            "OWNER_WHATSAPP nao configurado",
            flush=True,
        )
        return

    order = orders[sender]

    suffix = phone_suffix(sender)

    message = (
        "🔔 NOVO ENSAIO PARA PRODUÇÃO\n\n"
        f"Cliente: final {suffix}\n"
        f"Referências: {order['reference_count']}\n"
        f"Status: aguardando produção\n\n"
        "Depois de produzir, envie:\n"
        f"/produzido {suffix}"
    )

    send_whatsapp_message(
        OWNER_WHATSAPP,
        message
    )

    order["owner_notified"] = True

    print(
        f"PROPRIETARIO AVISADO | cliente={suffix}",
        flush=True,
    )


def notify_owner_payment(sender):

    if not OWNER_WHATSAPP:
        return

    suffix = phone_suffix(sender)

    message = (
        "💰 COMPROVANTE RECEBIDO\n\n"
        f"Cliente: final {suffix}\n\n"
        "Confira no banco se o dinheiro "
        "realmente entrou.\n\n"
        "Se estiver confirmado, envie:\n"
        f"/pago {suffix}"
    )

    send_whatsapp_message(
        OWNER_WHATSAPP,
        message
    )


# =========================================================
# COMANDOS DO PROPRIETARIO
# =========================================================

def handle_owner_command(sender, body):

    if sender != OWNER_WHATSAPP:
        return False

    normalized = normalize_text(body)

    if normalized.startswith("/produzido"):

        parts = normalized.split()

        if len(parts) < 2:
            send_whatsapp_message(
                sender,
                "Use: /produzido 1234"
            )
            return True

        customer = find_customer_by_suffix(
            parts[1]
        )

        if not customer:
            send_whatsapp_message(
                sender,
                "Não encontrei um cliente único com esse final."
            )
            return True

        orders[customer]["status"] = "PRODUCAO_CONCLUIDA"

        respond_with_agent(
            customer,
            "[SISTEMA: PRODUCAO CONCLUIDA]"
        )

        send_whatsapp_message(
            sender,
            (
                "✅ Produção marcada como concluída "
                f"para o cliente final {phone_suffix(customer)}."
            ),
        )

        return True

    if normalized.startswith("/pago"):

        parts = normalized.split()

        if len(parts) < 2:
            send_whatsapp_message(
                sender,
                "Use: /pago 1234"
            )
            return True

        customer = find_customer_by_suffix(
            parts[1]
        )

        if not customer:
            send_whatsapp_message(
                sender,
                "Não encontrei um cliente único com esse final."
            )
            return True

        orders[customer]["status"] = "PAGO"

        respond_with_agent(
            customer,
            (
                "[SISTEMA: PAGAMENTO CONFIRMADO "
                "PELO RESPONSAVEL]"
            )
        )

        send_whatsapp_message(
            sender,
            (
                "💰 Pagamento confirmado para "
                f"o cliente final {phone_suffix(customer)}."
            ),
        )

        return True

    if normalized.startswith("/status"):

        parts = normalized.split()

        if len(parts) < 2:
            send_whatsapp_message(
                sender,
                "Use: /status 1234"
            )
            return True

        customer = find_customer_by_suffix(
            parts[1]
        )

        if not customer:
            send_whatsapp_message(
                sender,
                "Cliente não encontrado."
            )
            return True

        order = orders[customer]

        send_whatsapp_message(
            sender,
            (
                "📋 PEDIDO\n\n"
                f"Cliente: final {phone_suffix(customer)}\n"
                f"Referências: {order['reference_count']}\n"
                f"Status: {order['status']}"
            ),
        )

        return True

    return False


# =========================================================
# FINALIZACAO DAS REFERENCIAS
# =========================================================

def customer_finished_references(text):

    normalized = normalize_text(text)

    expressions = {
        "pronto",
        "terminei",
        "terminei de enviar",
        "so essas",
        "sao essas",
        "essas sao as fotos",
        "pode fazer",
        "pode comecar",
    }

    return normalized in expressions


def finish_references(sender):

    count = orders[sender]["reference_count"]

    if count <= 0:
        return False

    orders[sender]["status"] = "AGUARDANDO_PRODUCAO"

    respond_with_agent(
        sender,
        (
            "[SISTEMA: REFERENCIAS FINALIZADAS. "
            f"O cliente enviou {count} fotografia(s) "
            "de referencia. O pedido foi encaminhado "
            "para producao.]"
        )
    )

    if not orders[sender]["owner_notified"]:
        notify_owner_ready(sender)

    return True


# =========================================================
# ROTAS
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return "Foto Express Hybrid Agent online", 200


@app.route("/status", methods=["GET"])
def status():

    return jsonify({
        "online": True,
        "openai": bool(OPENAI_API_KEY),
        "whatsapp": bool(WHATSAPP_TOKEN),
        "owner": bool(OWNER_WHATSAPP),
        "model": OPENAI_MODEL,
    }), 200


@app.route("/privacy", methods=["GET"])
def privacy():

    return """
    <!doctype html>
    <html lang="pt-BR">
    <head>
        <meta charset="utf-8">
        <title>Privacidade - Foto Express</title>
    </head>
    <body style="font-family:Arial;max-width:800px;margin:40px auto;padding:20px;line-height:1.6">
        <h1>Política de Privacidade - Foto Express</h1>
        <p>
        A Foto Express utiliza mensagens e fotografias
        enviadas voluntariamente pelos clientes para prestar
        os serviços solicitados.
        </p>
        <p>
        As informações podem ser processadas por provedores
        tecnológicos necessários à operação, incluindo
        mensageria, hospedagem, automação e inteligência
        artificial.
        </p>
        <p>
        A Foto Express não vende fotografias ou dados
        pessoais dos clientes.
        </p>
    </body>
    </html>
    """, 200


@app.route("/data-deletion", methods=["GET"])
def data_deletion():

    return """
    <!doctype html>
    <html lang="pt-BR">
    <head>
        <meta charset="utf-8">
        <title>Exclusão de Dados - Foto Express</title>
    </head>
    <body style="font-family:Arial;max-width:800px;margin:40px auto;padding:20px;line-height:1.6">
        <h1>Exclusão de Dados</h1>
        <p>
        O cliente pode solicitar a exclusão das informações
        e fotografias fornecidas através do canal oficial
        de atendimento da Foto Express.
        </p>
    </body>
    </html>
    """, 200


# =========================================================
# VERIFICACAO DO WEBHOOK
# =========================================================

@app.route("/webhook", methods=["GET"])
def verify_webhook():

    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if (
        mode == "subscribe"
        and token == VERIFY_TOKEN
        and challenge
    ):
        return challenge, 200

    return "Forbidden", 403


# =========================================================
# WEBHOOK PRINCIPAL
# =========================================================

@app.route("/webhook", methods=["POST"])
def receive_webhook():

    data = request.get_json(silent=True) or {}

    try:

        for entry in data.get("entry", []):

            for change in entry.get("changes", []):

                value = change.get("value", {})

                for message in value.get("messages", []):

                    sender = message.get("from", "")
                    message_id = message.get("id", "")
                    message_type = message.get("type", "")

                    if not sender:
                        continue

                    if already_processed(message_id):
                        print(
                            "Webhook duplicado ignorado.",
                            flush=True,
                        )
                        continue

                    print(
                        f"MENSAGEM | cliente={phone_suffix(sender)} "
                        f"| tipo={message_type}",
                        flush=True,
                    )

                    # =====================================
                    # TEXTO
                    # =====================================

                    if message_type == "text":

                        body = (
                            message
                            .get("text", {})
                            .get("body", "")
                            .strip()
                        )

                        if not body:
                            continue

                        # Comandos administrativos possuem
                        # prioridade.
                        if handle_owner_command(
                            sender,
                            body
                        ):
                            continue

                        # Cliente terminou de enviar fotos.
                        if customer_finished_references(
                            body
                        ):
                            if finish_references(sender):
                                continue

                        respond_with_agent(
                            sender,
                            body
                        )

                    # =====================================
                    # IMAGEM
                    # =====================================

                    elif message_type == "image":

                        image_data = message.get(
                            "image",
                            {}
                        )

                        caption = (
                            image_data
                            .get("caption", "")
                            .strip()
                        )

                        try:

                            receive_customer_photo(
                                sender,
                                image_data
                            )

                            count = orders[
                                sender
                            ]["reference_count"]

                            system_message = (
                                "[SISTEMA: NOVA FOTO DE "
                                "REFERENCIA RECEBIDA E "
                                "ARMAZENADA. "
                                f"Agora existem {count} "
                                "referencia(s) neste pedido. "
                                "O cliente pode enviar outras "
                                "fotografias se desejar."
                            )

                            if caption:
                                system_message += (
                                    " Legenda enviada pelo "
                                    f"cliente: {caption}"
                                )

                            system_message += "]"

                            respond_with_agent(
                                sender,
                                system_message
                            )

                        except Exception as error:

                            print(
                                f"ERRO FOTO: {error}",
                                flush=True,
                            )

                            send_whatsapp_message(
                                sender,
                                (
                                    "Recebi a foto, mas tive "
                                    "um problema para processar "
                                    "o arquivo. 📸 Pode enviá-la "
                                    "novamente?"
                                ),
                            )

                    # =====================================
                    # DOCUMENTO / COMPROVANTE
                    # =====================================

                    elif message_type == "document":

                        orders[sender][
                            "payment_receipt_received"
                        ] = True

                        orders[sender][
                            "status"
                        ] = "AGUARDANDO_CONFIRMACAO_PIX"

                        respond_with_agent(
                            sender,
                            "[SISTEMA: COMPROVANTE RECEBIDO]"
                        )

                        notify_owner_payment(sender)

                    # =====================================
                    # OUTROS
                    # =====================================

                    else:

                        respond_with_agent(
                            sender,
                            (
                                "[SISTEMA: O cliente enviou "
                                f"uma mensagem do tipo "
                                f"{message_type}.]"
                            )
                        )

    except Exception as error:

        print(
            f"ERRO WEBHOOK: "
            f"{type(error).__name__}: {error}",
            flush=True,
        )

    return "EVENT_RECEIVED", 200


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
