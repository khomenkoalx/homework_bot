from http import HTTPStatus
import logging
import os
import sys
import time

import requests
import telebot
from dotenv import load_dotenv

os.environ.pop('PRACTICUM_TOKEN', '')
load_dotenv()

log_file = __file__ + '.log'

# Константы
TOKEN_ABSENCE_MSG = 'Отсутствуют обязательные переменные окружения!'
DELIVERY_ERROR_MSG = (
    'Не удалось доставить сообщение {message}. Ошибка: {error}.'
)
API_ERROR_MSG = (
    'Ошибка API. Статус-код: {status_code}. '
    'Параметры запроса: {params}. '
    'Отказ в обслуживании: {error}. Код: {code}.'
)
HOMEWORK_KEY_MISSING_MSG = 'Ключ "homeworks" отсутствует.'
UNKNOWN_STATUS_MSG = 'Неизвестный статус работы: {status}'
HOMEWORK_NAME_MISSING_MSG = 'Ключ "homework_name" отсутствует в ответе API.'
HOMEWORK_STATUS_MISSING_MSG = 'Ключ "status" отсутствует в ответе API.'
NO_NEW_HOMEWORK_MSG = 'В ответе API отсутствуют новые домашние работы.'
CONNECTION_ERROR_MSG = 'Ошибка подключения: {error}'
TIMEOUT_ERROR_MSG = 'Превышено время ожидания: {error}'
REQUEST_ERROR_MSG = 'Ошибка при запросе к API {error}'
UNKNOWN_HOMEWORK_ERROR_MSG = 'Ключ "homework_name" отсутствует в ответе API.'

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(funcName)s - %(lineno)d'
    '- %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding='utf-8')
    ]
)

logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

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


def check_tokens():
    """
    Проверяет наличие необходимых токенов для работы с API и Telegram.

    Если отсутствует хотя бы одна переменная окружения, функция вызывает
    критическое логирование и генерирует исключение ValueError.

    Raises:
        ValueError: Если отсутствует один или несколько токенов.
    """
    missing_tokens = []
    for token in (PRACTICUM_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID):
        if not token:
            missing_tokens.append(token)
    if missing_tokens:
        logger.critical(TOKEN_ABSENCE_MSG)
        raise ValueError(TOKEN_ABSENCE_MSG)


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
        logger.debug(f'Отправлено сообщение {message}')
    except Exception as e:
        logger.exception(DELIVERY_ERROR_MSG.format(message=message, error=e))
    else:
        return True


def get_api_answer(timestamp):
    """
    Получает ответ от API Практикума начиная с указанного времени.

    Args:
        timestamp (str): Unix-временная метка, с которой начинается получение
        данных.

    Returns:
        dict: Ответ от API, представленный в виде словаря.

    Raises:
        ValueError: Если возникает ошибка при выполнении запроса к API
        или если статус ответа не равен HTTPStatus.OK.
    """
    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp}
        )
    except requests.ConnectionError as error:
        raise ValueError(f'Ошибка подключения: {error}')
    except requests.Timeout as error:
        raise ValueError(f'Превышено время ожидания: {error}')
    except requests.RequestException as error:
        raise ValueError(f'Ошибка при запросе к API {error}')

    response_dict = response.json()

    if response.status_code != HTTPStatus.OK:
        error_message = response_dict.get('error', 'Нет информации об ошибке.')
        error_code = response_dict.get('code', 'Неизвестный код ошибки.')

        raise ValueError(API_ERROR_MSG.format(
            status_code=response.status_code,
            params={'from_date': timestamp, 'headers': HEADERS},
            error=error_message,
            code=error_code
        ))

    return response_dict


def check_response(response):
    """
    Проверяет правильность структуры ответа от API.

    Args:
        response (dict): Ответ от API в виде словаря.

    Raises:
        TypeError: Если ответ не является словарем или если ключу
        'homeworks' не соответствует список.
        ValueError: Если в ответе отсутствует ключ 'homeworks' или
        список 'homeworks' пуст.
    """
    if not isinstance(response, dict):
        raise TypeError(
            f'Ответ от API является {type(response)}, а не словарем.'
        )
    if 'homeworks' not in response:
        raise KeyError(HOMEWORK_KEY_MISSING_MSG)

    if not isinstance(response.get('homeworks'), list):
        raise TypeError('Ключу homeworks соответствует не список.')
    if not response.get('homeworks'):
        logger.debug(NO_NEW_HOMEWORK_MSG)


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
        raise KeyError(HOMEWORK_NAME_MISSING_MSG)
    if 'status' not in homework:
        raise KeyError(HOMEWORK_STATUS_MISSING_MSG)
    status = homework.get('status')
    homework_name = homework.get('homework_name')
    verdict = HOMEWORK_VERDICTS.get(status)
    if status not in HOMEWORK_VERDICTS.keys():
        raise ValueError(UNKNOWN_STATUS_MSG.format(status=status))
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основной цикл выполнения программы."""
    check_tokens()

    bot = telebot.TeleBot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    last_message = NO_NEW_HOMEWORK_MSG
    send_message(bot, 'Бот запущен')
    while True:
        try:
            response = get_api_answer(timestamp)
            if response.get('current_date'):
                timestamp = int(response.get('current_date')) + 1
                check_response(response)
                homeworks = response.get('homeworks')
                if homeworks:
                    message = parse_status(homeworks[0])
                    if last_message != message:
                        sent_successfully = send_message(bot, message)
                        if sent_successfully:
                            last_message = message
                            sent_successfully = False
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.exception(f'Ошибка в работе программы: {error}')
            sent_successfully = send_message(bot, message)
            if sent_successfully:
                last_message = message
                sent_successfully = False
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
