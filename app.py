import os
import json
import urllib.request
import urllib.error

from flask import Flask, request, jsonify

app = Flask(__name__)


# =========================================================
# CONFIGURAÇÃO
# =========================================================

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
WABA_ID = os.environ.get("WABA_ID", "")

GRAPH_API_VERSION = "v26.0"


# =========================================================
# FUNÇÃO PARA CHAMAR A GRAPH API
# =========================================================

def graph_request(path, method="GET", payload=None):

    if not WHATSAPP_TOKEN:
        raise RuntimeError("WHATSAPP_TOKEN nao configurado")

    url = (
        f"https://graph.facebook.com/"
        f"{GRAPH_API_VERSION}/{path}"
    )

    data = None

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request_api = urllib.request.Request(
        url=url,
        data=data,
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        },
        method=method
    )

    try:

        with urllib.request.urlopen(
            request_api,
            timeout=20
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

        try:
            details = json.loads(body)
        except Exception:
            details = {"message": body}

        raise RuntimeError(
            json.dumps(details, ensure_ascii=False)
        )


# =========================================================
# PÁGINA INICIAL
# =========================================================

@app.route("/", methods=["GET"])
def home():

    return "Foto Express Webhook online", 200


# =========================================================
# STATUS
# =========================================================

@app.route("/status", methods=["GET"])
def status():

    return jsonify({
        "online": True,
        "verify_token_configurado": bool(VERIFY_TOKEN),
        "whatsapp_token_configurado": bool(WHATSAPP_TOKEN),
        "phone_number_id_configurado": bool(PHONE_NUMBER_ID),
        "waba_id_configurado": bool(WABA_ID)
    }), 200


# =========================================================
# POLÍTICA DE PRIVACIDADE
# =========================================================

@app.route("/privacy", methods=["GET"])
def privacy():

    return """
    <!DOCTYPE html>
    <html lang="pt-BR">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>Política de Privacidade - Foto Express</title>
    </head>

    <body style="
        font-family: Arial, sans-serif;
        max-width: 800px;
        margin: 40px auto;
        padding: 20px;
        line-height: 1.6;
    ">

        <h1>Política de Privacidade - Foto Express</h1>

        <p>
            <strong>
                Última atualização: 19 de setembro de 2026.
            </strong>
        </p>

        <p>
            A Foto Express utiliza o WhatsApp para receber
            mensagens, fotografias e instruções enviadas
            voluntariamente pelos clientes para prestação
            de serviços de criação, edição e transformação
            de imagens.
        </p>

        <h2>1. Dados que podemos receber</h2>

        <p>
            Podemos receber informações fornecidas pelo
            próprio cliente, incluindo mensagens, número
            associado ao WhatsApp, fotografias, imagens
            e instruções relacionadas ao serviço solicitado.
        </p>

        <h2>2. Como utilizamos os dados</h2>

        <p>
            Os dados são utilizados para atender o cliente,
            processar solicitações, produzir e entregar
            imagens, prestar suporte e operar o serviço
            Foto Express.
        </p>

        <h2>3. Fotografias</h2>

        <p>
            As fotografias enviadas pelos clientes são
            utilizadas para executar o serviço solicitado.
            A Foto Express não vende fotografias ou dados
            pessoais dos clientes.
        </p>

        <h2>4. Compartilhamento e processamento</h2>

        <p>
            Quando necessário para executar o serviço,
            informações podem ser processadas por provedores
            tecnológicos utilizados na operação, incluindo
            serviços de hospedagem, mensageria, automação
            e processamento de imagens.
        </p>

        <h2>5. Segurança</h2>

        <p>
            A Foto Express adota medidas razoáveis para
            proteger as informações utilizadas durante
            a prestação do serviço.
        </p>

        <h2>6. Exclusão de dados</h2>

        <p>
            O cliente pode solicitar a exclusão de seus dados
            entrando em contato com a Foto Express através
            do canal oficial de atendimento no WhatsApp.
        </p>

        <h2>7. Contato</h2>

        <p>
            Para dúvidas relacionadas à privacidade ou
            solicitações referentes aos seus dados,
            entre em contato com a Foto Express através
            do canal oficial de atendimento.
        </p>

    </body>
    </html>
    """, 200


# =========================================================
# EXCLUSÃO DE DADOS
# =========================================================

@app.route("/data-deletion", methods=["GET"])
def data_deletion():

    return """
    <!DOCTYPE html>
    <html lang="pt-BR">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>Exclusão de Dados - Foto Express</title>
    </head>

    <body style="
        font-family: Arial, sans-serif;
        max-width: 800px;
        margin: 40px auto;
        padding: 20px;
        line-height: 1.6;
    ">

        <h1>Solicitação de Exclusão de Dados</h1>

        <p>
            Os clientes da Foto Express podem solicitar
            a exclusão de informações e fotografias
            fornecidas durante o atendimento.
        </p>

        <p>
            Para solicitar a exclusão, entre em contato
            através do canal oficial de atendimento da
            Foto Express no WhatsApp e informe que deseja
            excluir seus dados.
        </p>

        <p>
            A solicitação será processada respeitando
            eventuais obrigações legais de retenção
            aplicáveis.
        </p>

    </body>
    </html>
    """, 200


# =========================================================
# CONSULTAR ASSINATURA DA WABA
# =========================================================

@app.route("/check-subscription", methods=["GET"])
def check_subscription():

    if not WABA_ID:
        return jsonify({
            "ok": False,
            "error": "WABA_ID nao configurado"
        }), 500

    if not WHATSAPP_TOKEN:
        return jsonify({
            "ok": False,
            "error": "WHATSAPP_TOKEN nao configurado"
        }), 500

    try:

        result = graph_request(
            f"{WABA_ID}/subscribed_apps",
            method="GET"
        )

        return jsonify({
            "ok": True,
            "subscription": result
        }), 200

    except Exception as error:

        return jsonify({
            "ok": False,
            "error": str(error)
        }), 500


# =========================================================
# ASSINAR O APP NA WABA
# ROTA TEMPORÁRIA DE CONFIGURAÇÃO
# =========================================================

@app.route("/subscribe-waba", methods=["GET"])
def subscribe_waba():

    if not WABA_ID:
        return jsonify({
            "ok": False,
            "error": "WABA_ID nao configurado"
        }), 500

    if not WHATSAPP_TOKEN:
        return jsonify({
            "ok": False,
            "error": "WHATSAPP_TOKEN nao configurado"
        }), 500

    try:

        result = graph_request(
            f"{WABA_ID}/subscribed_apps",
            method="POST"
        )

        return jsonify({
            "ok": True,
            "resultado": result
        }), 200

    except Exception as error:

        return jsonify({
            "ok": False,
            "error": str(error)
        }), 500


# =========================================================
# WEBHOOK - VERIFICAÇÃO DA META
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

        print(
            "WEBHOOK VERIFICADO COM SUCESSO",
            flush=True
        )

        return challenge, 200

    print(
        "FALHA NA VERIFICACAO DO WEBHOOK",
        flush=True
    )

    return "Forbidden", 403


# =========================================================
# WEBHOOK - RECEBER EVENTOS
# =========================================================

@app.route("/webhook", methods=["POST"])
def receive_webhook():

    try:

        data = request.get_json(silent=True) or {}

        print(
            "\n====================================",
            flush=True
        )

        print(
            "NOVO EVENTO RECEBIDO DA META",
            flush=True
        )

        print(
            "====================================",
            flush=True
        )

        entries = data.get("entry", [])

        for entry in entries:

            changes = entry.get("changes", [])

            for change in changes:

                field = change.get("field", "")
                value = change.get("value", {})

                print(
                    f"Campo: {field}",
                    flush=True
                )

                # =========================================
                # MENSAGENS
                # =========================================

                messages = value.get("messages", [])

                for message in messages:

                    sender = message.get("from", "")
                    message_id = message.get("id", "")
                    message_type = message.get("type", "")

                    print(
                        f"Remetente: {sender}",
                        flush=True
                    )

                    print(
                        f"Message ID: {message_id}",
                        flush=True
                    )

                    print(
                        f"Tipo: {message_type}",
                        flush=True
                    )

                    # -------------------------------------
                    # TEXTO
                    # -------------------------------------

                    if message_type == "text":

                        text_data = message.get(
                            "text",
                            {}
                        )

                        body = text_data.get(
                            "body",
                            ""
                        )

                        print(
                            f"Texto: {body}",
                            flush=True
                        )

                    # -------------------------------------
                    # IMAGEM
                    # -------------------------------------

                    elif message_type == "image":

                        image_data = message.get(
                            "image",
                            {}
                        )

                        media_id = image_data.get(
                            "id",
                            ""
                        )

                        mime_type = image_data.get(
                            "mime_type",
                            ""
                        )

                        caption = image_data.get(
                            "caption",
                            ""
                        )

                        print(
                            f"Media ID: {media_id}",
                            flush=True
                        )

                        print(
                            f"MIME: {mime_type}",
                            flush=True
                        )

                        print(
                            f"Legenda: {caption}",
                            flush=True
                        )

                    # -------------------------------------
                    # OUTROS TIPOS
                    # -------------------------------------

                    else:

                        print(
                            f"Tipo ainda nao tratado: "
                            f"{message_type}",
                            flush=True
                        )

                # =========================================
                # STATUS DE MENSAGENS
                # =========================================

                statuses = value.get("statuses", [])

                for status_item in statuses:

                    status_name = status_item.get(
                        "status",
                        ""
                    )

                    print(
                        f"Status WhatsApp: {status_name}",
                        flush=True
                    )

        print(
            "====================================\n",
            flush=True
        )

    except Exception as error:

        print(
            f"ERRO AO PROCESSAR WEBHOOK: {error}",
            flush=True
        )

    # Meta precisa receber HTTP 200 rapidamente.
    return "EVENT_RECEIVED", 200


# =========================================================
# INICIAR APLICAÇÃO
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
