import os
import json
import time
import uuid
import random
import threading
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

# Janela de silencio antes de responder.
TEXT_DEBOUNCE_MIN = 3.5
TEXT_DEBOUNCE_MAX = 5.5

PHOTO_DEBOUNCE_MIN = 5.0
PHOTO_DEBOUNCE_MAX = 7.0

os.makedirs(TEMP_DIR, exist_ok=True)

client = OpenAI(api_key=OPENAI_API_KEY)


# =========================================================
# MEMORIA TEMPORARIA
# =========================================================

conversations = defaultdict(
    lambda: deque(maxlen=24)
)

customer_photos = defaultdict(list)

orders = defaultdict(
    lambda: {
        "status": "ATENDIMENTO",
        "style": "",
        "package": "",
        "reference_count": 0,
        "owner_notified": False,
        "payment_receipt_received": False,
    }
)

processed_messages = {}

MESSAGE_TTL = 60 * 60 * 24


# =========================================================
# BUFFER DE MENSAGENS
# =========================================================

pending_messages = defaultdict(list)
pending_timers = {}

buffer_lock = threading.Lock()


# =========================================================
# AGENTE
# =========================================================

AGENT_INSTRUCTIONS = """
Voce e o atendente comercial da Foto Express no WhatsApp.

Atenda em portugues brasileiro.

Seu comportamento deve parecer uma conversa natural de
WhatsApp: humano, simpatico, breve e comercial.

Nunca diga que e inteligencia artificial.

Nao escreva como chatbot.

Nao use textos excessivamente formais.

Nao envie mensagens enormes.

Normalmente responda em 1 a 4 frases.

Use emojis com moderacao.

Nao comece toda resposta com "Olá".

Nao repita informacoes que o cliente ja recebeu.

Nao repita perguntas que o cliente ja respondeu.

Leia todo o contexto antes de responder.

==================================================
SERVICO
==================================================

A Foto Express transforma fotografias comuns em ensaios
fotograficos profissionais.

O cliente pode enviar uma ou varias fotografias como
referencia.

As fotografias servem para preservar a identidade e
aparencia da pessoa.

O cliente ve uma previa antes de pagar.

Esse e um dos principais diferenciais do servico.

==================================================
VARIAS MENSAGENS
==================================================

O sistema pode agrupar varias mensagens consecutivas do
cliente antes de chamar voce.

Exemplo:

Oi
queria saber como funciona
vou mandar umas fotos

Voce deve interpretar isso como uma unica sequencia de
conversa.

Nao responda separadamente a cada frase.

==================================================
VARIAS FOTOS
==================================================

O cliente pode mandar varias fotografias seguidas.

Se o sistema informar que foram recebidas varias fotos,
confirme o conjunto apenas uma vez.

Nao diga:

"foto recebida"
"foto recebida"
"foto recebida"

Prefira algo natural como:

"Recebi suas fotos 😊📸"

Se o cliente ainda puder mandar mais referencias, diga
brevemente que ele pode continuar enviando.

Quando terminar, ele pode dizer "pronto", "terminei",
"so essas", "pode fazer" ou algo equivalente.

==================================================
PRECOS
==================================================

Os precos oficiais sao:

4 fotos = R$10
10 fotos = R$20
20 fotos = R$35

O pacote principal e 10 fotos por R$20.

Nao despeje todos os precos sem necessidade.

Quando chegar naturalmente o momento da venda,
recomende primeiro:

10 fotos por R$20.

Explique que sao 10 fotos diferentes e que o cliente
recebe as 10 em alta qualidade e sem marca d'agua.

Se o cliente achar caro ou recusar R$20:

ofereca 4 fotos por R$10.

Se quiser mais:

ofereca 20 fotos por R$35.

Se perguntar diretamente quais sao todos os precos,
informe os tres.

Nunca invente desconto.

Nunca altere os precos.

==================================================
PREVIA
==================================================

O cliente ve o resultado antes de pagar.

Use isso para reduzir inseguranca quando for relevante.

Nunca diga que a previa esta pronta se o sistema nao
informou isso.

Nunca diga que as fotos foram produzidas se o sistema
nao informou isso.

==================================================
PAGAMENTO
==================================================

Nunca invente chave PIX.

Nunca trate um print ou arquivo de comprovante como
confirmacao definitiva do pagamento.

Quando receber:

[SISTEMA: COMPROVANTE RECEBIDO]

diga de forma natural que recebeu e que o pagamento
sera conferido.

Somente considere pago quando receber:

[SISTEMA: PAGAMENTO CONFIRMADO PELO RESPONSAVEL]

==================================================
PRODUCAO
==================================================

Quando receber:

[SISTEMA: REFERENCIAS FINALIZADAS]

significa que as referencias foram encaminhadas para
producao.

Responda de forma breve e natural.

Quando receber:

[SISTEMA: PRODUCAO CONCLUIDA]

significa que o responsavel terminou a producao.

Nao invente anexos, imagens ou links.

==================================================
RESPOSTAS CURTAS
==================================================

Entenda respostas curtas pelo contexto:

sim
quero
pode ser
fechado
10
20
essas
essa
pode fazer
manda
gostei

Nao obrigue o cliente a escrever frases completas.

==================================================
TOM
==================================================

O atendimento deve transmitir:

facilidade
seguranca
proximidade
agilidade
confianca

Nao pressione excessivamente.

Nao pareca um menu automatico.

Nao diga coisas como:

"Selecione uma opcao"
"Digite 1"
"Digite 2"

a menos que o cliente realmente precise disso.

==================================================
ESCALONAMENTO
==================================================

Encaminhe para o responsavel em caso de:

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

Responda ao que o cliente realmente quis dizer,
considerando toda a sequencia da conversa.

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

    return (
        "*" * (len(phone) - 4)
        + phone[-4:]
    )


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
        processed_messages.pop(
            message_id,
            None
        )


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

def graph_request(
    path,
    method="GET",
    payload=None
):

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

        data = json.dumps(
            payload
        ).encode("utf-8")

    req = urllib.request.Request(
        url=url,
        data=data,
        headers={
            "Authorization":
                f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type":
                "application/json",
        },
        method=method,
    )

    try:

        with urllib.request.urlopen(
            req,
            timeout=30
        ) as response:

            body = (
                response
                .read()
                .decode("utf-8")
            )

            if not body:
                return {}

            return json.loads(body)

    except urllib.error.HTTPError as error:

        body = (
            error
            .read()
            .decode(
                "utf-8",
                errors="replace"
            )
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
        raise RuntimeError(
            "Media ID vazio"
        )

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


def download_media_file(
    media_url,
    destination
):

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

    with open(
        destination,
        "wb"
    ) as file:

        file.write(content)

    return len(content)


def receive_customer_photo(
    sender,
    image_data
):

    media_id = image_data.get(
        "id",
        ""
    )

    webhook_mime = image_data.get(
        "mime_type",
        ""
    )

    if not media_id:
        raise RuntimeError(
            "Imagem sem Media ID"
        )

    media_info = get_media_info(
        media_id
    )

    media_url = media_info.get(
        "url",
        ""
    )

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

    customer_photos[sender] = (
        customer_photos[sender]
        [-MAX_REFERENCES:]
    )

    orders[sender][
        "reference_count"
    ] = len(
        customer_photos[sender]
    )

    orders[sender][
        "status"
    ] = "RECEBENDO_REFERENCIAS"

    print(
        "FOTO BAIXADA | "
        f"cliente={phone_suffix(sender)} "
        f"| referencias="
        f"{orders[sender]['reference_count']}",
        flush=True,
    )

    return destination


# =========================================================
# OPENAI
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


def ask_agent(
    sender,
    customer_message
):

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
            "Pode me contar um pouquinho mais?"
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


def respond_with_agent(
    sender,
    customer_message
):

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
            "AGENTE RESPONDEU | "
            f"cliente={phone_suffix(sender)}",
            flush=True,
        )

    except Exception as error:

        print(
            f"ERRO AGENTE: {error}",
            flush=True,
        )

        try:

            send_whatsapp_message(
                sender,
                (
                    "Tive um probleminha por aqui. 😊 "
                    "Pode me mandar novamente?"
                ),
            )

        except Exception:
            pass


# =========================================================
# AVISOS AO PROPRIETARIO
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
        f"Referências: "
        f"{order['reference_count']}\n"
        "Status: aguardando produção\n\n"
        "Depois de produzir, envie:\n"
        f"/produzido {suffix}"
    )

    send_whatsapp_message(
        OWNER_WHATSAPP,
        message
    )

    order["owner_notified"] = True

    print(
        "PROPRIETARIO AVISADO | "
        f"cliente={suffix}",
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

def handle_owner_command(
    sender,
    body
):

    if sender != OWNER_WHATSAPP:
        return False

    normalized = normalize_text(
        body
    )

    # -----------------------------------------------------
    # PRODUZIDO
    # -----------------------------------------------------

    if normalized.startswith(
        "/produzido"
    ):

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
                (
                    "Não encontrei um cliente "
                    "único com esse final."
                )
            )

            return True

        orders[customer][
            "status"
        ] = "PRODUCAO_CONCLUIDA"

        respond_with_agent(
            customer,
            "[SISTEMA: PRODUCAO CONCLUIDA]"
        )

        send_whatsapp_message(
            sender,
            (
                "✅ Produção marcada como "
                "concluída para o cliente "
                f"final {phone_suffix(customer)}."
            ),
        )

        return True

    # -----------------------------------------------------
    # PAGO
    # -----------------------------------------------------

    if normalized.startswith(
        "/pago"
    ):

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
                (
                    "Não encontrei um cliente "
                    "único com esse final."
                )
            )

            return True

        orders[customer][
            "status"
        ] = "PAGO"

        respond_with_agent(
            customer,
            (
                "[SISTEMA: PAGAMENTO "
                "CONFIRMADO PELO RESPONSAVEL]"
            )
        )

        send_whatsapp_message(
            sender,
            (
                "💰 Pagamento confirmado "
                "para o cliente final "
                f"{phone_suffix(customer)}."
            ),
        )

        return True

    # -----------------------------------------------------
    # STATUS
    # -----------------------------------------------------

    if normalized.startswith(
        "/status"
    ):

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
                "Cliente: final "
                f"{phone_suffix(customer)}\n"
                "Referências: "
                f"{order['reference_count']}\n"
                f"Status: {order['status']}"
            ),
        )

        return True

    return False


# =========================================================
# REFERENCIAS FINALIZADAS
# =========================================================

def customer_finished_references(text):

    normalized = normalize_text(
        text
    )

    expressions = {
        "pronto",
        "terminei",
        "terminei de enviar",
        "so essas",
        "sao essas",
        "essas sao as fotos",
        "pode fazer",
        "pode comecar",
        "pode fazer essas",
        "so essas mesmo",
    }

    if normalized in expressions:
        return True

    return False


def finish_references(sender):

    count = orders[sender][
        "reference_count"
    ]

    if count <= 0:
        return False

    orders[sender][
        "status"
    ] = "AGUARDANDO_PRODUCAO"

    respond_with_agent(
        sender,
        (
            "[SISTEMA: REFERENCIAS FINALIZADAS. "
            f"O cliente enviou {count} fotografia(s) "
            "de referencia. O pedido foi encaminhado "
            "para producao.]"
        )
    )

    if not orders[sender][
        "owner_notified"
    ]:

        notify_owner_ready(
            sender
        )

    return True


# =========================================================
# BUFFER / DEBOUNCE
# =========================================================

def schedule_customer_processing(
    sender,
    delay_type="text"
):

    with buffer_lock:

        old_timer = pending_timers.get(
            sender
        )

        if old_timer:

            try:
                old_timer.cancel()
            except Exception:
                pass

        if delay_type == "photo":

            delay = random.uniform(
                PHOTO_DEBOUNCE_MIN,
                PHOTO_DEBOUNCE_MAX
            )

        else:

            delay = random.uniform(
                TEXT_DEBOUNCE_MIN,
                TEXT_DEBOUNCE_MAX
            )

        timer = threading.Timer(
            delay,
            process_customer_buffer,
            args=(sender,)
        )

        timer.daemon = True

        pending_timers[sender] = timer

        timer.start()

        print(
            "AGUARDANDO SEQUENCIA | "
            f"cliente={phone_suffix(sender)} "
            f"| janela={delay:.1f}s",
            flush=True,
        )


def add_to_customer_buffer(
    sender,
    item,
    delay_type="text"
):

    with buffer_lock:

        pending_messages[sender].append(
            item
        )

    schedule_customer_processing(
        sender,
        delay_type
    )


def process_customer_buffer(sender):

    with buffer_lock:

        items = pending_messages.pop(
            sender,
            []
        )

        pending_timers.pop(
            sender,
            None
        )

    if not items:
        return

    try:

        text_parts = []
        photo_count = 0
        captions = []

        for item in items:

            item_type = item.get(
                "type"
            )

            if item_type == "text":

                text = item.get(
                    "text",
                    ""
                ).strip()

                if text:
                    text_parts.append(text)

            elif item_type == "photo":

                photo_count += 1

                caption = item.get(
                    "caption",
                    ""
                ).strip()

                if caption:
                    captions.append(
                        caption
                    )

        # -------------------------------------------------
        # VERIFICA SE CLIENTE FINALIZOU REFERENCIAS
        # -------------------------------------------------

        for text in text_parts:

            if customer_finished_references(
                text
            ):

                if finish_references(
                    sender
                ):
                    return

        # -------------------------------------------------
        # CONSTROI UMA UNICA MENSAGEM PARA A IA
        # -------------------------------------------------

        context_parts = []

        if photo_count > 0:

            total = orders[sender][
                "reference_count"
            ]

            context_parts.append(
                (
                    "[SISTEMA: O cliente acabou "
                    f"de enviar {photo_count} "
                    "nova(s) fotografia(s) de "
                    "referencia nesta sequencia. "
                    f"Ha {total} fotografia(s) "
                    "de referencia armazenada(s) "
                    "no pedido.]"
                )
            )

        if captions:

            context_parts.append(
                "Legendas das fotografias: "
                + " | ".join(captions)
            )

        if text_parts:

            context_parts.append(
                "Mensagens enviadas pelo cliente "
                "em sequencia:\n"
                + "\n".join(
                    f"- {text}"
                    for text in text_parts
                )
            )

        combined_message = "\n\n".join(
            context_parts
        )

        if not combined_message:
            return

        print(
            "PROCESSANDO SEQUENCIA | "
            f"cliente={phone_suffix(sender)} "
            f"| textos={len(text_parts)} "
            f"| fotos={photo_count}",
            flush=True,
        )

        respond_with_agent(
            sender,
            combined_message
        )

    except Exception as error:

        print(
            "ERRO BUFFER | "
            f"cliente={phone_suffix(sender)} "
            f"| {type(error).__name__}: "
            f"{error}",
            flush=True,
        )


# =========================================================
# ROTAS
# =========================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return (
        "Foto Express Hybrid Agent online",
        200
    )


@app.route(
    "/status",
    methods=["GET"]
)
def status():

    return jsonify({
        "online": True,
        "openai": bool(
            OPENAI_API_KEY
        ),
        "whatsapp": bool(
            WHATSAPP_TOKEN
        ),
        "owner": bool(
            OWNER_WHATSAPP
        ),
        "model": OPENAI_MODEL,
        "debounce": True,
    }), 200


@app.route(
    "/privacy",
    methods=["GET"]
)
def privacy():

    return """
    <!doctype html>
    <html lang="pt-BR">
    <head>
        <meta charset="utf-8">
        <title>Privacidade - Foto Express</title>
    </head>
    <body style="
        font-family:Arial;
        max-width:800px;
        margin:40px auto;
        padding:20px;
        line-height:1.6
    ">
        <h1>Política de Privacidade - Foto Express</h1>

        <p>
        A Foto Express utiliza mensagens e fotografias
        enviadas voluntariamente pelos clientes para
        prestar os serviços solicitados.
        </p>

        <p>
        As informações podem ser processadas por
        provedores tecnológicos necessários à operação,
        incluindo mensageria, hospedagem, automação e
        inteligência artificial.
        </p>

        <p>
        A Foto Express não vende fotografias ou dados
        pessoais dos clientes.
        </p>
    </body>
    </html>
    """, 200


@app.route(
    "/data-deletion",
    methods=["GET"]
)
def data_deletion():

    return """
    <!doctype html>
    <html lang="pt-BR">
    <head>
        <meta charset="utf-8">
        <title>Exclusão de Dados - Foto Express</title>
    </head>
    <body style="
        font-family:Arial;
        max-width:800px;
        margin:40px auto;
        padding:20px;
        line-height:1.6
    ">
        <h1>Exclusão de Dados</h1>

        <p>
        O cliente pode solicitar a exclusão das
        informações e fotografias fornecidas através
        do canal oficial de atendimento da Foto Express.
        </p>
    </body>
    </html>
    """, 200


# =========================================================
# VERIFICACAO WEBHOOK
# =========================================================

@app.route(
    "/webhook",
    methods=["GET"]
)
def verify_webhook():

    mode = request.args.get(
        "hub.mode"
    )

    token = request.args.get(
        "hub.verify_token"
    )

    challenge = request.args.get(
        "hub.challenge"
    )

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

@app.route(
    "/webhook",
    methods=["POST"]
)
def receive_webhook():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    try:

        for entry in data.get(
            "entry",
            []
        ):

            for change in entry.get(
                "changes",
                []
            ):

                value = change.get(
                    "value",
                    {}
                )

                for message in value.get(
                    "messages",
                    []
                ):

                    sender = message.get(
                        "from",
                        ""
                    )

                    message_id = message.get(
                        "id",
                        ""
                    )

                    message_type = message.get(
                        "type",
                        ""
                    )

                    if not sender:
                        continue

                    if already_processed(
                        message_id
                    ):

                        print(
                            "Webhook duplicado ignorado.",
                            flush=True,
                        )

                        continue

                    print(
                        "MENSAGEM | "
                        f"cliente={phone_suffix(sender)} "
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

                        # Comandos do dono sao imediatos.
                        if handle_owner_command(
                            sender,
                            body
                        ):
                            continue

                        # Mensagem normal entra no buffer.
                        add_to_customer_buffer(
                            sender,
                            {
                                "type": "text",
                                "text": body,
                            },
                            delay_type="text",
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

                            add_to_customer_buffer(
                                sender,
                                {
                                    "type": "photo",
                                    "caption": caption,
                                },
                                delay_type="photo",
                            )

                        except Exception as error:

                            print(
                                "ERRO FOTO: "
                                f"{error}",
                                flush=True,
                            )

                            send_whatsapp_message(
                                sender,
                                (
                                    "Tive um problema para "
                                    "receber essa foto. 📸 "
                                    "Pode enviá-la novamente?"
                                ),
                            )

                    # =====================================
                    # DOCUMENTO
                    # =====================================

                    elif message_type == "document":

                        orders[sender][
                            "payment_receipt_received"
                        ] = True

                        orders[sender][
                            "status"
                        ] = (
                            "AGUARDANDO_CONFIRMACAO_PIX"
                        )

                        respond_with_agent(
                            sender,
                            (
                                "[SISTEMA: "
                                "COMPROVANTE RECEBIDO]"
                            )
                        )

                        notify_owner_payment(
                            sender
                        )

                    # =====================================
                    # AUDIO
                    # =====================================

                    elif message_type == "audio":

                        add_to_customer_buffer(
                            sender,
                            {
                                "type": "text",
                                "text": (
                                    "[SISTEMA: O cliente "
                                    "enviou um audio. "
                                    "Neste momento o conteudo "
                                    "do audio nao foi "
                                    "transcrito.]"
                                ),
                            },
                            delay_type="text",
                        )

                    # =====================================
                    # OUTROS
                    # =====================================

                    else:

                        add_to_customer_buffer(
                            sender,
                            {
                                "type": "text",
                                "text": (
                                    "[SISTEMA: O cliente "
                                    "enviou uma mensagem "
                                    f"do tipo {message_type}.]"
                                ),
                            },
                            delay_type="text",
                        )

    except Exception as error:

        print(
            "ERRO WEBHOOK: "
            f"{type(error).__name__}: "
            f"{error}",
            flush=True,
        )

    # IMPORTANTE:
    # Meta recebe 200 imediatamente.
    # Nao esperamos o agente responder.
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
