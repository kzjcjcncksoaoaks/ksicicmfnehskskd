# --- ЭТОТ КОД КЛАДЕМ НА GITHUB (core.py) ---
import json
import os
import threading
import urllib.request
import ssl
from base_plugin import MethodHook
from android_utils import run_on_ui_thread
from hook_utils import find_class
from org.telegram.messenger import ApplicationLoader, UserObject, LocaleController
from ui.bulletin import BulletinHelper

# Настройки репозитория
OCCKNFHSYAGAPCPCLIGRM = "https://raw.githubusercontent.com/kzjcjcncksoaoaks/ksicicmfnehskskd/main"

# --- ХУКИ (Логика перехвата) ---
class BadgeHook(MethodHook):
    def __init__(self, logic):
        self.logic = logic 

    def after_hooked_method(self, param):
        if not self.logic.db_ready: return
        try:
            tl_object = param.args[0]
            obj_id = int(getattr(tl_object, "id", 0))
            
            # Обращаемся к логике, а не к plugin напрямую
            badge_conf = self.logic.get_badge_config(obj_id)
            if badge_conf:
                final_text = self.logic.format_text(badge_conf, tl_object)
                eid = int(badge_conf.get("emoji_id", 0))
                
                if self.logic.BadgeDTO:
                    try:
                        param.setResult(self.logic.BadgeDTO(eid, final_text, None, None))
                    except:
                        param.setResult(self.logic.BadgeDTO(eid, final_text))
        except: pass

class ProfileBadgeHook(MethodHook):
    def __init__(self, logic):
        self.logic = logic

    def after_hooked_method(self, param):
        if not self.logic.db_ready: return
        try:
            tl_object = param.args[0]
            obj_id = int(getattr(tl_object, "id", 0))
            badge_conf = self.logic.get_badge_config(obj_id)
            if badge_conf:
                final_text = self.logic.format_text(badge_conf, tl_object)
                param.setResult(str(final_text))
        except: pass

# --- ОСНОВНАЯ ЛОГИКА ---
class RemoteCore:
    def __init__(self, host_plugin):
        self.plugin = host_plugin # Ссылка на основной плагин в телефоне
        self.db = {}
        self.user_meta = {}
        self.config = {}
        self.db_ready = False
        self.BadgeDTO = None
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    def activate(self):
        """Запускается при загрузке кода"""
        try:
            self.BadgeDTO = find_class("com.exteragram.messenger.api.dto.BadgeDTO")
            
            # Загружаем кэш
            files_dir = ApplicationLoader.applicationContext.getExternalFilesDir(None)
            self.cache_path = os.path.join(str(files_dir.getAbsolutePath()), "ost_remote_cache.json")
            self._load_cache()
            
            # Регистрируем хуки
            self._setup_hooks()
            
            # Запускаем синхронизацию
            threading.Thread(target=self._sync_process, daemon=True).start()
            
            print("[RemoteCore] Activated successfully")
        except Exception as e:
            print(f"[RemoteCore] Error: {e}")

    def _setup_hooks(self):
        try:
            BadgesController = find_class("com.exteragram.messenger.badges.BadgesController")
            if BadgesController:
                m1 = BadgesController.getClass().getDeclaredMethod("getBadge", find_class("org.telegram.tgnet.TLObject"))
                m1.setAccessible(True)
                # Важно: добавляем хук в список host_plugin, чтобы он не потерялся
                self.plugin.hooks.append(self.plugin.hook_method(m1, BadgeHook(self)))

            ProfileBadgeHelper = find_class("com.exteragram.messenger.profile.ProfileBadgeHelper")
            if ProfileBadgeHelper:
                m2 = ProfileBadgeHelper.getClass().getDeclaredMethod("getVerifiedText", find_class("org.telegram.tgnet.TLObject"))
                m2.setAccessible(True)
                self.plugin.hooks.append(self.plugin.hook_method(m2, ProfileBadgeHook(self)))
        except: pass

    def get_badge_config(self, obj_id):
        return self.db.get(obj_id)

    def format_text(self, conf, tl_object):
        is_ru = LocaleController.getInstance().getCurrentLocaleInfo().getLangCode().startswith("ru")
        template = conf.get("text_ru") if is_ru else conf.get("text_en")
        if not template: template = "Verified"
        
        name = "Unknown"
        if hasattr(tl_object, "first_name"):
            name = UserObject.getUserName(tl_object)
        elif hasattr(tl_object, "title"):
            name = tl_object.title
            
        obj_id = getattr(tl_object, "id", 0)
        date_str = self.user_meta.get(obj_id, {}).get("date", "")
        
        return template.replace("{name}", str(name)).replace("{id}", str(obj_id)).replace("{date}", str(date_str))

    def _sync_process(self):
        try:
            # Сначала грузим настройки (где описаны бейджи)
            conf_url = f"{OCCKNFHSYAGAPCPCLIGRM}/settings.json"
            new_config = self._fetch_json(conf_url)
            
            if not new_config: return # Если нет инета, работаем на кэше

            self.config = new_config
            badges_def = self.config.get("badges", [])
            badges_def.sort(key=lambda x: x.get("priority", 99), reverse=True)

            temp_db = {}
            temp_meta = {}
            
            # Грузим списки пользователей
            for b_def in badges_def:
                file_name = b_def.get("file")
                if not file_name: continue
                
                # Парсим ID и Дату
                items = self._fetch_ids_with_data(f"{OCCKNFHSYAGAPCPCLIGRM}/{file_name}")
                for uid, date_val in items:
                    temp_db[uid] = b_def
                    if date_val:
                        temp_meta[uid] = {"date": date_val}

            self.db = temp_db
            self.user_meta = temp_meta
            self.db_ready = True
            self._save_cache()
            
            run_on_ui_thread(lambda: BulletinHelper.show_success(f"Обновлено (Remote).\nБаза: {len(temp_db)}"))
        except Exception as e:
            print(f"[RemoteCore] Sync Error: {e}")

    def _fetch_json(self, url):
        try:
            req = urllib.request.Request(url)
            req.add_header('Cache-Control', 'no-cache')
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=15) as r:
                return json.loads(r.read().decode('utf-8'))
        except: return None

    def _fetch_ids_with_data(self, url):
        results = []
        try:
            req = urllib.request.Request(url)
            req.add_header('Cache-Control', 'no-cache')
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=15) as r:
                lines = r.read().decode('utf-8').splitlines()
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    parts = line.split(':')
                    id_part = "".join(filter(lambda x: x.isdigit() or x == '-', parts[0]))
                    if not id_part: continue
                    uid = int(id_part)
                    date_formatted = ""
                    if len(parts) > 1:
                        raw_date = "".join(filter(str.isdigit, parts[1]))
                        if len(raw_date) == 8: # ddmmyyyy
                            date_formatted = f"{raw_date[:2]}.{raw_date[2:4]}.{raw_date[6:]}"
                        elif len(raw_date) == 6: # ddmmyy
                             date_formatted = f"{raw_date[:2]}.{raw_date[2:4]}.{raw_date[4:]}"
                    results.append((uid, date_formatted))
        except: pass
        return results

    def _save_cache(self):
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump({"db": self.db, "meta": self.user_meta, "config": self.config}, f)
        except: pass

    def _load_cache(self):
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.db = {int(k): v for k, v in data.get("db", {}).items()}
                    self.user_meta = {int(k): v for k, v in data.get("meta", {}).items()}
                    self.config = data.get("config", {})
                    self.db_ready = True
            except: pass

# --- ТОЧКА ВХОДА ---
# Этот код сработает, когда Загрузчик выполнит exec()
# 'host_plugin' будет передан из загрузчика
if 'host_plugin' in locals():
    core_logic = RemoteCore(host_plugin)
    core_logic.activate()
