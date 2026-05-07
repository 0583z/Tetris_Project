import socket
import threading
import json
import os

HOST, PORT = '0.0.0.0', 5555
DB_FILE = 'server_leaderboard.json'

def load_board():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f: return json.load(f)
    return {"single": [], "multi": []}

def save_board(data):
    with open(DB_FILE, 'w') as f: json.dump(data, f)

def handle_client(conn, player_id, connections):
    print(f"玩家 {player_id} 已连接")
    buffer = ""
    while True:
        try:
            data = conn.recv(4096).decode()
            if not data: break
            buffer += data
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if not line.strip(): continue
                msg = json.loads(line)
                t, opp_id = msg.get("type"), 1 - player_id
                opp_conn = connections[opp_id] if len(connections) > opp_id else None

                if t == "game_data" and opp_conn: opp_conn.sendall((line + "\n").encode())
                elif t == "attack" and opp_conn:
                    atk_pkg = json.dumps({"type": "be_attacked", "lines": msg.get("lines")}) + "\n"
                    opp_conn.sendall(atk_pkg.encode())
                elif t == "submit_score":
                    board = load_board()
                    m = msg.get("mode", "multi")
                    board[m].append({"name": msg.get("name"), "score": msg.get("score")})
                    board[m] = sorted(board[m], key=lambda x: x["score"], reverse=True)[:100]
                    save_board(board)
                elif t == "get_leaderboard":
                    resp = json.dumps({"type": "leaderboard_data", "data": load_board()}) + "\n"
                    conn.sendall(resp.encode())
        except: break
    if conn in connections: connections[player_id] = None
    conn.close()

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(2)
    print(f"服务器已在端口 {PORT} 启动...")
    conns = [None, None]
    idx = 0
    while True:
        c, addr = server.accept()
        conns[idx] = c
        threading.Thread(target=handle_client, args=(c, idx, conns), daemon=True).start()
        idx = 1 - idx

if __name__ == "__main__": main()