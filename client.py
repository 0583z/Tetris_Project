import pygame
import random
import socket
import threading
import json

# 配置参数
WIDTH, HEIGHT = 800, 700
GRID_SIZE = 30
COLUMNS, ROWS = 10, 20

# 方块形状
SHAPES = [
    [[1, 1, 1, 1]], [[1, 1], [1, 1]], [[0, 1, 0], [1, 1, 1]], 
    [[1, 1, 0], [0, 1, 1]], [[0, 1, 1], [1, 1, 0]]
]

class Tetris:
    def __init__(self):
        self.grid = [[0] * COLUMNS for _ in range(ROWS)]
        self.opponent_grid = [[0] * COLUMNS for _ in range(ROWS)]
        self.current_piece = self.new_piece()
        self.pos = [0, COLUMNS // 2 - 1]
        self.game_over = False
        self.opponent_game_over = False # 新增：记录对手是否触顶失败

    def new_piece(self): return random.choice(SHAPES)

    def check_collision(self, offset_r=0, offset_c=0, shape=None):
        shape = shape or self.current_piece
        for r_idx, row in enumerate(shape):
            for c_idx, val in enumerate(row):
                if val:
                    r = self.pos[0] + r_idx + offset_r
                    c = self.pos[1] + c_idx + offset_c
                    if r >= ROWS or c < 0 or c >= COLUMNS: return True
                    if r >= 0 and self.grid[r][c]: return True
        return False

    def lock_piece(self):
        for r_idx, row in enumerate(self.current_piece):
            for c_idx, val in enumerate(row):
                if val:
                    self.grid[self.pos[0] + r_idx][self.pos[1] + c_idx] = 1
        self.clear_lines()
        self.current_piece = self.new_piece()
        self.pos = [0, COLUMNS // 2 - 1]
        # 如果新生成的方块立刻发生碰撞，说明已经触顶，游戏结束
        if self.check_collision(): 
            self.game_over = True

    def clear_lines(self):
        new_grid = [row for row in self.grid if not all(row)]
        cleared = ROWS - len(new_grid)
        for _ in range(cleared): new_grid.insert(0, [0] * COLUMNS)
        self.grid = new_grid

    def rotate_piece(self):
        rotated = [list(row) for row in zip(*self.current_piece[::-1])]
        if not self.check_collision(shape=rotated): self.current_piece = rotated

    def draw_grid(self, screen, grid, offset_x, title, is_opponent=False):
        font = pygame.font.Font(None, 30)
        text = font.render(title, True, (255, 255, 255))
        screen.blit(text, (offset_x + 50, 10))

        for r in range(ROWS):
            for c in range(COLUMNS):
                rect = pygame.Rect(offset_x + c * GRID_SIZE, 50 + r * GRID_SIZE, GRID_SIZE, GRID_SIZE)
                if grid[r][c]:
                    color = (0, 150, 255) if is_opponent else (255, 0, 0)
                else:
                    color = (50, 50, 50)
                pygame.draw.rect(screen, color, rect, 0 if grid[r][c] else 1)
        
        # 只有在游戏未结束时，才画出正在掉落的方块
        if not is_opponent and not self.game_over:
            for r_idx, row in enumerate(self.current_piece):
                for c_idx, val in enumerate(row):
                    if val:
                        px = offset_x + (self.pos[1] + c_idx) * GRID_SIZE
                        py = 50 + (self.pos[0] + r_idx) * GRID_SIZE
                        pygame.draw.rect(screen, (0, 255, 0), (px, py, GRID_SIZE, GRID_SIZE))

def receive_data(sock, game):
    buffer = ""
    while True:
        try:
            data = sock.recv(4096).decode()
            if not data: break
            buffer += data
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if line.strip():
                    remote_data = json.loads(line)
                    game.opponent_grid = remote_data["grid"]
                    # 新增：接收对手的失败状态
                    game.opponent_game_over = remote_data.get("game_over", False) 
        except Exception as e:
            print(f"接收数据异常，已断开: {e}")
            break

def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("网络版俄罗斯方块对战")
    clock = pygame.time.Clock()
    
    # === 新增功能 2：开启键盘长按连发 ===
    # 参数1：按下后延迟 150 毫秒开始连发
    # 参数2：之后每隔 50 毫秒触发一次按键事件
    pygame.key.set_repeat(150, 50) 
    
    game = Tetris()

    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client_socket.connect(('127.0.0.1', 5555))
        threading.Thread(target=receive_data, args=(client_socket, game), daemon=True).start()
    except:
        print("无法连接到服务器，请确认 server.py 已启动！")
        return

    fall_time = 0
    fall_speed = 400
    running = True

    while running:
        screen.fill((30, 30, 40))
        fall_time += clock.get_time() 
        clock.tick(30)

        # 只有在双方都没死的情况下，才进行自动下落
        if not game.game_over and not game.opponent_game_over:
            if fall_time > fall_speed:
                fall_time = 0
                if not game.check_collision(offset_r=1): game.pos[0] += 1
                else: game.lock_piece()

        # 事件处理
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            # 只有在双方都没死的情况下，才响应键盘控制
            if event.type == pygame.KEYDOWN and not game.game_over and not game.opponent_game_over:
                if event.key == pygame.K_LEFT and not game.check_collision(offset_c=-1): game.pos[1] -= 1
                elif event.key == pygame.K_RIGHT and not game.check_collision(offset_c=1): game.pos[1] += 1
                elif event.key == pygame.K_DOWN and not game.check_collision(offset_r=1): game.pos[0] += 1
                elif event.key == pygame.K_UP: game.rotate_piece()

        # 发送数据
        try:
            temp_grid = [list(row) for row in game.grid]
            # 如果自己没死，才把活方块画进发送矩阵里
            if not game.game_over:
                for r_idx, row in enumerate(game.current_piece):
                    for c_idx, val in enumerate(row):
                        if val:
                            r, c = game.pos[0] + r_idx, game.pos[1] + c_idx
                            if 0 <= r < ROWS and 0 <= c < COLUMNS:
                                temp_grid[r][c] = 1
                                
            # === 新增功能 1：把自己的 game_over 状态一起发给对手 ===
            data_to_send = json.dumps({
                "grid": temp_grid, 
                "game_over": game.game_over 
            }) + "\n" 
            client_socket.sendall(data_to_send.encode())
        except:
            pass

        # 画面渲染
        game.draw_grid(screen, game.grid, offset_x=50, title="You", is_opponent=False)
        game.draw_grid(screen, game.opponent_grid, offset_x=450, title="Opponent", is_opponent=True)

        # === 绘制胜负提示文字 ===
        if game.game_over or game.opponent_game_over:
            font = pygame.font.Font(None, 80) # 大号字体
            if game.game_over:
                # 自己死了 -> 红色 You Lose
                text = font.render("YOU LOSE!", True, (255, 50, 50))
            else:
                # 对手死了 -> 绿色 You Win
                text = font.render("YOU WIN!", True, (50, 255, 50))
            
            # 将文字居中画在屏幕中间
            text_rect = text.get_rect(center=(WIDTH/2, HEIGHT/2))
            screen.blit(text, text_rect)

        pygame.display.flip()

    pygame.quit()

if __name__ == "__main__":
    main()