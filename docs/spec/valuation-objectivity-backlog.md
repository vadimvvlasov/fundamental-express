# Backlog: устранение искажений в оценке fair value

Status: DRAFT — идеи, не план на исполнение. Каждая задача независима, приоритет
внутри группы = порядок листинга. Все пункты найдены разбором текущего кода
(`src/fundamental_express/domain/valuation.py`, `bank.py`, `financial_analyzer.py`)
и живым кейсом расхождения RF (`bank_valuation` DDM $18.00 vs Ordinary DCF $57.76 —
см. коммит фикса роутинга single_ticker.py → AnalyzerFactory).

## Priority 1 — дёшево, конкретный найденный баг

### V01 — Tangible equity вместо сырого equity в distress-триггерах
**Проблема:** `ordinary_dcf_valuation` (`valuation.py:129-131`) считает
`debt_to_equity_ratio = latest_debt / latest_equity` на сыром equity (баланс,
гудвилл внутри). Раздутый M&A-гудвиллом equity занижает D/E → авто-переключение
DCF→DDM (`capital_distorted`) не срабатывает у компании с реально дистресс-балансом.
Аналогично `bank_valuation` (`valuation.py:275`) — floor `roe<=0 → 0.1*bvps` считает
bvps на сыром equity (в основной ветке `bvps*(roe/Ke)` equity алгебраически
сокращается, там не искажает — только в floor-случае).
**Прецедент в коде:** sin-чек долгосрочной платёжеспособности уже вычитает
гудвилл (`financial_analyzer.py:261`, `long_term_assets_adj = ... - goodwill`) —
паттерн есть, просто не переиспользован в valuation.py.
**Фикс:** завести `tangible_equity = shareholders_equity - goodwill - other_intangibles`
рядом с существующим полем, прогнать через него D/E-дистресс-чек и bvps-floor.
**Файлы:** `domain/valuation.py`, `financial_analyzer.py` (передать goodwill/intangibles
в оба вызова).
**Риск отсутствия фикса:** высокий — маскирует реальный leverage-риск именно у тех
компаний (частые acquirer'ы), где это важнее всего.

### V02 — Многоточечный CAGR вместо 2-точечного (endpoint) роста
**Проблема:** FCF CAGR (`valuation.py:41`) и оба dividend CAGR (`valuation.py:131,249`)
считаются как `(последний/первый)^(1/n) - 1` — один аномальный год (продажа актива,
разовый убыток, ковидный провал) на любом из двух концов окна двигает весь
5-летний прогноз DCF/DDM.
**Фикс:** regression по log(FCF) на годы (slope → CAGR) или медиана погодовых
темпов роста вместо endpoint-to-endpoint. Клампы (2-15% и т.д.) оставить как есть —
они уже страхуют от экстремумов, просто исходная точка станет устойчивее.
**Файлы:** `domain/valuation.py` (`ordinary_dcf_valuation`, `bank_valuation`).

### V03 — Нормализация разовых статей в FCF/Net Income перед DCF и sins-чеком
**Проблема:** FCF/Net Income берутся из yfinance как есть (GAAP), без вычета
impairment, gain/loss on sale, litigation settlement. И DCF-прогноз, и
`net_income_declining`/`nii_declining` sins реагируют на шум разового события,
а не на тренд бизнеса.
**Фикс:** если yfinance отдаёт строки unusual/extraordinary items — вычитать
их перед подачей в CAGR/DCF; если нет — хотя бы флагить в отчёте год с
аномальным (>2 стандартных отклонений от медианы) скачком FCF/NI как
"проверить вручную", не глушить молча.
**Файлы:** `financial_analyzer.py` (парсинг statement rows), `domain/valuation.py`.

## Priority 2 — методология, требует решения по допущениям

### V04 — Lease-adjusted net debt как альтернативный headline, не только сноска
**Проблема:** net debt = Long Term Debt − Cash, аренда исключена (осознанное
допущение, задокументировано в отчёте). Для ритейла/авиа/ресторанов operating
lease liabilities — фактически debt-like, исключение занижает долг и завышает
equity value.
**Фикс:** посчитать и вывести второй Enterprise Value/fair value с
`net_debt_incl_leases`, выбор какой считать headline — по сектору
(NAICS retail/airlines/restaurants → lease-inclusive by default).
**Файлы:** `domain/valuation.py`, `reporting/sections_ordinary.py`.

### V05 — Cost of debt (Kd) по факту компании, не фикс. 4.5%
**Проблема:** `cost_of_debt = 0.045` — одна ставка на все тикеры независимо
от кредитного качества (`valuation.py:33`). Investment-grade и junk-rated
компания получают одинаковый Kd → WACC искажён в разные стороны.
**Фикс:** implied rate = Interest Expense / Total Debt (когда обе строки
есть и total debt > 0), с разумными границами (напр. 2%-12%), fallback на
текущий фикс 4.5% если данных нет.
**Файлы:** `domain/valuation.py`.

### V06 — REIT cap rate чувствителен к ставочному режиму
**Проблема:** `REIT_CAP_RATE_MATRIX` (`valuation.py:308-313`) — статичные
5.5%-7.0% по keyword-категории, не привязаны к текущей безрисковой ставке.
REIT-оценка исторически сильно чувствительна к ставкам (cap rate ≈ Rf + spread);
хардкод не двигается вместе с макроциклом.
**Фикс:** cap_rate = базовый spread категории (текущие 5.5/6.0/6.5/7.0 как
spread над Rf) + текущий `rf_rate` (уже есть константа 0.04 в ordinary/bank
моделях — вынести в одно общее место и переиспользовать).
**Файлы:** `domain/valuation.py`.

### V07 — Трейлинг-среднее NOI/FFO вместо одного последнего года
**Проблема:** `reit_nav_valuation` берёт `noi.iloc[-1]` и `ffo.iloc[-1]` —
один снэпшот-год для оценки всего property portfolio value (`property_value =
latest_noi / cap_rate`). Тот же класс проблемы что V02, но для REIT-специфичных
метрик, отдельный код-путь.
**Фикс:** 2-3-летнее среднее NOI/FFO (или явный флаг "аномальный год" при
отклонении >20% от среднего).
**Файлы:** `domain/valuation.py` (`reit_nav_valuation`).

## Priority 3 — дороже, нужны дополнительные данные/дизайн-решение

### V08 — Beta sanity-check и релеверинг
**Проблема:** beta берётся из `info["beta"]` как есть — сырая 5Y monthly от
Yahoo, шумит на неликвиде, не релевереченная под текущую структуру капитала
компании, не всегда consistent между тикерами по методологии расчёта.
**Фикс:** clamp на явно невалидные значения (напр. beta<0 или beta>3 →
peer-average/1.0 fallback с явной пометкой в отчёте "beta проблемная,
использован fallback").
**Файлы:** `domain/valuation.py`, `financial_analyzer.py` (там где beta читается).

### V09 — Terminal growth завязать на сектор/зрелость, не флэт 2.5%
**Проблема:** `terminal_g = 0.025` — одна ставка для growth-tech и mature
utility одинаково (`valuation.py:78`, и дубли в bank/reit моделях).
**Фикс:** таблица по сектору (аналог `REIT_CAP_RATE_MATRIX`), верхняя граница
= долгосрочный номинальный GDP-прокси (~long-run inflation + real growth),
не выше WACC−1pp с защитой от деления на ноль (уже есть `if wacc > terminal_g`).
**Файлы:** `domain/valuation.py`.

### V10 — Число Грэма: сделать воспроизводимым кодом или убрать из отчётов
**Проблема:** таблица "Число Грэма" в `Screen55_Comparative_Report` посчитана
вручную в чате, не через `portfolio.py` — `grep` по репо не находит ни одного
упоминания Graham в коде. Не воспроизводится через CLI, будет молча
отсутствовать/расходиться при следующем прогоне.
**Фикс:** либо реализовать как настоящую секцию (`√(22.5 × EPS_ttm × tangible_BVPS)`,
используя V01's tangible equity, чтобы не повторить искажение из прошлого
обсуждения), либо явно пометить в любом будущем ad-hoc расчёте "не часть
методики, не воспроизводимо командой".
**Файлы:** новый модуль (`domain/graham.py`) или явная пометка в промпт-практике.

---

## Не в бэклоге (осознанно)

- Фикс. Rf=4%/ERP=5% (`valuation.py:32-33`) — можно вынести в конфиг, но это
  не искажение метода, а прозрачно задокументированное допущение методики
  (см. текст в отчётах "фиксированные допущения методики, не специфичны для
  компании"). Трогать только если появится запрос на per-country Rf/ERP.
