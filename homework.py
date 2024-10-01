from dotenv import load_dotenv
import os
import sys
import telebot
import time
from exceptions import TokenAbsenceException
import requests
import logging


load_dotenv()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)


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

previous_state = None
current_state = None


def check_tokens():
    """
    Проверяет наличие необходимых токенов в глобальных переменных окружения.

    Оценивает наличие токенов для доступа к API Практикума и Telegram.
    Если какой-либо из токенов отсутствует, добавляет его в список
    отсутствующих токенов.

    Если список отсутствующих токенов не пуст, вызывает исключение
    TokenAbsenceException с этим списком.

    Returns:
        None

    Raises:
        TokenAbsenceException: Если отсутствует хотя бы один из токенов.
    """
    missing_tokens = []
    if not PRACTICUM_TOKEN:
        missing_tokens.append('PRACTICUM_TOKEN')
    if not TELEGRAM_TOKEN:
        missing_tokens.append('TELEGRAM_TOKEN')
    if not TELEGRAM_CHAT_ID:
        missing_tokens.append('TELEGRAM_CHAT_ID')
    if missing_tokens:
        logger.critical(TokenAbsenceException(missing_tokens))
        raise TokenAbsenceException(missing_tokens)


def send_message(bot, message):
    """
    Отправляет сообщение в Telegram.

    Parameters:
        bot (telebot.TeleBot): Экземпляр бота Telegram для отправки сообщений.
        message (str): Сообщение для отправки в Telegram.

    Returns:
        None
    """
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logger.debug(f'Отправлено сообщение {message}')
    except Exception as e:
        logger.error(f'Не удалось доставить сообщение. Ошибка {e}')


def get_api_answer(timestamp):
    """
    Получает ответ от API Практикума начиная с указанного времени.

    Parameters:
        timestamp (int): Unix-время, с которого запрашиваются события домашних
        работ.

    Returns:
        dict: Ответ от API, содержащий информацию о домашних работах и времени
        запроса.

    Raises:
        ValueError: Если статус ответа не равен 200 или ответ не является JSON.
    """
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params={'from_date':
                                                                   timestamp})
        if response.status_code != 200:
            logger.error(f'Ошибка API. Статус-код: {response.status_code}')
            raise ValueError(f'Ошибка API. Статус-код: {response.status_code}')
    except requests.RequestException as error:
        logger.error(f'Ошибка при запросе к API: {error}')
        return None

    try:
        response_dict = response.json()
    except ValueError as error:
        logger.error(f'Ошибка при попытке декодировать JSON: {error}')
        raise ValueError('Ответ от API не является JSON.')

    if not isinstance(response_dict, dict):
        raise ValueError('Ответ от API не является словарем.')

    return response_dict


def check_response(response):
    """
    Проверяет корректность ответа от API.

    Parameters:
        response (dict): Ответ от API, содержащий информацию о домашних
        работах.

    Raises:
        TypeError: Если ответ не является словарем или ключ 'homeworks' не
        является списком.
        ValueError: Если в ответе отсутствуют ключи 'homeworks' или
        'current_date'.
    """
    if not isinstance(response, dict):
        raise TypeError('Ответ API должен быть словарем.')

    if 'homeworks' not in response:
        raise ValueError('Ключ "homeworks" отсутствует.')

    if 'current_date' not in response:
        raise ValueError('Ключ "current_date" отсутствует в ответе API.')

    if not isinstance(response['homeworks'], list):
        raise TypeError('Ключ "homeworks" должен содержать список.')

    if not response['homeworks']:
        logger.debug('В ответе API отсутствуют новые домашние работы.')


def parse_status(homework):
    """
    Извлекает статус домашнего задания и формирует сообщение о его изменении.

    Parameters:
        homework (dict): Словарь с информацией о домашнем задании.

    Returns:
        str: Сообщение о статусе домашней работы.

    Raises:
        KeyError: Если в словаре отсутствуют ключи 'homework_name' или
        'status'.
        ValueError: Если статус работы неизвестен.
    """
    if 'homework_name' not in homework:
        raise KeyError('Ключ "homework_name" отсутствует в ответе API.')
    if 'status' not in homework:
        raise KeyError('Ключ "status" отсутствует в ответе API.')
    homework_name = homework.get('homework_name')
    status = homework.get('status')
    verdict = HOMEWORK_VERDICTS.get(status)
    if verdict is None:
        raise ValueError(f'Неизвестный статус работы: {status}')
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


current_status = None


def main():
    """Основная логика работы бота."""
    check_tokens()

    bot = telebot.TeleBot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())

    while True:
        try:
            global current_status
            response = get_api_answer(timestamp)
            check_response(response)
            homeworks = response.get('homeworks')
            message = parse_status(homeworks[0])
            if current_status != message:
                send_message(bot, message)
                current_status = message
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
