# Optimize Films Schedule

Narzędzie CLI w Pythonie do wyliczania możliwych planów obejrzenia filmów w jednym dniu. Na wejściu podajesz filmy, seanse, kina, priorytety, reklamy, marginesy oraz lokalizacje, a na wyjściu dostajesz posortowaną listę możliwych terminarzy.

## Model danych

Konfiguracja jest plikiem JSON. Przykład znajduje się w `examples/sample_day.json`.

Najważniejsze sekcje:

- `priorities` — dowolna liczba kategorii ważności. Im większa liczba, tym mocniej dany film wpływa na sortowanie wyników.
- `films` — lista filmów z czasem trwania i przypisaną kategorią ważności.
- `cinemas` — lista kin; `ads_minutes` określa reklamowy bufor na początku seansu, `address`, `lat` i `lon` opisują routowalną lokalizację kina, a liczbowe `priority` (domyślnie `1`) może opcjonalnie wpływać na wynik optymalizacji.
- `places` — opcjonalna lista dodatkowych miejsc (np. dom, hotel, dworzec) z `id`, nazwą, `address`, `lat` i `lon`. Takie miejsce może być początkiem albo końcem dnia.
- `screenings` — lista seansów z godziną z repertuaru (`starts_at`). Opcjonalne `margin_before_minutes` i `margin_after_minutes` nadpisują domyślne marginesy dla konkretnego seansu.
- `constraints` — opcjonalne ograniczenia: `required_films`, `required_film_cinemas`, `start_location_id`, `end_location_id` oraz `breaks`. Przerwy mogą być tekstem `"HH:MM;HH:MM"` albo obiektem `{"from": "HH:MM", "to": "HH:MM", "location_id": "..."}`. Bez miejsca zakres blokuje filmy i przesuwa możliwy wyjazd do kolejnego kina na godzinę `to`; z miejscem optimizer sprawdza, czy da się dotrzeć do miejsca najpóźniej na `from`, pozostać tam co najmniej do `to`, a potem dojechać na kolejny film.
- `travel_times_file` — ścieżka do osobnego pliku JSON z bazową macierzą czasów przejazdu. Ścieżka relatywna jest liczona względem pliku wejściowego.
- `optimization_settings` — opcjonalne ustawienia, m.in. `sort_by_risk`, wymuszony `travel_time_profile` oraz progi ostrzeżeń ryzyka.

`cinemas` i `places` tworzą wspólny wewnętrzny model `locations`. Współrzędne `lat` i `lon` są podawane ręcznie; narzędzie nie geokoduje adresów automatycznie.

## Plik `travel_times`

Bazowe czasy przejazdu są przeniesione do osobnego JSON-a, np. `examples/sample_travel_times.json`. Obsługiwany jest prosty format liczbowy oraz rozszerzony format z dodatkowymi danymi routingu:

```json
{
  "default_minutes": 25,
  "profiles": [
    {"id": "morning", "start": "06:00", "end": "11:00"},
    {"id": "afternoon", "start": "15:00", "end": "19:00"}
  ],
  "times": {
    "kino-a": {
      "kino-b": {
        "minutes": 20,
        "distance_meters": 8200,
        "no_traffic_minutes": 16,
        "traffic_delay_minutes": 4,
        "raw": {}
      }
    }
  },
  "profile_times": {
    "afternoon": {
      "kino-a": {
        "kino-b": {"minutes": 28, "no_traffic_minutes": 16, "traffic_delay_minutes": 12}
      }
    }
  }
}
```

Optimizer wybiera profil czasowy na podstawie godziny wyjazdu z poprzedniego punktu. Jeśli nie znajdzie wpisu profilowego, używa `times`, a potem `default_minutes`.

## Generowanie `travel_times`

Osobny skrypt buduje macierz na podstawie kin i miejsc z głównego pliku JSON. Współrzędne muszą być wcześniej wpisane ręcznie.

Tryb testowy bez API:

```bash
python -m film_schedule.generate_travel_times examples/sample_day.json examples/generated_travel_times.json --provider static --static-minutes 20
```

Tryb TomTom:

```bash
TOMTOM_API_KEY=... python -m film_schedule.generate_travel_times examples/sample_day.json examples/generated_travel_times.json --provider tomtom
```

Skrypt zapisuje wynikowy plik `travel_times` oraz historyczny cache pojedynczych relacji w katalogu `.travel_cache` (albo w katalogu wskazanym przez `--cache-dir`). Cache pozwala ponownie wykorzystać wcześniej pobrane trasy i nie zużywać niepotrzebnie limitu API. Wpisy cache są oznaczane providerem; jeśli uruchomisz skrypt z innym providerem niż zapisany w cache, stary wpis zostanie pominięty i przeliczony ponownie.

Domyślnie generowane są profile:

- `morning` — 06:00-11:00,
- `midday` — 11:00-15:00,
- `afternoon` — 15:00-19:00,
- `evening` — 19:00-23:00,
- `night` — 23:00-06:00.

Możesz je nadpisać opcją `--profile`, np.:

```bash
python -m film_schedule.generate_travel_times input.json travel_times.json --profile lunch=12:00-14:00 --profile evening=18:00-22:00
```

## Uruchomienie optymalizacji

```bash
python -m film_schedule.cli examples/sample_day.json
```

Możesz też podać plik czasów przejazdu z CLI, nadpisując `travel_times_file` z wejścia:

```bash
python -m film_schedule.cli examples/sample_day.json --travel-times examples/sample_travel_times.json
```

Wynik tekstowy wygląda tak:

```text
1. score=250, filmy=4, dojazdy=85 min, czekanie=268 min, ryzyko=10, ostrzeżenia=1: Film 1 o 10:00 (Kino A); Film 2 o 12:50 (Kino A); Film 3 o 17:00 (Kino A); Film 4 o 21:20 (Kino C)
```

JSON do dalszego przetwarzania:

```bash
python -m film_schedule.cli examples/sample_day.json --format json --limit 10
```

Zapis wyników do pliku i osobnych rekordów:

```bash
python -m film_schedule.cli examples/sample_day.json --format json --limit 10 --output results/day.json
```

## Aktualna walidacja tras z wyniku

CLI może wypisać odcinki tras z najlepszych wyników, aby osobny proces mógł przeliczyć je aktualnym ruchem albo API live:

```bash
python -m film_schedule.cli examples/sample_day.json --validate-routes 3
```

Na tym etapie ta opcja nie odpytuje API sama; zwraca konkretne odcinki, godziny wyjazdu, wybrany profil, czasy i ryzyko dla top N planów. Dzięki temu można walidować tylko kilka najlepszych terminarzy zamiast każdej możliwej kombinacji.

## Ryzyko planu

Każdy odcinek może mieć dane `no_traffic_minutes`, `traffic_delay_minutes` i `minutes`. Na tej podstawie optimizer wylicza:

- `traffic_delay_minutes`,
- `traffic_ratio`,
- `risk_score`,
- ostrzeżenia dla tras z dużym opóźnieniem lub dużym stosunkiem czasu z ruchem do czasu bez ruchu.

Domyślnie ryzyko jest informacją w wyniku. Aby użyć go do sortowania po wymaganiach, punktacji i liczbie filmów, dodaj w JSON:

```json
{
  "optimization_settings": {
    "sort_by_risk": true,
    "risk": {
      "warning_threshold_minutes": 10,
      "warning_threshold_ratio": 1.5
    }
  }
}
```

Albo użyj flagi:

```bash
python -m film_schedule.cli examples/sample_day.json --sort-by-risk
```

Statyczne marginesy (`margin_before_minutes`, `margin_after_minutes`) pozostają podstawowym mechanizmem bezpieczeństwa. Ryzyko nie dodaje automatycznie dynamicznych marginesów, żeby nie komplikować modelu wykonalności; służy do ostrzegania i opcjonalnego sortowania.

## Sortowanie wyników

Wyniki są sortowane kolejno po:

1. największej liczbie spełnionych wymuszeń,
2. największym wyniku punktowym z priorytetów,
3. największej liczbie obejrzanych filmów,
4. opcjonalnie najmniejszym `risk_score`, jeśli włączono `sort_by_risk`,
5. najmniejszym łącznym czasie dojazdów,
6. najmniejszym łącznym czasie czekania,
7. wcześniejszej godzinie rozpoczęcia planu.

Filmy wczytywane z bazy filmów są porządkowane najpierw malejąco po wadze priorytetu z `priorities`, a następnie alfabetycznie po tytule. Priorytety kin są zwykłymi liczbami w rekordach `cinemas`; domyślnie nie są doliczane do `score`. Aby je włączyć, ustaw `optimization_settings.use_cinema_priorities: true` albo dodaj flagę `--use-cinema-priorities`.

Flagi `--earliest-start` i `--latest-end` standardowo oznaczają start i koniec filmu. Jeśli dodasz `--time-bounds-apply-to-locations`, `--earliest-start` oznacza godzinę wyjazdu ze `start_location_id`, a `--latest-end` godzinę przyjazdu do `end_location_id`.

Przy zapisie do pliku można rozdzielić format wyniku zbiorczego i pojedynczych tras. Przykład: zbiorczy plik tekstowy i pojedyncze terminarze jako JSON:

```bash
python -m film_schedule.cli examples/sample_day.json --output results/day.txt --format text --records-format json
```
