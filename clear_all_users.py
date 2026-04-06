#!/usr/bin/env python3
"""Скрипт для удаления всех пользователей и их данных.
Запуск: python clear_all_users.py
С флагом --force: python clear_all_users.py --force (без подтверждения)"""
import sys

def main():
    force = '--force' in sys.argv
    if not force:
        print("⚠️ ВНИМАНИЕ: Будут удалены ВСЕ пользователи и их данные!")
        confirm = input("Введите 'ДА' для подтверждения: ")
        if confirm.strip().upper() != 'ДА':
            print("Отменено.")
            sys.exit(0)
    
    from database import Database
    db = Database()
    count = db.delete_all_users()
    print(f"OK. Ochishcheno tablic: {count}")

if __name__ == '__main__':
    main()
