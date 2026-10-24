"""Сервис синхронизации локальной папки с папкой в облачном хранилище."""

import os
import sys
import time

import requests
from dotenv import dotenv_values
from loguru import logger as loguru_logger

from yandex_disk import YandexDisk


def read_config(env_path):
    """Прочитать параметры программы из файла .env."""
    if not os.path.isfile(env_path):
        sys.exit(
            f'Не найден файл настроек {env_path}.\n'
            'Скопируйте .env.example в .env и заполните параметры.'
        )
    return dotenv_values(env_path)


def check_config(config):
    """Завершить программу, если в .env заданы не все параметры."""
    required = (
        'LOCAL_FOLDER', 'CLOUD_FOLDER', 'TOKEN', 'SYNC_PERIOD', 'LOG_FILE',
    )
    missing = [key for key in required if not config.get(key)]
    if missing:
        sys.exit(f'В файле .env не заданы параметры: {", ".join(missing)}.')


def check_local_folder(path):
    """Завершить программу, если отслеживаемой папки нет."""
    if not os.path.isdir(path):
        sys.exit(
            f'Папка {path} не найдена.\n'
            'Проверьте параметр LOCAL_FOLDER в файле .env.'
        )


def parse_period(value):
    """Вернуть период синхронизации в секундах."""
    if not value.isdecimal() or int(value) == 0:
        sys.exit(
            f'Неверный период синхронизации: {value}.\n'
            'SYNC_PERIOD в файле .env должен быть целым числом секунд '
            'больше нуля.'
        )
    return int(value)


def setup_logger(log_file):
    """Настроить вывод лога в консоль и в файл и вернуть логгер."""
    log_format = (
        'synchronizer {time:YYYY-MM-DD HH:mm:ss,SSS} {level} {message}'
    )
    loguru_logger.remove()
    loguru_logger.add(sys.stderr, format=log_format, level='INFO')
    try:
        loguru_logger.add(
            log_file, format=log_format, level='INFO', encoding='utf-8',
        )
    except OSError as error:
        sys.exit(
            f'Не удалось открыть файл лога {log_file}: {error}.\n'
            'Проверьте параметр LOG_FILE в файле .env.'
        )
    return loguru_logger


def check_storage(storage, logger):
    """Завершить программу, если токен или папка в облаке неверны.

    Если нет интернета, программа продолжает работу: ошибки сети
    будут записываться в лог при каждой синхронизации.
    """
    messages = {
        401: 'Неверный токен доступа к облачному хранилищу. '
             'Получите новый токен и укажите его в TOKEN в файле .env.',
        404: 'Папка не найдена в облачном хранилище. '
             'Создайте её или исправьте CLOUD_FOLDER в файле .env.',
    }
    try:
        storage.get_info()
    except requests.HTTPError as error:
        status = error.response.status_code
        logger.error(messages.get(status, f'Ошибка хранилища: {error}'))
        sys.exit(1)
    except requests.RequestException as error:
        logger.error(f'Нет связи с облачным хранилищем. Ошибка: {error}')


def get_local_files(folder):
    """Вернуть словарь {имя файла: время изменения} для файлов в папке.

    Вложенные папки пропускаются.
    """
    paths = [os.path.join(folder, name) for name in os.listdir(folder)]
    return {
        os.path.basename(path): os.path.getmtime(path)
        for path in paths
        if os.path.isfile(path)
    }


def find_changed(local_files, cloud_files):
    """Вернуть имена файлов, изменённых локально после загрузки в облако."""
    return sorted(
        name for name in local_files.keys() & cloud_files.keys()
        if local_files[name] > cloud_files[name]
    )


def upload_file(upload, path, action, logger):
    """Загрузить файл методом коннектора и записать результат в лог."""
    name = os.path.basename(path)
    try:
        upload(path)
        logger.info(f'Файл {name} успешно {action}.')
    except (OSError, requests.RequestException) as error:
        logger.error(f'Файл {name} не {action}. Ошибка: {error}')


def delete_file(storage, name, logger):
    """Удалить файл из облака и записать результат в лог."""
    try:
        storage.delete(name)
        logger.info(f'Файл {name} успешно удалён.')
    except requests.RequestException as error:
        logger.error(f'Файл {name} не удалён. Ошибка: {error}')


def sync(storage, folder, logger):
    """Привести папку в облаке в соответствие с локальной папкой."""
    try:
        cloud_files = storage.get_info()
        local_files = get_local_files(folder)
    except (OSError, requests.RequestException) as error:
        logger.error(f'Синхронизация не выполнена. Ошибка: {error}')
        return
    for name in sorted(cloud_files.keys() - local_files.keys()):
        delete_file(storage, name, logger)
    for name in sorted(local_files.keys() - cloud_files.keys()):
        path = os.path.join(folder, name)
        upload_file(storage.load, path, 'записан', logger)
    for name in find_changed(local_files, cloud_files):
        path = os.path.join(folder, name)
        upload_file(storage.reload, path, 'перезаписан', logger)


def run(storage, folder, period, logger):
    """Синхронизировать папки каждые period секунд."""
    while True:
        sync(storage, folder, logger)
        time.sleep(period)


def main():
    """Настроить программу и запустить бесконечный цикл синхронизации."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    config = read_config(env_path)
    check_config(config)
    check_local_folder(config['LOCAL_FOLDER'])
    period = parse_period(config['SYNC_PERIOD'])
    logger = setup_logger(config['LOG_FILE'])
    logger.info(
        'Программа синхронизации файлов начинает работу '
        f'с директорией {config["LOCAL_FOLDER"]}.'
    )
    storage = YandexDisk(config['TOKEN'], config['CLOUD_FOLDER'])
    check_storage(storage, logger)
    try:
        run(storage, config['LOCAL_FOLDER'], period, logger)
    except KeyboardInterrupt:
        logger.info('Программа синхронизации файлов остановлена.')


if __name__ == '__main__':
    main()
