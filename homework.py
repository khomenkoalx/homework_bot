from http import HTTPStatus
import logging
import os
import sys
import time

import requests
import telebot
from dotenv import load_dotenv

load_dotenv()


TOKEN_ABSENCE_MESSAGE = 'Отсутствуют переменные окружения: {token}'
DELIVERY_ERROR_MESSAGE = (
    'Не удалось доставить сообщение {message}. Ошибка: {error}.'
)
API_ERROR_MESSAGE = (
    'Ошибка API. Статус-код: {status_code}. '
    'Параметры запроса: {params}. '
    'Отказ в обслуживании: {error}. Код: {code}.'
)
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
HOMEWORKS_NOT_LIST_MESSAGE = 'Ключу homeworks соответствует не список.'
API_ANSWER_NOT_DICTIONARY = ('Ответ от API является {actual_type}, '
                             'а не словарем')
MESSAGE_SENT_MESSAGE = 'Отправлено сообщение {message}'
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

logging.basicConfig(
    level=logging.DEBUG,
    format=('%(asctime)s - %(name)s - %(funcName)s - %(lineno)d'
            '- %(levelname)s - %(message)s'),
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'{__file__}.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


def check_tokens():
    """
    Проверяет наличие необходимых токенов для работы с API и Telegram.

    Если отсутствует хотя бы одна переменная окружения, функция вызывает
    критическое логирование и генерирует исключение ValueError.

    Raises:
        ValueError: Если отсутствует один или несколько токенов.
    """
    variables = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID
    }
    missing_tokens = [
        name for name, value in variables.items() if value is None
    ]
    if missing_tokens:
        logger.critical(
            TOKEN_ABSENCE_MESSAGE.format(token=', '.join(missing_tokens))
        )
        raise ValueError(
            TOKEN_ABSENCE_MESSAGE.format(token=', '.join(missing_tokens))
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
        ValueError: Если возникает ошибка при выполнении запроса к API
        или если статус ответа не равен HTTPStatus.OK.
    """
    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp}
        )
    except requests.RequestException as error:
        raise ValueError(f'Ошибка при запросе к API {error}')
    response_dict = response.json()  # ТОЧНО ЛИ СЮДА?

    if response.status_code != HTTPStatus.OK:
        error_message = response_dict.get('error')
        error_code = response_dict.get('code')

        raise ValueError(API_ERROR_MESSAGE.format(
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
            API_ANSWER_NOT_DICTIONARY.format(
                actual_type=type(response)
            )
        )
    if 'homeworks' not in response:
        raise KeyError(HOMEWORK_KEY_MISSING_MESSAGE)

    if not isinstance(response.get('homeworks'), list):
        raise TypeError(HOMEWORKS_NOT_LIST_MESSAGE)
    if not response.get('homeworks'):
        logger.debug(NO_NEW_HOMEWORK_MESSAGE)


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
            if response.get('current_date'):
                check_response(response)
                homeworks = response.get('homeworks')
                if homeworks:
                    message = parse_status(homeworks[0])
                    if last_message != message:
                        if send_message(bot, message):
                            last_message = message
                            timestamp = int(response.get('current_date'))
        except Exception as error:
            message = PROGRAM_FAIL_MESSAGE.format(error=error)
            logger.error(message)
            send_message(bot, message)
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':

    main()
