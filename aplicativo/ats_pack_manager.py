# -*- coding: utf-8 -*-
"""
ATS Pack Manager - Gerenciador de pacotes de som para o ts-fmod-plugin
(American Truck Simulator / Euro Truck Simulator 2)

- Lista os pacotes de som (.bank + .bank.guids) da pasta do plugin
- Importa pacotes de .zip/.scs/pasta/.bank direto para a pasta do plugin
- Perfis por caminhao: motor, cabine/interior e navegacao
- Previa do som (FMOD) com controle de RPM e carga
- Edita o sound_levels.txt (volumes)
- Grava o selected.bank.txt (nao gera .scs)
"""
import os, re, sys, io, json, time, shutil, zipfile, ctypes, string, threading, urllib.request
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP = "ATS&ETS2"
VERSION = "2.1 • Light & Dark"
CFG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ATS_Pack_Manager")
CFG_FILE = os.path.join(CFG_DIR, "config.json")
PLUGIN_URL = "https://github.com/dariowouters/ts-fmod-plugin/releases/latest"

GAMES = {
    "ATS":  {"folder": "American Truck Simulator", "exe": "amtrucks.exe"},
    "ETS2": {"folder": "Euro Truck Simulator 2",  "exe": "eurotrucks2.exe"},
}
LEVEL_KEYS = [("master", "Geral"), ("engine", "Motor"), ("exhaust", "Escapamento"), ("turbo", "Turbo"),
              ("interior", "Interior / cabine"), ("navigation", "Navegação"),
              ("exterior_when_windows_closed", "Externo c/ janelas fechadas")]

# ======================================================================= utilidades
def safe_name(s):
    s = os.path.splitext(os.path.basename(s))[0] if s.lower().endswith(".bank") else s
    s = re.sub(r"[^A-Za-z0-9_\-]+", "_", s).strip("_")
    return s or "som"

def category_of(event):
    e = event.lower()
    if e.startswith("engine/"): return "motor"
    if e.startswith("interior/"): return "cabine"
    return "nav"

def read_guids(path):
    """Retorna lista de (guid, 'event:/...') do arquivo .bank.guids"""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                p = line.split()
                if len(p) >= 2: out.append((p[0], p[1]))
    except OSError: pass
    return out

class Bank:
    def __init__(self, plugin_dir, bank_path):
        self.path = bank_path
        rel = os.path.relpath(bank_path, plugin_dir).replace("\\", "/")
        self.name = rel[:-5]                       # sem .bank
        self.guids_path = bank_path + ".guids"
        self.entries = read_guids(self.guids_path)
        self.events = [p[len("event:/"):] for g, p in self.entries if p.startswith("event:/")]
        self.cats = sorted({category_of(e) for e in self.events})
        self.size = os.path.getsize(bank_path)
    @property
    def ok(self): return os.path.isfile(self.guids_path) and " " not in self.name
    def cats_label(self):
        names = {"motor": "Motor", "cabine": "Cabine", "nav": "Navegação"}
        return ", ".join(names[c] for c in self.cats) or "?"

def scan_banks(plugin_dir):
    banks = []
    if not os.path.isdir(plugin_dir): return banks
    for r, _, fs in os.walk(plugin_dir):
        for f in fs:
            if f.lower().endswith(".bank") and f.lower() != "master.bank":
                banks.append(Bank(plugin_dir, os.path.join(r, f)))
    return sorted(banks, key=lambda b: b.name.lower())

def find_game_dirs(game):
    folder = GAMES[game]["folder"]
    cands = [os.path.join(r"F:\SteamLibrary\steamapps\common", folder)]
    steam_roots = [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    for root in steam_roots:
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            with open(vdf, encoding="utf-8", errors="ignore") as f:
                for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                    cands.append(os.path.join(m.group(1).replace("\\\\", "\\"), "steamapps", "common", folder))
        cands.append(os.path.join(root, "steamapps", "common", folder))
    for d in string.ascii_uppercase:
        cands.append(f"{d}:\\SteamLibrary\\steamapps\\common\\{folder}")
    seen, found = set(), []
    for c in cands:
        k = os.path.normcase(os.path.normpath(c))
        if k not in seen and os.path.isfile(os.path.join(c, "bin", "win_x64", GAMES[game]["exe"])):
            seen.add(k); found.append(c)
    return found

def extract_banks_from(src, plugin_dir, prefix=""):
    """Importa .bank/.bank.guids de zip/scs/pasta/arquivo. Retorna nomes importados."""
    imported, pairs = [], {}   # nome_base -> {"bank": (leitor), "guids": (leitor)}
    def add(fname, reader):
        low = fname.lower()
        if low.endswith(".bank.guids"): key, kind = fname[:-11], "guids"
        elif low.endswith(".bank"):     key, kind = fname[:-5], "bank"
        else: return
        if os.path.basename(key).lower() == "master": return
        pairs.setdefault(key, {})[kind] = reader
    if os.path.isdir(src):
        for r, _, fs in os.walk(src):
            for f in fs:
                full = os.path.join(r, f)
                add(os.path.relpath(full, src), (lambda p=full: open(p, "rb").read()))
        base_label = os.path.basename(os.path.normpath(src))
    elif src.lower().endswith((".zip", ".scs")):
        try: z = zipfile.ZipFile(src)
        except zipfile.BadZipFile:
            raise ValueError("Esse arquivo não é ZIP (pode ser .scs HashFS ou .rar).\n"
                             "Extraia com 7-Zip/WinRAR ou SCS Extractor e importe a PASTA.")
        for n in z.namelist():
            if not n.endswith("/"): add(n, (lambda n=n: z.read(n)))
        base_label = os.path.splitext(os.path.basename(src))[0]
    else:
        b = src[:-5] if src.lower().endswith(".bank") else src
        if src.lower().endswith(".bank.guids"): b = src[:-11]
        add(os.path.basename(b) + ".bank", lambda: open(b + ".bank", "rb").read())
        if os.path.isfile(b + ".bank.guids"):
            add(os.path.basename(b) + ".bank.guids", lambda: open(b + ".bank.guids", "rb").read())
        base_label = ""
    multi = len([k for k, v in pairs.items() if "bank" in v]) > 1
    for key, v in pairs.items():
        if "bank" not in v: continue
        bname = safe_name(os.path.basename(key))
        # nomes genericos (engine, sound, truck) ganham o nome do pacote
        if base_label and not multi:
            bname = safe_name(base_label)
        elif base_label and bname.lower() in ("engine", "sound", "truck", "interior", "exterior", "cabin"):
            bname = safe_name(base_label) + "_" + bname
        final, i = bname, 2
        while os.path.exists(os.path.join(plugin_dir, final + ".bank")):
            final = f"{bname}_{i}"; i += 1
        os.makedirs(plugin_dir, exist_ok=True)
        with open(os.path.join(plugin_dir, final + ".bank"), "wb") as f: f.write(v["bank"]())
        if "guids" in v:
            with open(os.path.join(plugin_dir, final + ".bank.guids"), "wb") as f: f.write(v["guids"]())
        imported.append((final, "guids" in v))
    return imported

def write_selected(plugin_dir, names):
    p = os.path.join(plugin_dir, "selected.bank.txt")
    if os.path.isfile(p): shutil.copy2(p, p + ".bak")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(n for n in names if n) + "\n")

def read_selected(plugin_dir):
    p = os.path.join(plugin_dir, "selected.bank.txt")
    try:
        with open(p, encoding="utf-8", errors="replace") as f: return f.read().split()
    except OSError: return []


# ======================================================================= windows: docs, janela e teclado
def documents_dir():
    try:
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)   # CSIDL_PERSONAL (respeita OneDrive)
        if buf.value: return buf.value
    except Exception: pass
    return os.path.join(os.path.expanduser("~"), "Documents")

def find_game_window():
    try:
        u = ctypes.windll.user32
        for title in ("American Truck Simulator", "Euro Truck Simulator 2", "American Truck Simulator Multiplayer",
                      "Euro Truck Simulator 2 Multiplayer"):
            h = u.FindWindowW(None, title)
            if h: return h
        found = []
        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def cb(h, _):
            n = u.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1); u.GetWindowTextW(h, b, n + 1)
                if "Truck Simulator" in b.value and u.IsWindowVisible(h) and APP not in b.value:
                    found.append(h); return False
            return True
        u.EnumWindows(CB(cb), 0)
        return found[0] if found else None
    except Exception:
        return None

SCAN = {"s": 0x1F, "d": 0x20, "k": 0x25, "r": 0x13, "e": 0x12, "l": 0x26, "o": 0x18, "a": 0x1E,
        " ": 0x39, "enter": 0x1C, "console": 0x29}

class _KI(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]
class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",); _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

def _key(sc, up=False):
    i = _INPUT(); i.type = 1; i.ki = _KI(0, sc, 0x0008 | (0x0002 if up else 0), 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_INPUT))

def _tap(sc):
    import time
    _key(sc); time.sleep(0.03); _key(sc, True); time.sleep(0.03)

def send_console_command(hwnd, cmd):
    """Foca o jogo, abre o console, digita o comando, Enter e fecha o console."""
    import time
    u = ctypes.windll.user32
    try:
        if u.IsIconic(hwnd): u.ShowWindow(hwnd, 9)
        u.keybd_event(0x12, 0, 0, 0); u.keybd_event(0x12, 0, 2, 0)    # ALT libera o foco
        u.SetForegroundWindow(hwnd); time.sleep(0.6)
        if u.GetForegroundWindow() != hwnd: return False
        _tap(SCAN["console"]); time.sleep(0.3)
        for ch in cmd.lower(): _tap(SCAN[ch])
        _tap(SCAN["enter"]); time.sleep(0.5)
        _tap(SCAN["console"])
        return True
    except Exception:
        return False

# ======================================================================= FMOD (previa)
class FMODGuid(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

def parse_guid(s):
    h = s.strip("{}").replace("-", "")
    g = FMODGuid(); g.Data1 = int(h[0:8], 16); g.Data2 = int(h[8:12], 16); g.Data3 = int(h[12:16], 16)
    for i in range(8): g.Data4[i] = int(h[16 + i * 2:18 + i * 2], 16)
    return g

class Preview:
    """Toca eventos de um .bank usando a FMOD Studio API (fmodstudio.dll)."""
    def __init__(self): self.dll = None; self.sys = None; self.banks = []; self.insts = []; self.err = ""; self.dll_path = ""; self.version = ""
    def load_dll(self, dirs):
        if self.dll: return True
        for d in dirs:
            for name in ("fmodstudio.dll", "fmodstudioL.dll"):
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    try:
                        if hasattr(os, "add_dll_directory"): os.add_dll_directory(d)
                        for core in (os.path.join(d, "fmod.dll"),
                                     os.path.join(d, "..", "..", "..", "core", "lib", "x64", "fmod.dll")):
                            if os.path.isfile(core):
                                if hasattr(os, "add_dll_directory"): os.add_dll_directory(os.path.dirname(os.path.abspath(core)))
                                ctypes.WinDLL(os.path.abspath(core)); break
                        self.dll = ctypes.WinDLL(p); self.dll_path = p; return True
                    except OSError as e: self.err = str(e)
        self.err = self.err or "fmodstudio.dll não encontrado"
        return False
    @staticmethod
    def _bcd(n): return int(str(n), 16)          # 22 -> 0x22 (formato FMOD_VERSION)
    @staticmethod
    def dll_version(p):
        try:
            ver = ctypes.windll.version
            size = ver.GetFileVersionInfoSizeW(p, None)
            if not size: return None
            buf = ctypes.create_string_buffer(size)
            ver.GetFileVersionInfoW(p, 0, size, buf)
            ptr, ln = ctypes.c_void_p(), ctypes.c_uint()
            if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(ln)): return None
            ffi = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
            return (ffi[2] >> 16, ffi[2] & 0xFFFF, ffi[3] >> 16)
        except Exception: return None
    def start_system(self):
        if self.sys: return True
        d = self.dll; sysp = ctypes.c_void_p(); last = None
        cands = []
        v = self.dll_version(self.dll_path)
        if v: cands.append((self._bcd(v[0]) << 16) | (self._bcd(v[1]) << 8) | self._bcd(v[2]))
        for major in (2, 1):
            for minor in range(15, -1, -1):
                for patch in range(99, -1, -1):
                    cands.append((self._bcd(major) << 16) | (self._bcd(minor) << 8) | self._bcd(patch))
        for ver in cands:
            r = d.FMOD_Studio_System_Create(ctypes.byref(sysp), ctypes.c_uint(ver))
            if r == 0:
                r = d.FMOD_Studio_System_Initialize(sysp, 256, 0, 0, None)
                if r == 0:
                    self.sys = sysp; self.version = "%x.%02x.%02x" % (ver >> 16, (ver >> 8) & 0xFF, ver & 0xFF)
                    return True
                self.err = f"Falha ao iniciar FMOD (erro {r})"; return False
            last = r
        self.err = f"Não consegui iniciar o FMOD (erro {last}). DLL: {self.dll_path} versão {v}"
        return False
    def unload(self):
        self.stop()
        for b in self.banks: self.dll.FMOD_Studio_Bank_Unload(b)
        self.banks = []
    def load(self, files):
        self.unload()
        for f in files:
            b = ctypes.c_void_p()
            r = self.dll.FMOD_Studio_System_LoadBankFile(self.sys, f.encode("utf-8"), 0, ctypes.byref(b))
            if r == 0: self.banks.append(b)
            elif not f.lower().endswith("master.bank"): raise RuntimeError(f"FMOD erro {r} ao carregar {os.path.basename(f)}")
    def play(self, guid):
        desc, inst = ctypes.c_void_p(), ctypes.c_void_p()
        g = parse_guid(guid)
        r = self.dll.FMOD_Studio_System_GetEventByID(self.sys, ctypes.byref(g), ctypes.byref(desc))
        if r: raise RuntimeError(f"Evento não encontrado (erro FMOD {r})")
        self.dll.FMOD_Studio_EventDescription_CreateInstance(desc, ctypes.byref(inst))
        self.dll.FMOD_Studio_EventInstance_Start(inst)
        self.insts.append(inst)
    def set_param(self, name, val):
        for i in self.insts:
            self.dll.FMOD_Studio_EventInstance_SetParameterByName(i, name.encode(), ctypes.c_float(val), 0)
    def stop(self):
        for i in self.insts:
            self.dll.FMOD_Studio_EventInstance_Stop(i, 1); self.dll.FMOD_Studio_EventInstance_Release(i)
        self.insts = []
    def update(self):
        if self.sys: self.dll.FMOD_Studio_System_Update(self.sys)

# ======================================================================= interface (estilo Sound Pack Manager)
RELEASE_API = "https://api.github.com/repos/dariowouters/ts-fmod-plugin/releases/latest"
PALETTES = {
    "light": dict(BG="#F6F8FA", CARD="#FFFFFF", ROW="#FFFFFF", ROW2="#F3F6F9",
        FG="#20313F", MUT="#566777", BLUE="#255E8D", BLUE_H="#194A72",
        GREEN="#27634C", RED="#A13232", WARN_BG="#EDF4FA", WARN_FG="#255E8D",
        OK="#27634C", BORDER="#DCE4EB", SOFT="#E5EFF7", PRIMARY_FG="#FFFFFF",
        TRACK="#8395A5", DISABLED="#7C8790"),
    "dark": dict(BG="#161C22", CARD="#202930", ROW="#202930", ROW2="#27333F",
        FG="#F2F6FA", MUT="#B5C3CF", BLUE="#85BDF2", BLUE_H="#A2CCF5",
        GREEN="#85CBA7", RED="#F09B9B", WARN_BG="#243545", WARN_FG="#B5D7F5",
        OK="#85CBA7", BORDER="#445362", SOFT="#2C4358", PRIMARY_FG="#142332",
        TRACK="#7C91A3", DISABLED="#8F9DAA"),
}
def use_palette(name):
    globals().update(PALETTES.get(name,PALETTES["light"]))
use_palette("light")
FONT = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
VOL_KEYS = [("master", "Volume Geral:"), ("engine", "Som do Motor:"), ("exhaust", "Som do Escapamento:"),
            ("turbo", "Som do Turbo:"), ("interior", "Som de Efeitos de Cabine:"),
            ("exterior_when_windows_closed", "Som com Janelas Fechadas:"), ("navigation", "Voz da Navegação:")]
PREVIEW_LEN = 12.0   # segundos da simulacao de aceleracao

def rpm_curve(t):
    """(rpm, carga) para simular: marcha lenta -> acelera -> segura -> freio motor -> lenta"""
    if t < 2:   return 650, 0.0
    if t < 6:   return 650 + (2000 - 650) * (t - 2) / 4, 1.0
    if t < 7.5: return 2000, 1.0
    if t < 11:  return 2000 - (2000 - 650) * (t - 7.5) / 3.5, 0.0
    return 650, 0.0

def btn(parent, text, cmd, bg=None, hover=None, w=None, **kw):
    bg = BLUE if bg is None else bg
    hover = BLUE_H if hover is None else hover
    fg = FG if bg in (SOFT, ROW2, CARD, BG) else PRIMARY_FG
    b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                  activebackground=hover, activeforeground=fg, disabledforeground=DISABLED,
                  relief="flat", bd=0, font=(FONT, 10), cursor="hand2", padx=16, pady=11,
                  highlightthickness=1, highlightbackground=bg, highlightcolor=BLUE, **kw)
    if w: b.config(width=w)
    b.bind("<Enter>", lambda e: b.config(bg=hover) if str(b['state']) != 'disabled' else None)
    b.bind("<Leave>", lambda e: b.config(bg=ROW2 if str(b["state"])=="disabled" else bg))
    return b

def section(parent, title, scroll=False):
    outer = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
    outer.pack(fill="both", expand=True, padx=0, pady=(8, 0))
    tk.Label(outer, text=title, bg=CARD, fg=FG, font=(FONT, 13, "bold")).pack(anchor="w", padx=24, pady=(20,12))
    body = tk.Frame(outer, bg=CARD); body.pack(fill="both", expand=True, padx=20, pady=(0,20))
    if scroll:
        area=Scrollable(body);area.pack(fill="both",expand=True)
        area.inner.configure(bg=CARD)
        return area.inner
    return body

def warn_box(parent, lines):
    f = tk.Frame(parent, bg=WARN_BG); f.pack(fill="x", pady=(0,14))
    tk.Label(f, text="Depois de salvar, aplique no jogo", bg=WARN_BG, fg=WARN_FG,
             font=(FONT, 10,"bold")).pack(anchor="w", padx=16,pady=(12,2))
    tk.Label(f, text='Use o botão Aplicar no jogo ou digite "sdk reload" no console.',
             bg=WARN_BG, fg=MUT, font=(FONT,10)).pack(anchor="w", padx=16,pady=(0,12))
    return f

class Scrollable(tk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg=ROW2, **kw)
        self.cv = tk.Canvas(self, bg=ROW2, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.cv.yview)
        self.inner = tk.Frame(self.cv, bg=ROW2)
        self.inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.win = self.cv.create_window((0, 0), window=self.inner, anchor="nw")
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfig(self.win, width=e.width))
        self.cv.configure(yscrollcommand=sb.set)
        self.cv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.cv.bind_all("<MouseWheel>", self._wheel, add="+")
        self.cv.bind_all("<Button-4>", self._wheel, add="+")
        self.cv.bind_all("<Button-5>", self._wheel, add="+")
    def _wheel(self,e):
        w=self.winfo_containing(self.winfo_pointerx(),self.winfo_pointery())
        while w is not None:
            if w is self:
                step=(-1 if e.num==4 else 1) if e.num in (4,5) else int(-e.delta/120)
                self.cv.yview_scroll(step,"units");return
            w=getattr(w,"master",None)

class MaterialScale(tk.Canvas):
    def __init__(self,parent,variable,command,**kw):
        super().__init__(parent,height=28,bg=CARD,bd=0,highlightthickness=1,
                         highlightbackground=CARD,highlightcolor=BLUE,takefocus=1,cursor="hand2",**kw)
        self.var,self.command=variable,command
        self.bind("<Configure>",lambda e:self.draw())
        self.bind("<Button-1>",self.change);self.bind("<B1-Motion>",self.change)
        for key,delta in [("Left",-.05),("Down",-.05),("Right",.05),("Up",.05)]:
            self.bind("<"+key+">",lambda e,d=delta:self.set(self.var.get()+d))
        self.bind("<Home>",lambda e:self.set(0));self.bind("<End>",lambda e:self.set(2))
        self.var.trace_add("write",lambda *a:self.draw())
    def set(self,value):
        value=max(0,min(2,round(value/.05)*.05));self.var.set(value);self.command(value)
    def change(self,event):
        self.focus_set();self.set((event.x-14)/max(1,self.winfo_width()-28)*2)
    def draw(self):
        self.delete("all");w=self.winfo_width();x=14+(max(0,min(2,self.var.get()))/2)*(w-28)
        self.create_line(14,14,w-14,14,fill=TRACK,width=4,capstyle="round")
        self.create_line(14,14,x,14,fill=BLUE,width=4,capstyle="round")
        self.create_oval(x-8,6,x+8,22,fill=BLUE,outline=BLUE)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = self.load_cfg()
        use_palette(self.cfg.get("theme","light"))
        self.title(self.app_title()); self.geometry("1240x850"); self.minsize(1100, 780); self.configure(bg=BG)
        try: self.iconbitmap(os.path.join(os.path.dirname(__file__), "ATS_ETS2.ico"))
        except Exception: pass
        self.banks, self.rows, self.preview = [], [], Preview()
        self.playing = None; self.play_t0 = 0; self.play_pos = 0.0
        self._setup_styles()
        self._pending = None
        self._header(); self._tabs()
        self.protocol("WM_DELETE_WINDOW",self.close_app)
        self.startup(); self._tick_job = self.after(50 if self.playing else 250, self._tick)

    def _setup_styles(self):
        self.configure(bg=BG)
        self.option_add("*Font", (FONT,10))
        self.option_add("*Entry.Background",CARD)
        self.option_add("*TCombobox*Listbox.background",CARD)
        self.option_add("*TCombobox*Listbox.foreground",FG)
        self.option_add("*TCombobox*Listbox.selectBackground",SOFT)
        self.option_add("*TCombobox*Listbox.selectForeground",FG)
        s=ttk.Style(self)
        if s.theme_use() != "clam":s.theme_use("clam")
        s.layout("TNotebook.Tab",[])
        s.configure("TNotebook",background=BG,borderwidth=0,tabmargins=0,lightcolor=BG,darkcolor=BG,bordercolor=BG)
        s.configure("Vertical.TScrollbar",background=BORDER,troughcolor=BG,arrowcolor=MUT,bordercolor=BG,
                    lightcolor=BORDER,darkcolor=BORDER,gripcount=0,borderwidth=0)
        s.map("Vertical.TScrollbar",background=[("active",SOFT),("pressed",BLUE)])
        s.configure("TCombobox",fieldbackground=CARD,background=SOFT,foreground=FG,arrowcolor=FG,
                    bordercolor=BORDER,lightcolor=BORDER,darkcolor=BORDER,padding=7)
        s.map("TCombobox",fieldbackground=[("readonly",CARD)],foreground=[("readonly",FG)],
              background=[("active",SOFT)],selectbackground=[("readonly",SOFT)],selectforeground=[("readonly",FG)])

    def set_theme(self,name):
        if name not in PALETTES or name==self.cfg.get("theme","light"):return
        page=getattr(self,"current_page","ronco")
        search=self.q.get();variant=self.pick_variant.get()
        levels={k:v.get() for k,v in self.lvl.items()}
        pending=set(self._pending) if self._pending is not None else None
        self.stop_preview()
        self.cfg["theme"]=name;self.save_cfg()
        for event in ("<MouseWheel>","<Button-4>","<Button-5>"):
            self.unbind_all(event)
        for child in self.winfo_children():child.destroy()
        use_palette(name);self._setup_styles()
        self.rows=[];self.playing=None;self._pending=pending
        self._header();self._tabs();self.refresh_all()
        self.q.set(search)
        for k,value in levels.items():
            self.lvl[k].set(value);self.lvl_lbl[k].config(text=f"{value:.2f}")
        self.pick_variant.set(variant);self.fill_pickups()
        self.show_page(page)

    def close_app(self):
        self.stop_preview()
        try:self.after_cancel(self._tick_job)
        except (AttributeError,tk.TclError):pass
        self.update_idletasks()
        try:self.preview.unload()
        except Exception:pass
        self.destroy()

    def app_title(self):
        return "ATS&ETS2  |  Sound Manager"

    # ---------------- config
    def load_cfg(self):
        try:
            with open(CFG_FILE, encoding="utf-8") as f: c = json.load(f)
        except Exception: c = {}
        c.setdefault("game", "ATS"); c.setdefault("game_dir", {}); c.setdefault("fmod_dir", "")
        c.setdefault("plugin_version", {})
        if c.get("theme") not in PALETTES:c["theme"]="light"
        return c
    def save_cfg(self):
        os.makedirs(CFG_DIR, exist_ok=True)
        with open(CFG_FILE, "w", encoding="utf-8") as f: json.dump(self.cfg, f, indent=2, ensure_ascii=False)
    @property
    def game(self): return self.cfg["game"]
    @property
    def game_dir(self): return self.cfg["game_dir"].get(self.game, "")
    @property
    def plugins_dir(self): return os.path.join(self.game_dir, "bin", "win_x64", "plugins")
    @property
    def plugin_dir(self): return os.path.join(self.plugins_dir, "ts-fmod-plugin")
    def game_ok(self):
        return bool(self.game_dir) and os.path.isfile(os.path.join(self.game_dir, "bin", "win_x64", GAMES[self.game]["exe"]))

    # ---------------- cabecalho
    def _header(self):
        side = tk.Frame(self, bg=CARD, width=206, highlightbackground=BORDER, highlightthickness=1)
        side.pack(side="left", fill="y"); side.pack_propagate(False)
        brand = tk.Frame(side,bg=CARD); brand.pack(fill="x",padx=22,pady=(30,32))
        try:
            self.brand_img = tk.PhotoImage(file=os.path.join(os.path.dirname(__file__),"logo.png"))
            tk.Label(brand,image=self.brand_img,bg=CARD).pack(anchor="w",pady=(0,12))
        except Exception: pass
        tk.Label(brand,text="ATS&ETS2",bg=CARD,fg=FG,font=(FONT,19,"bold")).pack(anchor="w")
        tk.Label(brand,text="SOUND MANAGER",bg=CARD,fg=MUT,font=(FONT,9)).pack(anchor="w",pady=(2,0))
        self.nav_buttons = {}
        for key,label in [("ronco","Biblioteca"),("pickups","Caminhonetes"),("vol","Volumes"),("inst","Instalação"),("con","Console")]:
            b=btn(side,label,lambda k=key:self.show_page(k),bg=CARD,hover=ROW2,anchor="w")
            b.pack(fill="x",padx=12,pady=3);self.nav_buttons[key]=b
        foot=tk.Frame(side,bg=CARD);foot.pack(side="bottom",fill="x",padx=22,pady=24)
        tk.Label(foot,text="Aparência",bg=CARD,fg=MUT,font=(FONT,9)).pack(anchor="w",pady=(0,6))
        self.theme_var=tk.StringVar(value="Escuro" if self.cfg.get("theme")=="dark" else "Claro")
        theme_box=ttk.Combobox(foot,textvariable=self.theme_var,values=["Claro","Escuro"],state="readonly",width=14)
        theme_box.pack(fill="x",pady=(0,16))
        theme_box.bind("<<ComboboxSelected>>",lambda e:self.set_theme("dark" if self.theme_var.get()=="Escuro" else "light"))
        tk.Label(foot,text="Material · 2.1",bg=CARD,fg=MUT,font=(FONT,9)).pack(anchor="w")
        tk.Label(foot,text="Seu som. No seu ritmo.",bg=CARD,fg=MUT,font=(FONT,9)).pack(anchor="w",pady=(4,0))
        self.main=tk.Frame(self,bg=BG);self.main.pack(side="left",fill="both",expand=True,padx=28,pady=24)
        top=tk.Frame(self.main,bg=BG);top.pack(fill="x",pady=(0,24))
        self.title_lbl=tk.Label(top,text=self.app_title(),bg=BG,fg=FG,font=(FONT,11,"bold"));self.title_lbl.pack(side="left")
        self.game_btns={}
        for k in ("ETS2","ATS"):
            b=btn(top,k,lambda k=k:self.set_game(k),bg=SOFT,hover=BORDER,w=5)
            b.pack(side="right",padx=(6,0));self.game_btns[k]=b
        self.page_title=tk.Label(self.main,bg=BG,fg=FG,font=(FONT,25,"bold"),anchor="w")
        self.page_title.pack(fill="x")
        self.page_sub=tk.Label(self.main,bg=BG,fg=MUT,font=(FONT,10),anchor="w")
        self.page_sub.pack(fill="x",pady=(6,18))
        self.paint_game_btns()

    def paint_game_btns(self):
        for k,b in self.game_btns.items():
            c=BLUE if k==self.game else SOFT
            b.config(bg=c,fg=PRIMARY_FG if k==self.game else FG)
            b.bind("<Leave>",lambda e,b=b,c=c:b.config(bg=c))

    def _tabs(self):
        bottom=tk.Frame(self.main,bg=BG);bottom.pack(side="bottom",fill="x",pady=(16,0))
        tk.Label(bottom,text="As alterações de som são globais no plugin.",bg=BG,fg=MUT,font=(FONT,9)).pack(side="left")
        self.apply_btn=btn(bottom,"Aplicar no jogo",self.apply_in_game)
        self.apply_btn.pack(side="right")
        self.nb=ttk.Notebook(self.main);self.nb.pack(fill="both",expand=True)
        self.t_inst,self.t_ronco,self.t_vol,self.t_con,self.t_pickups=(tk.Frame(self.nb,bg=BG) for _ in range(5))
        self.pages={"inst":self.t_inst,"ronco":self.t_ronco,"vol":self.t_vol,"con":self.t_con,"pickups":self.t_pickups}
        for frame in self.pages.values():self.nb.add(frame)
        self._tab_install();self._tab_ronco();self._tab_volume();self._tab_console();self._tab_pickups()
        self.show_page("ronco")

    def show_page(self,key):
        self.current_page=key
        self.stop_preview()
        text={"ronco":("Sua biblioteca de sons","Escolha um ronco, ouça a prévia e salve sua seleção."),
              "pickups":("Roncos de caminhonetes","Somente gravações reais. Original e esportivo, separados por veículo."),
              "vol":("Tudo no volume certo","Ajuste o equilíbrio dos sons sem pressa."),
              "inst":("Prepare seu jogo","Conecte a pasta do jogo e gerencie o plugin."),
              "con":("Conecte as mudanças","Configure o console para recarregar os sons durante o jogo.")}
        self.apply_btn.config(state="disabled" if key=="pickups" else "normal",bg=ROW2 if key=="pickups" else BLUE)
        self.page_title.config(text=text[key][0]);self.page_sub.config(text=text[key][1]);self.nb.select(self.pages[key])
        for k,b in self.nav_buttons.items():
            c=SOFT if k==key else CARD
            b.config(bg=c,fg=BLUE if k==key else MUT,font=(FONT,10,"bold" if k==key else "normal"))
            b.bind("<Leave>",lambda e,b=b,c=c:b.config(bg=c))

    def _tab_pickups(self):
        f=section(self.t_pickups,"Coleção de caminhonetes")
        h=tk.Frame(f,bg=CARD);h.pack(fill="x",pady=(0,14))
        tk.Label(h,text="Escapamento",bg=CARD,fg=MUT).pack(side="left")
        self.pick_variant=tk.StringVar(value="Original")
        cb=ttk.Combobox(h,textvariable=self.pick_variant,values=["Original","Esportivo"],state="readonly",width=16)
        cb.pack(side="right");cb.bind("<<ComboboxSelected>>",lambda e:self.fill_pickups())
        tk.Label(f,text="Os WAV são material de preparação: precisam virar bancos FMOD compatíveis.\nImportar aqui não instala nem aplica esses áudios no jogo.",
                 bg=WARN_BG,fg=WARN_FG,font=(FONT,10),justify="left",anchor="w",padx=14,pady=12).pack(side="bottom",fill="x",pady=(12,0))
        self.pick_scroll=Scrollable(f);self.pick_scroll.pack(fill="both",expand=True)
        self.pick_list=self.pick_scroll.inner
        self.fill_pickups()

    def fill_pickups(self):
        for w in self.pick_list.winfo_children():w.destroy()
        for key,title,motor in [("hilux","Toyota Hilux","2.8 diesel"),("s10","Chevrolet S10","2.8 diesel"),
              ("ranger","Ford Ranger","3.2 diesel"),("amarok","Volkswagen Amarok","3.0 V6 diesel"),("f150","Ford F-150","5.0 V8 · gasolina")]:
            path=self.cfg.get("pickup_audio",{}).get(key,{}).get(self.pick_variant.get(),"")
            ready=os.path.isfile(path)
            row=tk.Frame(self.pick_list,bg=CARD);row.pack(fill="x",pady=0)
            tk.Frame(row,bg=BORDER,height=1).pack(fill="x")
            inside=tk.Frame(row,bg=CARD);inside.pack(fill="x",pady=9)
            left=tk.Frame(inside,bg=CARD);left.pack(side="left",fill="x",expand=True)
            tk.Label(left,text=title,bg=CARD,fg=FG,font=(FONT,11,"bold")).pack(anchor="w")
            tk.Label(left,text=motor+"  ·  "+("WAV importado · banco pendente" if ready else "Sem gravação importada"),bg=CARD,fg=MUT,font=(FONT,9)).pack(anchor="w",pady=(3,0))
            btn(inside,"Importar WAV",lambda k=key:self.import_pickup(k),bg=SOFT,hover=BORDER).pack(side="right",padx=(8,0))
            b=btn(inside,"Ouvir",lambda p=path:self.listen_pickup(p),bg=ROW2,hover=BORDER)
            b.pack(side="right");b.config(state="normal" if ready else "disabled")

    def import_pickup(self,key):
        src=filedialog.askopenfilename(title="Gravação real — WAV PCM",filetypes=[("Áudio WAV","*.wav")])
        if not src:return
        import wave
        try:
            with wave.open(src,'rb') as w:
                if w.getcomptype()!='NONE' or w.getsampwidth() not in (1,2,3) or w.getnchannels() not in (1,2):
                    raise ValueError("Use WAV PCM mono ou estéreo de 8, 16 ou 24 bits.")
        except Exception as e:return messagebox.showerror(APP,"Arquivo WAV não suportado.\n"+str(e))
        if not messagebox.askyesno(APP,"Você confirma que é uma gravação REAL deste motor e escapamento, feita por você ou com autorização/licença para edição e uso?\n\nO app não verifica a origem automaticamente."):return
        variant=self.pick_variant.get()
        dest=os.path.join(CFG_DIR,"pickup_audio",key,variant+".wav");os.makedirs(os.path.dirname(dest),exist_ok=True)
        if os.path.abspath(src)!=os.path.abspath(dest):shutil.copy2(src,dest)
        self.cfg.setdefault("pickup_audio",{}).setdefault(key,{})[variant]=dest
        self.save_cfg();self.fill_pickups()

    def listen_pickup(self,path):
        if os.name!='nt':return messagebox.showinfo(APP,"A reprodução WAV desta versão usa o áudio do Windows.")
        try:
            import winsound
            winsound.PlaySound(path,winsound.SND_FILENAME|winsound.SND_ASYNC)
        except Exception as e:messagebox.showerror(APP,"Não foi possível tocar o WAV.\n"+str(e))

    # ================================================= aba 1: instalar
    def _tab_install(self):
        f=section(self.t_inst,"Pasta do jogo e plugin",scroll=True)
        self.inst_status=tk.Label(f,text="",bg=CARD,fg=FG,font=(FONT,13,"bold"));self.inst_status.pack(anchor="w",pady=(8,8))
        self.plug_status=tk.Label(f,text="",bg=CARD,fg=MUT,font=(FONT,10));self.plug_status.pack(anchor="w")
        self.inst_path=tk.Label(f,text="",bg=ROW2,fg=MUT,font=(FONT,10),wraplength=790,justify="left",anchor="w",padx=16,pady=16)
        self.inst_path.pack(fill="x",pady=14)
        row=tk.Frame(f,bg=CARD);row.pack(fill="x")
        btn(row,"Escolher pasta do jogo",self.pick_game_dir).pack(side="left")
        btn(row,"Abrir pasta do plugin",self.open_plugin_dir,bg=SOFT,hover=BORDER).pack(side="left",padx=10)
        tk.Frame(f,bg=BORDER,height=1).pack(fill="x",pady=18)
        tk.Label(f,text="Gerenciar instalação",bg=CARD,fg=FG,font=(FONT,12,"bold")).pack(anchor="w",pady=(0,12))
        row=tk.Frame(f,bg=CARD);row.pack(fill="x")
        btn(row,"Instalar plugin",self.install_plugin).pack(side="left")
        btn(row,"Atualizar",lambda:self.install_plugin(update=True),bg=SOFT,hover=BORDER).pack(side="left",padx=8)
        btn(row,"Importar ZIP offline",self.install_from_file,bg=SOFT,hover=BORDER).pack(side="left")
        btn(row,"Desinstalar",self.uninstall_plugin,bg=ROW2,hover=BORDER).pack(side="right")
        self.upd_lbl=tk.Label(f,text="Feche o jogo antes de instalar ou atualizar o plugin.",bg=CARD,fg=MUT,font=(FONT,10))
        self.upd_lbl.pack(anchor="w",pady=12)
        tk.Label(f,text="Onde encontrar a pasta?\nNa Steam: Gerenciar → Procurar arquivos locais.\nSelecione a pasta principal do ATS ou ETS2, não a pasta bin.",bg=WARN_BG,fg=WARN_FG,font=(FONT,10),padx=18,pady=16,justify="left").pack(fill="x",pady=(8,0))

    def refresh_install(self):
        if self.game_ok():
            self.inst_status.config(text="☑ Jogo encontrado!", fg=OK)
            self.inst_path.config(text="Caminho: " + self.plugins_dir)
        else:
            self.inst_status.config(text="Escolha a pasta do seu jogo", fg=MUT)
            self.inst_path.config(text="Nenhuma pasta selecionada")
        dll = os.path.isfile(os.path.join(self.plugins_dir, "ts-fmod-plugin.dll")) if self.game_ok() else False
        mb = os.path.isfile(os.path.join(self.plugin_dir, "master.bank")) if self.game_ok() else False
        v = self.cfg["plugin_version"].get(self.game, "")
        if dll and mb: self.plug_status.config(text=f"✔ Plugin instalado {('(versão ' + v + ')') if v else ''}", fg=OK)
        elif dll or mb: self.plug_status.config(text="⚠ Plugin incompleto — clique em Instalar Plugin", fg=WARN_FG)
        else: self.plug_status.config(text="Plugin não instalado", fg=MUT)

    def startup(self):
        if not self.game_ok():
            found = find_game_dirs(self.game)
            if found: self.cfg["game_dir"][self.game] = found[0]; self.save_cfg()
        self.refresh_all()

    def refresh_all(self):
        self.title(self.app_title()); self.title_lbl.config(text=self.app_title()); self.paint_game_btns()
        self.refresh_install(); self.fill_roncos(); self.load_levels(); self.update_console_lbl()

    def set_game(self,g):
        self.stop_preview();self._pending=None;self.cfg["game"]=g;self.save_cfg();self.startup()

    def pick_game_dir(self):
        d = filedialog.askdirectory(title=f"Pasta principal do {GAMES[self.game]['folder']}")
        if not d: return
        d = os.path.normpath(d); exe = GAMES[self.game]["exe"]
        while not os.path.isfile(os.path.join(d, "bin", "win_x64", exe)):
            nd = os.path.dirname(d)
            if nd == d: return messagebox.showerror(APP, f"Não achei bin\\win_x64\\{exe} nessa pasta.")
            d = nd
        self.cfg["game_dir"][self.game] = d; self.save_cfg(); self.refresh_all()

    def open_plugin_dir(self):
        if not self.game_ok(): return messagebox.showinfo(APP, "Jogo não encontrado.")
        os.makedirs(self.plugin_dir, exist_ok=True); os.startfile(self.plugin_dir)

    def _apply_plugin_zip(self, data, tag):
        z = zipfile.ZipFile(io.BytesIO(data)); names = z.namelist()
        dll = next((n for n in names if n.lower().endswith("ts-fmod-plugin.dll")), None)
        mb = next((n for n in names if n.lower() == f"{self.game.lower()}/master.bank"), None)
        if not dll or not mb: raise ValueError("Arquivo do plugin inválido (falta a dll ou o master.bank).")
        os.makedirs(self.plugin_dir, exist_ok=True)
        with open(os.path.join(self.plugins_dir, "ts-fmod-plugin.dll"), "wb") as f: f.write(z.read(dll))
        with open(os.path.join(self.plugin_dir, "master.bank"), "wb") as f: f.write(z.read(mb))
        for n in ("selected.bank.txt", "sound_levels.txt"):
            src = next((x for x in names if x.lower().endswith("ts-fmod-plugin/" + n)), None)
            dst = os.path.join(self.plugin_dir, n)
            if src and not os.path.isfile(dst):
                with open(dst, "wb") as f: f.write(z.read(src) if n != "selected.bank.txt" else b"")
        self.cfg["plugin_version"][self.game] = tag; self.save_cfg()

    def install_plugin(self, update=False):
        if not self.game_ok(): return messagebox.showinfo(APP, "Primeiro mostre onde está o jogo (Procurar Pasta).")
        if find_game_window(): return messagebox.showwarning(APP, "Feche o jogo antes de instalar/atualizar o plugin.")
        self.config(cursor="watch"); self.update()
        try:
            req = urllib.request.Request(RELEASE_API, headers={"User-Agent": "ATS-Sound-Pack-Manager"})
            rel = json.load(urllib.request.urlopen(req, timeout=20))
            tag = rel.get("tag_name", "")
            if update and tag and tag == self.cfg["plugin_version"].get(self.game) and \
               os.path.isfile(os.path.join(self.plugins_dir, "ts-fmod-plugin.dll")):
                self.config(cursor=""); return messagebox.showinfo(APP, f"Você já tem a versão mais nova ({tag}).")
            url = next(a["browser_download_url"] for a in rel["assets"] if a["name"].lower().endswith(".zip"))
            data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ATS-Sound-Pack-Manager"}),
                                          timeout=60).read()
            self._apply_plugin_zip(data, tag)
            messagebox.showinfo(APP, f"Plugin {'atualizado' if update else 'instalado'}! (versão {tag})\n\n"
                                "Ao abrir o jogo, aceite o aviso de 'SDK/plugins' que aparece.")
        except Exception as e:
            messagebox.showerror(APP, f"Não consegui baixar o plugin:\n{e}\n\nBaixe o plugin_files.zip em\n{PLUGIN_URL}\n"
                                 "e use 'Instalar de arquivo .zip'.")
        finally:
            self.config(cursor=""); self.refresh_all()

    def install_from_file(self):
        if not self.game_ok(): return messagebox.showinfo(APP, "Primeiro mostre onde está o jogo (Procurar Pasta).")
        p = filedialog.askopenfilename(title="plugin_files.zip", filetypes=[("ZIP", "*.zip")])
        if not p: return
        try:
            with open(p, "rb") as f: self._apply_plugin_zip(f.read(), "manual")
            messagebox.showinfo(APP, "Plugin instalado!")
        except Exception as e: messagebox.showerror(APP, str(e))
        self.refresh_all()

    def uninstall_plugin(self):
        if not self.game_ok(): return
        if find_game_window(): return messagebox.showwarning(APP, "Feche o jogo antes de desinstalar.")
        dll = os.path.join(self.plugins_dir, "ts-fmod-plugin.dll")
        if not os.path.isfile(dll): return messagebox.showinfo(APP, "O plugin não está instalado.")
        if not messagebox.askyesno(APP, "Desinstalar o plugin? (os sons do jogo voltam ao original)"): return
        os.remove(dll)
        if messagebox.askyesno(APP, "Apagar também a pasta ts-fmod-plugin com todos os roncos?\n(Não = manter os roncos)"):
            self.stop_preview(); shutil.rmtree(self.plugin_dir, ignore_errors=True)
        self.cfg["plugin_version"].pop(self.game, None); self.save_cfg(); self.refresh_all()

    # ================================================= aba 2: mudar ronco
    def _tab_ronco(self):
        f=section(self.t_ronco,"Pacotes instalados")
        warn_box(f,[])
        top=tk.Frame(f,bg=CARD);top.pack(fill="x",pady=(0,12))
        self.q=tk.StringVar();self.q.trace_add("write",lambda *a:self.fill_roncos())
        tk.Label(top,text="Buscar",bg=CARD,fg=MUT).pack(side="left",padx=(0,10))
        tk.Entry(top,textvariable=self.q,bg=ROW2,fg=FG,insertbackground=FG,relief="flat",width=26,
                 highlightthickness=1,highlightbackground=BORDER,highlightcolor=BLUE).pack(side="left",ipady=9)
        btn(top,"Importar pacotes",self.import_menu,bg=SOFT,hover=BORDER).pack(side="right")
        btn(top,"Atualizar",self.fill_roncos,bg=ROW2,hover=BORDER).pack(side="right",padx=8)
        self.sel_lbl=tk.Label(f,text="",bg=CARD,fg=MUT,font=(FONT,9),anchor="w");self.sel_lbl.pack(fill="x",pady=(0,8))
        bottom=tk.Frame(f,bg=CARD);bottom.pack(side="bottom",fill="x",pady=(14,0))
        self.count_lbl=tk.Label(bottom,text="",bg=CARD,fg=MUT,font=(FONT,9));self.count_lbl.pack(side="left")
        btn(bottom,"Salvar seleção",self.save_roncos).pack(side="right")
        self.sc=Scrollable(f);self.sc.pack(fill="both",expand=True)


    def fill_roncos(self):
        if not hasattr(self,"sc"):return
        self.stop_preview()
        for w in self.sc.inner.winfo_children():w.destroy()
        self.rows=[]
        self.banks=scan_banks(self.plugin_dir) if self.game_ok() else []
        if self._pending is None:self._pending=set(read_selected(self.plugin_dir) if self.game_ok() else [])
        q=self.q.get().casefold()
        order=sorted(self.banks,key=lambda b:("motor" not in b.cats,b.name.casefold()))
        shown=[b for b in order if q in b.name.casefold()]
        if not shown:
            empty=tk.Frame(self.sc.inner,bg=ROW2);empty.pack(fill="both",expand=True,pady=14)
            title="Nenhum resultado" if q else ("Sua biblioteca começa aqui" if self.game_ok() else "Vamos conectar seu jogo?")
            desc="Tente buscar por outro nome." if q else ("Importe um pacote .bank compatível para ouvir e selecionar." if self.game_ok() else "Escolha a pasta do ATS ou ETS2 na seção Instalação.")
            tk.Label(empty,text=title,bg=ROW2,fg=FG,font=(FONT,15,"bold")).pack(pady=(12,8))
            tk.Label(empty,text=desc,bg=ROW2,fg=MUT,font=(FONT,10)).pack(pady=(0,18))
            if not self.game_ok():btn(empty,"Configurar jogo",lambda:self.show_page("inst")).pack(pady=(0,18))
        # Conserver les lignes filtrées sans perdre la sélection en mémoire.
        for b in order:
            v=tk.BooleanVar(value=b.name in self._pending)
            if b not in shown:
                self.rows.append({"bank":b,"var":v});continue
            r=tk.Frame(self.sc.inner,bg=CARD);r.pack(fill="x",pady=(0,2))
            tk.Checkbutton(r,variable=v,bg=CARD,activebackground=CARD,selectcolor=CARD,fg=BLUE,bd=0,
                 highlightthickness=1,highlightbackground=CARD,highlightcolor=BLUE,
                 command=lambda b=b,v=v:self.on_check(b,v)).pack(side="left",padx=(10,8),pady=16)
            name=tk.Frame(r,bg=CARD,width=240);name.pack(side="left",fill="y");name.pack_propagate(False)
            tk.Label(name,text=b.name,bg=CARD,fg=FG,font=(FONT,10,"bold"),anchor="w",wraplength=230).pack(fill="x",pady=(12,0))
            is_motor="motor" in b.cats
            tk.Label(name,text=("Motor" if is_motor else "Cabine / outros")+f"  ·  {b.size/1048576:.1f} MB",bg=CARD,fg=MUT,font=(FONT,9),anchor="w").pack(fill="x",pady=(2,10))
            row={"bank":b,"var":v,"frame":r}
            if not os.path.isfile(b.guids_path):tk.Label(r,text="Falta .bank.guids",bg=CARD,fg=RED,font=(FONT,9)).pack(side="right",padx=12)
            elif is_motor:
                pb=btn(r,"▶",lambda row=row:self.toggle_play(row),bg=SOFT,hover=BORDER,w=2)
                pb.pack(side="left",padx=10,pady=12)
                cv=tk.Canvas(r,width=128,height=6,bg=BORDER,highlightthickness=0);cv.pack(side="left",padx=8)
                cv.bind("<Button-1>",lambda e,row=row:self.seek(row,e.x/max(1,row['bar'].winfo_width())))
                tl=tk.Label(r,text="0:00",bg=CARD,fg=MUT,font=(FONT,9));tl.pack(side="left",padx=8)
                btn(r,"Início",lambda row=row:self.restart(row),bg=ROW2,hover=BORDER).pack(side="right",padx=10)
                row.update(play=pb,bar=cv,time=tl)
            else:tk.Label(r,text="Sem prévia de motor",bg=CARD,fg=MUT,font=(FONT,9)).pack(side="right",padx=18)
            self.rows.append(row)
        self.count_lbl.config(text=f"{len(shown)} de {len(self.banks)} pacotes")
        self.update_sel_lbl()

    def checked(self): return [r for r in self.rows if r["var"].get()]

    def on_check(self,b,v):
        ch=self.checked()
        if len(ch)>2 or sum("motor" in r["bank"].cats for r in ch)>1:
            v.set(False);messagebox.showwarning(APP,"Escolha até um pacote de motor e um de cabine.")
        self._pending={r["bank"].name for r in self.checked()}
        self.update_sel_lbl()

    def update_sel_lbl(self):
        ch=[r["bank"].name for r in self.checked()]
        text="Selecionado: "+", ".join(ch) if ch else "Nenhum pacote selecionado · som original"
        self.sel_lbl.config(text=text[:115])

    def save_roncos(self):
        if not self.game_ok(): return messagebox.showinfo(APP, "Jogo não encontrado.")
        ch = self.checked()
        ch.sort(key=lambda r: "motor" not in r["bank"].cats)       # motor primeiro
        write_selected(self.plugin_dir, [r["bank"].name for r in ch])
        self.update_sel_lbl()
        if find_game_window():
            if messagebox.askyesno(APP, "Alterações salvas!\n\nO jogo está aberto. Aplicar agora (sdk reload)?"):
                self.apply_in_game()
        else:
            messagebox.showinfo(APP, "Alterações salvas! O ronco vai carregar quando você abrir o jogo.")

    def import_menu(self):
        if not self.game_ok(): return messagebox.showinfo(APP, "Jogo não encontrado.")
        m = tk.Menu(self, tearoff=0, bg=CARD, fg=FG, activebackground=SOFT, activeforeground=FG)
        m.add_command(label="Arquivo .zip / .scs", command=lambda: [self.do_import(p) for p in filedialog.askopenfilenames(
            filetypes=[("Mods", "*.zip *.scs"), ("Todos", "*.*")])])
        m.add_command(label="Pasta com .bank", command=lambda: (lambda d: d and self.do_import(d))(filedialog.askdirectory()))
        m.add_command(label="Arquivo .bank", command=lambda: [self.do_import(p) for p in filedialog.askopenfilenames(
            filetypes=[("FMOD bank", "*.bank")])])
        m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())

    def do_import(self, src):
        try: res = extract_banks_from(src, self.plugin_dir)
        except Exception as e: return messagebox.showerror(APP, str(e))
        self.fill_roncos()
        if not res: return messagebox.showwarning(APP, "Nenhum arquivo .bank encontrado.")
        messagebox.showinfo(APP, "Importado:\n\n" + "\n".join(f"• {n}" + ("" if g else "  ⚠ sem .bank.guids") for n, g in res))

    # ---------------- previa
    def fmod_dirs(self):
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
        ds = [self.cfg.get("fmod_dir", ""), os.path.join(self.game_dir, "bin", "win_x64"), base,
              os.path.join(base, "fmod"), self.plugins_dir]
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            fs = os.path.join(root, "FMOD SoundSystem")
            if os.path.isdir(fs):
                ds += [os.path.join(fs, x) for x in sorted(os.listdir(fs), reverse=True) if x.startswith("FMOD Studio 2")]
                ds.append(os.path.join(fs, "FMOD Studio API Windows", "api", "studio", "lib", "x64"))
        return [d for d in ds if d and os.path.isdir(d)]

    def toggle_play(self, row):
        if self.playing is row:
            if self.preview.insts: self.pause(); return
        self.start_play(row, 0.0 if self.playing is not row else self.play_pos)

    def start_play(self, row, pos):
        self.stop_preview(keep_pos=False)
        if not (self.preview.load_dll(self.fmod_dirs()) and self.preview.start_system()):
            return messagebox.showwarning(APP, "Prévia indisponível: " + self.preview.err)
        b = row["bank"]
        ev = next((g for g, p in b.entries if p == "event:/engine/engine"), None) or \
             next((g for g, p in b.entries if p.startswith("event:/engine/")), None)
        if not ev: return
        try:
            files = [os.path.join(self.plugin_dir, "master.bank"), b.path]
            self.preview.load([x for x in files if os.path.isfile(x)])
            for g, p in b.entries:     # motor + escapamento + turbo juntos
                if p in ("event:/engine/engine", "event:/engine/exhaust", "event:/engine/turbo"): self.preview.play(g)
            if not self.preview.insts: self.preview.play(ev)
        except Exception as e:
            return messagebox.showerror(APP, f"Erro na prévia:\n{e}")
        self.playing = row; self.play_pos = pos; self.play_t0 = time.time() - pos
        row["play"].config(text="⏸")

    def pause(self):
        self.preview.stop(); self.play_pos = time.time() - self.play_t0
        if self.playing: self.playing["play"].config(text="▶")

    def restart(self, row): self.start_play(row, 0.0)
    def seek(self, row, frac): self.start_play(row, max(0, min(1, frac)) * PREVIEW_LEN)

    def stop_preview(self, keep_pos=False):
        if os.name == "nt":
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except Exception: pass
        try:
            if self.preview.sys: self.preview.stop()
        except Exception: pass
        if self.playing:
            try:
                self.playing["play"].config(text="▶"); self.draw_bar(self.playing, 0)
            except tk.TclError: pass
        self.playing = None

    def draw_bar(self,row,t):
        cv=row["bar"];cv.delete("all")
        cv.create_rectangle(0,0,max(1,cv.winfo_width())*t/PREVIEW_LEN,6,fill=BLUE,width=0)
        row["time"].config(text=f"{int(t)//60}:{int(t)%60:02d}")

    def _tick(self):
        try:
            if self.playing and self.preview.insts:
                t = time.time() - self.play_t0
                if t >= PREVIEW_LEN: self.stop_preview()
                else:
                    rpm, load = rpm_curve(t)
                    self.preview.set_param("rpm", rpm); self.preview.set_param("load", load)
                    self.preview.set_param("brake", 1.0 if 7.5 <= t < 11 else 0.0)
                    self.draw_bar(self.playing, t)
            self.preview.update()
        except Exception: pass
        self._tick_job = self.after(50 if self.playing else 250, self._tick)

    # ================================================= aba 3: volume
    def _tab_volume(self):
        f=section(self.t_vol,"Mixagem do plugin")
        tk.Label(f,text="0,00 = silêncio    ·    1,00 = nível de referência    ·    2,00 = amplificação",bg=WARN_BG,fg=WARN_FG,padx=16,pady=14,font=(FONT,10)).pack(fill="x",pady=(0,14))
        self.lvl,self.lvl_lbl={},{}
        labels={"master":"Geral","engine":"Motor","exhaust":"Escapamento","turbo":"Turbo","interior":"Cabine","exterior_when_windows_closed":"Janelas fechadas","navigation":"Navegação"}
        for k,t in VOL_KEYS:
            r=tk.Frame(f,bg=CARD);r.pack(fill="x",pady=3)
            tk.Label(r,text=labels[k],bg=CARD,fg=FG,font=(FONT,10),width=20,anchor="w").pack(side="left")
            v=tk.DoubleVar(value=.5);self.lvl[k]=v
            l=tk.Label(r,text="0.50",bg=SOFT,fg=BLUE,font=(FONT,10,"bold"),width=6,pady=4);l.pack(side="right",padx=(18,0));self.lvl_lbl[k]=l
            MaterialScale(r,variable=v,command=lambda x,k=k:self.lvl_lbl[k].config(text=f"{float(x):.2f}")).pack(side="left",fill="x",expand=True)
        b=tk.Frame(f,bg=CARD);b.pack(fill="x",pady=(12,0))
        btn(b,"Salvar volumes",self.save_levels).pack(side="right")
        btn(b,"Restaurar padrão",self.default_levels,bg=SOFT,hover=BORDER).pack(side="left")


    def levels_path(self): return os.path.join(self.plugin_dir, "sound_levels.txt")
    def load_levels(self):
        try:
            with open(self.levels_path(), encoding="utf-8") as f: d = json.load(f)
        except Exception: d = {}
        for k, _ in VOL_KEYS:
            v = float(d.get(k, 0.75 if k in ("interior", "navigation", "exterior_when_windows_closed") else 0.5))
            self.lvl[k].set(v); self.lvl_lbl[k].config(text=f"{v:.2f}")
    def default_levels(self):
        for k, _ in VOL_KEYS:
            v = 0.75 if k in ("interior", "navigation", "exterior_when_windows_closed") else 0.5
            self.lvl[k].set(v); self.lvl_lbl[k].config(text=f"{v:.2f}")
    def save_levels(self):
        if not self.game_ok(): return messagebox.showinfo(APP, "Jogo não encontrado.")
        try:
            with open(self.levels_path(), encoding="utf-8") as f: d = json.load(f)
        except Exception: d = {}
        for k, _ in VOL_KEYS: d[k] = round(self.lvl[k].get(), 2)
        d.setdefault("config_version", 2)
        os.makedirs(self.plugin_dir, exist_ok=True)
        with open(self.levels_path(), "w", encoding="utf-8") as f: json.dump(d, f, indent=4)
        if find_game_window():
            if messagebox.askyesno(APP, "Volume salvo! Aplicar agora no jogo (sdk reload)?"): self.apply_in_game()
        else: messagebox.showinfo(APP, "Volume salvo!")

    # ================================================= aba 4: console
    def _tab_console(self):
        f=section(self.t_con,"Console do jogo",scroll=True)
        tk.Label(f,text="Uma configuração. Mudanças sem reiniciar.",bg=CARD,fg=FG,font=(FONT,15,"bold")).pack(anchor="w",pady=(12,16))
        tk.Label(f,text="1   Feche completamente o jogo.\n\n2   Ative o console no botão abaixo.\n\n3   Abra o jogo e entre no seu veículo.\n\n4   Depois de salvar um som, use Aplicar no jogo.",bg=CARD,fg=MUT,font=(FONT,11),justify="left").pack(anchor="w")
        self.con_lbl=tk.Label(f,text="",bg=ROW2,fg=MUT,font=(FONT,10),padx=16,pady=14)
        self.con_lbl.pack(fill="x",pady=16)
        r=tk.Frame(f,bg=CARD);r.pack(fill="x")
        btn(r,"Ativar console",lambda:self.set_console(True)).pack(side="left")
        btn(r,"Desativar",lambda:self.set_console(False),bg=SOFT,hover=BORDER).pack(side="left",padx=10)
        tk.Label(f,text='Comando manual: sdk reload\nA tecla de abertura do console depende do teclado.\nUma cópia de segurança do config.cfg é criada antes da alteração.',bg=WARN_BG,fg=WARN_FG,font=(FONT,10),justify="left",padx=16,pady=12).pack(fill="x",pady=16)

    def config_cfg(self): return os.path.join(documents_dir(), GAMES[self.game]["folder"], "config.cfg")

    def update_console_lbl(self):
        p = self.config_cfg()
        try:
            with open(p, encoding="utf-8", errors="replace") as f: t = f.read()
            on = re.search(r'uset\s+g_console\s+"1"', t) and re.search(r'uset\s+g_developer\s+"1"', t)
            self.con_lbl.config(text="✔ Console e Câmera 0 ATIVOS" if on else "✖ Console desativado",
                                fg=OK if on else RED)
        except OSError:
            self.con_lbl.config(text="config.cfg não encontrado — abra e feche o jogo uma vez", fg=RED)

    def set_console(self, on):
        if find_game_window(): return messagebox.showwarning(APP, "Feche o jogo completamente antes.")
        p = self.config_cfg()
        try:
            with open(p, encoding="utf-8", errors="replace") as f: t = f.read()
        except OSError: return messagebox.showerror(APP, f"Não achei:\n{p}\n\nAbra e feche o jogo uma vez.")
        shutil.copy2(p, p + ".bak"); v = "1" if on else "0"
        for key in ("g_console", "g_developer"):
            if re.search(rf'uset\s+{key}\s+"\d+"', t): t = re.sub(rf'uset\s+{key}\s+"\d+"', f'uset {key} "{v}"', t)
            else: t += f'\nuset {key} "{v}"'
        with open(p, "w", encoding="utf-8", newline="") as f: f.write(t)
        self.update_console_lbl()
        messagebox.showinfo(APP, "Console e Câmera 0 " + ("ATIVADOS!" if on else "desativados."))

    def apply_in_game(self):
        self.clipboard_clear(); self.clipboard_append("sdk reload")
        hwnd = find_game_window()
        if not hwnd: return messagebox.showinfo(APP, "O jogo não está aberto. O som vai carregar quando você abrir o jogo.")
        if not send_console_command(hwnd, "sdk reload"):
            messagebox.showwarning(APP, "Não consegui controlar o jogo.\nNo jogo, abra o console (tecla ') e cole com "
                                   "Ctrl+V: sdk reload\n\n(Se o jogo roda como administrador, abra este app como administrador.)")

if __name__ == "__main__":
    try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass
    App().mainloop()
