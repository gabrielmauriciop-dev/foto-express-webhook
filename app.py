import os
import json
import time
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

client = OpenAI(api_key=OPENAI_API_KEY)

# Memoria simples para a fase de testes.
# Mantem as ultimas mensagens de cada cliente enquanto
# esta instancia do Render estiver ativa.
conversations = defaultdict(lambda: deque(maxlen=20))

# Evita responder duas vezes caso a Meta repita um webhook.
processed_messages = {}
MESSAGE_TTL = 60 * 60 * 24


# =========================================================
# REGRAS DO AGENTE FOTO EXPRESS
# =========================================================

AGENT_INSTRUCTIONS = """
Voce e o atendente comercial da Foto Express no WhatsApp.

Voce conversa diretamente com clientes brasileiros interessados
em transformar fotos comuns de celular em fotografias profissionais.

Seu objetivo e atender bem, entender o que o cliente deseja e
conduzir naturalmente a venda.

==================================================
COMO FUNCIONA A FOTO EXPRESS
==================================================

O cliente envia uma foto.

A Foto Express transforma essa foto em fotografias profissionais,
com diferentes cenarios, roupas e estilos.

O cliente pode ver uma previa antes de pagar.

Depois da confirmacao do pagamento, as fotografias finais sao
entregues em alta qualidade e sem marca d'agua.

==================================================
PRECOS
==================================================

4 fotos = R$10
10 fotos = R$20
20 fotos = R$35

O pacote principal e mais recomendado e:

10 fotos por R$20.

==================================================
REGRA COMERCIAL
==================================================

Nao comece despejando todos os precos.

Primeiro converse naturalmente.

Quando apropriado, recomende principalmente:

10 fotos por R$20.

Explique que sao 10 fotos diferentes e que o cliente recebe
as 10 fotos.

Se o cliente achar caro, disser que nao pode pagar R$20 ou
recusar claramente o pacote de R$20, ofereca:

4 fotos por R$10.

Se o cliente demonstrar que quer mais fotos ou perguntar por
um pacote maior, ofereca:

20 fotos por R$35.

Se ele perguntar diretamente todos os precos, informe os tres.

==================================================
ANTES DO PAGAMENTO
==================================================

O grande diferencial da Foto Express e:

O CLIENTE VE A PREVIA ANTES DE PAGAR.

Use isso naturalmente quando houver inseguranca ou duvida.

Nunca pressione agressivamente.

Nunca invente desconto.

Nunca altere os precos.

Nunca prometa brindes ou fotos extras.

==================================================
PIX
==================================================

Nao invente chave PIX.

Nao solicite pagamento antes de o cliente decidir comprar.

Se o cliente disser claramente que quer pagar, fechar,
fazer o PIX ou pedir a chave PIX, diga:

"Perfeito 😊 Vou te passar os dados para pagamento."

Em seguida diga que os dados de pagamento serao enviados
pelo atendimento.

Nao invente CPF, telefone, e-mail ou chave PIX.

==================================================
FOTOS
==================================================

Quando o sistema informar que o cliente enviou uma foto,
confirme que a foto foi recebida.

Pergunte sobre o estilo somente se isso ainda for necessario.

Exemplos de estilos que o cliente pode pedir:

- terno
- executivo
- casual
- praia
- fazenda
- agro
- casal
- familia
- aniversario
- gospel
- profissional
- estudio
- corpo inteiro

Se o cliente ja informou o estilo anteriormente, nao pergunte
a mesma coisa novamente.

Nao diga que a imagem foi produzida se o sistema ainda nao
informou isso.

Nao diga que uma previa esta pronta se ela ainda nao estiver pronta.

==================================================
CONVERSA
==================================================

Fale em portugues brasileiro.

Seja simpatico, humano, breve e profissional.

WhatsApp exige mensagens curtas.

Normalmente responda em 1 a 4 frases.

Pode usar poucos emojis de forma natural.

Nao pareca um chatbot.

Nao diga:
"Sou uma inteligencia artificial."
"Sou um assistente virtual."
"Como posso ajuda-lo hoje?"

Nao repita saudacoes em todas as mensagens.

Nao repita informacoes que o cliente ja forneceu.

Leia o historico antes de responder.

Se o cliente disser apenas "sim", "quero", "pode ser",
"fechado" ou algo semelhante, interprete usando o historico.

==================================================
EXEMPLOS
==================================================

Cliente:
"Oi"

Resposta possivel:
"Olá! 😊 Você quer transformar uma foto sua em um ensaio profissional? Você consegue ver o resultado antes de pagar."

Cliente:
"Quanto custa?"

Resposta possivel:
"O mais escolhido é o ensaio com 10 fotos por R$20 😊 São 10 fotos diferentes e você recebe todas em alta qualidade. Você vê a prévia antes de pagar."

Cliente:
"Tem mais barato?"

Resposta:
"Tenho sim 😊 A opção menor é de 4 fotos por R$10."

Cliente:
"Quero de terno"

Resposta possivel:
"Perfeito! 👔 Podemos fazer seu ensaio com um estilo elegante de terno. Pode me enviar uma foto sua aqui."

Cliente:
"Quero 20"

Resposta:
"Perfeito 😊 O ensaio com 20 fotos fica R$35, com bastante variedade de cenários, roupas e estilos. Pode me enviar sua foto."

==================================================
PROBLEMAS
==================================================

Se houver reclamacao seria, problema de pagamento, pedido de
reembolso, ameaca, assunto juridico ou uma situacao que voce
nao consegue resolver com seguranca, diga de forma natural
que vai encaminhar para o responsavel pelo atendimento.

Nao invente solucoes.

==================================================
REGRA MAIS IMPORTANTE
==================================================

Responda ao que o cliente realmente disse considerando TODO
o historico apresentado.

Nao use uma resposta fixa.

Nao reinicie a conversa a cada mensagem.
"""


# =========================================================
# FUNCOES AUXILIARES
# =========================================================

def mask_phone(phone):
    if not phone:
        return "desconhecido"

    if len(phone) <= 4:
        return "****"

    return "*" * (len(phone) - 4) + phone[-4:]


def cleanup_processed_messages():
    now = time.time()

    expired = [
        message_id
        for message_id, timestamp in processed_messages.items()
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


# =========================================================
# META GRAPH API
# =========================================================

def graph_request(path, method="GET", payload=None):

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
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")

            if not body:
                return {}

            return json.loads(body)

    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Erro Meta HTTP {error.code}: {body}"
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
# AGENTE OPENAI
# =========================================================

def build_conversation_input(sender, current_message):

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


def ask_agent(sender, customer_message):

    input_messages = build_conversation_input(
        sender,
        customer_message,
    )

    response = client.responses.create(
        model=OPENAI_MODEL,
        reasoning={"effort": "low"},
        instructions=AGENT_INSTRUCTIONS,
        input=input_messages,
    )

    answer = (response.output_text or "").strip()

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
            customer_message,
        )

        send_whatsapp_message(
            sender,
            answer,
        )

        print(
            f"Agente respondeu para {mask_phone(sender)}",
            flush=True,
        )

    except Exception as error:

        print(
            f"ERRO NO AGENTE: {type(error).__name__}: {error}",
            flush=True,
        )

        try:
            send_whatsapp_message(
                sender,
                (
                    "Tive um probleminha para processar "
                    "sua mensagem agora. 😊 "
                    "Pode me mandar novamente em instantes?"
                ),
            )
        except Exception as send_error:
            print(
                f"ERRO NO ENVIO DE EMERGENCIA: {send_error}",
                flush=True,
            )


# =========================================================
# ROTAS
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return "Foto Express Agent online", 200


@app.route("/status", methods=["GET"])
def status():

    return jsonify({
        "online": True,
        "openai": bool(OPENAI_API_KEY),
        "whatsapp": bool(WHATSAPP_TOKEN),
        "phone_number": bool(PHONE_NUMBER_ID),
        "webhook": bool(VERIFY_TOKEN),
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
        A Foto Express utiliza informações enviadas
        voluntariamente pelos clientes através do WhatsApp
        para prestar serviços de criação e edição de imagens.
        </p>

        <p>
        Isso pode incluir mensagens, fotografias e informações
        necessárias para executar o serviço solicitado.
        </p>

        <p>
        As informações podem ser processadas por provedores
        tecnológicos necessários à operação do serviço,
        incluindo serviços de mensageria, hospedagem,
        automação e inteligência artificial.
        </p>

        <p>
        A Foto Express não vende fotografias ou dados pessoais
        dos clientes.
        </p>

        <p>
        O cliente pode solicitar informações ou exclusão de
        seus dados através do canal oficial de atendimento
        da Foto Express.
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
        Clientes da Foto Express podem solicitar a exclusão
        das informações e fotografias fornecidas durante
        o atendimento.
        </p>

        <p>
        A solicitação pode ser feita através do canal oficial
        de atendimento da Foto Express no WhatsApp.
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
# RECEBER WEBHOOK
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
                        f"Mensagem recebida de "
                        f"{mask_phone(sender)} | "
                        f"tipo={message_type}",
                        flush=True,
                    )

                    # -------------------------------------
                    # TEXTO
                    # -------------------------------------

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
                                body,
                            )

                    # -------------------------------------
                    # FOTO
                    # -------------------------------------

                    elif message_type == "image":

                        image_data = message.get(
                            "image",
                            {},
                        )

                        caption = (
                            image_data
                            .get("caption", "")
                            .strip()
                        )

                        system_message = (
                            "[SISTEMA FOTO EXPRESS: "
                            "O cliente acabou de enviar "
                            "uma fotografia pelo WhatsApp."
                        )

                        if caption:
                            system_message += (
                                f" A legenda escrita pelo "
                                f"cliente foi: {caption}"
                            )

                        system_message += "]"

                        respond_with_agent(
                            sender,
                            system_message,
                        )

                    # -------------------------------------
                    # AUDIO
                    # -------------------------------------

                    elif message_type == "audio":

                        send_whatsapp_message(
                            sender,
                            (
                                "Recebi seu áudio 😊 "
                                "Por enquanto, pode me mandar "
                                "a mensagem por escrito para "
                                "eu te atender direitinho?"
                            ),
                        )

                    # -------------------------------------
                    # OUTROS
                    # -------------------------------------

                    else:

                        send_whatsapp_message(
                            sender,
                            (
                                "Recebi sua mensagem 😊 "
                                "Se puder, me envie por texto "
                                "ou mande sua foto por aqui."
                            ),
                        )

    except Exception as error:

        print(
            f"ERRO WEBHOOK: {type(error).__name__}: {error}",
            flush=True,
        )

    # Meta precisa receber 200.
    return "EVENT_RECEIVED", 200


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000,
        )
    )

    app.run(
        host="0.0.0.0",
        port=port,
    )
