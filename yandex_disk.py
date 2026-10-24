"""Коннектор к облачному хранилищу Яндекс Диск."""

import os
from datetime import datetime

import requests


class YandexDisk:
    """Работа с файлами в одной папке на Яндекс Диске.

    При ошибке сети или API методы выбрасывают requests.RequestException,
    при ошибке чтения локального файла — OSError.
    """

    API_URL = 'https://cloud-api.yandex.net/v1/disk/resources'
    PAGE_SIZE = 100
    TIMEOUT = 30

    def __init__(self, token, folder):
        """
        :param token: OAuth-токен Яндекс Диска.
        :param folder: существующая папка на Диске для резервных копий.
        """
        self.folder = f'disk:/{folder.strip("/")}'
        self.headers = {'Authorization': f'OAuth {token}'}

    def get_info(self):
        """Вернуть словарь {имя файла: время изменения} для файлов в папке.

        Время — секунды с начала эпохи, как у os.path.getmtime.
        Вложенные папки пропускаются.
        """
        files = {}
        offset = 0
        while True:
            page = self._get_page(offset)
            files.update(self._parse_items(page['items']))
            offset += self.PAGE_SIZE
            if offset >= page['total']:
                return files

    def load(self, path, overwrite=False):
        """Загрузить локальный файл в папку на Диске."""
        href = self._get_upload_link(os.path.basename(path), overwrite)
        with open(path, 'rb') as file:
            response = requests.put(href, data=file, timeout=self.TIMEOUT)
        response.raise_for_status()

    def reload(self, path):
        """Перезаписать файл на Диске новой версией локального файла."""
        self.load(path, overwrite=True)

    def delete(self, filename):
        """Удалить файл из папки на Диске (файл попадёт в корзину Диска)."""
        response = requests.delete(
            self.API_URL,
            headers=self.headers,
            params={'path': self._remote_path(filename)},
            timeout=self.TIMEOUT,
        )
        response.raise_for_status()

    def _get_page(self, offset):
        """Запросить одну страницу списка содержимого папки."""
        response = requests.get(
            self.API_URL,
            headers=self.headers,
            params={
                'path': self.folder,
                'limit': self.PAGE_SIZE,
                'offset': offset,
            },
            timeout=self.TIMEOUT,
        )
        response.raise_for_status()
        return response.json()['_embedded']

    def _get_upload_link(self, filename, overwrite):
        """Получить ссылку, по которой нужно загрузить файл."""
        response = requests.get(
            f'{self.API_URL}/upload',
            headers=self.headers,
            params={
                'path': self._remote_path(filename),
                'overwrite': str(overwrite).lower(),
            },
            timeout=self.TIMEOUT,
        )
        response.raise_for_status()
        return response.json()['href']

    def _remote_path(self, filename):
        """Вернуть путь к файлу на Диске."""
        return f'{self.folder}/{filename}'

    @staticmethod
    def _parse_items(items):
        """Оставить из ответа API только файлы: имя и время изменения."""
        return {
            item['name']: datetime.fromisoformat(item['modified']).timestamp()
            for item in items
            if item['type'] == 'file'
        }
