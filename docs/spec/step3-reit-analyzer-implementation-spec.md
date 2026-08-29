# ТЗ на Шаг 3: Нативная интеграция REIT-анализатора (ReitAnalyzer)
**Статус:** ФИНАЛЬНОЕ — готово для передачи кодинг-агенту.  
**Целевая аудитория:** ИИ-разработчик (Claude Code, Cursor), работающий со стабильным ядром после успешного завершения Шагов 1 и 2.

---

## 0. Границы проекта и не-цели (Scope & Non-goals)
**В рамках Шага 3 (В фокусе):**
1. Полная реализация класса `ReitAnalyzer` в `analyzers.py`, заменяющая временную заглушку-делегат из Шага 1.
2. Парсинг специфических бухгалтерских строк REIT через `find_row()` (FFO, AFFO, NOI, CapEx, амортизация).
3. Специализированный двухэтапный чеклист «грехов» REIT (2 критических и 6 второстепенных) взамен Ordinary-логики.
4. Оценка справедливой стоимости по методу чистой стоимости активов (NAV - Net Asset Value) с использованием отраслевых ставок капитализации (Cap Rate).
5. Адаптация рендеринга PDF и Markdown под REIT-метрики (вывод FFO, AFFO, NOI, Occupancy, Cap Rate и NAV-моста).
6. Интеграция в `portfolio_analyzer.py` (вывод FFO, AFFO, NAV в сравнительной таблице для строк REIT-эмитентов).

**Вне рамок Шага 3:**
* Изменение работающих Ordinary и Banking модулей (жесткий инвариант: регрессионные тесты на MCD, AAPL, JPM, BAC должны проходить без изменений в байтах их отчетов).

---

## 1. Архитектура REIT-анализатора (`ReitAnalyzer`)
Класс `ReitAnalyzer` наследуется от `BaseAnalyzer` и полностью реализует все абстрактные методы. Больше нет делегирования в `OrdinaryAnalyzer`.

### 1.1 Роутинг в `AnalyzerFactory`
Роутер проверяет индустрию эмитента. Если `info.get('industry')` или `info.get('sector')` содержит маркеры REIT, управление передается в `ReitAnalyzer`:
```python
# Маркеры в yfinance info:
is_reit = (
    "reit" in str(info.get("industry", "")).lower() or 
    "real estate investment trust" in str(info.get("industry", "")).lower()
)
```

---

## 2. Специфические метрики REIT (Математическая база)

Из-за бумажного списания стоимости недвижимости (амортизации) чистая прибыль (`Net Income`) REIT искусственно занижена [210]. Для оценки используются три специфические метрики:

### 2.1 FFO (Funds From Operations — Средства от операций) [212, 213]
Показатель эффективности операционной деятельности фонда.
$$\text{FFO} = \text{Net Income} + \text{Depreciation \& Amortization} - \text{Gain on Sale of Real Estate}$$

### 2.2 AFFO (Adjusted Funds From Operations — Скорректированные средства от операций) [214, 215]
Реальный свободный денежный поток фонда, очищенный от обязательных затрат на поддержание недвижимости.
$$\text{AFFO} = \text{FFO} - \text{Recurring Capital Expenditures (CapEx)}$$

### 2.3 NOI (Net Operating Income — Чистый операционный доход) [240]
Доход от аренды за вычетом операционных расходов и налогов на имущество.
$$\text{NOI} = \text{Rental Revenue} - \text{Property Operating Expenses} - \text{Real Estate Taxes}$$

---

## 3. Маппинг строк из `yfinance` для REIT

Для поиска строк в отчетах `yfinance.financials`, `yfinance.balance_sheet` и `yfinance.cashflow` ИИ-агент должен использовать следующие ключи для двухэтапного алгоритма `find_row()`:

| Метрика | Ключи для `find_row()` | Описание и консервативный дефолт |
| :--- | :--- | :--- |
| **Depreciation & Amortization** | `["Depreciation And Amortization", "Depreciation & Amortization", "Depreciation"]` | Берутся из Cash Flow. Если нет — `0.0`. [213] |
| **Gain on Sale of Real Estate** | `["Gain on Sale of Real Estate", "Gain on Sale of Investment Property", "Gain on Sale of Business"]` | Из Cash Flow. Если не найден — `0.0`. [213] |
| **Capital Expenditures** | `["Capital Expenditure", "Capital Expenditures", "CapEx"]` | Из Cash Flow. Если не найден — `0.0`. [214] |
| **Rental Revenue** | `["Rental Revenue", "Total Revenue", "Revenue"]` | Из Income Statement. Ключевая арендная выручка. [240] |
| **Property Operating Exp.** | `["Property Operating Expense", "Property Expenses", "Operating Expense", "Operating Expenses"]` | Из Income Statement. Операционные расходы на здания. [240] |
| **Real Estate Taxes** | `["Real Estate Taxes", "Property Taxes", "Taxes Other Than Income Taxes"]` | Если нет в явном виде, брать `0.0` (предполагаем, что они уже внутри Property Exp.). [240] |
| **Construction in Progress**| `["Construction In Progress", "Capital Work In Progress", "CIP"]` | Из Balance Sheet. Строящиеся объекты. Если нет — `0.0`. [244] |
| **Receivables** | `["Receivables", "Accounts Receivable", "Net Receivables"]` | Из Balance Sheet. Дебиторская задолженность. Если нет — `0.0`. [243] |
| **Occupancy Rate** | Поиск в `info` по ключу `occupancy` или `occupancyRate`. | Если в `info` нет, использовать консервативный дефолт **95.0%** (`0.95`) и выводить предупреждение в консоль. [202, 205] |

*Примечание:* Все извлеченные долларовые показатели должны проходить через FX-конвертер (Currency Bridge) из Шага 1, если валюта отчетности отличается от валюты торгов [262].

---

## 4. Двухуровневый чеклист «грехов» REIT (`calculate_reit_metrics`)

Вместо Ordinary-чеклиста для REIT применяется специализированная модель [194, 211].

### 4.1 Критические грехи (Любой из них = 🔴 SKIP)
1. **Дивиденды «в долг» (AFFO Payout > 100%):**  
   Дивиденды на акцию превышают реальный денежный поток AFFO на акцию. Траст разрушает капитал, выплачивая дивиденды за счет новых долгов или эмиссии. [219]
   $$\text{AFFO Payout Ratio} = \frac{\text{Dividends Paid}}{\text{AFFO}} > 1.0 \quad (\text{или } > 100\%)$$
   *(Если дивиденды не выплачиваются вообще — грех не засчитывается).*
2. **Низкая заполняемость объектов (Occupancy Rate < 80%):**  
   Менее 80% площадей сдано арендаторам. Простаивающие здания приносят только издержки. [203]
   $$\text{Occupancy Rate} < 0.80$$
3. **Отрицательный реальный капитал:**  
   $$\text{Shareholders Equity} \le 0$$ [265]

### 4.2 Второстепенные грехи REIT (Суммируемый балл)
Сравнивается последний отчетный год с предыдущим (YoY).

| Вес | Грех | Условие проверки |
| :--- | :--- | :--- |
| **1.0** | **Падение AFFO** | $AFFO_{current} < AFFO_{prior}$ (при условии, что оба $> 0$) [220] |
| **1.0** | **Снижение заполняемости**| $Occupancy_{current} < Occupancy_{prior}$ [220] |
| **1.0** | **Размытие капитала через SPO** | Количество акций в обращении выросло YoY более чем на **2.5%** [220] |
| **0.5** | **Критический долг (D/E)** | $\text{Debt-to-Equity} = \frac{\text{Total Debt}}{\text{Shareholders Equity}} > 200\% \quad (> 2.0)$ [219] |
| **0.5** | **Падение NOI** | $NOI_{current} < NOI_{prior}$ [220] |
| **0.3** | **Рост доли капинвестиций** | Отношение $\frac{CapEx}{FFO}$ увеличилось более чем на **5%** YoY. [220] |

*Специальный бонус за Buyback:* Если количество акций сократилось более чем на **1.5%** YoY, из итогового балла вычитается **-0.5 балла** (итоговый балл не может упасть ниже 0.0) [288].

### 4.3 Шкала вердикта (при 0 критических грехов):
* **Балл $\le 1.0$** $\rightarrow$ 🟢 **КУПИТЬ (BUY)**
* **Балл от 1.01 до 2.5** $\rightarrow$ 🟡 **НАБЛЮДАТЬ (WATCH)**
* **Балл $> 2.5$** $\rightarrow$ 🔴 **ПРОПУСТИТЬ (SKIP)**

---

## 5. Оценка справедливой стоимости по методу NAV (Net Asset Value)

Стандартная модель DCF неприменима к REIT из-за искажения свободного кэш-флоу операциями с недвижимостью [214]. Вместо нее рассчитывается чистая стоимость активов (NAV) [243, 244].

### 5.1 Определение ставки капитализации (Cap Rate) [238]
Если точная ставка не найдена в `info` или отчетах, применяется консервативная матрица медиан в зависимости от специализации REIT (определяется по ключевым словам в `info.get('industry')` или `summary`):
* **Industrial / Logistics** (Склады, логистические центры — например, PLD): **5.5%** (`0.055`)
* **Residential** (Многоквартирные дома, апартаменты — например, AVB, EQR): **6.0%** (`0.060`)
* **Healthcare / Medical** (Больницы, лаборатории — например, DOC): **6.5%** (`0.065`)
* **Office / Retail / Malls** (Торговые центры, офисы — например, O, SPG): **7.0%** (`0.070`)
* **Default (Все остальные случаи):** **6.5%** (`0.065`)

### 5.2 Математический расчет NAV-модели [235, 243, 244, 245]
1. **Стоимость недвижимости (Property Value):**
   $$\text{Property Value} = \frac{\text{NOI}}{\text{Cap Rate}}$$
2. **Чистая стоимость активов (Net Asset Value):**
   $$\text{NAV} = \text{Property Value} + \text{Cash} + \text{Receivables} + \text{Construction In Progress} - \text{Total Liabilities}$$
3. **Справедливая цена на акцию (Fair Value per Share):**
   $$\text{Fair Price} = \frac{\text{NAV}}{\text{Shares Outstanding}}$$

---

## 6. Требования к формированию отчетов и CLI

### 6.1 Изменения в отчетах (PDF и Markdown)
Для REIT-эмитентов вместо разделов «Операционный кэш-флоу» и «DCF-оценка» выводятся разделы:
* **REIT Operating Performance:** Исторические данные за 4 года для: FFO, AFFO, NOI, CapEx, Dividends Paid.
* **NAV Valuation Bridge:** Наглядный пошаговый расчет:
  * NOI $\rightarrow$ Примененный Cap Rate $\rightarrow$ Property Value.
  * Плюс: Cash, Receivables, Construction in Progress.
  * Минус: Total Liabilities.
  * Итоговый NAV $\rightarrow$ Shares Outstanding $\rightarrow$ Fair Price.

### 6.2 Интеграция в `portfolio_analyzer.py`
В сравнительной таблице портфеля для строк REIT-эмитентов вместо классических колонок `P/E`, `FCF` выводить:
* `P/FFO` (вместо `P/E`).
* `AFFO Payout` (вместо `Payout`).
* `NAV Fair Price` (вместо `DCF Fair Price`).
* Рядом с тикером REIT-компаний выводится суффикс `(REIT)` для визуального разделения.

---

## 7. Чек-лист тестирования (Test Plan)

ИИ-агент должен добавить тесты в `tests/test_verdict_scoring.py` и провести live-проверку.

### 7.1 Сценарии модульных тестов:
1. **Критический грех по AFFO Payout:** Тест на превышение выплаты дивидендов над AFFO (например, AFFO = $1.0 на акцию, дивиденды = $1.2 на акцию) $\rightarrow$ вердикт должен переключаться в `🔴 SKIP`.
2. **Критический грех по Occupancy:** Заполнение объектов = 78% $\rightarrow$ автоматический `🔴 SKIP`.
3. **Расчет NAV-моста:** Инициализация мока с NOI = $100M, Cap Rate = 5.0%, Cash = $10M, Liabilities = $500M, Shares = 10M.
   * Property Value = $100M / 0.05 = $2000M.
   * NAV = $2000M + $10M - $500M = $1510M.
   * Fair Price = $151M. Проверить точность до цента.
4. **Снятие флага `--force`:** Убедиться, что REIT-тикеры теперь анализируются нативно без вызова исключения `UnsupportedSectorError`.

### 7.2 Реальные тикеры для live-проверки:
* **Realty Income (`O`):** Отраслевой эталон. Ожидается нативный запуск, применение Cap Rate = 7.0%, расчет FFO/AFFO и NAV.
* **Simon Property Group (`SPG`):** Проверка крупного ритейл-REIT.
* **Prologis (`PLD`):** Проверка логистического гиганта (Cap Rate = 5.5%).
* **AAPL (Регрессионный тест):** Убедиться, что ядро обычных компаний работает без изменений и Apple сохраняет вердикт `WATCH` после Шага 1.

---

## 8. Результаты тестирования (реализация Шага 3)

### 8.1 Реализация

- `financial_analyzer.py`: добавлены `compute_reit_metrics()` (чеклист §4 + NAV §5), `build_reit_markdown_report()`, `build_reit_pdf_report()`, `generate_ffo_chart()`, `_reit_cap_rate()`. `check_sector_suitability()` теперь всегда возвращает `(None, None)` — REIT (как и Financial Services в Шаге 2) больше не относится ни к одному запрещённому сектору; функция и `UnsupportedSectorError` сохранены как задел на случай будущего запрещённого сектора и чтобы не трогать протестированный рендеринг предупреждающего баннера в Ordinary-отчётах.
- `analyzers.py`: `ReitAnalyzer` переписан как самостоятельная реализация `BaseAnalyzer` (больше не наследует делегат). Класс-делегат `_DelegatingStubAnalyzer` удалён целиком — после Шага 3 им уже никто не пользуется (и `BankAnalyzer`, и `ReitAnalyzer` реализованы нативно). `AnalyzerFactory.get_analyzer()` маршрутизирует REIT (по маркеру `"reit"`/`"real estate investment trust"` в `info.industry`/`info.sector`) безусловно, до вызова `check_sector_suitability()`, тем же паттерном, что и банки в Шаге 2.
- `portfolio_analyzer.py`: `_liquidity_label`/`_cashflow_label`/`_leverage_label` получили третью ветку `_is_reit(m)` — P/FFO вместо CR/LTD, AFFO Payout вместо FCF/NII, Total Debt/Equity как и у банков (у REIT тоже нет классического Enterprise Value/Net Debt). `_ticker_label()` добавляет суффикс `(REIT)` к тикеру. Ширина колонки тикера в консольной таблице увеличена с 7 до 14 символов, чтобы суффикс не ломал выравнивание.
- **Найденная и исправленная реальная ошибка выравнивания годов:** унаследованный из Ordinary-кода трёхстрочный `try/except` (сортировка `financials`/`balance`/`cashflow` по году через `df[years_sorted]`, взятый из `df_fin.columns`) молча ломается, когда один из трёх отчётов недосчитывается одного года относительно другого — `df_bal[years_sorted]` кидает `KeyError`, `except Exception: pass` его глотает, и `df_fin` при этом уже успевает пересортироваться (более ранняя строка в том же `try`), а `df_bal`/`df_cf` — нет. Итог: `.iloc[-1]`/`.iloc[-2]` из разных отчётов сравнивают РАЗНЫЕ года без единой видимой ошибки. Живой пример — `PLD` (`financials`: 5 лет, `balance`: 4 года, отсутствует 2021): при первой реализации `affo_payout_ratio` ошибочно выходил `None`, а NAV считался на рассинхронизированных цифрах (было 73 590M, стало 63 722M после фикса). Это код Шага 2/3 (не Ordinary — `compute_metrics()` не тронут), поэтому исправлено: добавлена `_align_statement_years()` — пересекает множества колонок всех трёх отчётов и сортирует только общий поднабор лет; подключена в `compute_bank_metrics()` и `compute_reit_metrics()`. Для JPM/BAC результат не изменился (их `financials`-годы уже были подмножеством `balance`/`cashflow`, баг не проявлялся), для PLD результат стал корректным.

### 8.2 Отклонения от буквального текста ТЗ (обоснованные)

1. **Тесты добавлены в отдельный файл `tests/test_reit_analyzer.py`, а не в `tests/test_verdict_scoring.py`** (как буквально просит §7) — тот же принцип, что и в Шаге 2 (`test_bank_analyzer.py`): не трогать файл с существующими 21 Ordinary-тестом, чтобы жёсткий инвариант «45 существующих тестов не меняются ни байтом» соблюдался механически, а не «на честном слове».
2. **Приоритет ключевых слов для `Dividends Paid` — `"Cash Dividends Paid"` перед `"Common Stock Dividend Paid"`.** Живая проверка на SPG показала, что строка `yfinance` `"Common Stock Dividend Paid"` (-$439M) отражает лишь малую часть реальных выплат, а остальное (-$2.79B) непонятно почему помещено в `"Preferred Stock Dividend Paid"` (у SPG нет привилегированных акций такого объёма — особенность маппинга yfinance для UPREIT-структуры Simon Property Group). `"Cash Dividends Paid"` (-$3.23B) совпадает с `dividendRate × shares` ($8.9 × 323.55M ≈ $2.88B, с поправкой на распределения OP-паёв) и был выбран как более надёжный основной источник для всех трёх живых тикеров (O/SPG/PLD).
3. **`"Net Loan"` уже учтено в Шаге 2** — не относится к REIT, но напоминание: аналогичный класс проблем (реальное имя строки в `yfinance` расходится со списком ключевых слов из ТЗ) снова встретился в Шаге 3 (см. пункт 2 выше и находку с рассинхронизацией годов) — оба раза устранены хирургически, без отклонения от остальной спецификации.

### 8.3 Тестирование

**Unit-тесты** (`.venv/bin/python3 -m pytest tests/ -q`): **69 passed** (21 существующих `test_verdict_scoring.py` + 24 существующих `test_bank_analyzer.py`, оба без изменений + 24 новых `test_reit_analyzer.py` — критические AFFO Payout/Occupancy/Equity, все 6 второстепенных грехов, бонус за байбэк, границы вердикта 1.0/2.5, точный расчёт NAV-моста по контрольному примеру §7.1 (NOI=$100M, Cap Rate=5%, Cash=$10M, Liabilities=$500M, Shares=10M → Property Value=$2000M → NAV=$1510M → Fair Price=$151.00, сошлось до цента), матрица Cap Rate по всем 4 отраслевым ключевым словам + дефолт, и нативная маршрутизация в `AnalyzerFactory` без `--force`).

**Realty Income (`O`)** (без `--force`, `AnalyzerFactory` → `ReitAnalyzer`):
- Вердикт: 🟢 КУПИТЬ / СИЛЬНЫЙ КАНДИДАТ (0 крит. / 0.0 из 4.3, грехов не обнаружено).
- Cap Rate: **7.0%** (Office / Retail / Malls, отраслевой ключ `"REIT - Retail"`) — совпадает с ожиданием ТЗ §7.2.
- FFO/AFFO за 2025: 3 582.8 млн (Gain on Sale и CapEx не найдены в `yfinance` для `O` → AFFO = FFO). NOI: 3 022.6 млн.
- NAV Bridge: Property Value = 3022.6/0.07 = 43 180.3 млн → +Cash 434.8 +Receivables 4 419.0 +CIP 0 −Liabilities 32 671.6 = **NAV 15 362.5 млн**.
- Fair value = 16.24 USD против цены 61.98 USD → ПЕРЕОЦЕНЕНА на 73.8%. Occupancy Rate недоступен в `yfinance.info` → дефолт 95.0% (с предупреждением в консоль). AFFO Payout = 81.5%, Total Debt/Equity = 0.74x.
- PDF + MD сгенерированы без ошибок (`output/O_fundamental_report_2026-08-29.{pdf,md}`).

**Simon Property Group (`SPG`)** (без `--force`):
- Вердикт: 🟢 КУПИТЬ / СИЛЬНЫЙ КАНДИДАТ (0 крит. / 0.5 из 4.3 — `high_leverage`, D/E = 5.60x).
- Cap Rate: **7.0%** (`"REIT - Retail"`). AFFO Payout = 61.6% (после исправления приоритета ключевого слова дивидендов, см. §8.2.2).
- Fair value = 93.44 USD против цены 214.56 USD → ПЕРЕОЦЕНЕНА на 56.4%.
- PDF + MD сгенерированы без ошибок.

**Prologis (`PLD`)** (без `--force`):
- Вердикт: 🟢 КУПИТЬ / СИЛЬНЫЙ КАНДИДАТ (0 крит. / 1.0 из 4.3 — `affo_declining`).
- Cap Rate: **5.5%** (Industrial / Logistics, `"REIT - Industrial"`) — совпадает с ожиданием ТЗ §7.2.
- NAV = 63 722.2 млн (после фикса рассинхронизации годов, см. §8.1) → Fair value = 67.05 USD против цены 140.70 USD → ПЕРЕОЦЕНЕНА на 52.3%.
- PDF + MD сгенерированы без ошибок.

**Портфельный запуск** `portfolio_analyzer.py AAPL:20 JPM:20 O:20 PLD:20 SPG:20` (без `--force`): проходит успешно для всех пяти тикеров сразу (Ordinary + Bank + REIT в одном прогоне), сводная таблица (консоль/PDF/MD) показывает `P/FFO`/`AFFO Payout`/`Total Debt-Equity` для REIT-строк с суффиксом `(REIT)` у тикера, `LTD`/`NII`/`D/E` для банка, `CR`/`FCF`/`Net Debt` для AAPL — всё в общих колонках без конфликтов. Отдельно проверено `O:100 --force` — идентичный результат (обратная совместимость флага подтверждена и для REIT).

**Регрессия (`AAPL`, `MCD`, `JPM`, `BAC`)**:
- `git diff <Шаг-2-коммит> -- financial_analyzer.py` показывает, что из существовавшего на момент Шага 2 кода тронуты только `check_sector_suitability()` (REIT-ветка убрана, как и Financial Services в Шаге 2) и два инлайн-блока сортировки годов внутри `compute_bank_metrics()`/`compute_reit_metrics()` (вынесены в `_align_statement_years()`). Ordinary-функция `compute_metrics()` не задета ни одной строкой.
- `python financial_analyzer.py AAPL` и `python financial_analyzer.py MCD` (Ordinary CLI-путь) отработали успешно тем же кодом, что и раньше.
- `compute_bank_metrics()` для JPM/BAC даёт **побитово идентичные** значения (DDM, CAGR_div, DPS, Fair Value, вердикт) до и после подключения `_align_statement_years()` — годы `financials` для этих двух банков уже были подмножеством `balance`/`cashflow`, поэтому найденный баг выравнивания там не проявлялся и фикс не изменил ни одного числа.
- Все 45 тестов Шагов 1-2 (`test_verdict_scoring.py` + `test_bank_analyzer.py`) проходят без изменений в файлах тестов.
