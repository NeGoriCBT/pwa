class States:
    # Создание записи
    WAITING_SITUATION = "waiting_situation"
    
    WAITING_EMOTION = "waiting_emotion"
    WAITING_CUSTOM_EMOTION = "waiting_custom_emotion"
    WAITING_EMOTION_INTENSITY = "waiting_emotion_intensity"
    WAITING_MORE_EMOTIONS = "waiting_more_emotions"
    
    WAITING_AUTOMATIC_THOUGHT = "waiting_automatic_thought"
    WAITING_AUTOMATIC_THOUGHT_CONFIDENCE = "waiting_automatic_thought_confidence"
    
    WAITING_ACTION = "waiting_action"
    
    WAITING_EVIDENCE_FOR = "waiting_evidence_for"
    WAITING_EVIDENCE_AGAINST = "waiting_evidence_against"
    
    WAITING_ALTERNATIVE_THOUGHT = "waiting_alternative_thought"
    WAITING_ALTERNATIVE_THOUGHT_CONFIDENCE = "waiting_alternative_thought_confidence"
    WAITING_MORE_ALTERNATIVE_THOUGHTS = "waiting_more_alternative_thoughts"
    
    WAITING_EMOTION_REASSESSMENT = "waiting_emotion_reassessment"
    WAITING_NEW_EMOTION = "waiting_new_emotion"
    WAITING_CUSTOM_NEW_EMOTION = "waiting_custom_new_emotion"
    WAITING_NEW_EMOTION_INTENSITY = "waiting_new_emotion_intensity"
    WAITING_MORE_NEW_EMOTIONS = "waiting_more_new_emotions"
    
    WAITING_NOTE_TO_FUTURE_SELF = "waiting_note_to_future_self"
    
    # Удаление записей
    WAITING_DELETE_PERIOD = "waiting_delete_period"
    WAITING_DELETE_START_DATE = "waiting_delete_start_date"
    WAITING_DELETE_END_DATE = "waiting_delete_end_date"
    WAITING_DELETE_CONFIRMATION = "waiting_delete_confirmation"
    
    # Скачивание
    WAITING_DOWNLOAD_PERIOD = "waiting_download_period"
    WAITING_DOWNLOAD_START_DATE = "waiting_download_start_date"
    WAITING_DOWNLOAD_END_DATE = "waiting_download_end_date"
    
    # Поиск
    WAITING_SEARCH_QUERY = "waiting_search_query"
    WAITING_SEARCH_DATE = "waiting_search_date"
    
    # Дневник экспозиций (новый процесс)
    WAITING_EXPOSURE_TYPE = "waiting_exposure_type"  # Выбор типа записи
    WAITING_EXPOSURE_SITUATION = "waiting_exposure_situation"
    WAITING_EXPOSURE_DATE = "waiting_exposure_date"
    WAITING_EXPOSURE_TIME = "waiting_exposure_time"  # Формат hh:MM
    WAITING_EXPOSURE_EXPECTATION = "waiting_exposure_expectation"  # Ожидание/страх
    WAITING_EXPOSURE_PROBABILITY = "waiting_exposure_probability"  # Вероятность 0-100
    WAITING_EXPOSURE_EMOTION = "waiting_exposure_emotion"  # Эмоция
    WAITING_EXPOSURE_EMOTION_INTENSITY = "waiting_exposure_emotion_intensity"  # Выраженность 0-100
    WAITING_EXPOSURE_MORE_EMOTIONS = "waiting_exposure_more_emotions"  # Еще эмоции?
    WAITING_EXPOSURE_MORE_EXPECTATIONS = "waiting_exposure_more_expectations"  # Еще ожидания?
    WAITING_EXPOSURE_DURATION = "waiting_exposure_duration"  # Продолжительность в минутах/часах
    WAITING_EXPOSURE_EXPECTATION_FULFILLED = "waiting_exposure_expectation_fulfilled"  # Свершилось ли ожидание (да/нет/не совсем)
    WAITING_EXPOSURE_REALITY_DESCRIPTION = "waiting_exposure_reality_description"  # Как все прошло на самом деле
    WAITING_EXPOSURE_WHAT_MATCHED = "waiting_exposure_what_matched"  # Что было именно так, как ожидали
    WAITING_EXPOSURE_WHAT_DIFFERED = "waiting_exposure_what_differed"  # Что было иначе
    WAITING_EXPOSURE_REALITY_EMOTION = "waiting_exposure_reality_emotion"  # Выбор дополнительной эмоции в реальности
    WAITING_EXPOSURE_REALITY_EMOTION_INTENSITY = "waiting_exposure_reality_emotion_intensity"  # Выраженность реальной эмоции
    WAITING_EXPOSURE_REALITY_MORE_EMOTIONS = "waiting_exposure_reality_more_emotions"  # Еще эмоции реальные?
    WAITING_EXPOSURE_FINAL_SUMMARY = "waiting_exposure_final_summary"  # Итоговое резюме
    WAITING_EXPOSURE_REALITY = "waiting_exposure_reality"  # Старый формат - для обратной совместимости

    # Напоминания: ввод времени (ЧЧ:ММ в локальном времени пользователя)
    WAITING_REMINDER_TIME = "waiting_reminder_time"

    # Админ: рассылка всем пользователям
    ADMIN_BROADCAST_MESSAGE = "admin_broadcast_message"

    # Пароль: создание и проверка
    WAITING_PASSWORD_CREATE = "waiting_password_create"
    WAITING_PASSWORD_VERIFY = "waiting_password_verify"
    WAITING_PASSWORD_FOR_DISABLE = "waiting_password_for_disable"  # Проверка перед отключением
    WAITING_PASSWORD_NEW_FOR_ENABLE = "waiting_password_new_for_enable"  # Новый пароль при включении