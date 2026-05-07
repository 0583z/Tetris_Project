import pygame
import random
import socket
import threading
import json
import os

# --- 1. 极致低延迟音频预配置 ---
try:
    pygame.mixer.pre_init(44100, -16, 2, 512)
except:
    pass

# --- 2. 全局常量与配色 ---
WIDTH, HEIGHT = 1000, 700 
GRID_SIZE = 30
COLUMNS, ROWS = 10, 20
BLOCK_COLOR, GRID_COLOR, BG_COLOR = (68, 80, 89), (50, 50, 60), (30, 30, 40)
FLASH_COLOR = (255, 255, 255)
SHAPES = [[[1,1,1,1]], [[1,1],[1,1]], [[0,1,0],[1,1,1]], [[1,1,0],[0,1,1]], [[0,1,1],[1,1,0]]]
LOCAL_DB = "local_single_scores.json"

app_state = {"local_single": [], "server_multi": [], "conn_status": "OFFLINE"}

# --- 3. 音效控制器 (加入进阶机制) ---
class SoundController:
    def __init__(self):
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.sounds = {}
        sfx_map = {
            "move": "move.wav", 
            "rotate": "rotate.wav", 
            "drop": "drop.wav", 
            "clear": "clear.wav", 
            "attack": "attack.wav", 
            "over": "gameover.wav"
        }
        for name, file in sfx_map.items():
            p = os.path.join(self.base_path, "assets", file)
            if os.path.exists(p): 
                self.sounds[name] = pygame.mixer.Sound(p)
                self.sounds[name].set_volume(0.4)
        
        # 精准匹配你的文件名
        self.bgm_normal = os.path.join(self.base_path, "assets", "resonance.wav")
        self.bgm_fast = os.path.join(self.base_path, "assets", "fast_resonance.wav")
        
        self.bgm_state = "normal"  # 状态机：normal 或 fast
        self.bgm_playing = False
        
        # 移动音效节流阀（防止长按爆音）
        self.last_move_time = 0

    def play(self, name):
        if name in self.sounds: 
            # 恢复默认音量（防止被 Combo 调大后影响后续）
            if name == "clear": self.sounds[name].set_volume(0.4)
            self.sounds[name].play()

    def play_move(self):
        """长按节流版移动音效"""
        now = pygame.time.get_ticks()
        if now - self.last_move_time > 100:  # 冷却时间 100ms
            if "move" in self.sounds:
                self.sounds["move"].play()
            self.last_move_time = now

    def play_clear(self, combo):
        """连击动态扩音系统"""
        if "clear" in self.sounds:
            snd = self.sounds["clear"]
            # 基础音量 0.4，每次连击增加 0.2，最高 1.0 (满共鸣)
            vol = min(1.0, 0.4 + (combo - 1) * 0.2)
            snd.set_volume(vol)
            snd.play()

    def set_danger_bgm(self, is_danger):
        """动态 BGM 切换引擎"""
        target_state = "fast" if is_danger else "normal"
        target_path = self.bgm_fast if is_danger else self.bgm_normal
        
        if self.bgm_state != target_state:
            self.bgm_state = target_state
            if os.path.exists(target_path):
                # 0.5秒淡出现在的，然后立刻切入新的
                pygame.mixer.music.fadeout(500)
                pygame.mixer.music.load(target_path)
                pygame.mixer.music.set_volume(0.4 if is_danger else 0.3)
                pygame.mixer.music.play(-1, fade_ms=500)

    def start_bgm(self):
        if os.path.exists(self.bgm_normal) and not self.bgm_playing:
            try:
                pygame.mixer.music.load(self.bgm_normal)
                pygame.mixer.music.set_volume(0.3)
                pygame.mixer.music.play(-1, fade_ms=2000)
                self.bgm_playing = True
            except: pass

# --- 4. 辅助工具 ---
def get_font(size):
    p = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]
    for f in p:
        if os.path.exists(f): return pygame.font.Font(f, size)
    return pygame.font.Font(None, size)

def load_local_scores():
    if os.path.exists(LOCAL_DB):
        try:
            with open(LOCAL_DB, "r") as f: return json.load(f)
        except: return []
    return []

def save_local_score(name, score):
    scores = load_local_scores()
    scores.append({"name": name, "score": score})
    scores = sorted(scores, key=lambda x: x["score"], reverse=True)[:100]
    with open(LOCAL_DB, "w") as f: json.dump(scores, f)
    app_state["local_single"] = scores

# --- 5. 核心游戏引擎 ---
class Tetris:
    def __init__(self, mode="single", sock=None, sfx=None):
        self.mode, self.socket, self.sfx = mode, sock, sfx
        self.grid = [[0] * COLUMNS for _ in range(ROWS)]
        self.opponent_grid = [[0] * COLUMNS for _ in range(ROWS)]
        self.bag = []
        self.current_piece = self._get_from_bag()
        self.next_piece = self._get_from_bag()
        self.pos = [0, COLUMNS // 2 - 1]
        self.game_over = False
        self.score, self.score_submitted = 0, False
        
        self.total_lines = 0
        self.level = 1
        self.flashing_rows = []
        self.flash_timer = 0 
        
        # 连击计数器
        self.combo_count = 0

    def _get_from_bag(self):
        if not self.bag: self.bag = list(range(len(SHAPES))); random.shuffle(self.bag)
        return SHAPES[self.bag.pop()]

    def check_collision(self, offset_r=0, offset_c=0, shape=None):
        shape = shape or self.current_piece
        for r_idx, row in enumerate(shape):
            for c_idx, val in enumerate(row):
                if val:
                    r, c = self.pos[0] + r_idx + offset_r, self.pos[1] + c_idx + offset_c
                    if r >= ROWS or c < 0 or c >= COLUMNS: return True
                    if r >= 0 and self.grid[r][c]: return True
        return False

    def rotate_piece(self):
        rotated = [list(row) for row in zip(*self.current_piece[::-1])]
        if not self.check_collision(shape=rotated): self.current_piece = rotated

    def lock_piece(self):
        for r_idx, row in enumerate(self.current_piece):
            for c_idx, val in enumerate(row):
                if val: self.grid[self.pos[0] + r_idx][self.pos[1] + c_idx] = 1
        if self.sfx: self.sfx.play("drop")
        
        self.flashing_rows = [i for i, row in enumerate(self.grid) if all(row)]
        
        if self.flashing_rows:
            self.flash_timer = 6
            self.combo_count += 1
            if self.sfx: self.sfx.play_clear(self.combo_count)
        else:
            self.combo_count = 0 # 未消行，连击中断
            self.spawn_next()

    def finalize_clear(self):
        cleared = len(self.flashing_rows)
        new_grid = [row for i, row in enumerate(self.grid) if i not in self.flashing_rows]
        for _ in range(cleared): new_grid.insert(0, [0] * COLUMNS)
        self.grid = new_grid
        
        self.total_lines += cleared
        self.level = 1 + (self.total_lines // 10)
        # 连击分数加成
        self.score += (cleared ** 2) * 100 * self.combo_count 
        
        if self.mode == "multi" and self.socket and cleared >= 2:
            atk = {2:1, 3:2, 4:4}.get(cleared, 0)
            if atk > 0:
                if self.sfx: self.sfx.play("attack")
                try: self.socket.sendall((json.dumps({"type":"attack","lines":atk})+"\n").encode())
                except: pass
        self.flashing_rows = []
        self.spawn_next()

    def spawn_next(self):
        # 扫描前 5 行，只要有方块就触发危机场 BGM
        danger = any(self.grid[r][c] for r in range(5) for c in range(COLUMNS))
        if self.sfx: self.sfx.set_danger_bgm(danger)

        self.current_piece, self.next_piece = self.next_piece, self._get_from_bag()
        self.pos = [0, COLUMNS // 2 - 1]
        if self.check_collision(): 
            self.game_over = True
            if self.sfx: self.sfx.play("over")

    def add_garbage(self, count):
        for _ in range(count):
            self.grid.pop(0)
            new_row = [1] * COLUMNS
            new_row[random.randint(0, COLUMNS-1)] = 0
            self.grid.append(new_row)
        # 如果收到大量垃圾行，可能直接进入危险状态
        danger = any(self.grid[r][c] for r in range(5) for c in range(COLUMNS))
        if self.sfx: self.sfx.set_danger_bgm(danger)

    def draw_grid(self, screen, grid, offset_x, title, is_opponent=False):
        # 加入连击数 UI 显示
        header = f"{title} | LV.{self.level} | 得分:{self.score}"
        if not is_opponent and self.combo_count > 1:
            header += f" | Combo x{self.combo_count}!"
        
        screen.blit(get_font(24).render(header if not is_opponent else title, True, (255,255,255)), (offset_x, 15))
        
        for r in range(ROWS):
            is_flashing = not is_opponent and r in self.flashing_rows and (self.flash_timer % 2 == 0)
            for c in range(COLUMNS):
                rect = pygame.Rect(offset_x + c * GRID_SIZE, 50 + r * GRID_SIZE, GRID_SIZE, GRID_SIZE)
                if is_flashing: pygame.draw.rect(screen, FLASH_COLOR, rect.inflate(-2,-2), border_radius=4)
                elif grid[r][c]: pygame.draw.rect(screen, BLOCK_COLOR, rect.inflate(-2,-2), border_radius=4)
                else: pygame.draw.rect(screen, GRID_COLOR, rect, 1)
        
        if not is_opponent and not self.game_over and not self.flashing_rows:
            for r_idx, row in enumerate(self.current_piece):
                for c_idx, val in enumerate(row):
                    if val:
                        px = offset_x + (self.pos[1] + c_idx) * GRID_SIZE
                        py = 50 + (self.pos[0] + r_idx) * GRID_SIZE
                        pygame.draw.rect(screen, BLOCK_COLOR, pygame.Rect(px, py, GRID_SIZE, GRID_SIZE).inflate(-2,-2), border_radius=4)

        px_x = offset_x + COLUMNS * GRID_SIZE + 20
        screen.blit(get_font(20).render("下一个", True, (150,150,150)), (px_x, 50))
        p = self.next_piece if not is_opponent else None
        if p:
            for r_idx, row in enumerate(p):
                for c_idx, val in enumerate(row):
                    if val: pygame.draw.rect(screen, BLOCK_COLOR, pygame.Rect(px_x + c_idx*20, 80 + r_idx*20, 18, 18), border_radius=3)

# --- 6. 通信与 UI ---
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
                    if msg.get("type") == "leaderboard_data": app_state["server_multi"] = msg.get("data", {}).get("multi", [])
                    elif msg.get("type") == "game_data": game.opponent_grid = msg.get("grid")
                    elif msg.get("type") == "be_attacked": game.add_garbage(msg.get("lines"))
        except: break

def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("俄罗斯方块：心流反馈引擎")
    clock = pygame.time.Clock()
    
    # 你最爱的长按连发已就位！
    pygame.key.set_repeat(150, 50)
    
    sfx = SoundController()
    sfx.start_bgm()
    
    state, player_name, server_ip = "MENU", "", "127.0.0.1"
    active_input, client_socket = None, None
    game = Tetris(sfx=sfx)
    app_state["local_single"] = load_local_scores()

    name_rect = pygame.Rect(WIDTH//2 - 150, 180, 300, 50)
    ip_rect =   pygame.Rect(WIDTH//2 - 150, 250, 300, 50)
    btn_single = pygame.Rect(WIDTH//2 - 150, 330, 300, 50)
    btn_multi =  pygame.Rect(WIDTH//2 - 150, 400, 300, 50)
    btn_board =  pygame.Rect(WIDTH//2 - 150, 470, 300, 50)
    btn_back =   pygame.Rect(WIDTH//2 - 100, 620, 200, 50)

    def try_connect():
        nonlocal client_socket
        if client_socket: return True
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(1.5); client_socket.connect((server_ip, 5555))
            threading.Thread(target=receive_data, args=(client_socket, game), daemon=True).start()
            app_state["conn_status"] = "ONLINE"
            return True
        except:
            client_socket = None; app_state["conn_status"] = "OFFLINE"
            return False

    fall_time = 0
    while True:
        screen.fill(BG_COLOR); dt = clock.tick(30); fall_time += dt
        current_speed = max(100, 450 - (game.level * 40))

        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); return
            if state == "MENU":
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if name_rect.collidepoint(event.pos): active_input = "NAME"
                    elif ip_rect.collidepoint(event.pos): active_input = "IP"
                    else: active_input = None
                    if btn_single.collidepoint(event.pos) and player_name:
                        game = Tetris("single", sfx=sfx); state = "SINGLE"
                    elif btn_multi.collidepoint(event.pos) and player_name:
                        if try_connect(): game = Tetris("multi", client_socket, sfx); state = "MULTI"
                    elif btn_board.collidepoint(event.pos):
                        try_connect()
                        if client_socket: client_socket.sendall(json.dumps({"type":"get_leaderboard"}).encode()+b"\n")
                        state = "LEADERBOARD"
                if event.type == pygame.KEYDOWN and active_input:
                    if event.key == pygame.K_BACKSPACE:
                        if active_input == "NAME": player_name = player_name[:-1]
                        else: server_ip = server_ip[:-1]
                    elif event.unicode.isprintable():
                        if active_input == "NAME": player_name += event.unicode
                        else: server_ip += event.unicode
            elif state == "LEADERBOARD":
                if (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE) or \
                   (event.type == pygame.MOUSEBUTTONDOWN and btn_back.collidepoint(event.pos)): state = "MENU"
            elif state in ["SINGLE", "MULTI"]:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE: state = "MENU"
                    elif not game.game_over and game.flash_timer == 0:
                        # 重点：修改为调用 play_move()，享受节流连音
                        if event.key == pygame.K_LEFT and not game.check_collision(offset_c=-1): 
                            game.pos[1] -= 1; sfx.play_move()
                        elif event.key == pygame.K_RIGHT and not game.check_collision(offset_c=1): 
                            game.pos[1] += 1; sfx.play_move()
                        elif event.key == pygame.K_DOWN and not game.check_collision(offset_r=1): 
                            game.pos[0] += 1; sfx.play_move()
                        elif event.key == pygame.K_UP: 
                            game.rotate_piece(); sfx.play("rotate")

        if state in ["SINGLE", "MULTI"] and not game.game_over:
            if game.flash_timer > 0:
                game.flash_timer -= 1
                if game.flash_timer == 0: game.finalize_clear()
            else:
                if fall_time > current_speed:
                    fall_time = 0
                    if not game.check_collision(offset_r=1): game.pos[0] += 1
                    else: game.lock_piece()
            if state == "MULTI" and client_socket:
                try:
                    temp = [list(row) for row in game.grid]
                    if not game.game_over:
                        for r, row in enumerate(game.current_piece):
                            for c, v in enumerate(row):
                                if v and 0<=game.pos[0]+r<ROWS and 0<=game.pos[1]+c<COLUMNS: temp[game.pos[0]+r][game.pos[1]+c]=1
                    client_socket.sendall((json.dumps({"type":"game_data","grid":temp})+"\n").encode())
                except: pass
            if game.game_over and not game.score_submitted:
                if state == "SINGLE": save_local_score(player_name, game.score)
                elif client_socket: client_socket.sendall((json.dumps({"type":"submit_score","mode":"multi","name":player_name,"score":game.score})+"\n").encode())
                game.score_submitted = True

        if state == "MENU":
            screen.blit(get_font(80).render("俄罗斯方块", True, (200,200,200)), (WIDTH//2-200, 60))
            pygame.draw.rect(screen, (100,150,255) if active_input=="NAME" else GRID_COLOR, name_rect, 2)
            screen.blit(get_font(24).render(f"昵称: {player_name}", True, (255,255,255)), (name_rect.x+10, name_rect.y+10))
            pygame.draw.rect(screen, (100,150,255) if active_input=="IP" else GRID_COLOR, ip_rect, 2)
            screen.blit(get_font(24).render(f"服务IP: {server_ip}", True, (255,255,255)), (ip_rect.x+10, ip_rect.y+10))
            for b, t in [(btn_single, "单人模式"), (btn_multi, "双人对战"), (btn_board, "排行榜")]:
                pygame.draw.rect(screen, BLOCK_COLOR, b, border_radius=5)
                screen.blit(get_font(30).render(t, True, (255,255,255)), (b.x+90, b.y+8))
        elif state == "LEADERBOARD":
            screen.blit(get_font(50).render("排 行 榜", True, (200,200,200)), (WIDTH//2-70, 50))
            app_state["local_single"] = load_local_scores()
            for i, e in enumerate(app_state["local_single"][:12]):
                screen.blit(get_font(26).render(f"{i+1}. {e['name']} - {e['score']}", True, (255,255,255)), (150, 160+i*35))
            for i, e in enumerate(app_state["server_multi"][:12]):
                screen.blit(get_font(26).render(f"{i+1}. {e['name']} - {e['score']}", True, (255,255,255)), (600, 160+i*35))
            pygame.draw.rect(screen, BLOCK_COLOR, btn_back, border_radius=5)
            screen.blit(get_font(30).render("返回菜单", True, (255,255,255)), (btn_back.x+40, btn_back.y+8))
        elif state in ["SINGLE", "MULTI"]:
            game.draw_grid(screen, game.grid, 50, player_name)
            if state == "MULTI": game.draw_grid(screen, game.opponent_grid, 550, "对手", True)
            if game.game_over:
                txt = get_font(80).render("GAME OVER", True, (255,50,50))
                screen.blit(txt, (WIDTH//2-200, HEIGHT//2-50))
        pygame.display.flip()

if __name__ == "__main__": main()