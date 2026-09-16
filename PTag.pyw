# PTag by GigelHarbuz
import os
import sys
import re
import time
import json
import subprocess
import glob
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime
import threading
# Setare limba
lang = {}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Languages', 'current.json'), encoding='utf-8') as f:
    lang = json.load(f)
# Interfata PM3 pentru clientul proxmarkbuilds pe Windows
class Proxmark3Interface:
    def __init__(self, bat_file):
        self.bat_file = bat_file
        self.process = None
        self.running = False
        self.log_file = None
        self.last_position = 0

    def find_log_file(self, client_dir):
        log_dir = os.path.join(client_dir, ".proxmark3", "logs")
        if not os.path.exists(log_dir):
            return None
        pattern = os.path.join(log_dir, "*.txt")
        log_files = glob.glob(pattern)
        if log_files:
            return max(log_files, key=os.path.getmtime)
        time.sleep(10)
        log_files = glob.glob(pattern)
        if log_files:
            return max(log_files, key=os.path.getmtime)
        return None

    def read_new_output(self):
        if not self.log_file or not os.path.exists(self.log_file):
            return ""
        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(self.last_position)
                new_content = f.read()
                self.last_position = f.tell()
                return new_content
        except Exception:
            return ""

    def _clear_log_dir(self, client_dir):
        """Sterge toate logurile inainte de pornire"""
        log_dir = os.path.join(client_dir, ".proxmark3", "logs")
        if not os.path.exists(log_dir):
            return
        for f in glob.glob(os.path.join(log_dir, "*.txt")):
            try:
                os.remove(f)
            except Exception:
                pass

    def start(self):
        """Porneste clientul PM3 si verifica conectctarea"""
        try:
            full_path = os.path.abspath(self.bat_file)
            working_dir = os.path.dirname(full_path)
            client_dir = os.path.join(working_dir, "client")
            self._clear_log_dir(client_dir)
            self.process = subprocess.Popen(
                ['cmd', '/c', full_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=working_dir,
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.running = True
            self.log_file = self.find_log_file(client_dir)
            if self.log_file:
                try:
                    with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(0, 0)
                        self.last_position = 0
                except Exception:
                    self.last_position = 0

            banner = ""
            for _ in range(15):
                time.sleep(1)
                chunk = self.read_new_output()
                if chunk:
                    banner += chunk
                if "proxmark3>" in banner.lower() or "[usb] pm3 -->" in banner.lower():
                    break

            def is_fail(text):
                t = text.lower()
                return ("communicating with proxmark3 device failed" in t or
                        "cannot communicate with the proxmark3" in t)

            sections = re.split(r'(?=\[\+\] Using UART port)', banner, flags=re.IGNORECASE)
            com_port = None
            for section in sections:
                m = re.search(r'Using UART port\s+(COM\d+)', section, re.IGNORECASE)
                if m and not is_fail(section):
                    com_port = m.group(1).upper()

            if com_port:
                return (True, com_port)

            if is_fail(banner):
                return (False, "comm_failed")

            return (True, None)
        except Exception:
            return (False, None)

    def send_command(self, command, on_freeze=None):
        """Trimite comanda la proxmark si verifica daca clientul a dat crash"""
        if not self.process or not self.running:
            return ""
        try:
            cmd_bytes = (command + "\n").encode('utf-8')
            self.process.stdin.write(cmd_bytes)
            self.process.stdin.flush()
            for _ in range(15):
                time.sleep(2)
                output = self.read_new_output()
                if output:
                    return output
            if on_freeze:
                threading.Thread(target=on_freeze, daemon=True).start()
            return ""
        except Exception:
            return ""

    def send_command_noread(self, command):
        """Trimite comanda la proxmark fara citire output, folosita pentru crak la parola"""
        if not self.process or not self.running:
            return False
        try:
            self.process.stdin.write((command + "\n").encode('utf-8'))
            self.process.stdin.flush()
            return True
        except Exception:
            return False

    def stop(self):
        self.running = False
        if self.process:
            try:
                try:
                    self.process.stdin.write(b"quit\n")
                    self.process.stdin.flush()
                    time.sleep(2)
                except Exception:
                    pass
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        if self.log_file and os.path.exists(self.log_file):
            try:
                time.sleep(1)
                os.remove(self.log_file)
            except Exception:
                pass

    def force_stop(self):
        """Killuieste clientul cand da crash"""
        self.running = False
        if self.process:
            try:
                self.process.kill()
                self.process.wait(timeout=5)
            except Exception:
                pass
            self.process = None
        if self.log_file and os.path.exists(self.log_file):
            for _ in range(5):
                try:
                    os.remove(self.log_file)
                    break
                except Exception:
                    time.sleep(1)
        self.log_file = None
        self.last_position = 0



SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SAVED_DIR  = os.path.join(SCRIPT_DIR, "Saved")


def ensure_saved_dir():
    os.makedirs(SAVED_DIR, exist_ok=True)


def parse_lf_search(output: str):
    """
    Verifica ID si cip la citire tag

    Format id:   "EM 410x ID FFFFFFFFFF"
    Format cip:
        "Couldn't identify a chipset"  → "unknown/EM4100"
        "Chipset detection: T55xx"     → "T5577"
        "Chipset detection: EM4x05 / EM4x69" → "EM4305"

    """
    tag_id    = None
    chip_type = None

    m = re.search(r'EM\s+410x\s+ID\s+([0-9A-Fa-f]{10})\b', output, re.IGNORECASE)
    if m:
        tag_id = m.group(1).upper()

    if re.search(r"Couldn'?t\s+identify\s+a\s+chipset", output, re.IGNORECASE):
        chip_type = "unknown/EM4100"
    elif re.search(r'Chipset\s+detection\s*:\s*T55xx', output, re.IGNORECASE):
        chip_type = "T5577"
    elif re.search(r'Chipset\s+detection\s*:\s*EM4x05', output, re.IGNORECASE):
        chip_type = "EM4305"

    return tag_id, chip_type


def parse_em410x_reader(output: str):
    """Verifica DOAR ID la citire tag"""
    m = re.search(r'EM\s+410x\s+ID\s+([0-9A-Fa-f]{10})\b', output, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None



def ask_filename(parent, title=lang['filename.title'], prompt=lang['filename.prompt']):
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.grab_set()

    pad = dict(padx=12, pady=6)
    tk.Label(dialog, text=prompt).pack(**pad)

    var = tk.StringVar()
    entry = tk.Entry(dialog, textvariable=var, width=32)
    entry.pack(**pad)
    entry.focus_set()

    result = [None]

    def ok():
        result[0] = var.get().strip()
        dialog.destroy()

    def cancel():
        dialog.destroy()

    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=(0, 10))
    tk.Button(btn_frame, text="OK",     width=10, command=ok).pack(side=tk.LEFT,  padx=5)
    tk.Button(btn_frame, text="Cancel", width=10, command=cancel).pack(side=tk.LEFT, padx=5)

    entry.bind("<Return>", lambda _: ok())
    entry.bind("<Escape>", lambda _: cancel())

    parent.wait_window(dialog)
    return result[0]



def ask_set_id(parent, current_id=""):
    dialog = tk.Toplevel(parent)
    dialog.title(lang['setid.title'])
    dialog.resizable(False, False)
    dialog.grab_set()

    tk.Label(dialog, text=lang['setid.prompt']).pack(padx=12, pady=(12, 4))

    var = tk.StringVar(value=current_id)
    entry = tk.Entry(dialog, textvariable=var, width=24, font=("Courier", 13))
    entry.pack(padx=12, pady=4)
    entry.focus_set()
    entry.select_range(0, tk.END)

    result = [None]

    def ok():
        val = var.get().strip().upper()
        if not re.fullmatch(r'[0-9A-F]{10}', val):
            messagebox.showerror(lang['err.title'],
                                 lang['setid.err.prompt'],
                                 parent=dialog)
            return
        result[0] = val
        dialog.destroy()

    def cancel():
        dialog.destroy()

    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=(4, 12))
    tk.Button(btn_frame, text="OK",     width=10, command=ok).pack(side=tk.LEFT,  padx=5)
    tk.Button(btn_frame, text="Cancel", width=10, command=cancel).pack(side=tk.LEFT, padx=5)

    entry.bind("<Return>", lambda _: ok())
    entry.bind("<Escape>", lambda _: cancel())

    parent.wait_window(dialog)
    return result[0]



class TagTab(tk.Frame):
    """
    Tab pentru cartelele 125k - Electra si EM4100

    Parametri
    ----------
    tag_type_key   : str   – "EM" sau "Electra"  (pentru a diferentia intre dump-uri la electra si chinezarii)
    clone_extra    : str   – argumente pt clonare, necesar la electra, panourile cu soft mai nou de 2011 nu accepta taguri standard EM4100 ("" sau "--electra")
    """

    def __init__(self, master, app, tag_type_key: str, clone_extra: str = ""):
        super().__init__(master)
        self.app           = app
        self.tag_type_key  = tag_type_key
        self.clone_extra   = clone_extra

        self._tag_id   = tk.StringVar(value="—")
        self._chip_type = tk.StringVar(value="—")

        self._build_ui()


    def _build_ui(self):
        info = tk.LabelFrame(self, text=lang['label.taginfo'], padx=10, pady=8)
        info.pack(fill=tk.X, padx=16, pady=(16, 8))

        tk.Label(info, text=lang['label.tagid'],    anchor="w", width=12).grid(row=0, column=0, sticky="w", pady=3)
        tk.Label(info, textvariable=self._tag_id,
                 font=("Courier", 13, "bold"), anchor="w", fg="#1a6b2e").grid(
                     row=0, column=1, sticky="w", padx=6)

        tk.Label(info, text=lang['label.chip'], anchor="w", width=12).grid(row=1, column=0, sticky="w", pady=3)
        tk.Label(info, textvariable=self._chip_type,
                 font=("Courier", 11), anchor="w", fg="#444").grid(
                     row=1, column=1, sticky="w", padx=6)

        btn_frame = tk.Frame(self)
        btn_frame.pack(padx=16, pady=8, fill=tk.X)

        btn_cfg = dict(width=14, height=2, relief=tk.GROOVE, cursor="hand2")

        self._btn_read  = tk.Button(btn_frame, text=lang['btn.read'],  **btn_cfg, command=self._read_tag)
        self._btn_setid = tk.Button(btn_frame, text=lang['btn.setid'],    **btn_cfg, command=self._set_id)
        self._btn_load  = tk.Button(btn_frame, text=lang['btn.openfile'], **btn_cfg, command=self._load_file)
        self._btn_save  = tk.Button(btn_frame, text=lang['btn.savefile'], **btn_cfg, command=self._save_file)
        self._btn_write = tk.Button(btn_frame, text=lang['btn.write'], **btn_cfg,
                                    command=self._write_tag, bg="#c8e6c9")

        for i, btn in enumerate([self._btn_read, self._btn_setid,
                                  self._btn_load, self._btn_save, self._btn_write]):
            btn.grid(row=0, column=i, padx=5, pady=4)

        log_frame = tk.LabelFrame(self, text=lang['label.output'], padx=6, pady=6)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 16))

        self._log = tk.Text(log_frame, height=10, state=tk.DISABLED,
                            font=("Courier", 10), bg="#1e1e1e", fg="#d4d4d4",
                            wrap=tk.WORD, relief=tk.FLAT)
        scroll = tk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scroll.set)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)


    def _log_write(self, text: str):
        self._log.configure(state=tk.NORMAL)
        self._log.insert(tk.END, text + "\n")
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    def _set_buttons_state(self, state):
        for btn in [self._btn_read, self._btn_setid,
                    self._btn_load, self._btn_save, self._btn_write]:
            btn.configure(state=state)

    def _run_in_thread(self, func):
        """Ruleaza in thread"""
        self._set_buttons_state(tk.DISABLED)
        def wrapper():
            try:
                func()
            finally:
                self.after(0, lambda: self._set_buttons_state(tk.NORMAL))
        threading.Thread(target=wrapper, daemon=True).start()

    def _send(self, command):
        """wrapper pentru send_command"""
        def on_freeze():
            self._log_write(f"[!] {lang['cmd.freeze']}")
            self.app.reconnect()
        return self.app.pm3.send_command(command, on_freeze=on_freeze)


    def _read_tag(self):
        if not self.app.pm3_ready():
            return

        def task():
            self._log_write(f"[*] {lang['cmd.running']} 'lf search' ...")
            output = self._send("lf search")
            self._log_write(output or "(no output)")

            tag_id, chip_type = parse_lf_search(output or "")

            if tag_id:
                self.after(0, lambda: self._tag_id.set(tag_id))
                self.after(0, lambda: self._chip_type.set(chip_type or "Unknown"))
                self._log_write(f"[+] {lang['cmd.tagid']}:    {tag_id}")
                self._log_write(f"[+] {lang['cmd.chip']}: {chip_type or 'Unknown'}")
            else:
                self._log_write(f"[-] {lang['cmd.err.notag']}")
                self.after(0, lambda: self._tag_id.set("—"))
                self.after(0, lambda: self._chip_type.set("—"))

        self._run_in_thread(task)

    def _set_id(self):
        current = self._tag_id.get()
        if current == "—":
            current = ""
        new_id = ask_set_id(self, current)
        if new_id is not None:
            self._tag_id.set(new_id)
            self._log_write(f"[*] {lang['cmd.manualid']}: {new_id}")

    def _load_file(self):
        ensure_saved_dir()
        path = filedialog.askopenfilename(
            title=lang['loadfile.title'],
            initialdir=SAVED_DIR,
            filetypes=[("PTag File", "*.ptg"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror(lang['err.title'], f"{lang['loadfile.err.prompt']}:\n{e}")
            return

        file_type = data.get("tag_type", "")
        if file_type.upper() != self.tag_type_key.upper():
            messagebox.showerror(
                lang['err.title'],
                f"{lang['loadfile.err.pr1']} '{file_type}'.\n"
                f"{lang['loadfile.err.pr2']} '{self.tag_type_key}'."
            )
            return

        loaded_id = data.get("tag_id", "")
        self._tag_id.set(loaded_id.upper())
        self._chip_type.set(data.get("chip_type", "—"))
        self._log_write(f"[+] Tag ID '{loaded_id}' {lang['cmd.loadfile']}: {os.path.basename(path)}")

    def _save_file(self):
        tag_id = self._tag_id.get()
        if tag_id == "—" or not tag_id:
            messagebox.showwarning(lang['err.title'], lang['err.notagid'])
            return

        ensure_saved_dir()

        folder = filedialog.askdirectory(
            title=lang['save.title'],
            initialdir=SAVED_DIR
        )
        if not folder:
            return

        filename = ask_filename(self, title=lang['filename.title'],
                                prompt=lang['filename.prompt'])
        if not filename:
            return

        save_path = os.path.join(folder, filename + ".ptg")

        payload = {
            "tag_id":   tag_id,
            "tag_type": self.tag_type_key,
            "chip_type": self._chip_type.get() if self._chip_type.get() != "—" else ""
        }

        try:
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2)
            self._log_write(f"[+] {lang['cmd.save']}: {save_path}")
            messagebox.showinfo(lang['save.ok.title'], f"{lang['cmd.save']}:\n{save_path}")
        except Exception as e:
            messagebox.showerror(lang['err.title'], f"{lang['save.err.prompt']}:\n{e}")

    def _write_tag(self):
        tag_id = self._tag_id.get()
        if tag_id == "—" or not tag_id:
            messagebox.showwarning(lang['err.title'], lang['err.notagid'])
            return

        if not self.app.pm3_ready():
            return

        confirm = messagebox.askokcancel(
            lang['write.title'],
            f"{lang['write.pr1']}\n"
            f"{lang['write.pr2']}"
        )
        if not confirm:
            return

        def task():
            extra = (" " + self.clone_extra).rstrip() if self.clone_extra else ""
            clone_cmd = f"lf em 410x clone --id {tag_id}{extra}"
            self._log_write(f"[*] {lang['cmd.running']}: {clone_cmd}")
            clone_out = self._send(clone_cmd)
            self._log_write(clone_out or "(no output)")

            self._log_write(f"[*] {lang['cmd.verification']} - {lang['cmd.running']} 'lf em 410x reader' ...")
            verify_out = self._send("lf em 410x reader")
            self._log_write(verify_out or "(no output)")

            read_id = parse_em410x_reader(verify_out or "")
            if read_id and read_id.upper() == tag_id.upper():
                self._log_write(f"[+] {lang['cmd.verification']} OK - ID: {read_id}")
                self.after(0, lambda: messagebox.showinfo(lang['write.title'], lang['write.ok.prompt']))
            else:
                self._log_write(
                    f"[-] {lang['cmd.verification']} {lang['cmd.failed']} - T5577 Tag ID: {read_id!r}, Original ID: {tag_id}"
                )
                self.after(0, lambda: messagebox.showerror(
                    lang['err.title'],
                    lang['write.err.prompt']
                ))

        self._run_in_thread(task)




def ask_password(parent, title=lang['pass.title'], prompt=lang['pass.prompt']):
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.grab_set()
    tk.Label(dialog, text=prompt).pack(padx=12, pady=(12, 4))
    var = tk.StringVar()
    entry = tk.Entry(dialog, textvariable=var, width=20, font=("Courier", 13))
    entry.pack(padx=12, pady=4)
    entry.focus_set()
    result = [None]
    def ok():
        val = var.get().strip().upper()
        if not re.fullmatch(r'[0-9A-F]{8}', val):
            messagebox.showerror(lang['err.title'],
                                 lang['pass.err.prompt'],
                                 parent=dialog)
            return
        result[0] = val
        dialog.destroy()
    def cancel():
        dialog.destroy()
    btn_frame = tk.Frame(dialog)
    btn_frame.pack(pady=(4, 12))
    tk.Button(btn_frame, text="OK",     width=10, command=ok).pack(side=tk.LEFT,  padx=5)
    tk.Button(btn_frame, text="Cancel", width=10, command=cancel).pack(side=tk.LEFT, padx=5)
    entry.bind("<Return>", lambda _: ok())
    entry.bind("<Escape>", lambda _: cancel())
    parent.wait_window(dialog)
    return result[0]


class T5577Tab(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self._build_ui()

    def _build_ui(self):
        btn_frame = tk.LabelFrame(self, text=lang['label.t55'], padx=10, pady=10)
        btn_frame.pack(fill=tk.X, padx=16, pady=(16, 8))
        btn_cfg = dict(width=16, height=2, relief=tk.GROOVE, cursor="hand2")
        self._btn_wipe   = tk.Button(btn_frame, text=lang['btn.wipe'],        **btn_cfg, command=self._wipe_tag)
        self._btn_addpwd = tk.Button(btn_frame, text=lang['btn.addpass'],    **btn_cfg, command=self._add_password)
        self._btn_rmpwd  = tk.Button(btn_frame, text=lang['btn.rempass'], **btn_cfg, command=self._remove_password)
        self._btn_crack  = tk.Button(btn_frame, text=lang['btn.crack'],  **btn_cfg, command=self._crack_password, bg="#fff3cd")
        self._btn_fake   = tk.Button(btn_frame, text=lang['btn.fake'],  **btn_cfg, command=self._check_fake)
        for i, btn in enumerate([self._btn_wipe, self._btn_addpwd, self._btn_rmpwd,
                                  self._btn_crack, self._btn_fake]):
            btn.grid(row=0, column=i, padx=5, pady=4)
        log_frame = tk.LabelFrame(self, text=lang['label.output'], padx=6, pady=6)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(4, 16))
        self._log = tk.Text(log_frame, height=10, state=tk.DISABLED,
                            font=("Courier", 10), bg="#1e1e1e", fg="#d4d4d4",
                            wrap=tk.WORD, relief=tk.FLAT)
        scroll = tk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scroll.set)
        self._log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _log_write(self, text):
        self._log.configure(state=tk.NORMAL)
        self._log.insert(tk.END, text + "\n")
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    def _set_buttons_state(self, state):
        for btn in [self._btn_wipe, self._btn_addpwd, self._btn_rmpwd,
                    self._btn_crack, self._btn_fake]:
            btn.configure(state=state)

    def _run_in_thread(self, func):
        self._set_buttons_state(tk.DISABLED)
        def wrapper():
            try:
                func()
            finally:
                self.after(0, lambda: self._set_buttons_state(tk.NORMAL))
        threading.Thread(target=wrapper, daemon=True).start()

    def _send(self, command):
        """send_command wrapper that auto-reconnects if the client freezes."""
        def on_freeze():
            self._log_write(f"[!] {lang['cmd.freeze']}")
            self.app.reconnect()
        return self.app.pm3.send_command(command, on_freeze=on_freeze)

    def _detect(self):
        self._log_write(f"[*] {lang['cmd.running']} 'lf t55 detect' ...")
        out = self._send("lf t55 detect")
        self._log_write(out or "(no output)")
        if re.search(r'Chip\s+type[.\s]+T55x7', out or "", re.IGNORECASE):
            self._log_write(f"[+] {lang['cmd.detected']} T55x7")
            return True
        self.after(0, lambda: messagebox.showerror(
            lang['err.title'],
            lang['det.err.prompt']
        ))
        return False

    def _wipe_tag(self):
        if not self.app.pm3_ready():
            return
        def task():
            if not self._detect():
                return
            self._log_write(f"[*] {lang['cmd.running']} 'lf t55 wipe' ...")
            out = self._send("lf t55 wipe")
            self._log_write(out or "(no output)")
            self.after(0, lambda: messagebox.showinfo("Wipe", lang['wipe.ok.prompt']))
        self._run_in_thread(task)

    def _add_password(self):
        if not self.app.pm3_ready():
            return
        pwd = ask_password(self, title=lang['pass.title'],
                           prompt=lang['pass.prompt'])
        if pwd is None:
            return
        def task():
            if not self._detect():
                return
            cmd = f"lf t5 protect -n {pwd}"
            self._log_write(f"[*] {lang['cmd.running']}: {cmd}")
            out = self._send(cmd)
            self._log_write(out or "(no output)")
            self.after(0, lambda: messagebox.showinfo(
                lang['pass.title'], f"{lang['pass.title']} {pwd} {lang['pass.ok.prompt']}"))
        self._run_in_thread(task)

    def _remove_password(self):
        if not self.app.pm3_ready():
            return
        confirm = messagebox.askokcancel(
            lang['pass.title'], lang['rempass.prompt'])
        if not confirm:
            return
        pwd = ask_password(self, title=lang['pass.title'],
                           prompt=lang['pass.prompt'])
        if pwd is None:
            return
        def task():
            cmd = f"lf t55 wipe -p {pwd}"
            self._log_write(f"[*] {lang['cmd.running']}: {cmd}")
            out = self._send(cmd)
            self._log_write(out or "(no output)")
            self.after(0, lambda: messagebox.showinfo(
                lang['pass.title'], lang['rempass.ok.prompt']))
        self._run_in_thread(task)

    def _crack_password(self):
        if not self.app.pm3_ready():
            return
        confirm = messagebox.askokcancel(
            lang['pass.title'], lang['crack.prompt'])
        if not confirm:
            return
        def task():
            self._log_write(f"[*] {lang['cmd.running']} 'lf t55 chk'")
            if not self.app.pm3.send_command_noread("lf t55 chk"):
                self._log_write(f"[!] {lang['crack.cmd.err']}")
                return
            found_pwd = None
            for _ in range(30):
                time.sleep(2)
                chunk = self.app.pm3.read_new_output()
                if chunk:
                    self._log_write(chunk.rstrip())
                m = re.search(r'found valid password[:\s]+\[\s*([0-9A-Fa-f]{8})\s*\]',
                              chunk or "", re.IGNORECASE)
                if m:
                    found_pwd = m.group(1).upper()
                    break
                if re.search(r'no valid password found', chunk or "", re.IGNORECASE):
                    self._log_write(f"[-] {lang['crack.err.prompt']}")
                    self.after(0, lambda: messagebox.showerror(
                        lang['err.title'], lang['crack.err.prompt']))
                    return
            if not found_pwd:
                self._log_write(f"[-] {lang['crack.err.timeout']}.")
                self.after(0, lambda: messagebox.showerror(
                    lang['err.title'], f"{lang['crack.err.prompt']} ({lang['crack.err.timeout']})"))
                return
            self._log_write(f"[+] {lang['crack.found']}: {found_pwd}")
            self._log_write(f"[*] {lang['crack.wiping']}: lf t55 wipe -p {found_pwd}")
            wipe_out = self._send(f"lf t55 wipe -p {found_pwd}")
            self._log_write(wipe_out or "(no output)")
            p = found_pwd
            self.after(0, lambda: messagebox.showinfo(
                "Success",
                f"{lang['crack.found']}: {p}\n{lang['crack.wiped']}."))
        self._run_in_thread(task)

    def _check_fake(self):
        if not self.app.pm3_ready():
            return
        def task():
            ok = self._detect()
            if ok:
                self.after(0, lambda: messagebox.showinfo(
                    lang['fake.title'],
                    lang['fake.prompt']))
        self._run_in_thread(task)




# tabul pentru setari are placeholders in caz ca s-a buguit si s-a sters fisierul de config, si a disparut limba selectata
class PreferencesTab(tk.Frame):
    LANGUAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Languages")

    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self._selected = tk.StringVar()
        self._build_ui()

    def _scan_languages(self):
        """Scaneaza folderul languages pentru limbile existente."""
        pattern = os.path.join(self.LANGUAGES_DIR, "*.json")
        files = glob.glob(pattern)
        result = []
        for path in sorted(files):
            if os.path.basename(path).lower() == "current.json":
                continue
            display = os.path.splitext(os.path.basename(path))[0]
            result.append((display, path))
        return result

    def _build_ui(self):
        outer = tk.LabelFrame(self, text=lang.get("prefs.lang.title", "Language"),
                              padx=14, pady=12)
        outer.pack(fill=tk.X, padx=20, pady=(20, 8))
        tk.Label(self, text="PTag by GigelHarbuz 2026",
                                     fg="#888").pack(anchor="center",side="bottom")
        langs = self._scan_languages()

        if not langs:
            tk.Label(outer, text=lang.get("prefs.lang.none", "No language files found."),
                     fg="#888").pack(anchor="w")
            return

        current_name = self._current_lang_name()

        for display, path in langs:
            rb = tk.Radiobutton(
                outer,
                text=display,
                variable=self._selected,
                value=display,
                font=("TkDefaultFont", 11),
                cursor="hand2"
            )
            rb.pack(anchor="w", pady=2)
            if display == current_name:
                self._selected.set(display)

        tk.Button(
            self,
            text=lang.get("prefs.btn.apply", "Apply"),
            width=20, height=2,
            relief=tk.GROOVE, cursor="hand2",
            bg="#c8e6c9",
            command=lambda: self._apply(langs)
        ).pack(pady=14)

    def _current_lang_name(self):
        """Citeste numele limbii din jsonul ei"""
        try:
            with open(os.path.join(self.LANGUAGES_DIR, "current.json"),
                      encoding="utf-8") as f:
                data = json.load(f)
            return data.get("_lang_name", "")
        except Exception:
            return ""

    def _apply(self, langs):
        chosen_display = self._selected.get()
        if not chosen_display:
            messagebox.showwarning(
                lang.get("prefs.warn.title", "No selection"),
                lang.get("prefs.warn.prompt", "Please select a language first.")
            )
            return

        path = next((p for d, p in langs if d == chosen_display), None)
        if not path:
            return

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror(lang.get("err.title", "Error"), str(e))
            return

        data["_lang_name"] = chosen_display

        current_path = os.path.join(self.LANGUAGES_DIR, "current.json")
        try:
            with open(current_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror(lang.get("err.title", "Error"), str(e))
            return

        self.app._disconnect()
        python = sys.executable
        os.execv(python, [python] + sys.argv)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PTag V1.3")
        self.geometry("720x560")
        self.resizable(True, True)

        self.pm3: Proxmark3Interface | None = None
        self._pm3_lock = threading.Lock()

        self._build_ui()
        self._try_autostart()
        self.protocol("WM_DELETE_WINDOW", self._on_close)


    def _build_ui(self):
        top = tk.Frame(self, bd=1, relief=tk.SUNKEN)
        top.pack(fill=tk.X, side=tk.TOP)

        self._status_var = tk.StringVar(value=lang['label.disconnected'])
        self._status_dot = tk.Label(top, text="●", fg="#cc3333", font=("TkDefaultFont", 14))
        self._status_dot.pack(side=tk.LEFT, padx=(8, 2), pady=3)
        tk.Label(top, textvariable=self._status_var, anchor="w").pack(side=tk.LEFT, pady=3)

        tk.Button(top, text=lang['btn.connect'], width=10,
                  command=self._connect).pack(side=tk.RIGHT, padx=6, pady=3)
        tk.Button(top, text=lang['btn.disconnect'], width=10,
                  command=self._disconnect).pack(side=tk.RIGHT, padx=2, pady=3)

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._tab_em      = TagTab(self._notebook, self, tag_type_key="EM",      clone_extra="")
        self._tab_electra = TagTab(self._notebook, self, tag_type_key="Electra", clone_extra="--electra")
        self._tab_t5577   = T5577Tab(self._notebook, self)
        self._tab_prefs   = PreferencesTab(self._notebook, self)

        self._notebook.add(self._tab_em,      text="  EM410x  ")
        self._notebook.add(self._tab_electra, text="  Electra  ")
        self._notebook.add(self._tab_t5577,   text="  T5577   ")
        self._notebook.add(self._tab_prefs,   text=f"  {lang.get('tab.prefs', 'Preferences - TO SHOW TEXT, SELECT LANGUAGE HERE')}  ")


    def _try_autostart(self):
        """Try to find pm3.bat in the script directory and connect."""
        bat = os.path.join(SCRIPT_DIR, "pm3.bat")
        if os.path.exists(bat):
            self._do_connect(bat)

    def _connect(self):
        bat = filedialog.askopenfilename(
            title="Select pm3.bat",
            initialdir=SCRIPT_DIR,
            filetypes=[("Batch file", "*.bat"), ("All files", "*.*")]
        )
        if bat:
            self._do_connect(bat)

    def _do_connect(self, bat_path: str):
        self._bat_path = bat_path
        self._set_status(lang['label.connecting'], "#e6a817")

        def task():
            pm3 = Proxmark3Interface(bat_path)
            ok, info = pm3.start()
            if ok:
                with self._pm3_lock:
                    self.pm3 = pm3
                label = lang['label.connected']
                if info:
                    label = f"{label} - {info}"
                self.after(0, lambda: self._set_status(label, "#2e7d32"))
            elif info == "comm_failed":
                self.after(0, lambda: self._set_status(lang['label.disconnected'], "#cc3333"))
                self.after(0, lambda: messagebox.showerror(
                    lang['err.title'],
                    lang.get('err.commfailed')
                ))
            else:
                self.after(0, lambda: self._set_status(lang['label.disconnected'], "#cc3333"))
                self.after(0, lambda: messagebox.showerror(
                    lang['err.title'],
                    f"{lang['err.cantstart']}:\n{bat_path}"
                ))

        threading.Thread(target=task, daemon=True).start()

    def reconnect(self):
        """Reconectare la proxmark"""
        bat_path = getattr(self, '_bat_path', None)
        if not bat_path:
            return
        self.after(0, lambda: self._set_status(lang['label.reconnecting'], "#e6a817"))
        with self._pm3_lock:
            if self.pm3:
                try:
                    self.pm3.force_stop()
                except Exception:
                    pass
                self.pm3 = None
        pm3 = Proxmark3Interface(bat_path)
        ok, info = pm3.start()
        if ok:
            with self._pm3_lock:
                self.pm3 = pm3
            label = lang['label.connected']
            if info:
                label = f"{label} - {info}"
            self.after(0, lambda: self._set_status(label, "#2e7d32"))
        else:
            self.after(0, lambda: self._set_status(lang['label.disconnected'], "#cc3333"))

    def _disconnect(self):
        with self._pm3_lock:
            if self.pm3:
                self.pm3.stop()
                self.pm3 = None
        self._set_status(lang['label.disconnected'], "#cc3333")

    def _set_status(self, text: str, color: str):
        self._status_var.set(text)
        self._status_dot.configure(fg=color)

    def pm3_ready(self) -> bool:
        """Verifica daca proxmarkul e conectat"""
        with self._pm3_lock:
            ready = self.pm3 is not None and self.pm3.running
        if not ready:
            messagebox.showerror(
                lang['err.title'],
                lang['err.disconnected']
            )
        return ready

    def _on_close(self):
        self._disconnect()
        self.destroy()



if __name__ == "__main__":
    ensure_saved_dir()
    app = App()
    app.mainloop()
