import os
from flask import Flask, request

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")


@app.route("/", methods=["GET"])
def home():
    return "Foto Express Webhook online", 200


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200

    return "Forbidden", 403


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

                    if message_type == "text":
                        text = message.get("text", {}).get("body", "")
                        print("Texto:", text, flush=True)

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

                    else:
                        print("Tipo ainda não tratado:", message_type, flush=True)

                    print("=" * 60, flush=True)

    except Exception as error:
        # Não derruba o webhook se chegar algum evento inesperado
        print("Erro ao processar webhook:", str(error), flush=True)

    return "EVENT_RECEIVED", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
