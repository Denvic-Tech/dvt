import sys
import re

print(f"ARGV: {sys.argv}")

commit_msg_file = sys.argv[1]

with open(commit_msg_file, "r", encoding="utf-8") as f:
    msg = f.read().strip()

pattern = r"^(ADD|UPD|FIX|HFIX|RM|CLR) .+"

if not re.match(pattern, msg):
    print("Неверный формат commit message!\n")
    print("Ожидаемый формат:")
    print("  ADD: описание       — добавление нового функционала, сущностей или файлов")
    print("  UPD: описание       — обновление существующего функционала, сущностей или файлов")
    print("  FIX: описание       — исправление ошибки")
    print("  HFIX: описание      — горячая/быстрая заглушка для фикса")
    print("  RM: описание        — удаление функционала, сущностей или файлов")
    print("  CLR: описание       — рефакторинг, чистка кода\n")
    print(f"Ваш коммит: '{msg}'")
    sys.exit(1)

sys.exit(0)
