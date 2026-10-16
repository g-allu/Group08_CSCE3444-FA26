
from flask import Flask, jsonify, request, send_from_directory
from pathlib import Path
from translator import Translator

app = Flask(__name__)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
translator = Translator()


@app.route("/", methods=["GET"])
def home():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>", methods=["GET"])
def frontend_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# FR-07: Add letter
@app.route("/api/add-letter", methods=["POST"])
def add_letter():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({"error": "JSON object required"}), 400

    letter = data.get("letter")
    result = translator.add_letter(letter)

    if result is None:
        return jsonify({"error": "Enter one letter A-Z"}), 400

    return jsonify({"transcript": result})


# FR-07: Add space
@app.route("/api/add-space", methods=["POST"])
def add_space():
    return jsonify({
        "transcript": translator.add_space()
    })


# FR-08: Delete last character
@app.route("/api/delete-last", methods=["POST"])
def delete_last():
    return jsonify({
        "transcript": translator.delete_last()
    })


# FR-09: Reset session
@app.route("/api/reset", methods=["POST"])
def reset():
    return jsonify({
        "transcript": translator.reset()
    })


# Get current transcript
@app.route("/api/transcript", methods=["GET"])
def get_transcript():
    return jsonify({
        "transcript": translator.get_transcript()
    })


if __name__ == "__main__":
    app.run(debug=True)
