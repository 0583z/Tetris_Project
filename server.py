import socket
import threading

# 服务器配置
HOST = '127.0.0.1' # 本地测试IP
PORT = 5555

def handle_client(conn, player_id, connections):
    """处理单个客户端的数据收发"""
    print(f"玩家 {player_id} 已连接.")
    
    # 获取对手的连接对象
    opponent_id = 1 if player_id == 0 else 0
    
    while True:
        try:
            # 接收当前玩家发来的数据 (网格状态)
            data = conn.recv(2048)
            if not data:
                print(f"玩家 {player_id} 断开连接.")
                break
            
            # 如果对手已经连接，就把数据转发给对手
            if len(connections) == 2:
                opponent_conn = connections[opponent_id]
                opponent_conn.sendall(data)
                
        except Exception as e:
            print(f"玩家 {player_id} 连接异常: {e}")
            break

    print(f"连接关闭: 玩家 {player_id}")
    connections.remove(conn)
    conn.close()

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind((HOST, PORT))
    except socket.error as e:
        print(f"绑定端口失败: {e}")
        return

    server.listen(2) # 最多允许2个玩家连接
    print("服务器已启动，等待玩家连接...")

    connections = []
    player_id = 0

    while True:
        conn, addr = server.accept()
        connections.append(conn)
        
        # 为每个新连接的玩家开启一个独立的线程处理数据
        thread = threading.Thread(target=handle_client, args=(conn, player_id, connections))
        thread.start()
        
        player_id += 1
        if player_id >= 2:
            print("两个玩家均已连接，游戏开始！")
            player_id = 0 # 重置，理论上这里可以加入更多房间逻辑

if __name__ == "__main__":
    main()