import os
import threading
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime, timezone, timedelta

app = Flask(__name__)
CORS(app)

# تخزين الغرف في الذاكرة الحية المشتركة بين الأجهزة
GLOBAL_ROOMS_DATA = {}

# Lock حديدي لمنع تضارب التحديثات الحية المتزامنة بين الأجهزة
ROOM_LOCK = threading.Lock()

# مدة حذف الغرف غير النشطة تلقائياً لتوفير موارد الذاكرة
ROOM_TIMEOUT_MINUTES = 60


def create_room(room_id):
    return {
        "room_id": room_id,
        "current_sheet": 0,
        "current_mode": "tf",
        "active_card_id": "sheet-0-tf-q-0",
        "answers": {},
        "updated_at": datetime.now(timezone.utc).isoformat()
    }


def cleanup_old_rooms():
    """
    حذف الغرف القديمة تلقائياً من الذاكرة الحية إذا مر عليها ساعة بدون نشاط
    """
    now = datetime.now(timezone.utc)

    with ROOM_LOCK:
        rooms_to_delete = []

        for room_id, room_data in GLOBAL_ROOMS_DATA.items():
            try:
                updated_time = datetime.fromisoformat(room_data["updated_at"])
                if now - updated_time > timedelta(minutes=ROOM_TIMEOUT_MINUTES):
                    rooms_to_delete.append(room_id)
            except Exception:
                continue

        for room_id in rooms_to_delete:
            del GLOBAL_ROOMS_DATA[room_id]


# --- الحل الجذري للمشكلة ---
# جعل السيرفر يخدم الصفحة الرئيسية أو أي ملف HTML فرعي تطلبه تلقائياً
@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def serve_index(path):
    # إذا انتهى المسار بـ .html أو طلب الصفحة الرئيسية، يخدمها من المجلد الرئيسي (الأب لمجلد api)
    return send_from_directory('..', path)


@app.route('/api/state', methods=['GET'])
def get_state():
    room = request.args.get('room')

    if not room:
        return jsonify({"error": "Room required"}), 400

    cleanup_old_rooms()

    with ROOM_LOCK:
        if room not in GLOBAL_ROOMS_DATA:
            GLOBAL_ROOMS_DATA[room] = create_room(room)

        return jsonify(GLOBAL_ROOMS_DATA[room])


@app.route('/api/update', methods=['POST'])
def update_state():
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    room = data.get('room')

    if not room:
        return jsonify({"error": "Room required"}), 400

    card_id = data.get('cardId')
    selected_idx = data.get('selectedIdx')
    status = data.get('status')
    input_value = data.get('inputValue', '')

    cleanup_old_rooms()

    with ROOM_LOCK:
        if room not in GLOBAL_ROOMS_DATA:
            GLOBAL_ROOMS_DATA[room] = create_room(room)

        room_ref = GLOBAL_ROOMS_DATA[room]
        room_ref["updated_at"] = datetime.now(timezone.utc).isoformat()

        # تحديث رقم الشيت الحالي بذكاء جماعي قسري
        if data.get('current_sheet') is not None:
            room_ref["current_sheet"] = int(data.get('current_sheet'))

        # تحديث مود الحل الحالي (MCQ / True/False / وا اكمل)
        if data.get('current_mode') is not None:
            room_ref["current_mode"] = str(data.get('current_mode'))

        # تحديث السؤال النشط حالياً لفرض الـ AutoScroll الموحد
        if data.get('active_card_id') is not None:
            room_ref["active_card_id"] = str(data.get('active_card_id'))

        # حفظ وإثبات إجابات الطلاب حية داخل الذاكرة
        if card_id:
            if "answers" not in room_ref:
                room_ref["answers"] = {}
            
            room_ref["answers"][card_id] = {
                "selectedIdx": selected_idx,
                "status": status,
                "inputValue": input_value,
                "submitted_at": datetime.now(timezone.utc).isoformat()
            }

    return jsonify({
        "success": True,
        "room": room
    })


@app.route('/api/reset', methods=['POST'])
def reset_room():
    data = request.get_json()
    room = data.get('room')

    if not room:
        return jsonify({"error": "Room required"}), 400

    with ROOM_LOCK:
        GLOBAL_ROOMS_DATA[room] = create_room(room)

    return jsonify({
        "success": True,
        "message": "Room reset successfully"
    })


@app.route('/api/rooms', methods=['GET'])
def list_rooms():
    with ROOM_LOCK:
        return jsonify({
            "rooms": list(GLOBAL_ROOMS_DATA.keys()),
            "count": len(GLOBAL_ROOMS_DATA)
        })


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        threaded=True
    )
