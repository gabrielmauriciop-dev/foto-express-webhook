import os
from flask import Flask, request

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")


# =========================================================
# PÁGINA INICIAL
# =========================================================

@app.route("/", methods=["GET"])
def home():
    return "Foto Express Webhook online", 200


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
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
            <strong>Última atualização: 19 de setembro de 2026.</strong>
        </p>

        <p>
            A Foto Express utiliza o WhatsApp para receber mensagens,
            fotografias e instruções enviadas voluntariamente pelos clientes
            para prestação de serviços de criação, edição e transformação
            de imagens.
        </p>

        <h2>1. Dados que podemos receber</h2>

        <p>
            Podemos receber informações fornecidas pelo próprio cliente,
            incluindo mensagens, número associado ao WhatsApp, fotografias,
            imagens e instruções relacionadas ao serviço solicitado.
        </p>

        <h2>2. Como utilizamos os dados</h2>

        <p>
            Os dados são utilizados para atender o cliente, processar
            solicitações, produzir e entregar imagens, prestar suporte
            e operar o serviço Foto Express.
        </p>

        <h2>3. Fotografias</h2>

        <p>
            As fotografias enviadas pelos clientes são utilizadas para
            executar o serviço solicitado. A Foto Express não vende
            fotografias ou dados pessoais dos clientes.
        </p>

        <h2>4. Compartilhamento e processamento</h2>

        <p>
            Quando necessário para executar o serviço, informações podem
            ser processadas por provedores tecnológicos utilizados na
            operação, incluindo serviços de hospedagem, mensageria,
            automação e processamento de imagens.
        </p>

        <h2>5. Segurança</h2>

        <p>
            A Foto Express adota medidas razoáveis para proteger as
            informações utilizadas durante a prestação do serviço e
            limitar seu acesso às finalidades necessárias à operação.
        </p>

        <h2>6. Exclusão de dados</h2>

        <p>
            O cliente pode solicitar a exclusão dos seus dados pessoais
            e fotografias entrando em contato com a Foto Express pelo
            mesmo canal oficial de WhatsApp utilizado no atendimento.
        </p>

        <p>
            Também disponibilizamos instruções específicas na página
            de exclusão de dados da Foto Express.
        </p>

        <h2>7. Contato</h2>

        <p>
            Para dúvidas sobre privacidade ou solicitações relacionadas
            aos seus dados pessoais, entre em contato com a Foto Express
            pelos canais oficiais de atendimento.
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
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
            Clientes da Foto Express podem solicitar a exclusão de seus
            dados pessoais e fotografias entrando em contato pelo mesmo
            canal oficial de WhatsApp utilizado para o atendimento.
        </p>

        <h2>Como solicitar</h2>

        <p>
            Envie uma mensagem pelo canal oficial de atendimento da
            Foto Express informando que deseja a exclusão dos dados
            relacionados ao seu atendimento.
        </p>

        <p>
            Após a identificação da solicitação, os dados sob controle
            da Foto Express serão tratados de acordo com a legislação
            aplicável e eventuais obrigações legais de retenção.
        </p>

        <h2>Dúvidas</h2>

        <p>
            Para dúvidas relacionadas à privacidade e ao tratamento
            de dados pessoais, entre em contato com a Foto Express
            pelos canais oficiais de atendimento.
        </p>

    </body>
    </html>
    """, 200


# =========================================================
# VERIFICAÇÃO DO WEBHOOK DA META
# =========================================================

@app.route("/webhook", methods=["GET"])
def verify_webhook():

    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200

    return "Forbidden", 403


# =========================================================
# RECEBIMENTO DE MENSAGENS DO WHATSAPP
# =========================================================

@app.route("/webhook", methods=["POST"])
def receive_webhook():

    data = request.get_json(silent=True) or {}

    try:

        entries = data.get("entry", [])

        for entry in entries:

            changes = entry.get("changes", [])

            for change in changes:

                value = change.get("value", {})

                # Ignora atualizações que não contêm mensagens
                messages = value.get("messages", [])

                for message in messages:

                    sender = message.get("from")
                    message_type = message.get("type")

                    print("=" * 60, flush=True)
                    print("NOVA MENSAGEM RECEBIDA", flush=True)
                    print("Cliente:", sender, flush=True)
                    print("Tipo:", message_type, flush=True)

                    # -------------------------------------------------
                    # MENSAGEM DE TEXTO
                    # -------------------------------------------------

                    if message_type == "text":

                        text = message.get("text", {}).get("body", "")

                        print("Texto:", text, flush=True)

                    # -------------------------------------------------
                    # FOTO
                    # -------------------------------------------------

                    elif message_type == "image":

                        image = message.get("image", {})

                        media_id = image.get("id")
                        mime_type = image.get("mime_type")
                        caption = image.get("caption", "")

                        print("FOTO RECEBIDA", flush=True)
                        print("Media ID:", media_id, flush=True)
                        print("Formato:", mime_type, flush=True)

                        if caption:
                            print("Legenda:", caption, flush=True)

                    # -------------------------------------------------
                    # OUTROS TIPOS
                    # -------------------------------------------------

                    else:

                        print(
                            "Tipo ainda não tratado:",
                            message_type,
                            flush=True
                        )

                    print("=" * 60, flush=True)

    except Exception as error:

        # Evita derrubar o webhook caso chegue um evento inesperado
        print(
            "Erro ao processar webhook:",
            str(error),
            flush=True
        )

    # Meta precisa receber HTTP 200 rapidamente
    return "EVENT_RECEIVED", 200


# =========================================================
# INICIALIZAÇÃO
# =========================================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )
