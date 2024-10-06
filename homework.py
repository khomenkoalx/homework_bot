from http import HTTPStatus
import logging
import os
import sys
import time

import requests
import telebot
from dotenv import load_dotenv

from exceptions import InvalidJSONError, ConnectionError

os.environ.pop('PRACTICUM_TOKEN')

load_dotenv()

TOKEN_NAMES = ('PRACTICUM_TOKEN', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID')

TOKEN_ABSENCE_MESSAGE = 'Отсутствуют переменные окружения: {token}'
DELIVERY_ERROR_MESSAGE = (
    'Не удалось доставить сообщение {message}. Ошибка: {error}.'
)
INVALID_JSON_MESSAGE = (
    'Ошибка API. Статус-код: {status_code}. '
    'Параметры запроса: {endpoint}, {headers}, {params}. '
    'Найденные имена ключей: {found_keys} '
    'Отказ в обслуживании: {error}.'
)
REQUEST_ERROR_MESSAGE = ('Ошибка при запросе к API. Адрес: {endpoint}, '
                         'заголовки: {headers}, параметры: {params}')
HOMEWORK_KEY_MISSING_MESSAGE = 'Ключ "homeworks" отсутствует.'
UNKNOWN_STATUS_MESSAGE = 'Неизвестный статус работы: {status}'
HOMEWORK_NAME_MISSING_MESSAGE = ('Ключ "homework_name" отсутствует '
                                 'в ответе API.')
HOMEWORK_STATUS_MISSING_MESSAGE = 'Ключ "status" отсутствует в ответе API.'
NO_NEW_HOMEWORK_MESSAGE = 'В ответе API отсутствуют новые домашние работы.'
CONNECTION_ERROR_MESSAGE = 'Ошибка подключения: {error}'
TIMEOUT_ERROR_MESSAGE = 'Превышено время ожидания: {error}'
REQUEST_ERROR_MESSAGE = 'Ошибка при запросе к API {error}'
UNKNOWN_HOMEWORK_ERROR_MESSAGE = ('Ключ "homework_name" отсутствует '
                                  'в ответе API.')
PROGRAM_FAIL_MESSAGE = 'Сбой в работе программы {error}'
HOMEWORKS_NOT_LIST_MESSAGE = ('Ключу homeworks соответствует {actual_type}, '
                              'а не список.')
API_ANSWER_NOT_DICTIONARY = ('Ответ от API является {actual_type}, '
                             'а не словарем')
MESSAGE_SENT_MESSAGE = 'Отправлено сообщение {message}'
WRONG_JSON_KEYS = ('code', 'error')

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

logger = logging.getLogger(__name__)


def check_tokens():
    """
    Проверяет наличие необходимых токенов для работы с API и Telegram.

    Если отсутствует хотя бы одна переменная окружения, функция вызывает
    критическое логирование и генерирует исключение ValueError.

    Raises:
        ValueError: Если отсутствует один или несколько токенов.
    """
    missing_tokens = [
        name for name in TOKEN_NAMES if not globals().get(name)
    ]
    if missing_tokens:
        logger.critical(TOKEN_ABSENCE_MESSAGE.format(token=missing_tokens))
        raise ValueError(
            TOKEN_ABSENCE_MESSAGE.format(token=missing_tokens)
        )


def send_message(bot, message):
    """
    Отправляет сообщение в Telegram чат.

    Args:
        bot: Объект бота Telegram, используемый для отправки сообщения.
        message (str): Сообщение, которое необходимо отправить.

    Raises:
        Exception: Если происходит ошибка при отправке сообщения,
        сообщение будет залогировано как исключение.
    """
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logger.debug(MESSAGE_SENT_MESSAGE.format(message=message))
        return True
    except Exception as e:
        logger.exception(
            DELIVERY_ERROR_MESSAGE.format(message=message, error=e)
        )
        return False


def get_api_answer(timestamp):
    """
    Получает ответ от API Практикума начиная с указанного времени.

    Args:
        timestamp (str): Unix-временная метка, с которой начинается получение
        данных.

    Returns:
        dict: Ответ от API, представленный в виде словаря.

    Raises:
        ConnectionError: Если возникает ошибка при выполнении запроса к API.
        InvalidJSONError: Если статус ответа не равен 200.
    """
    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp}
        )
    except requests.RequestException:
        raise ConnectionError(
            REQUEST_ERROR_MESSAGE.format(
                endpoint=ENDPOINT,
                headers=HEADERS,
                params={'from_date': timestamp}
            )
        )
    if response.status_code != HTTPStatus.OK:
        error_message = response.json().get('error')
        error_code = response.json().get('code')

        raise InvalidJSONError(INVALID_JSON_MESSAGE.format(
            status_code=response.status_code,
            endpoint=ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp},
            found_keys=[key for key in response.json().keys()
                        if key in WRONG_JSON_KEYS],
            error=error_message or error_code
        )
        )
    return response.json()


def check_response(response):
    """
    Проверяет правильность структуры ответа от API.

    Args:
        response (dict): Ответ от API в виде словаря.

    Raises:
        TypeError: Если ответ не является словарем, если ключу
        'homeworks' не соответствует список, если в ответе отсутствует
        ключ 'homeworks'.
        KeyError: Если в ответе отсутствует ключ 'homeworks'.
    """
    if not isinstance(response, dict):
        raise TypeError(
            API_ANSWER_NOT_DICTIONARY.format(
                actual_type=type(response)
            )
        )
    if 'homeworks' not in response:
        raise KeyError(HOMEWORK_KEY_MISSING_MESSAGE)
    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError(HOMEWORKS_NOT_LIST_MESSAGE.format(
            actual_type=type(homeworks)
        )
        )


def parse_status(homework):
    """
    Парсит статус домашней работы.

    Args:
        homework (dict): Словарь, представляющий домашнюю работу,
        содержащий ключи 'homework_name' и 'status'.

    Returns:
        str: Сообщение об изменении статуса проверки работы.

    Raises:
        KeyError: Если отсутствует ключ 'homework_name' или 'status'.
        ValueError: Если у домашней работы неожиданный статус.
    """
    if 'homework_name' not in homework:
        raise KeyError(HOMEWORK_NAME_MISSING_MESSAGE)
    if 'status' not in homework:
        raise KeyError(HOMEWORK_STATUS_MISSING_MESSAGE)
    status = homework.get('status')
    homework_name = homework.get('homework_name')
    verdict = HOMEWORK_VERDICTS.get(status)
    if status not in HOMEWORK_VERDICTS.keys():
        raise ValueError(UNKNOWN_STATUS_MESSAGE.format(status=status))
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основной цикл выполнения программы."""
    check_tokens()
    bot = telebot.TeleBot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    last_message = NO_NEW_HOMEWORK_MESSAGE
    while True:
        try:
            response = get_api_answer(timestamp)
            check_response(response)
            homeworks = response.get('homeworks')
            if not homeworks:
                logger.debug(NO_NEW_HOMEWORK_MESSAGE)
            else:
                message = parse_status(homeworks[0])
                if last_message != message:
                    if send_message(bot, message):
                        last_message = message
                        timestamp = timestamp or response.get('current_date')
        except Exception as error:
            message = PROGRAM_FAIL_MESSAGE.format(error=error)
            logger.error(message)
            if last_message != message:
                if send_message(bot, message):
                    last_message = message
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format=('%(asctime)s - %(name)s - %(funcName)s - %(lineno)d'
                '- %(levelname)s - %(message)s'),
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f'{__file__}.log', encoding='utf-8')
        ]
    )
    main()
