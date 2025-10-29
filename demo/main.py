import os
import pygame
import requests

# ---------------------------- CONFIG ----------------------------
SCREEN_W, SCREEN_H = 960, 540
FPS = 60
PORTRAIT_SIZE = 128
CHAT_BOX_H = 200
MARGIN = 12
SHOW_TOP_BAR = True

NPCS = [
    {"id": "Sam",   "name": "Sam",   "file": "sam.png"},
    {"id": "Linus", "name": "Linus", "file": "linus.png"},
    {"id": "Shane", "name": "Shane", "file": "shane.png"},
]

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
BG_FILE = os.path.join(ASSETS_DIR, "bg.jpg")

# Integration mode: set to True to call an HTTP API instead of the local Python stub
USE_HTTP_API = False
API_URL = "http://127.0.0.1:8000/npc_reply"  # e.g., FastAPI: GET /npc_reply?npc_id=Sam&player=Hello

# ------------------- INTEGRATION: YOUR PROJECT HERE -------------------
def get_npc_reply(npc_id: str, player_text: str) -> str:
    if USE_HTTP_API:
        try:
            r = requests.get(API_URL, params={"npc_id": npc_id, "player": player_text}, timeout=15)
            r.raise_for_status()
            data = r.json()
            return data.get("text", "(No text field in API response)")
        except Exception as e:
            return f"(API error: {e})"
    # Fallback: simple canned replies for demo
    canned = {
        "Sam":   ["Hey!", "The sun feels great today.", "Wanna toss a ball later?"],
        "Linus": ["Hello there.", "The wilderness has its secrets.", "Waste not, want not."],
        "Shane": ["What?", "I'm busy.", "The saloon's open, I guess."],
    }
    import random
    return random.choice(canned.get(npc_id, ["..."]))

# ---------------------------- STARDew PANEL HELPERS ----------------------------
def _lerp(a, b, t):
    return int(a + (b - a) * t)

def _vertical_gradient(size, top_rgb, bottom_rgb, radius=0):
    """生成垂直渐变圆角面板"""
    w, h = size
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        t = y / max(1, h - 1)
        c = (_lerp(top_rgb[0], bottom_rgb[0], t),
             _lerp(top_rgb[1], bottom_rgb[1], t),
             _lerp(top_rgb[2], bottom_rgb[2], t))
        pygame.draw.line(surf, c, (0, y), (w, y))
    if radius > 0:
        mask = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
        surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return surf

def draw_stardew_dialog(surface, rect, portrait_surf, npc_name):
    """
    在 rect 区域内绘制星露谷风格对话框（木框 + 渐变 + 右侧头像 + 名牌）
    返回：左侧“文字区域”的 rect，给 ChatLog 使用
    """
    # ---- 颜色（可调）----
    wood_dark = (105, 70, 35)     # 深木
    wood_mid  = (145, 100, 55)    # 木边
    wood_light= (190, 140, 90)    # 高光
    paper_top = (243, 226, 191)   # 米黄上
    paper_bot = (221, 186, 135)   # 米黄下
    border_radius = 14

    x, y, w, h = rect
    # 外木框
    pygame.draw.rect(surface, wood_dark, rect, border_radius=border_radius)
    pygame.draw.rect(surface, wood_mid,  rect, width=4, border_radius=border_radius)

    # 内边距
    pad = 10
    inner = pygame.Rect(x + pad, y + pad, w - 2*pad, h - 2*pad)

    # 左文字区 / 右头像区
    portrait_w = 170
    gap = 8
    text_rect = pygame.Rect(inner.left + 8, inner.top + 8,
                            inner.w - portrait_w - gap - 16, inner.h - 16)
    portrait_rect = pygame.Rect(text_rect.right + gap, inner.top + 8,
                                portrait_w - 16, text_rect.h - 46)  # 下方留名牌
    nameplate_rect = pygame.Rect(portrait_rect.left, portrait_rect.bottom + 6,
                                 portrait_rect.w, 32)

    # 渐变纸面
    paper = _vertical_gradient((inner.w, inner.h), paper_top, paper_bot, radius=border_radius-4)
    surface.blit(paper, inner.topleft)

    # 分隔线
    pygame.draw.line(surface, wood_light, (text_rect.right + gap//2, inner.top + 6),
                     (text_rect.right + gap//2, inner.bottom - 6), width=3)

    # 头像框
    pygame.draw.rect(surface, wood_mid, portrait_rect.inflate(8, 8), border_radius=8)
    pygame.draw.rect(surface, wood_light, portrait_rect.inflate(8, 8), width=2, border_radius=8)
    pygame.draw.rect(surface, wood_dark, portrait_rect, border_radius=6)
    if portrait_surf is not None:
        # 不再强制拉伸到固定 128x128，而是用“原始大小”（即与顶栏一致的 PORTRAIT_SIZE）
        img = portrait_surf
        tw, th = img.get_size()
        max_w, max_h = portrait_rect.w - 8, portrait_rect.h - 8
        # 若以后调大/调小面板，超出就按比例“仅向下”缩小以适配框；不放大，保持与顶栏一致观感
        scale = min(1.0, max_w / tw, max_h / th)
        if scale < 1.0:
            img = pygame.transform.smoothscale(img, (int(tw * scale), int(th * scale)))
        # 居中
        tx = portrait_rect.x + (portrait_rect.w - img.get_width()) // 2
        ty = portrait_rect.y + (portrait_rect.h - img.get_height()) // 2
        surface.blit(img, (tx, ty))

    # 名牌
    pygame.draw.rect(surface, wood_light, nameplate_rect, border_radius=6)
    pygame.draw.rect(surface, wood_mid,   nameplate_rect, width=2, border_radius=6)
    font_name = pygame.font.SysFont("Arial", 18)
    name_surf = font_name.render(npc_name, True, (60, 40, 20))
    surface.blit(name_surf, (nameplate_rect.centerx - name_surf.get_width() // 2,
                             nameplate_rect.centery - name_surf.get_height() // 2))

    # 角钉装饰
    for cx, cy in [(inner.left+6, inner.top+6), (inner.right-6, inner.top+6),
                   (inner.left+6, inner.bottom-6), (inner.right-6, inner.bottom-6)]:
        pygame.draw.circle(surface, wood_mid, (cx, cy), 3)

    return text_rect

# ---------------------------- UI HELPERS ----------------------------
class ChatLog:
    def __init__(self, max_entries=200):
        self.lines = []  # list of (speaker, text)
        self.max_entries = max_entries
        self.scroll = 0  # pixels scrolled

    def add(self, speaker, text):
        self.lines.append((speaker, text))
        if len(self.lines) > self.max_entries:
            self.lines = self.lines[-self.max_entries:]

    def draw(self, surf, font, rect, bg_color=None, text_color=(40, 28, 16), speaker_color=(90, 60, 30)):
        if bg_color is not None:
            pygame.draw.rect(surf, bg_color, rect, border_radius=8)

        x, y = rect.x + MARGIN, rect.y + MARGIN
        wrap_w = rect.w - 2*MARGIN

        # 渲染（带简单换行）
        rendered = []
        for speaker, text in self.lines:
            sp = font.render(f"{speaker}:", True, speaker_color)
            rendered.append(sp)
            words = text.split()
            cur = ""
            for w in words:
                test = (cur + " " + w).strip()
                if font.size(test)[0] > wrap_w:
                    rendered.append(font.render(cur, True, text_color))
                    cur = w
                else:
                    cur = test
            if cur:
                rendered.append(font.render(cur, True, text_color))
            rendered.append(font.render("", True, text_color))

        total_h = sum(r.get_height()+2 for r in rendered)
        view_h = rect.h - 2*MARGIN
        self.scroll = max(min(self.scroll, max(0, total_h - view_h)), 0)

        y2 = rect.y + rect.h - MARGIN
        for r in reversed(rendered):
            y2 -= (r.get_height()+2)
            if y2 + (r.get_height()+2) < rect.y + MARGIN:
                break
            if y2 < rect.y + rect.h - MARGIN:
                surf.blit(r, (x, y2 - self.scroll))

    def scroll_wheel(self, dy):
        self.scroll += dy * 24

class InputBox:
    def __init__(self, rect, font):
        self.rect = pygame.Rect(rect)
        self.font = font
        self.active = True        # 默认激活：无需点击即可输入
        self.text = ""

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
            return None
        elif event.type == pygame.KEYDOWN:   # 不要求 active 才接收
            if event.key == pygame.K_RETURN:
                t = self.text.strip()
                self.text = ""
                return t
            elif event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            else:
                if event.unicode and event.unicode.isprintable():
                    self.text += event.unicode
        return None

    def draw(self, surf):
        pygame.draw.rect(surf, (30,30,30), self.rect, border_radius=8)
        pygame.draw.rect(surf, (120,120,120), self.rect, 2, border_radius=8)
        txt = self.font.render(self.text or "Type here...", True, (220,220,220))
        surf.blit(txt, (self.rect.x + 10, self.rect.y + (self.rect.h - txt.get_height()) // 2))

# ---------------------------- MAIN APP ----------------------------
def load_image(path, size=None):
    img = pygame.image.load(path).convert_alpha()
    if size:
        img = pygame.transform.smoothscale(img, size)
    return img

def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Stardew-style NPC Demo")
    clock = pygame.time.Clock()

    # Fonts
    font = pygame.font.SysFont("Arial", 18)
    font_small = pygame.font.SysFont("Arial", 14)

    # Assets
    bg = load_image(BG_FILE, (SCREEN_W, SCREEN_H))
    portraits = []
    for npc in NPCS:
        path = os.path.join(ASSETS_DIR, npc["file"])
        img = load_image(path, (PORTRAIT_SIZE, PORTRAIT_SIZE))  # 顶栏头像尺寸
        portraits.append({"npc": npc, "img": img, "rect": pygame.Rect(0,0,PORTRAIT_SIZE,PORTRAIT_SIZE)})

    # Layout
    top_bar_h = PORTRAIT_SIZE + 2*MARGIN if SHOW_TOP_BAR else 0
    chat_rect = pygame.Rect(MARGIN, top_bar_h + MARGIN, SCREEN_W - 2*MARGIN, CHAT_BOX_H)
    input_rect = pygame.Rect(MARGIN, chat_rect.bottom + 8, SCREEN_W - 2*MARGIN, 36)

    # Position portraits centered at top (if shown)
    total_w = len(portraits)*PORTRAIT_SIZE + (len(portraits)-1)*MARGIN
    start_x = (SCREEN_W - total_w) // 2
    for i, p in enumerate(portraits):
        p["rect"].topleft = (start_x + i*(PORTRAIT_SIZE + MARGIN), MARGIN)

    chat = ChatLog()
    input_box = InputBox(input_rect, font)  # 默认已 active=True
    selected_npc = NPCS[0]  # default selection

    chat.add("System", "Type and press Enter to talk. Click a portrait to switch NPC.")
    chat.add("System", f"Talking to: {selected_npc['name']}")

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1 and SHOW_TOP_BAR:
                    for p in portraits:
                        if p["rect"].collidepoint(event.pos):
                            selected_npc = p["npc"]
                            chat.add("System", f"Talking to: {selected_npc['name']}")
                if event.button == 4:  # wheel up
                    chat.scroll_wheel(-1)
                if event.button == 5:  # wheel down
                    chat.scroll_wheel(1)

            # 输入框事件（无需先点击）
            sent = input_box.handle_event(event)
            if sent:
                chat.add("You", sent)
                reply = get_npc_reply(selected_npc["id"], sent)
                chat.add(selected_npc["name"], reply)

        # Draw
        screen.blit(bg, (0,0))

        # 顶部头像条（可关）
        if SHOW_TOP_BAR:
            bar_rect = pygame.Rect(0,0,SCREEN_W, top_bar_h + 4)
            s = pygame.Surface((bar_rect.w, bar_rect.h), pygame.SRCALPHA)
            s.fill((0,0,0,90))
            screen.blit(s, bar_rect.topleft)
            for p in portraits:
                screen.blit(p["img"], p["rect"].topleft)
                name_surf = font_small.render(p["npc"]["name"], True, (255,255,255))
                name_x = p["rect"].x + (PORTRAIT_SIZE - name_surf.get_width())//2
                screen.blit(name_surf, (name_x, p["rect"].bottom + 2))
                if p["npc"]["id"] == selected_npc["id"]:
                    pygame.draw.rect(screen, (255,255,100), p["rect"], 3, border_radius=8)
                else:
                    pygame.draw.rect(screen, (200,200,200), p["rect"], 1, border_radius=8)

        # --- Stardew-style dialog panel ---
        # 右侧头像：与顶栏“完全一致大小”
        sel_img = None
        for p in portraits:
            if p["npc"]["id"] == selected_npc["id"]:
                sel_img = p["img"]  # 已经是 PORTRAIT_SIZE 大小
                break

        text_area = draw_stardew_dialog(
            surface=screen,
            rect=chat_rect,
            portrait_surf=sel_img,
            npc_name=selected_npc["name"]
        )

        # 在面板的文字区绘制聊天内容（不涂底色）
        chat.draw(screen, font, text_area, bg_color=None)
        input_box.draw(screen)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()

if __name__ == "__main__":
    main()
