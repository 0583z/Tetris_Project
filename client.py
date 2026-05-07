import pygame
import random
import socket
import threading
import json
import os

# 配置参数
WIDTH, HEIGHT = 1000, 700 
GRID_SIZE = 30
COLUMNS, ROWS = 10, 20

# 怀旧复古质感配色
BLOCK_COLOR = (68, 80, 89)
GRID_COLOR = (50, 50, 60)
BG_COLOR = (30, 30, 40)

# 方块形状
SHAPES = [
    [[1, 1, 1, 1]], # I
    [[1, 1], [1, 1]], # O
    [[0, 1, 0], [1, 1, 1]], # T
    [[1, 1, 0], [0, 1, 1]], # S
    [[0, 1, 1], [1, 1, 0]]  # Z
]

app_state = {
    "leaderboard": {"single": [], "multi": []}
}

def get_font(size):
    """安全获取支持中文的字体，直接读取系统文件绕过 SysFont 报错"""
    # 优先尝试加载 Windows 自带的微软雅黑
    font_path = "C:/Windows/Fonts/msyh.ttc" 
    if os.path.exists(font_path):
        return pygame.font.Font(font_path, size)
    # 备用方案：黑体
    font_path_alt = "C:/Windows/Fonts/simhei.ttf"
    if os.path.exists(font_path_alt):
        return pygame.font.Font(font_path_alt, size)
    # 极端情况降级（不支持中文）
    return pygame.font.Font(None, size)

class Tetris:
    def __init__(self, mode="single"):
        self.mode = mode
        self.grid = [[0] * COLUMNS for _ in range(ROWS)]
        self.opponent_grid = [[0] * COLUMNS for _ in range(ROWS)]
        self.opponent_next = None 
        
        self.bag = []
        self.current_piece = self._get_from_bag()
        self.next_piece = self._get_from_bag()
        
        self.pos = [0, COLUMNS // 2 - 1]
        self.game_over = False
        self.opponent_game_over = False
        self.score = 0
        self.score_submitted = False

    def _get_from_bag(self):
        if not self.bag:
            self.bag = list(range(len(SHAPES)))
            random.shuffle(self.bag)
        idx = self.bag.pop()
        return SHAPES[idx]

    def check_collision(self, offset_r=0, offset_c=0, shape=None):
        shape = shape or self.current_piece
        for r_idx, row in enumerate(shape):
            for c_idx, val in enumerate(row):
                if val:
                    r, c = self.pos[0] + r_idx + offset_r, self.pos[1] + c_idx + offset_c
                    if r >= ROWS or c < 0 or c >= COLUMNS: return True
                    if r >= 0 and self.grid[r][c]: return True
        return False

    def lock_piece(self):
        for r_idx, row in enumerate(self.current_piece):
            for c_idx, val in enumerate(row):
                if val: self.grid[self.pos[0] + r_idx][self.pos[1] + c_idx] = 1
        self.clear_lines()
        
        self.current_piece = self.next_piece
        self.next_piece = self._get_from_bag()
        
        self.pos = [0, COLUMNS // 2 - 1]
        if self.check_collision(): self.game_over = True

    def clear_lines(self):
        new_grid = [row for row in self.grid if not all(row)]
        cleared = ROWS - len(new_grid)
        for _ in range(cleared): new_grid.insert(0, [0] * COLUMNS)
        self.grid = new_grid
        if self.mode == "single" and cleared > 0:
            self.score += (cleared ** 2) * 100

    def rotate_piece(self):
        rotated = [list(row) for row in zip(*self.current_piece[::-1])]
        if not self.check_collision(shape=rotated): self.current_piece = rotated

    def draw_grid(self, screen, grid, offset_x, title, is_opponent=False):
        font = get_font(30)
        header = f"{title}" if self.mode == "multi" else f"{title} | 得分: {self.score}"
        if is_opponent: header = title
        screen.blit(font.render(header, True, (255, 255, 255)), (offset_x, 10))

        for r in range(ROWS):
            for c in range(COLUMNS):
                rect = pygame.Rect(offset_x + c * GRID_SIZE, 50 + r * GRID_SIZE, GRID_SIZE, GRID_SIZE)
                if grid[r][c]:
                    pygame.draw.rect(screen, BLOCK_COLOR, rect.inflate(-2, -2), border_radius=4)
                else:
                    pygame.draw.rect(screen, GRID_COLOR, rect, 1)
        
        if not is_opponent and not self.game_over:
            for r_idx, row in enumerate(self.current_piece):
                for c_idx, val in enumerate(row):
                    if val:
                        px, py = offset_x + (self.pos[1]+c_idx)*GRID_SIZE, 50 + (self.pos[0]+r_idx)*GRID_SIZE
                        pygame.draw.rect(screen, BLOCK_COLOR, pygame.Rect(px, py, GRID_SIZE, GRID_SIZE).inflate(-2, -2), border_radius=4)

    def draw_preview(self, screen, offset_x, is_opponent=False):
        preview_x = offset_x + COLUMNS * GRID_SIZE + 20
        font = get_font(24)
        screen.blit(font.render("下一个", True, (150, 150, 150)), (preview_x, 50))
        
        piece = self.opponent_next if is_opponent else self.next_piece
        if piece:
            for r_idx, row in enumerate(piece):
                for c_idx, val in enumerate(row):
                    if val:
                        px, py = preview_x + c_idx * 20, 80 + r_idx * 20
                        pygame.draw.rect(screen, BLOCK_COLOR, pygame.Rect(px, py, 18, 18), border_radius=3)

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
                    msg = json.loads(line)
                    if msg.get("type") == "leaderboard_data":
                        app_state["leaderboard"] = msg.get("data", {})
                    elif msg.get("type") == "game_data":
                        game.opponent_grid = msg.get("grid", [])
                        game.opponent_game_over = msg.get("game_over", False)
                        game.opponent_next = msg.get("next") 
        except: break

def draw_button(screen, rect, text, active=True):
    pygame.draw.rect(screen, BLOCK_COLOR if active else GRID_COLOR, rect, border_radius=4)
    surf = get_font(36).render(text, True, (255, 255, 255))
    text_rect = surf.get_rect(center=rect.center)
    screen.blit(surf, text_rect)

def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("俄罗斯方块竞技版")
    clock = pygame.time.Clock()
    pygame.key.set_repeat(150, 50)
    
    state, player_name, input_active = "MENU", "", False
    game = Tetris()
    
    # --- 修复 1：在这里统一声明 input_rect 变量 ---
    input_rect = pygame.Rect(WIDTH//2 - 150, 200, 300, 50)
    
    btn_single = pygame.Rect(WIDTH//2 - 150, 280, 300, 50)
    btn_multi =  pygame.Rect(WIDTH//2 - 150, 350, 300, 50)
    btn_board =  pygame.Rect(WIDTH//2 - 150, 420, 300, 50)
    
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client_socket.connect(('127.0.0.1', 5555))
        threading.Thread(target=receive_data, args=(client_socket, game), daemon=True).start()
    except: pass

    fall_time, fall_speed = 0, 400
    while True:
        screen.fill(BG_COLOR)
        fall_time += clock.get_time()
        clock.tick(30)

        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); return
            
            if state == "MENU":
                if event.type == pygame.MOUSEBUTTONDOWN:
                    # --- 修复 2：使用定义好的 input_rect ---
                    input_active = input_rect.collidepoint(event.pos)
                    if player_name:
                        if btn_single.collidepoint(event.pos): game = Tetris(mode="single"); state = "SINGLE"
                        elif btn_multi.collidepoint(event.pos): game = Tetris(mode="multi"); state = "MULTI"
                    if btn_board.collidepoint(event.pos):
                        client_socket.sendall((json.dumps({"type": "get_leaderboard"}) + "\n").encode())
                        state = "LEADERBOARD"
                if event.type == pygame.KEYDOWN and input_active:
                    if event.key == pygame.K_BACKSPACE: player_name = player_name[:-1]
                    elif len(player_name) < 10 and event.unicode.isprintable(): player_name += event.unicode
            
            elif state == "LEADERBOARD":
                if event.type == pygame.MOUSEBUTTONDOWN and pygame.Rect(WIDTH//2-100, 600, 200, 50).collidepoint(event.pos): state = "MENU"
            
            elif state in ["SINGLE", "MULTI"]:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: 
                        state = "MENU"
                    elif not game.game_over and not (state == "MULTI" and game.opponent_game_over):
                        if event.key == pygame.K_LEFT and not game.check_collision(offset_c=-1): game.pos[1] -= 1
                        elif event.key == pygame.K_RIGHT and not game.check_collision(offset_c=1): game.pos[1] += 1
                        elif event.key == pygame.K_DOWN and not game.check_collision(offset_r=1): game.pos[0] += 1
                        elif event.key == pygame.K_UP: game.rotate_piece()

        if state == "MENU":
            screen.blit(get_font(80).render("俄 罗 斯 方 块", True, (200, 200, 200)), (WIDTH//2 - 200, 80))
            
            # --- 修复 3：统一使用 input_rect ---
            pygame.draw.rect(screen, (100, 150, 255) if input_active else GRID_COLOR, input_rect, 2, border_radius=4)
            name_surf = get_font(36).render(f"玩家昵称: {player_name}", True, (255, 255, 255))
            name_rect = name_surf.get_rect(centery=input_rect.centery, left=input_rect.left + 20)
            screen.blit(name_surf, name_rect)
            
            # 移除了多余的一行 "单人游戏" 绘制
            draw_button(screen, btn_single, "单人游戏", active=bool(player_name))
            draw_button(screen, btn_multi, "双人对战", active=bool(player_name))
            draw_button(screen, btn_board, "排 行 榜")

        elif state == "LEADERBOARD":
            screen.blit(get_font(60).render("历 史 最 高 分", True, (200, 200, 200)), (WIDTH//2 - 150, 50))
            draw_button(screen, pygame.Rect(WIDTH//2-100, 600, 200, 50), "返回主菜单")
            
            screen.blit(get_font(30).render("单人模式", True, (150, 150, 150)), (200, 130))
            screen.blit(get_font(30).render("双人对战", True, (150, 150, 150)), (650, 130))

            for i, e in enumerate(app_state["leaderboard"]["single"][:12]):
                screen.blit(get_font(28).render(f"{i+1}. {e['name']} - {e['score']}", True, (255,255,255)), (180, 170 + i*30))
            for i, e in enumerate(app_state["leaderboard"]["multi"][:12]):
                screen.blit(get_font(28).render(f"{i+1}. {e['name']} - {e['score']}", True, (255,255,255)), (630, 170 + i*30))

        elif state in ["SINGLE", "MULTI"]:
            if not game.game_over and not (state == "MULTI" and game.opponent_game_over):
                if fall_time > fall_speed:
                    fall_time = 0
                    if not game.check_collision(offset_r=1): game.pos[0] += 1
                    else: game.lock_piece()

            if state == "MULTI":
                temp_grid = [list(row) for row in game.grid]
                if not game.game_over:
                    for r_idx, row in enumerate(game.current_piece):
                        for c_idx, val in enumerate(row):
                            if val and 0 <= game.pos[0]+r_idx < ROWS and 0 <= game.pos[1]+c_idx < COLUMNS:
                                temp_grid[game.pos[0]+r_idx][game.pos[1]+c_idx] = 1
                try:
                    client_socket.sendall((json.dumps({
                        "type": "game_data", "grid": temp_grid, "game_over": game.game_over, "next": game.next_piece
                    }) + "\n").encode())
                except: pass

            if game.game_over and not game.score_submitted:
                client_socket.sendall((json.dumps({"type": "submit_score", "mode": game.mode, "name": player_name, "score": game.score}) + "\n").encode())
                game.score_submitted = True

            game.draw_grid(screen, game.grid, offset_x=50, title=player_name)
            game.draw_preview(screen, offset_x=50) 
            
            if state == "MULTI":
                game.draw_grid(screen, game.grid if False else game.opponent_grid, offset_x=550, title="对手", is_opponent=True)
                game.draw_preview(screen, offset_x=550, is_opponent=True) 

            if game.game_over or (state == "MULTI" and game.opponent_game_over):
                msg = "游戏结束" if state == "SINGLE" else ("YOU LOSE!" if game.game_over else "YOU WIN!")
                color = (255, 50, 50) if game.game_over else (50, 255, 50)
                
                font_face = pygame.font.Font(None, 100) if state == "MULTI" else get_font(80)
                surf = font_face.render(msg, True, color)
                screen.blit(surf, surf.get_rect(center=(WIDTH/2, HEIGHT/2 - 20)))
                
                screen.blit(get_font(30).render("按 ESC 返回主菜单", True, (200, 200, 200)), (WIDTH//2-110, HEIGHT//2+60))

        pygame.display.flip()

if __name__ == "__main__":
    main()