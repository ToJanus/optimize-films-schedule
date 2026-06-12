# Optimize Films Schedule

Narzędzie CLI w Pythonie do wyliczania wszystkich możliwych planów obejrzenia filmów w jednym dniu. Na wejściu podajesz filmy, seanse, kina, priorytety, czas reklam, czasy dojazdu oraz marginesy bezpieczeństwa, a na wyjściu dostajesz posortowaną listę możliwych terminarzy.

## Model danych

Konfiguracja jest plikiem JSON. Przykład znajduje się w `examples/sample_day.json`.

Najważniejsze sekcje:

- `priorities` — dowolna liczba kategorii ważności. Im większa liczba, tym mocniej dany film wpływa na sortowanie wyników.
- `films` — lista filmów z czasem trwania i przypisaną kategorią ważności.
- `cinemas` — lista kin; `ads_minutes` określa reklamowy bufor na początku seansu w danym kinie.
- `screenings` — lista seansów z godziną z repertuaru (`starts_at`). Opcjonalne `margin_before_minutes` i `margin_after_minutes` nadpisują domyślne marginesy dla konkretnego seansu.
- `travel_times` — ręczna macierz czasów przejazdu między kinami. To najprostsza darmowa opcja, bez zależności od zewnętrznych API i limitów map.

Optimizer zakłada, że godzina seansu to godzina z repertuaru, a właściwy film zaczyna się po reklamach danego kina. Czas zablokowany dla seansu liczony jest od `starts_at + ads_minutes - margin_before_minutes` do `starts_at + ads_minutes + duration_minutes + margin_after_minutes`.

## Uruchomienie

```bash
python -m film_schedule.cli examples/sample_day.json
```

Wynik tekstowy wygląda tak:

```text
1. score=250, filmy=4, dojazdy=35 min, czekanie=275 min: Film 1 o 10:00 (Kino A); Film 2 o 12:50 (Kino A); Film 3 o 17:00 (Kino A); Film 4 o 21:20 (Kino C)
```

Możesz też dostać JSON do dalszego przetwarzania:

```bash
python -m film_schedule.cli examples/sample_day.json --format json --limit 10
```

Jeśli chcesz pokazać tylko warianty, które zawierają każdy zdefiniowany film dokładnie raz, dodaj:

```bash
python -m film_schedule.cli examples/sample_day.json --all-films
```

## Sortowanie wyników

Wyniki są sortowane kolejno po:

1. największym wyniku punktowym z priorytetów,
2. największej liczbie obejrzanych filmów,
3. najmniejszym łącznym czasie dojazdów,
4. najmniejszym łącznym czasie czekania,
5. wcześniejszej godzinie rozpoczęcia planu.

## Automatyczne czasy dojazdu

Na start używana jest ręczna macierz `travel_times`, bo jest przewidywalna, darmowa i działa offline. W przyszłości można dodać importer z API map, np. OpenStreetMap/OSRM albo komercyjnego API, ale wtedy dochodzą limity, klucze API, cache oraz niejednoznaczność adresów kin.
