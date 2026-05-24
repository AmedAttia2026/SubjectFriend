import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# ضع بيانات قاعدة البيانات الخاصة بك هنا
db_user = "YOUR_DB_USERNAME"
db_pass = "YOUR_DB_PASSWORD"
MONGO_URI = os.environ.get("MONGO_URI", f"mongodb+srv://{db_user}:{db_pass}@cluster0.8wawfsu.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")

client = MongoClient(MONGO_URI)
db = client['ml_suite_db']
rooms_collection = db['rooms']

# إعداد لخدمة ملف الـ HTML الرئيسي عند فتح الرابط
@app.route('/')
def serve_index():
    return send_from_directory('..', 'index.html')

@app.route('/api/state', methods=['GET'])
def get_state():
    room = request.args.get('room')
    if not room: return jsonify({"error": "Room required"}), 400
    room_data = rooms_collection.find_one({"room_id": room})
    if not room_data:
        rooms_collection.insert_one({"room_id": room, "answers": {}, "updated_at": datetime.utcnow()})
        return jsonify({"room_id": room, "answers": {}})
    return jsonify({"room_id": room_data["room_id"], "answers": room_data.get("answers", {})})

@app.route('/api/update', methods=['POST'])
def update_state():
    data = request.json
    room, card_id = data.get('room'), data.get('cardId')
    if not room or not card_id: return jsonify({"error": "Invalid data"}), 400
    
    rooms_collection.update_one(
        {"room_id": room},
        {"$set": {
            f"answers.{card_id}.selectedIdx": data.get('selectedIdx'),
            f"answers.{card_id}.status": data.get('status'),
            f"answers.{card_id}.inputValue": data.get('inputValue', ''),
            "updated_at": datetime.utcnow()
        }},
        upsert=True
    )
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(debug=True)