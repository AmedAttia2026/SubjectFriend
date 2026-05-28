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
        "voice_peers": [],  # مصفوفة لتخزين معرفات الصوت النشطة للجروب
        "active_users": {},  # تخزين أسماء المستخدمين النشطين وتوقيت تواجدهم { peer_id: { "username": username, "last_seen": timestamp } }
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


@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def serve_index(path):
    return send_from_directory('..', path)


@app.route('/api/state', methods=['GET'])
def get_state():
    room = request.args.get('room')
    peer_id = request.args.get('peer_id')  # استقبال معرف الصوت للجهاز الحالي
    username = request.args.get('username')  # استقبال اسم الطالب النشط للربط والمزامنة

    if not room:
        return jsonify({"error": "Room required"}), 400

    cleanup_old_rooms()

    with ROOM_LOCK:
        if room not in GLOBAL_ROOMS_DATA:
            GLOBAL_ROOMS_DATA[room] = create_room(room)

        room_ref = GLOBAL_ROOMS_DATA[room]
        now_ts = datetime.now(timezone.utc).timestamp()
        
        # تسجيل معرف الصوت للجهاز الحالي إذا لم يكن مسجلاً مسبقاً
        if peer_id and peer_id not in room_ref["voice_peers"]:
            room_ref["voice_peers"].append(peer_id)
            room_ref["updated_at"] = datetime.now(timezone.utc).isoformat()

        # مزامنة وتسجيل اسم الطالب النشط المرتبط بالـ peer_id مع تحديث وقت التواجد (Heartbeat)
        if peer_id and username:
            if "active_users" not in room_ref or not isinstance(room_ref["active_users"], dict):
                room_ref["active_users"] = {}
            room_ref["active_users"][peer_id] = {
                "username": username,
                "last_seen": now_ts
            }
            room_ref["updated_at"] = datetime.now(timezone.utc).isoformat()

        # تنظيف المستخدمين الذين غادروا ولم يرسلوا نبضات حية خلال 15 ثانية
        if "active_users" in room_ref and isinstance(room_ref["active_users"], dict):
            expired_peers = []
            for pid, user_info in list(room_ref["active_users"].items()):
                if isinstance(user_info, dict):
                    last_seen = user_info.get("last_seen", 0)
                    if now_ts - last_seen > 15.0:  # 15 ثانية حد أقصى للغياب
                        expired_peers.append(pid)
                else:
                    expired_peers.append(pid)
            
            for pid in expired_peers:
                del room_ref["active_users"][pid]
                if pid in room_ref["voice_peers"]:
                    room_ref["voice_peers"].remove(pid)
                room_ref["updated_at"] = datetime.now(timezone.utc).isoformat()

        # تحويل بيانات الأعضاء النشطين لبنية مبسطة متوافقة مع واجهة العميل { peer_id: username }
        client_active_users = {}
        if "active_users" in room_ref and isinstance(room_ref["active_users"], dict):
            for pid, user_info in room_ref["active_users"].items():
                if isinstance(user_info, dict):
                    client_active_users[pid] = user_info.get("username", "Anonymous")
                else:
                    client_active_users[pid] = user_info

        # إنشاء نسخة لإرسالها للعميل مع الحفاظ على البيانات الأصلية بالخادم
        response_data = dict(room_ref)
        response_data["active_users"] = client_active_users

        return jsonify(response_data)


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

        if data.get('current_sheet') is not None:
            room_ref["current_sheet"] = int(data.get('current_sheet'))

        if data.get('current_mode') is not None:
            room_ref["current_mode"] = str(data.get('current_mode'))

        if data.get('active_card_id') is not None:
            room_ref["active_card_id"] = str(data.get('active_card_id'))

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


if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        threaded=True
    )
