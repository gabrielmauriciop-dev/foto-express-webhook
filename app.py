import os
import json
import time
import uuid
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

GRAPH_API_VERSION = "v26.0"
OPENAI_MODEL = "gpt-5.6-luna"

TEMP_DIR = "/tmp/foto_express"

os.makedirs(TEMP_DIR, exist_ok=True)

client = OpenAI(api_key=OPENAI_API_KEY)


# =========================================================
# MEMORIA TEMPORARIA
# =========================================================

conversations = defaultdict(
    lambda: deque(maxlen=20)
)

customer_photos = defaultdict(list)

processed_messages = {}

MESSAGE_TTL = 60 * 60 * 24


# =========================================================
# INSTRUCOES DO AGENTE
# =========================================================

AGENT_INSTRUCTIONS = """
Voce e o atendente comercial da Foto Express no WhatsApp.

Voce conversa diretamente com clientes brasileiros interessados
em transformar fotos comuns de celular em fotografias profissionais.

Seu objetivo e atender bem, entender o que o cliente deseja e
conduzir naturalmente a venda.

==================================================
COMO FUNCIONA
==================================================

O cliente envia uma fotografia.

A Foto Express transforma essa fotografia em fotografias
profissionais com diferentes cenarios, roupas e estilos.

O cliente ve uma previa antes de pagar.

Depois da confirmacao do pagamento, recebe as fotografias
finais em alta qualidade e sem marca d'agua.

==================================================
PRECOS
==================================================

4 fotos = R$10
10 fotos = R$20
20 fotos = R$35

O principal pacote e:

10 fotos por R$20.

==================================================
VENDA
==================================================

Nao despeje todos os precos logo no inicio.

Converse naturalmente.

Quando apropriado, recomende principalmente:

10 fotos por R$20.

Explique que sao 10 fotografias diferentes e que o cliente
recebe as 10.

Se o cliente achar caro ou recusar claramente R$20,
ofereca:

4 fotos por R$10.

Se quiser mais fotos ou perguntar por pacote maior,
ofereca:

20 fotos por R$35.

Se perguntar diretamente todos os precos,
informe os tres.

Nunca invente descontos.

Nunca altere os precos.

Nunca prometa brindes.

==================================================
PREVIA
==================================================

Um diferencial importante e:

O CLIENTE VE A PREVIA ANTES DE PAGAR.

Use isso naturalmente quando houver inseguranca.

Nunca diga que uma fotografia ou previa esta pronta
se o sistema nao informou isso.

==================================================
PIX
==================================================

Nunca invente chave PIX.

Se o cliente disser claramente que quer pagar,
fechar ou pedir a chave PIX, diga que os dados de
pagamento serao enviados pelo atendimento.

==================================================
FOTOGRAFIAS
==================================================

Quando receber a informacao do sistema:

"[SISTEMA: FOTO RECEBIDA E ARMAZENADA]"

isso significa que a fotografia foi realmente recebida
e baixada pelo sistema.

Nesse caso, confirme brevemente o recebimento.

Se o cliente ja explicou o estilo desejado, nao pergunte
novamente.

Se ainda nao informou estilo e isso for importante,
pergunte de maneira natural.

Exemplos:

terno
executivo
casual
praia
fazenda
agro
casal
familia
aniversario
gospel
estudio
profissional
corpo inteiro

==================================================
CONVERSA
==================================================

Fale em portugues brasileiro.

Seja humano, simpatico, breve e profissional.

Normalmente use entre 1 e 4 frases.

Pode usar poucos emojis.

Nao diga que e inteligencia artificial.

Nao reinicie a conversa a cada mensagem.

Nao repita saudacoes.

Nao pergunte novamente algo que o cliente ja respondeu.

Use todo o historico apresentado para interpretar
respostas curtas como:

"sim"
"quero"
"pode ser"
"fechado"
"essa"
"10"
"20"

==================================================
PROBLEMAS
==================================================

Reclamacoes serias, problemas de pagamento, reembolso,
questoes juridicas ou situacoes que voce nao consegue
resolver com seguranca devem ser encaminhadas ao
responsavel pelo atendimento.

Nao invente solucoes.

==================================================
REGRA PRINCIPAL
==================================================

Responda ao que o cliente realmente disse considerando
todo o historico.

Nao use resposta fixa.

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


# =========================================================
# GRAPH API
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


# =========================================================
# ENVIAR WHATSAPP
# =========================================================

def send_whatsapp_message(
    to,
    text
):

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
# MIDIA DO WHATSAPP
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


def download_media_file(
    media_url,
    destination
):

    if not media_url:
        raise RuntimeError(
            "URL da midia nao encontrada"
        )

    req = urllib.request.Request(
        url=media_url,
        headers={
            "Authorization":
                f"Bearer {WHATSAPP_TOKEN}",
        },
        method="GET",
    )

    try:

        with urllib.request.urlopen(
            req,
            timeout=60
        ) as response:

            content = response.read()

            if not content:
                raise RuntimeError(
                    "Arquivo baixado esta vazio"
                )

            with open(
                destination,
                "wb"
            ) as file:
                file.write(content)

            return len(content)

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
            f"Erro ao baixar midia "
            f"HTTP {error.code}: {body}"
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
            "Webhook de imagem sem Media ID"
        )

    print(
        "Consultando fotografia na Meta...",
        flush=True,
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

    if not os.path.exists(destination):
        raise RuntimeError(
            "Arquivo nao encontrado apos download"
        )

    customer_photos[sender].append({
        "path": destination,
        "mime_type": mime_type,
        "size": size,
        "received_at": time.time(),
    })

    # Mantemos no maximo as 10 referencias
    # mais recentes por cliente nesta fase.
    customer_photos[sender] = (
        customer_photos[sender][-10:]
    )

    print(
        "FOTO BAIXADA COM SUCESSO",
        flush=True,
    )

    print(
        f"Tipo: {mime_type}",
        flush=True,
    )

    print(
        f"Tamanho: {size} bytes",
        flush=True,
    )

    print(
        "Arquivo temporario criado.",
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

    history = conversations[sender]

    input_messages = []

    for item in history:

        input_messages.append({
            "role": item["role"],
            "content": item["content"],
        })

    input_messages.append({
        "role": "user",
        "content": current_message,
    })

    return input_messages


def ask_agent(
    sender,
    customer_message
):

    input_messages = (
        build_conversation_input(
            sender,
            customer_message
        )
    )

    response = client.responses.create(
        model=OPENAI_MODEL,
        reasoning={
            "effort": "low"
        },
        instructions=AGENT_INSTRUCTIONS,
        input=input_messages,
    )

    answer = (
        response.output_text
        or ""
    ).strip()

    if not answer:

        answer = (
            "Recebi sua mensagem 😊 "
            "Pode me explicar um "
            "pouquinho mais?"
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
            "Agente respondeu para "
            f"{mask_phone(sender)}",
            flush=True,
        )

    except Exception as error:

        print(
            "ERRO NO AGENTE: "
            f"{type(error).__name__}: "
            f"{error}",
            flush=True,
        )

        try:

            send_whatsapp_message(
                sender,
                (
                    "Tive um probleminha "
                    "para processar sua "
                    "mensagem agora. 😊 "
                    "Pode tentar novamente "
                    "em instantes?"
                ),
            )

        except Exception as send_error:

            print(
                "ERRO NO ENVIO DE EMERGENCIA: "
                f"{send_error}",
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
        "Foto Express Agent online",
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
        "phone_number": bool(
            PHONE_NUMBER_ID
        ),
        "webhook": bool(
            VERIFY_TOKEN
        ),
        "model": OPENAI_MODEL,
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
        <title>
            Privacidade - Foto Express
        </title>
    </head>

    <body style="
        font-family:Arial;
        max-width:800px;
        margin:40px auto;
        padding:20px;
        line-height:1.6
    ">

        <h1>
            Política de Privacidade -
            Foto Express
        </h1>

        <p>
            A Foto Express utiliza informações
            enviadas voluntariamente pelos clientes
            através do WhatsApp para prestar serviços
            de criação e edição de imagens.
        </p>

        <p>
            Isso pode incluir mensagens, fotografias
            e informações necessárias para executar
            o serviço solicitado.
        </p>

        <p>
            As informações podem ser processadas
            por provedores tecnológicos necessários
            à operação do serviço, incluindo
            mensageria, hospedagem, automação e
            inteligência artificial.
        </p>

        <p>
            A Foto Express não vende fotografias
            ou dados pessoais dos clientes.
        </p>

        <p>
            O cliente pode solicitar informações
            ou exclusão de seus dados através do
            canal oficial de atendimento.
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
        <title>
            Exclusão de Dados - Foto Express
        </title>
    </head>

    <body style="
        font-family:Arial;
        max-width:800px;
        margin:40px auto;
        padding:20px;
        line-height:1.6
    ">

        <h1>
            Exclusão de Dados
        </h1>

        <p>
            Clientes da Foto Express podem solicitar
            a exclusão das informações e fotografias
            fornecidas durante o atendimento.
        </p>

        <p>
            A solicitação pode ser feita através do
            canal oficial de atendimento da
            Foto Express no WhatsApp.
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
# RECEBER WEBHOOK
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
                        "Mensagem recebida de "
                        f"{mask_phone(sender)} "
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

                        if body:

                            respond_with_agent(
                                sender,
                                body
                            )

                    # =====================================
                    # IMAGEM
                    # =====================================

                    elif message_type == "image":

                        image_data = (
                            message.get(
                                "image",
                                {}
                            )
                        )

                        caption = (
                            image_data
                            .get(
                                "caption",
                                ""
                            )
                            .strip()
                        )

                        try:

                            receive_customer_photo(
                                sender,
                                image_data
                            )

                            system_message = (
                                "[SISTEMA: "
                                "FOTO RECEBIDA E "
                                "ARMAZENADA. "
                                "A fotografia do "
                                "cliente foi baixada "
                                "com sucesso."
                            )

                            if caption:

                                system_message += (
                                    " O cliente enviou "
                                    "junto a seguinte "
                                    "legenda: "
                                    f"{caption}"
                                )

                            system_message += "]"

                            respond_with_agent(
                                sender,
                                system_message
                            )

                        except Exception as error:

                            print(
                                "ERRO AO RECEBER FOTO: "
                                f"{type(error).__name__}: "
                                f"{error}",
                                flush=True,
                            )

                            send_whatsapp_message(
                                sender,
                                (
                                    "Recebi sua foto, "
                                    "mas tive um problema "
                                    "ao processar o arquivo. "
                                    "📸 Pode me enviar essa "
                                    "foto novamente?"
                                ),
                            )

                    # =====================================
                    # AUDIO
                    # =====================================

                    elif message_type == "audio":

                        send_whatsapp_message(
                            sender,
                            (
                                "Recebi seu áudio 😊 "
                                "Por enquanto, pode me "
                                "mandar por escrito para "
                                "eu te atender direitinho?"
                            ),
                        )

                    # =====================================
                    # OUTROS
                    # =====================================

                    else:

                        send_whatsapp_message(
                            sender,
                            (
                                "Recebi sua mensagem 😊 "
                                "Pode me enviar por texto "
                                "ou mandar sua foto "
                                "por aqui."
                            ),
                        )

    except Exception as error:

        print(
            "ERRO WEBHOOK: "
            f"{type(error).__name__}: "
            f"{error}",
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
