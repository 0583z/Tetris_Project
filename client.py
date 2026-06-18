import pygame
import random
import socket
import threading
import json
import os
import sys

try:
    pygame.mixer.pre_init(44100, -16, 2, 512)
except: pass

def resource_path(relative_path):
    """获取资源文件的绝对路径，兼容 PyInstaller 打包"""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

# --- 全局配置与暗黑科技风色盘 ---
WIDTH, HEIGHT = 1000, 700 
GRID_SIZE = 30
COLUMNS, ROWS = 10, 20
BLOCK_COLOR = (68, 80, 89)
GRID_COLOR = (50, 50, 60)
BG_COLOR = (30, 30, 40)
PANEL_BG = (40, 40, 52)
FLASH_COLOR = (255, 255, 255)
SHAPES = [
    [[1,1,1,1]],           # I
    [[1,1],[1,1]],         # O
    [[0,1,0],[1,1,1]],     # T
    [[1,1,0],[0,1,1]],     # Z
    [[0,1,1],[1,1,0]],     # S
    [[1,0,0],[1,1,1]],     # L
    [[0,0,1],[1,1,1]]      # J
]

# 客户端全局核心大厅状态机
# 状态机空间: LOGIN(登录框), LOBBY(好友大厅), SINGLE(单人游玩), MULTI(好友跨屏对战)
lobby_data = {
    "my_name": "",
    "conn_status": "DISCONNECTED",  # DISCONNECTED, CONNECTING, VERIFYING, LOBBY
    "err_msg": "",
    "friends": {},        # 结构: {"好友名": "online"/"offline"}
    "requests": [],       # 收到的好友请求
    "active_toast": "",
    "toast_timer": 0,
    "incoming_invite": None, # 接收到的对战申请，结构: "发件人名字"
    "opponent_name": ""
}

# --- 智能声效反馈引擎 ---
class SoundController:
    def __init__(self):
        sfx_map = {"move": "move.wav", "rotate": "rotate.wav", "drop": "drop.wav",
                   "clear": "clear.wav", "attack": "attack.wav", "over": "gameover.wav"}
        self.sounds = {}
        for name, file in sfx_map.items():
            p = resource_path(os.path.join("assets", file))
            if os.path.exists(p):
                self.sounds[name] = pygame.mixer.Sound(p)
                self.sounds[name].set_volume(0.4)

        self.bgm_normal = resource_path(os.path.join("assets", "resonance.wav"))
        self.bgm_fast = resource_path(os.path.join("assets", "fast_resonance.wav"))
        self.bgm_state, self.bgm_playing = "normal", False
        self.last_move_time = 0

    def play(self, name):
        if name in self.sounds: 
            if name == "clear": self.sounds[name].set_volume(0.4)
            self.sounds[name].play()

    def play_move(self):
        now = pygame.time.get_ticks()
        if now - self.last_move_time > 100:
            if "move" in self.sounds: self.sounds["move"].play()
            self.last_move_time = now

    def play_clear(self, combo):
        if "clear" in self.sounds:
            snd = self.sounds["clear"]
            snd.set_volume(min(1.0, 0.4 + (combo - 1) * 0.2))
            snd.play()

    def set_danger_bgm(self, is_danger):
        target_state = "fast" if is_danger else "normal"
        target_path = self.bgm_fast if is_danger else self.bgm_normal
        if self.bgm_state != target_state:
            self.bgm_state = target_state
            if os.path.exists(target_path):
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

def get_font(size):
    p = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]
    for f in p:
        if os.path.exists(f): return pygame.font.Font(f, size)
    return pygame.font.Font(None, size)

def trigger_toast(msg):
    lobby_data["active_toast"] = msg
    lobby_data["toast_timer"] = 60 # 2秒展示

# --- 核心游戏物理沙盒 ---
class Tetris:
    def __init__(self, mode="single", sock=None, sfx=None, opponent=""):
        self.mode, self.socket, self.sfx, self.opponent = mode, sock, sfx, opponent
        self.grid = [[0] * COLUMNS for _ in range(ROWS)]
        self.opponent_grid = [[0] * COLUMNS for _ in range(ROWS)]
        self.bag = []
        self.current_piece = self._get_from_bag()
        self.next_piece = self._get_from_bag()
        self.pos = [0, COLUMNS // 2 - 1]
        
        self.game_over, self.opponent_game_over = False, False
        self.score, self.total_lines, self.level = 0, 0, 1
        self.flashing_rows, self.flash_timer, self.combo_count = [], 0, 0

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
            self.combo_count = 0
            self.spawn_next()

    def finalize_clear(self):
        cleared = len(self.flashing_rows)
        new_grid = [row for i, row in enumerate(self.grid) if i not in self.flashing_rows]
        for _ in range(cleared): new_grid.insert(0, [0] * COLUMNS)
        self.grid = new_grid
        
        self.total_lines += cleared
        self.level = 1 + (self.total_lines // 10)
        self.score += (cleared ** 2) * 100 * self.combo_count 
        
        if self.mode == "multi" and self.socket and cleared >= 2:
            atk = {2:1, 3:2, 4:4}.get(cleared, 0)
            if atk > 0:
                if self.sfx: self.sfx.play("attack")
                try:
                    pkg = json.dumps({"type": "attack", "target": self.opponent, "lines": atk}) + "\n"
                    self.socket.sendall(pkg.encode('utf-8'))
                except: pass
        self.flashing_rows = []
        self.spawn_next()

    def spawn_next(self):
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
        # 网格整体上移后，检查当前方块是否与新网格碰撞；若碰撞则向上回退
        while self.check_collision() and self.pos[0] > 0:
            self.pos[0] -= 1
        # 若回退后仍在顶部碰撞，则游戏结束
        if self.check_collision():
            self.game_over = True
            if self.sfx: self.sfx.play("over")
        danger = any(self.grid[r][c] for r in range(5) for c in range(COLUMNS))
        if self.sfx: self.sfx.set_danger_bgm(danger)

    def draw_grid(self, screen, grid, offset_x, title, is_opponent=False):
        header = f"{title} | LV.{self.level} | 得分:{self.score}"
        if not is_opponent and self.combo_count > 1: header += f" | Combo x{self.combo_count}!"
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

# --- 异步全局网络网关 ---
def network_listener(sock, game_engine_ref_box):
    buffer = ""
    global current_state
    while True:
        try:
            data = sock.recv(4096).decode('utf-8')
            if not data: break
            buffer += data
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if not line.strip(): continue
                msg = json.loads(line)
                m_type = msg.get("type")
                
                if m_type == "login_resp":
                    if msg.get("success"):
                        lobby_data["my_name"] = msg.get("username")
                        lobby_data["friends"] = msg.get("friends", {})
                        lobby_data["requests"] = msg.get("requests", [])
                        lobby_data["conn_status"] = "LOBBY"
                    else:
                        lobby_data["err_msg"] = msg.get("reason", "验证失败")
                        lobby_data["conn_status"] = "DISCONNECTED"
                        
                elif m_type == "toast":
                    trigger_toast(msg.get("msg", ""))
                    
                elif m_type == "friend_status":
                    user = msg.get("username")
                    stat = msg.get("status")
                    if user in lobby_data["friends"]:
                        lobby_data["friends"][user] = stat
                        
                elif m_type == "new_request":
                    lobby_data["requests"].append(msg.get("from"))
                    trigger_toast(f"🔔 收到来自 {msg.get('from')} 的好友申请")
                    
                elif m_type == "sync_requests":
                    lobby_data["requests"] = msg.get("requests", [])
                    
                elif m_type == "friend_added":
                    user = msg.get("username")
                    stat = msg.get("status", "offline")
                    lobby_data["friends"][user] = stat
                    if "sync_requests" in msg:
                        lobby_data["requests"] = msg.get("sync_requests")
                    trigger_toast(f"🎉 已和 {user} 成功建立好友关系！")
                    
                elif m_type == "invite_received":
                    lobby_data["incoming_invite"] = msg.get("from")
                    
                elif m_type == "match_start":
                    opp = msg.get("opponent")
                    lobby_data["opponent_name"] = opp
                    # 激活实例化新对战模块句柄
                    game_engine_ref_box[0] = Tetris("multi", sock, None, opp) 
                    game_engine_ref_box[1] = True # 标记进入状态切换
                    
                elif m_type == "game_data":
                    if game_engine_ref_box[0]:
                        game_engine_ref_box[0].opponent_grid = msg.get("grid")
                        if "game_over" in msg:
                            game_engine_ref_box[0].opponent_game_over = msg.get("game_over")
                            
                elif m_type == "attack":
                    if game_engine_ref_box[0]:
                        game_engine_ref_box[0].add_garbage(msg.get("lines"))
        except: break

def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("俄罗斯方块：好友邀请对战版")
    clock = pygame.time.Clock()
    pygame.key.set_repeat(150, 50)
    
    sfx = SoundController()
    sfx.start_bgm()
    
    # 状态标记
    state = "LOGIN"
    input_name = ""
    input_ip = "127.0.0.1"
    input_add_friend = ""
    active_field = "NAME" # NAME, IP, FRIEND_BOX
    
    client_socket = None
    # 拳头包装引用盒，用于在线程内修改外部游玩引擎
    game_box = [None, False] 
    
    # 静态UI按钮区域计算
    field_name_rect = pygame.Rect(WIDTH//2 - 150, 220, 300, 45)
    field_ip_rect =   pygame.Rect(WIDTH//2 - 150, 290, 300, 45)
    btn_login_rect =  pygame.Rect(WIDTH//2 - 150, 360, 300, 50)
    
    btn_single_rect = pygame.Rect(80, 150, 260, 50)
    field_add_rect =  pygame.Rect(80, 290, 260, 45)
    btn_add_rect =    pygame.Rect(80, 350, 260, 45)
    
    btn_return_game = pygame.Rect(WIDTH - 160, 20, 140, 40)
    
    fall_time = 0
    
    while True:
        screen.fill(BG_COLOR)
        dt = clock.tick(30)
        fall_time += dt
        
        # 吐司消息计时器衰减
        if lobby_data["toast_timer"] > 0:
            lobby_data["toast_timer"] -= 1
            if lobby_data["toast_timer"] == 0: lobby_data["active_toast"] = ""

        # 检测线程中介是否要求强制开启对战状态
        if game_box[1]:
            game_box[1] = False
            # 剥离并传入声效控制器
            game_box[0].sfx = sfx
            state = "MULTI"

        current_speed = max(100, 450 - (game_box[0].level * 40)) if game_box[0] else 450

        # --- 事件驱动总线 ---
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return
                
            if event.type == pygame.MOUSEBUTTONDOWN:
                if state == "LOGIN":
                    if field_name_rect.collidepoint(event.pos): active_field = "NAME"
                    elif field_ip_rect.collidepoint(event.pos): active_field = "IP"
                    elif btn_login_rect.collidepoint(event.pos) and input_name.strip():
                        # 发起全局网络握手
                        lobby_data["conn_status"] = "CONNECTING"
                        try:
                            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            client_socket.settimeout(2.0)
                            client_socket.connect((input_ip, 5555))
                            client_socket.settimeout(None)
                            
                            lobby_data["conn_status"] = "VERIFYING"
                            # 开启后台接收监听管道
                            threading.Thread(target=network_listener, args=(client_socket, game_box), daemon=True).start()
                            # 发送登录报文
                            pkg = json.dumps({"type": "login", "username": input_name.strip()}) + "\n"
                            client_socket.sendall(pkg.encode('utf-8'))
                            state = "LOBBY"
                        except Exception as e:
                            client_socket = None
                            lobby_data["conn_status"] = "DISCONNECTED"
                            lobby_data["err_msg"] = "连接服务器失败，请检查IP"
                            
                elif state == "LOBBY":
                    if field_add_rect.collidepoint(event.pos): active_field = "FRIEND_BOX"
                    else: active_field = None
                    
                    # 1. 触发单人快玩
                    if btn_single_rect.collidepoint(event.pos):
                        game_box[0] = Tetris("single", None, sfx)
                        state = "SINGLE"
                        
                    # 2. 触发添加好友请求
                    elif btn_add_rect.collidepoint(event.pos) and input_add_friend.strip():
                        if client_socket:
                            pkg = json.dumps({"type": "add_friend", "target": input_add_friend.strip()}) + "\n"
                            client_socket.sendall(pkg.encode('utf-8'))
                            input_add_friend = ""
                            
                    # 3. 实时循环遍历好友列表按钮（点击邀请）
                    y_offset = 200
                    for f_name, f_stat in list(lobby_data["friends"].items()):
                        if f_stat == "online":
                            invite_btn = pygame.Rect(WIDTH - 230, y_offset - 2, 120, 32)
                            if invite_btn.collidepoint(event.pos):
                                pkg = json.dumps({"type": "invite_friend", "target": f_name}) + "\n"
                                client_socket.sendall(pkg.encode('utf-8'))
                                trigger_toast(f"✉️ 已向 {f_name} 发出对战请求")
                        y_offset += 45
                        
                    # 4. 实时遍历处理收到的好友申请 (同意/拒绝)
                    req_y = 480
                    for req_user in list(lobby_data["requests"][:3]):
                        btn_acc = pygame.Rect(210, req_y - 2, 60, 30)
                        btn_rej = pygame.Rect(280, req_y - 2, 60, 30)
                        if btn_acc.collidepoint(event.pos):
                            pkg = json.dumps({"type": "accept_friend", "from": req_user}) + "\n"
                            client_socket.sendall(pkg.encode('utf-8'))
                        elif btn_rej.collidepoint(event.pos):
                            pkg = json.dumps({"type": "reject_friend", "from": req_user}) + "\n"
                            client_socket.sendall(pkg.encode('utf-8'))
                        req_y += 40
                        
                    # 5. 弹出弹窗邀请机制处理 (如果存在邀请弹窗)
                    if lobby_data["incoming_invite"]:
                        box_acc = pygame.Rect(WIDTH//2 - 130, HEIGHT//2 + 20, 100, 40)
                        box_rej = pygame.Rect(WIDTH//2 + 30, HEIGHT//2 + 20, 100, 40)
                        if box_acc.collidepoint(event.pos):
                            pkg = json.dumps({"type": "accept_invite", "from": lobby_data["incoming_invite"]}) + "\n"
                            client_socket.sendall(pkg.encode('utf-8'))
                            lobby_data["incoming_invite"] = None
                        elif box_rej.collidepoint(event.pos):
                            pkg = json.dumps({"type": "reject_invite", "from": lobby_data["incoming_invite"]}) + "\n"
                            client_socket.sendall(pkg.encode('utf-8'))
                            lobby_data["incoming_invite"] = None
                            
                elif state in ["SINGLE", "MULTI"]:
                    if btn_return_game.collidepoint(event.pos):
                        state = "LOBBY" if client_socket else "LOGIN"
                        sfx.set_danger_bgm(False)
                        game_box[0] = None

            if event.type == pygame.KEYDOWN:
                if state == "LOGIN":
                    if event.key == pygame.K_BACKSPACE:
                        if active_field == "NAME": input_name = input_name[:-1]
                        elif active_field == "IP": input_ip = input_ip[:-1]
                    elif event.unicode.isprintable():
                        if active_field == "NAME" and len(input_name) < 12: input_name += event.unicode
                        elif active_field == "IP": input_ip += event.unicode
                elif state == "LOBBY":
                    if active_field == "FRIEND_BOX":
                        if event.key == pygame.K_BACKSPACE: input_add_friend = input_add_friend[:-1]
                        elif event.unicode.isprintable() and len(input_add_friend) < 12: input_add_friend += event.unicode
                elif state in ["SINGLE", "MULTI"]:
                    if event.key == pygame.K_ESCAPE:
                        state = "LOBBY" if client_socket else "LOGIN"
                        sfx.set_danger_bgm(False)
                        game_box[0] = None
                    elif game_box[0] and not game_box[0].game_over and not game_box[0].opponent_game_over and game_box[0].flash_timer == 0:
                        g = game_box[0]
                        if event.key == pygame.K_LEFT and not g.check_collision(offset_c=-1): g.pos[1] -= 1; sfx.play_move()
                        elif event.key == pygame.K_RIGHT and not g.check_collision(offset_c=1): g.pos[1] += 1; sfx.play_move()
                        elif event.key == pygame.K_DOWN and not g.check_collision(offset_r=1): g.pos[0] += 1; sfx.play_move()
                        elif event.key == pygame.K_UP: g.rotate_piece(); sfx.play("rotate")

        # --- 状态物理循环帧渲染与格斗时钟更新 ---
        if state in ["SINGLE", "MULTI"] and game_box[0]:
            g = game_box[0]
            if not g.game_over and not g.opponent_game_over:
                if g.flash_timer > 0:
                    g.flash_timer -= 1
                    if g.flash_timer == 0: g.finalize_clear()
                else:
                    if fall_time > current_speed:
                        fall_time = 0
                        if not g.check_collision(offset_r=1): g.pos[0] += 1
                        else: g.lock_piece()
            
            # 实时数据广播同步
            if state == "MULTI" and client_socket:
                try:
                    temp = [list(row) for row in g.grid]
                    if not g.game_over:
                        for r, row in enumerate(g.current_piece):
                            for c, v in enumerate(row):
                                if v and 0<=g.pos[0]+r<ROWS and 0<=g.pos[1]+c<COLUMNS: temp[g.pos[0]+r][g.pos[1]+c]=1
                    pkg = json.dumps({"type": "game_data", "target": g.opponent, "grid": temp, "game_over": g.game_over}) + "\n"
                    client_socket.sendall(pkg.encode('utf-8'))
                except: pass

        # --- UI界面宏观绘制层 ---
        if state == "LOGIN":
            screen.blit(get_font(70).render("俄罗斯方块", True, (220,220,230)), (WIDTH//2 - 175, 80))
            
            # 绘制输入输入框框
            pygame.draw.rect(screen, (100,150,255) if active_field=="NAME" else GRID_COLOR, field_name_rect, 2, border_radius=4)
            screen.blit(get_font(20).render(f"注册独立用户名: {input_name}", True, (255,255,255)), (field_name_rect.x+12, field_name_rect.y+10))
            
            pygame.draw.rect(screen, (100,150,255) if active_field=="IP" else GRID_COLOR, field_ip_rect, 2, border_radius=4)
            screen.blit(get_font(20).render(f"对战主机IP: {input_ip}", True, (255,255,255)), (field_ip_rect.x+12, field_ip_rect.y+10))
            
            pygame.draw.rect(screen, BLOCK_COLOR, btn_login_rect, border_radius=6)
            screen.blit(get_font(24).render("进入游戏大厅", True, (255,255,255)), (btn_login_rect.x+75, btn_login_rect.y+10))
            
            if lobby_data["err_msg"]:
                screen.blit(get_font(18).render(lobby_data["err_msg"], True, (255,70,70)), (WIDTH//2 - 130, 430))
                
        elif state == "LOBBY":
            # 1. 顶部身份状态面板
            pygame.draw.rect(screen, PANEL_BG, pygame.Rect(40, 30, WIDTH - 80, 80), border_radius=8)
            screen.blit(get_font(26).render(f"🏆 欢迎来到竞技大厅 : {lobby_data['my_name']}", True, (100,255,150)), (60, 52))
            
            # 2. 左侧核心面板（单人快速开局，增加好友申请）
            pygame.draw.rect(screen, PANEL_BG, pygame.Rect(40, 130, 340, 530), border_radius=8)
            
            pygame.draw.rect(screen, (80, 100, 120), btn_single_rect, border_radius=5)
            screen.blit(get_font(22).render("🕹️ 单人模式 (极速快玩)", True, (255,255,255)), (btn_single_rect.x+20, btn_single_rect.y+10))
            
            # 分割线
            pygame.draw.line(screen, GRID_COLOR, (60, 230), (360, 230), 2)
            
            screen.blit(get_font(20).render("➕ 扩充我的朋友圈", True, (200,200,220)), (60, 250))
            pygame.draw.rect(screen, (100,150,255) if active_field=="FRIEND_BOX" else GRID_COLOR, field_add_rect, 2, border_radius=4)
            screen.blit(get_font(18).render(input_add_friend if input_add_friend else "输入好友ID...", True, (255,255,255) if input_add_friend else (120,120,130)), (field_add_rect.x+10, field_add_rect.y+10))
            
            pygame.draw.rect(screen, (60, 140, 90) if input_add_friend.strip() else (60,70,65), btn_add_rect, border_radius=5)
            screen.blit(get_font(20).render("发送好友申请", True, (255,255,255)), (btn_add_rect.x+70, btn_add_rect.y+10))
            
            # 好友申请专区
            screen.blit(get_font(20).render("📥 收到的好友申请", True, (200,200,220)), (60, 440))
            if not lobby_data["requests"]:
                screen.blit(get_font(16).render("暂无申请", True, (120,120,130)), (60, 480))
            else:
                req_y = 480
                for req_user in lobby_data["requests"][:3]:
                    screen.blit(get_font(18).render(f"用户: {req_user}", True, (255,255,255)), (60, req_y))
                    
                    btn_acc = pygame.Rect(210, req_y - 2, 60, 30)
                    pygame.draw.rect(screen, (40,150,80), btn_acc, border_radius=4)
                    screen.blit(get_font(14).render("同意", True, (255,255,255)), (btn_acc.x+16, btn_acc.y+6))
                    
                    btn_rej = pygame.Rect(280, req_y - 2, 60, 30)
                    pygame.draw.rect(screen, (180,60,60), btn_rej, border_radius=4)
                    screen.blit(get_font(14).render("拒绝", True, (255,255,255)), (btn_rej.x+16, btn_rej.y+6))
                    req_y += 40
            
            # 3. 右侧巨型好友花名册状态面板
            pygame.draw.rect(screen, PANEL_BG, pygame.Rect(400, 130, WIDTH - 440, 530), border_radius=8)
            screen.blit(get_font(22).render("👥 我的好友花名册", True, (220,220,240)), (430, 150))
            
            if not lobby_data["friends"]:
                screen.blit(get_font(18).render("广袤人海，孤单一人。在左侧尝试添加好友吧！", True, (140,140,150)), (430, 220))
            else:
                y_offset = 200
                for f_name, f_stat in list(lobby_data["friends"].items()):
                    # 绘制好友昵称
                    screen.blit(get_font(20).render(f_name, True, (255,255,255)), (430, y_offset))
                    # 绘制在线彩灯指示器
                    if f_stat == "online":
                        pygame.draw.circle(screen, (50,255,100), (620, y_offset + 14), 7)
                        screen.blit(get_font(16).render("在线", True, (50,255,100)), (635, y_offset + 4))
                        
                        # 呼叫对战按钮
                        invite_btn = pygame.Rect(WIDTH - 230, y_offset - 2, 120, 32)
                        pygame.draw.rect(screen, (130, 90, 200), invite_btn, border_radius=4)
                        screen.blit(get_font(16).render("⚡ 邀请对战", True, (255,255,255)), (invite_btn.x+18, invite_btn.y+5))
                    else:
                        pygame.draw.circle(screen, (150,150,160), (620, y_offset + 14), 7)
                        screen.blit(get_font(16).render("离线", True, (150,150,160)), (635, y_offset + 4))
                    
                    y_offset += 45

            # 4. 终极邀请通知拦截器弹窗
            if lobby_data["incoming_invite"]:
                overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 200))
                screen.blit(overlay, (0,0))
                
                popup = pygame.Rect(WIDTH//2 - 200, HEIGHT//2 - 100, 400, 200)
                pygame.draw.rect(screen, PANEL_BG, popup, border_radius=12)
                pygame.draw.rect(screen, (150,100,255), popup, 2, border_radius=12)
                
                txt = get_font(22).render(f"⚔️ 玩家 【{lobby_data['incoming_invite']}】 正在疯狂渴望与你决战！", True, (255,255,255))
                screen.blit(txt, (WIDTH//2 - txt.get_width()//2, HEIGHT//2 - 50))
                
                box_acc = pygame.Rect(WIDTH//2 - 130, HEIGHT//2 + 20, 100, 40)
                pygame.draw.rect(screen, (40,160,80), box_acc, border_radius=6)
                screen.blit(get_font(18).render("迎战", True, (255,255,255)), (box_acc.x+32, box_acc.y+8))
                
                box_rej = pygame.Rect(WIDTH//2 + 30, HEIGHT//2 + 20, 100, 40)
                pygame.draw.rect(screen, (180,60,60), box_rej, border_radius=6)
                screen.blit(get_font(18).render("拒绝", True, (255,255,255)), (box_rej.x+32, box_rej.y+8))

        elif state in ["SINGLE", "MULTI"] and game_box[0]:
            g = game_box[0]
            g.draw_grid(screen, g.grid, 50, lobby_data["my_name"] if lobby_data["my_name"] else "玩家")
            if state == "MULTI":
                g.draw_grid(screen, g.opponent_grid, 550, f"对手: {g.opponent}", True)
            
            # 渲染右上角返回大厅按钮
            pygame.draw.rect(screen, BLOCK_COLOR, btn_return_game, border_radius=5)
            screen.blit(get_font(22).render("返回大厅", True, (255,255,255)), (btn_return_game.x + 22, btn_return_game.y + 6))
            
            if g.game_over or g.opponent_game_over:
                if state == "SINGLE": txt = get_font(80).render("GAME OVER", True, (255,50,50))
                else:
                    if g.game_over: txt = get_font(80).render("YOU LOSE!", True, (255,50,50))
                    else: txt = get_font(80).render("YOU WIN!", True, (50,255,50))
                screen.blit(txt, (WIDTH//2 - txt.get_width()//2, HEIGHT//2 - 50))

        # 5. 全局系统飘字横幅 (Toast)
        if lobby_data["active_toast"]:
            t_surface = get_font(18).render(lobby_data["active_toast"], True, (255,255,255))
            t_rect = pygame.Rect(WIDTH//2 - t_surface.get_width()//2 - 15, 20, t_surface.get_width() + 30, 40)
            pygame.draw.rect(screen, (50,55,75), t_rect, border_radius=20)
            pygame.draw.rect(screen, (100,180,255), t_rect, 1, border_radius=20)
            screen.blit(t_surface, (WIDTH//2 - t_surface.get_width()//2, 28))

        pygame.display.flip()

if __name__ == "__main__":
    main()