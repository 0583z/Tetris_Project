import os


# ==============================
# 项目基础路径
# ==============================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ASSETS_DIR = os.path.join(BASE_DIR, "assets")
DATA_DIR = os.path.join(BASE_DIR, "data")


# ==============================
# 网络配置
# ==============================

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555

BUFFER_SIZE = 4096
ENCODING = "utf-8"


# ==============================
# 数据文件路径
# ==============================

USERS_FILE = os.path.join(DATA_DIR, "users.json")
FRIENDS_FILE = os.path.join(DATA_DIR, "friends.json")
RANKING_FILE = os.path.join(DATA_DIR, "ranking.json")
SCORE_FILE = os.path.join(DATA_DIR, "scores.json")


# ==============================
# 游戏基础配置
# ==============================

BLOCK_SIZE = 30
BOARD_WIDTH = 10
BOARD_HEIGHT = 20

INITIAL_FALL_SPEED = 500
MIN_FALL_SPEED = 100


# ==============================
# 窗口配置
# ==============================

WINDOW_TITLE = "俄罗斯方块双人对战"

SINGLE_PLAYER_MODE = "single"
MULTI_PLAYER_MODE = "multi"


def get_asset_path(filename: str) -> str:
    """
    获取资源文件路径。

    参数:
        filename: 资源文件名

    返回:
        完整资源文件路径
    """
    return os.path.join(ASSETS_DIR, filename)


def get_data_path(filename: str) -> str:
    """
    获取数据文件路径。

    参数:
        filename: 数据文件名

    返回:
        完整数据文件路径
    """
    return os.path.join(DATA_DIR, filename)