"""
companies/validators.py

Валидаторы реквизитов юридических лиц.

ИНН проверяется по контрольной сумме (алгоритм ФНС):
  * 10 цифр — ИНН юридического лица, одна контрольная цифра (10-я);
  * 12 цифр — ИНН ИП / физлица, две контрольные цифры (11-я и 12-я).

Функции не имеют побочных эффектов и не зависят от моделей, поэтому их
можно использовать и в формах, и в data-миграциях.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError

# Веса для расчёта контрольных цифр ИНН.
INN_10_WEIGHTS: tuple[int, ...] = (2, 4, 10, 3, 5, 9, 4, 6, 8)
INN_11_WEIGHTS: tuple[int, ...] = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
INN_12_WEIGHTS: tuple[int, ...] = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)

INN_LENGTHS: tuple[int, ...] = (10, 12)

INVALID_INN_MESSAGE = (
    "ИНН должен состоять из 10 цифр (юрлицо) или 12 цифр (ИП) "
    "и проходить проверку контрольной суммы."
)


def _control_digit(digits: str, weights: tuple[int, ...]) -> int:
    """Контрольная цифра: сумма произведений по модулю 11, затем по модулю 10."""
    total = sum(int(digit) * weight for digit, weight in zip(digits, weights, strict=True))
    return total % 11 % 10


def is_valid_inn(value: str) -> bool:
    """
    True, если строка похожа на корректный ИНН (10 или 12 цифр,
    контрольная сумма совпадает, не состоит из одних нулей).
    """
    if not isinstance(value, str):
        return False
    value = value.strip()
    if len(value) not in INN_LENGTHS or not (value.isascii() and value.isdigit()):
        return False
    if not value.strip("0"):
        return False
    if len(value) == 10:
        return _control_digit(value[:9], INN_10_WEIGHTS) == int(value[9])
    # 12 цифр: 11-я цифра считается по первым 10, 12-я — по первым 11.
    eleventh = _control_digit(value[:10], INN_11_WEIGHTS)
    twelfth = _control_digit(value[:11], INN_12_WEIGHTS)
    return eleventh == int(value[10]) and twelfth == int(value[11])


def validate_inn(value: str) -> None:
    """Валидатор поля ИНН. Пустое значение пропускает (обязательность — у поля)."""
    if value in (None, ""):
        return
    if not is_valid_inn(value):
        raise ValidationError(INVALID_INN_MESSAGE, code="invalid_inn")
