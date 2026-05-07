import socket
import threading
import json
import os

HOST = '127.0.0.1'
PORT = 5555
DB_FILE = 'server_leaderboard.json'

def load_board():
    """读取排行榜数据，若不存在则初始化"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    return {"single": [], "multi": []}

def save_board(data):
    """保存数据到服务器硬盘"""
    with open(DB_FILE, 'w') as f:
        json.dump(data, f)

def handle_client(conn, player_id, connections):
    print(f"Player {player_id} connected.")
    opponent_id = 1 if player_id == 0 else 0
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
                msg_type = msg.get("type", "game_data")

                if msg_type == "game_data":
                    # 转发对战数据给另一个玩家
                    if len(connections) == 2:
                        opponent_conn = connections[opponent_id]
                        opponent_conn.sendall((line + "\n").encode())
                        
                elif msg_type == "submit_score":
                    # 接收成绩，插入并截断前 100 名
                    board = load_board()
                    mode = msg.get("mode", "single")
                    board[mode].append({"name": msg.get("name"), "score": msg.get("score")})
                    # 核心逻辑：按分数降序排序，只保留前 100
                    board[mode] = sorted(board[mode], key=lambda x: x["score"], reverse=True)[:100]
                    save_board(board)
                    
                elif msg_type == "get_leaderboard":
                    # 返回排行榜数据给客户端
                    board = load_board()
                    resp = json.dumps({"type": "leaderboard_data", "data": board}) + "\n"
                    conn.sendall(resp.encode())
                    
        except Exception as e:
            print(f"Connection error Player {player_id}: {e}")
            break

    print(f"Player {player_id} disconnected.")
    if conn in connections:
        connections.remove(conn)
    conn.close()

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(2)
    print("Server running. Waiting for connections...")

    connections = []
    player_id = 0

    while True:
        conn, addr = server.accept()
        connections.append(conn)
        threading.Thread(target=handle_client, args=(conn, player_id, connections), daemon=True).start()
        player_id = (player_id + 1) % 2

if __name__ == "__main__":
    main()