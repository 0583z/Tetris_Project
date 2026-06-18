import socket
import threading
import json
import os

HOST, PORT = '0.0.0.0', 5555
DB_FILE = 'server_accounts.json'

# 全局内存数据库与在线会话追踪
# online_players 结构: { "用户名": socket_conn }
online_players = {}
online_lock = threading.Lock()
db_lock = threading.Lock()

def load_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

def save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def broadcast_status_to_friends(username, status):
    """通知所有在线好友该玩家的状态改变 (online / offline)"""
    with db_lock:
        db = load_db()
        friends = list(db.get(username, {}).get("friends", []))
    if friends:
        msg = json.dumps({"type": "friend_status", "username": username, "status": status}) + "\n"
        with online_lock:
            for f in friends:
                if f in online_players:
                    try: online_players[f].sendall(msg.encode('utf-8'))
                    except: pass

def handle_client(conn, addr):
    my_username = None
    buffer = ""
    print(f"📡 新的网络连接接入: {addr}")
    
    while True:
        try:
            data = conn.recv(4096).decode('utf-8')
            if not data: break
            buffer += data
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if not line.strip(): continue
                msg = json.loads(line)
                m_type = msg.get("type")
                
                # --- 1. 登录/注册系统 ---
                if m_type == "login":
                    username = msg.get("username", "").strip()
                    if not username:
                        conn.sendall((json.dumps({"type": "login_resp", "success": False, "reason": "用户名不能为空"}) + "\n").encode('utf-8'))
                        continue

                    with db_lock:
                        db = load_db()
                        # 如果账号不存在则自动创建（极简无密码注册）
                        if username not in db:
                            db[username] = {"friends": [], "requests": []}
                            save_db(db)
                        friends_list = list(db[username].get("friends", []))
                        requests_list = list(db[username].get("requests", []))

                    with online_lock:
                        if username in online_players:
                            conn.sendall((json.dumps({"type": "login_resp", "success": False, "reason": "该账号已在别处登录"}) + "\n").encode('utf-8'))
                            continue
                        online_players[username] = conn
                        my_username = username
                        friends_status = {f: ("online" if f in online_players else "offline") for f in friends_list}

                    resp = {
                        "type": "login_resp",
                        "success": True,
                        "username": username,
                        "friends": friends_status,
                        "requests": requests_list
                    }
                    conn.sendall((json.dumps(resp) + "\n").encode('utf-8'))

                    # 广播给自己所有在线好友：我上线了
                    broadcast_status_to_friends(username, "online")
                
                # --- 2. 添加好友申请 ---
                elif m_type == "add_friend":
                    target = msg.get("target", "").strip()
                    if target == my_username:
                        conn.sendall((json.dumps({"type": "toast", "msg": "不能添加自己为好友"}) + "\n").encode('utf-8'))
                        continue

                    toast_msg = None
                    with db_lock:
                        db = load_db()
                        if target not in db:
                            toast_msg = f"玩家 {target} 不存在"
                        elif target in db[my_username].get("friends", []):
                            toast_msg = "你们已经是好友了"
                        elif my_username in db[target].get("requests", []):
                            toast_msg = "已发送过申请，请勿重复发送"
                        else:
                            # 存入目标用户的申请列表
                            db[target]["requests"].append(my_username)
                            save_db(db)
                            toast_msg = "好友申请已发出"

                    if toast_msg:
                        conn.sendall((json.dumps({"type": "toast", "msg": toast_msg}) + "\n").encode('utf-8'))

                    # 如果目标用户在线且申请成功，实时推送申请通知
                    if toast_msg == "好友申请已发出":
                        with online_lock:
                            if target in online_players:
                                online_players[target].sendall((json.dumps({"type": "new_request", "from": my_username}) + "\n").encode('utf-8'))

                # --- 3. 同意好友申请 ---
                elif m_type == "accept_friend":
                    from_user = msg.get("from", "").strip()
                    accepted = False
                    my_requests = []
                    with db_lock:
                        db = load_db()
                        if from_user in db[my_username].get("requests", []):
                            db[my_username]["requests"].remove(from_user)
                            if from_user not in db[my_username]["friends"]:
                                db[my_username]["friends"].append(from_user)
                            if my_username not in db[from_user]["friends"]:
                                db[from_user]["friends"].append(my_username)
                            save_db(db)
                            accepted = True
                            my_requests = list(db[my_username]["requests"])

                    if accepted:
                        with online_lock:
                            my_status = "online" if my_username in online_players else "offline"
                            from_status = "online" if from_user in online_players else "offline"

                            conn.sendall((json.dumps({"type": "friend_added", "username": from_user, "status": from_status, "sync_requests": my_requests}) + "\n").encode('utf-8'))
                            if from_user in online_players:
                                online_players[from_user].sendall((json.dumps({"type": "friend_added", "username": my_username, "status": my_status}) + "\n").encode('utf-8'))

                # --- 4. 拒绝好友申请 ---
                elif m_type == "reject_friend":
                    from_user = msg.get("from", "").strip()
                    rejected = False
                    my_requests = []
                    with db_lock:
                        db = load_db()
                        if from_user in db[my_username].get("requests", []):
                            db[my_username]["requests"].remove(from_user)
                            save_db(db)
                            rejected = True
                            my_requests = list(db[my_username]["requests"])

                    if rejected:
                        conn.sendall((json.dumps({"type": "sync_requests", "requests": my_requests}) + "\n").encode('utf-8'))

                # --- 5. 对战邀请路由系统 ---
                elif m_type == "invite_friend":
                    target = msg.get("target", "").strip()
                    with online_lock:
                        if target in online_players:
                            online_players[target].sendall((json.dumps({"type": "invite_received", "from": my_username}) + "\n").encode('utf-8'))
                        else:
                            conn.sendall((json.dumps({"type": "toast", "msg": "该好友当前已下线"}) + "\n").encode('utf-8'))

                # --- 6. 接受对战邀请 (核心对战房间建立) ---
                elif m_type == "accept_invite":
                    host_user = msg.get("from", "").strip()
                    with online_lock:
                        if host_user in online_players:
                            # 相互绑定对手句柄
                            # 告诉房主：对方接受了，进入游戏
                            online_players[host_user].sendall((json.dumps({"type": "match_start", "opponent": my_username, "is_host": True}) + "\n").encode('utf-8'))
                            # 告诉接受者：房间建立成功，进入游戏
                            conn.sendall((json.dumps({"type": "match_start", "opponent": host_user, "is_host": False}) + "\n").encode('utf-8'))
                        else:
                            conn.sendall((json.dumps({"type": "toast", "msg": "邀请发起人已离开大厅"}) + "\n").encode('utf-8'))

                # --- 7. 拒绝对战邀请 ---
                elif m_type == "reject_invite":
                    host_user = msg.get("from", "").strip()
                    with online_lock:
                        if host_user in online_players:
                            online_players[host_user].sendall((json.dumps({"type": "toast", "msg": f"{my_username} 拒绝了你的对战邀请"}) + "\n").encode('utf-8'))

                # --- 8. 实时对战数据高速转发转发通道 ---
                elif m_type in ["game_data", "attack"]:
                    target = msg.get("target", "").strip()
                    with online_lock:
                        if target in online_players:
                            # 瘦身并原样转发
                            conn_to_send = online_players[target]
                            conn_to_send.sendall((line + "\n").encode('utf-8'))
        except:
            break

    # 玩家断开连接清理
    if my_username:
        with online_lock:
            if my_username in online_players:
                del online_players[my_username]
        print(f"❌ 玩家 {my_username} 已下线")
        # 广播给好友
        broadcast_status_to_friends(my_username, "offline")
    conn.close()

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(100)
    print(f"🚀 超级对战与好友大厅服务器已启动，正在端口 {PORT} 守候...")
    while True:
        c, addr = server.accept()
        threading.Thread(target=handle_client, args=(c, addr), daemon=True).start()

if __name__ == "__main__":
    main()