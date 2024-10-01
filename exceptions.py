class TokenAbsenceException(Exception):
    """
    Исключение, вызываемое при отсутствии одного или нескольких токенов.

    Attributes:
        missing_tokens (list): Список отсутствующих токенов.
    """

    def __init__(self, missing_tokens):
        """
        Инициализирует TokenAbsenceException с отсутствующими токенами.

        Args:
            missing_tokens (list): Список переменных окружения, которые
            отсутствуют.
        """
        self.missing_tokens = missing_tokens
        message = (
            'Отсутствуют необходимые переменные окружения: '
            f'{", ".join(self.missing_tokens)}'
        )
        super().__init__(message)
